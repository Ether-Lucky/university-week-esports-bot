"""Tryout cog — status, check-in, start (voice provisioning), crown, end."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import discord
from discord import app_commands
from discord.ext import commands

from ..bot import EsportsBot
from ..domain.enums import ResourceOwnerType
from ..domain.server_blueprint import slug
from ..infra import dashboard, db, tryout_env
from ..infra.discord_gateway import DiscordResourceGateway
from ..infra.discord_resources import DiscordResourceService
from ..infra.resource_repository import SqlResourceRepository
from ..repositories.core import EventRepository, GameRepository
from ..services.checkin_service import CheckinService
from ..services.errors import ServiceError
from ..services.event_service import EventService
from ..services.tryout_service import TryoutService
from .checks import is_staff


async def _game_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    async with db.session_scope() as s:
        event = await EventRepository(s).get_active(interaction.guild_id)
        if event is None:
            return []
        games = await GameRepository(s).list_games_for_event(event.id)
    cur = current.lower()
    return [
        app_commands.Choice(name=g.name, value=g.name)
        for g in games
        if cur in g.name.lower()
    ][:25]


class TryoutCog(commands.Cog):
    def __init__(self, bot: EsportsBot) -> None:
        self.bot = bot

    tryout = app_commands.Group(name="tryout", description="Tryout operations.", guild_only=True)

    @tryout.command(name="status", description="Show tryout readiness per game.")
    async def status(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None:
                await interaction.followup.send("No active event.", ephemeral=True)
                return
            readiness, overall = await TryoutService(s).validate(event.id)
        embed = discord.Embed(
            title="Tryout Status",
            colour=discord.Colour.green() if overall else discord.Colour.red(),
        )
        for r in readiness:
            def mark(ok: bool) -> str:
                return "✓" if ok else "✗"
            embed.add_field(
                name=r.game_name,
                value=(
                    f"{mark(r.mechanics)} Mechanics\n{mark(r.challonge)} Challonge\n"
                    f"{mark(r.complete_teams >= 2)} {r.complete_teams} complete teams\n"
                    f"{mark(r.date_ok)} Date configured"
                ),
                inline=True,
            )
        embed.description = "**READY**" if overall else "**NOT READY**"
        await interaction.followup.send(embed=embed, ephemeral=True)

    @tryout.command(name="schedule", description="Set the tryout date & time (staff).")
    @app_commands.describe(
        date="Date as YYYY-MM-DD", time="Time as HH:MM (24-hour), in the event's timezone"
    )
    async def schedule(self, interaction: discord.Interaction, date: str, time: str) -> None:
        await interaction.response.defer(ephemeral=True)
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None or not await is_staff(interaction, s, event.id, self.bot.settings):
                await interaction.followup.send("Staff only.", ephemeral=True)
                return
            try:
                naive = datetime.strptime(f"{date.strip()} {time.strip()}", "%Y-%m-%d %H:%M")
                tz = ZoneInfo(event.timezone)
            except (ValueError, ZoneInfoNotFoundError):
                await interaction.followup.send(
                    "Invalid date/time. Use `date:2027-02-14` and `time:09:30`.", ephemeral=True
                )
                return
            local_dt = naive.replace(tzinfo=tz)
            await EventService(s).set_schedule(
                event_id=event.id, actor_discord_id=interaction.user.id,
                actor_username=str(interaction.user), tryout_at=local_dt.astimezone(UTC),
            )
            when = local_dt.strftime("%A, %d %b %Y at %I:%M %p")
            tzname, event_id = event.timezone, event.id
        await self._announce_tryout(interaction.guild, event_id, when, tzname)
        await dashboard.refresh(interaction.guild, event_id)
        await interaction.followup.send(
            f"✅ Tryout scheduled for **{when}** ({tzname}) and announced.", ephemeral=True
        )

    async def _announce_tryout(
        self, guild: discord.Guild, event_id: int, when: str, tzname: str
    ) -> None:
        """Post the tryout schedule in #apply and ping Audience."""
        async with db.session_scope() as s:
            resources = DiscordResourceService(
                DiscordResourceGateway(guild), SqlResourceRepository(s)
            )
            apply_id = await resources.find(
                event_id, ResourceOwnerType.SYSTEM, None, "ch_apply"
            )
            audience_id = await resources.find(
                event_id, ResourceOwnerType.SYSTEM, None, "role_audience"
            )
        channel = guild.get_channel(apply_id) if apply_id else None
        if channel is None:
            return
        role = guild.get_role(audience_id) if audience_id else None
        embed = discord.Embed(
            title="📅 Tryout Schedule",
            description=(
                f"The tryout is scheduled for **{when}** ({tzname}).\n\n"
                "Get your team ready, and **check in** with `/tryout checkin` before it begins!"
            ),
            colour=discord.Colour.gold(),
        )
        await channel.send(
            content=role.mention if role else None, embed=embed,
            allowed_mentions=discord.AllowedMentions(roles=True),
        )

    @tryout.command(name="checkin", description="Check yourself in for the tryout.")
    async def checkin(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None:
                await interaction.followup.send("No active event.", ephemeral=True)
                return
            try:
                await CheckinService(s).check_in(
                    event_id=event.id, member_discord_id=interaction.user.id,
                    username=str(interaction.user),
                )
            except (ServiceError, ValueError) as exc:
                await interaction.followup.send(f"❌ {exc}", ephemeral=True)
                return
        await interaction.followup.send("✅ Checked in!", ephemeral=True)

    @tryout.command(
        name="checkin-all", description="Check in every team member at once (staff)."
    )
    async def checkin_all(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None or not await is_staff(interaction, s, event.id, self.bot.settings):
                await interaction.followup.send("Staff only.", ephemeral=True)
                return
            count = await CheckinService(s).check_in_all(
                event_id=event.id, actor_discord_id=interaction.user.id,
                actor_username=str(interaction.user),
            )
        await interaction.followup.send(
            f"✅ Checked in {count} team member(s).", ephemeral=True
        )

    @tryout.command(name="start", description="Start the tryout (Head/Committee).")
    async def start(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None or not await is_staff(interaction, s, event.id, self.bot.settings):
                await interaction.followup.send("Staff only.", ephemeral=True)
                return
            try:
                plans = await TryoutService(s).start(
                    event_id=event.id, actor_discord_id=interaction.user.id,
                    actor_username=str(interaction.user),
                )
            except (ServiceError, ValueError) as exc:
                await interaction.followup.send(f"❌ {exc}", ephemeral=True)
                return
            games = {g.id: g.name for g in await GameRepository(s).list_games_for_event(event.id)}
            event_id = event.id
        total = await tryout_env.provision_tryout_channels(
            interaction.guild, event_id, plans, games
        )
        hidden = await tryout_env.set_focus(interaction.guild, event_id, hide=True)
        started_ids = {p.game_id for p in plans}
        started = [n for gid, n in games.items() if gid in started_ids]
        skipped = [n for gid, n in games.items() if gid not in started_ids]
        msg = (
            f"🚀 Tryout started for: **{', '.join(started)}**.\n"
            f"Created {total} team voice channels in per-game tryout categories, and hid "
            f"{hidden} other channels so everyone focuses on the tryout (they return on "
            "`/tryout end`)."
        )
        if skipped:
            msg += (
                f"\n\n⏭️ Skipped (not ready — no tryout): **{', '.join(skipped)}**. "
                "Appoint their players with `/tryout appoint`."
            )
        await interaction.followup.send(msg, ephemeral=True)


    @tryout.command(name="crown", description="Crown a champion team for a game (staff).")
    async def crown(self, interaction: discord.Interaction, game: str, team_id: int) -> None:
        await interaction.response.defer(ephemeral=True)
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None or not await is_staff(interaction, s, event.id, self.bot.settings):
                await interaction.followup.send("Staff only.", ephemeral=True)
                return
            game_list = await GameRepository(s).list_games_for_event(event.id)
            games = {g.name.lower(): g for g in game_list}
            g = games.get(game.lower())
            if g is None:
                await interaction.followup.send("Unknown game.", ephemeral=True)
                return
            try:
                member_ids = await TryoutService(s).crown_champion(
                    event_id=event.id, game_id=g.id, team_id=team_id,
                    actor_discord_id=interaction.user.id, actor_username=str(interaction.user),
                )
                event_id = event.id
            except (ServiceError, ValueError) as exc:
                await interaction.followup.send(f"❌ {exc}", ephemeral=True)
                return
            resources = DiscordResourceService(
                DiscordResourceGateway(interaction.guild), SqlResourceRepository(s)
            )
            player_role_id = await resources.find(
                event_id, ResourceOwnerType.SYSTEM, None, "role_player"
            )
        # Grant the Player role to champion members (OQ-10).
        role = interaction.guild.get_role(player_role_id) if player_role_id else None
        if role:
            for did in member_ids:
                member = interaction.guild.get_member(did)
                if member:
                    await member.add_roles(role, reason="Tryout champion -> Player")
        await interaction.followup.send(
            f"🏆 Crowned team #{team_id} champion of **{g.name}**; Player role granted.",
            ephemeral=True,
        )

    @tryout.command(
        name="appoint",
        description="Appoint a Player for a game that formed no teams (staff).",
    )
    @app_commands.describe(game="The game", member="The member to appoint as a Player")
    @app_commands.autocomplete(game=_game_autocomplete)
    async def appoint(
        self, interaction: discord.Interaction, game: str, member: discord.Member
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None or not await is_staff(interaction, s, event.id, self.bot.settings):
                await interaction.followup.send("Staff only.", ephemeral=True)
                return
            game_list = await GameRepository(s).list_games_for_event(event.id)
            g = next((x for x in game_list if x.name.lower() == game.lower()), None)
            if g is None:
                await interaction.followup.send("Unknown game.", ephemeral=True)
                return
            resources = DiscordResourceService(
                DiscordResourceGateway(interaction.guild), SqlResourceRepository(s)
            )
            player_id = await resources.find(
                event.id, ResourceOwnerType.SYSTEM, None, "role_player"
            )
            game_role_id = await resources.find(
                event.id, ResourceOwnerType.SYSTEM, None, f"game_role:{slug(g.name)}"
            )
        granted = []
        for rid, label in ((player_id, "Player"), (game_role_id, g.name)):
            role = interaction.guild.get_role(rid) if rid else None
            if role and role not in member.roles:
                try:
                    await member.add_roles(role, reason=f"Appointed for {g.name} (no teams)")
                    granted.append(label)
                except discord.HTTPException:
                    pass
        if granted:
            await interaction.followup.send(
                f"✅ Appointed {member.mention} for **{g.name}** — granted: {', '.join(granted)}.",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                f"{member.mention} already has those roles (or the roles are missing).",
                ephemeral=True,
            )

    @tryout.command(name="end", description="Finalize the tryout -> RESULTS (staff).")
    async def end(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None or not await is_staff(interaction, s, event.id, self.bot.settings):
                await interaction.followup.send("Staff only.", ephemeral=True)
                return
            try:
                await TryoutService(s).finish(
                    event_id=event.id, actor_discord_id=interaction.user.id,
                    actor_username=str(interaction.user),
                )
                event_id = event.id
            except (ServiceError, ValueError) as exc:
                await interaction.followup.send(f"❌ {exc}", ephemeral=True)
                return
        restored = await tryout_env.set_focus(interaction.guild, event_id, hide=False)
        await interaction.followup.send(
            f"Tryout ended. Event is now in RESULTS; restored visibility on {restored} channels. "
            "Run `/export all`, then `/system cleanup`.",
            ephemeral=True,
        )


async def setup(bot: EsportsBot) -> None:
    await bot.add_cog(TryoutCog(bot))
