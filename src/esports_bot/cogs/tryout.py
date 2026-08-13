"""Tryout cog — status, check-in, start (voice provisioning), crown, end."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from ..bot import EsportsBot
from ..domain.enums import ResourceOwnerType
from ..domain.server_blueprint import slug
from ..infra import db
from ..infra.discord_gateway import DiscordResourceGateway
from ..infra.discord_resources import DiscordResourceService
from ..infra.resource_repository import SqlResourceRepository
from ..repositories.core import EventRepository, GameRepository
from ..services.checkin_service import CheckinService
from ..services.errors import ServiceError
from ..services.tryout_service import TryoutService
from .checks import is_staff


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
        await self._provision_voice(interaction.guild, event_id, plans, games)
        total = sum(p.channel_count for p in plans)
        await interaction.followup.send(
            f"🚀 Tryout started. Created {total} match voice channels.", ephemeral=True
        )

    async def _provision_voice(self, guild, event_id, plans, games) -> None:
        async with db.session_scope() as s:
            resources = DiscordResourceService(
                DiscordResourceGateway(guild), SqlResourceRepository(s)
            )
            for plan in plans:
                s_slug = slug(games.get(plan.game_id, "game"))
                cat_id = await resources.find(
                    event_id, ResourceOwnerType.GAME, None, f"cat_game:{s_slug}"
                )
                for idx, (a, b) in enumerate(plan.pairs, start=1):
                    vc_id = await resources.ensure_voice_channel(
                        event_id, ResourceOwnerType.GAME, None,
                        f"tryout_voice:{plan.game_id}:{idx}",
                        f"{s_slug}-tryout-{idx}", category_id=cat_id,
                    )
                    role_a = await resources.find(
                        event_id, ResourceOwnerType.TEAM, a, f"team_role:{a}"
                    )
                    role_b = await resources.find(
                        event_id, ResourceOwnerType.TEAM, b, f"team_role:{b}"
                    )
                    vc = guild.get_channel(vc_id)
                    if vc:
                        await vc.set_permissions(
                            guild.default_role, view_channel=False, connect=False
                        )
                        for rid in (role_a, role_b):
                            role = guild.get_role(rid) if rid else None
                            if role:
                                await vc.set_permissions(role, view_channel=True, connect=True)

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
            except (ServiceError, ValueError) as exc:
                await interaction.followup.send(f"❌ {exc}", ephemeral=True)
                return
        await interaction.followup.send(
            "Tryout ended. Event is now in RESULTS. Run `/export all`, then `/system cleanup`.",
            ephemeral=True,
        )


async def setup(bot: EsportsBot) -> None:
    await bot.add_cog(TryoutCog(bot))
