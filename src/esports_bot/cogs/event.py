"""/event commands — create and configure the event (docs/command-specification.md)."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from ..bot import EsportsBot
from ..domain.enums import ResourceOwnerType, ResourceStatus
from ..infra import db
from ..infra.discord_gateway import DiscordResourceGateway
from ..infra.discord_resources import DiscordResourceService
from ..infra.resource_repository import SqlResourceRepository
from ..repositories.core import EventRepository
from ..services.errors import ServiceError
from ..services.event_service import EventService
from .checks import is_head_or_owner


class EventCog(commands.Cog):
    def __init__(self, bot: EsportsBot) -> None:
        self.bot = bot

    event = app_commands.Group(
        name="event",
        description="Create and manage the E-Sports event.",
        default_permissions=discord.Permissions(manage_guild=True),
        guild_only=True,
    )

    async def _active_event_id(self, guild_id: int) -> int | None:
        async with db.session_scope() as s:
            ev = await EventRepository(s).get_active(guild_id)
            return ev.id if ev else None

    @event.command(name="create", description="Create a new event (E-Sports Head only).")
    @app_commands.describe(
        name="Event name", year="Event year", school="School name",
        email_domain="School email domain (e.g. uphsl.edu.ph)",
        timezone="IANA timezone (e.g. Asia/Manila)",
    )
    async def create(
        self, interaction: discord.Interaction, name: str, year: int,
        school: str, email_domain: str, timezone: str = "Asia/Manila",
    ) -> None:
        if not is_head_or_owner(interaction, self.bot.settings):
            await interaction.response.send_message(
                "Only the E-Sports Head can create an event.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        try:
            async with db.session_scope() as s:
                svc = EventService(s)
                ev = await svc.create_event(
                    guild_id=interaction.guild_id, name=name, year=year,
                    school_name=school, email_domain=email_domain, timezone=timezone,
                    actor_discord_id=interaction.user.id,
                    actor_username=str(interaction.user),
                )
                msg = (
                    f"Created event **{ev.name} {ev.year}** (state: {ev.state.value}). "
                    "Next: `/event configure add-game`, then `/setup preview`."
                )
        except (ServiceError, ValueError) as exc:
            msg = f"Could not create event: {exc}"
        await interaction.followup.send(msg, ephemeral=True)

    configure = app_commands.Group(
        name="configure", description="Configure the event.", parent=event
    )

    @configure.command(name="add-game", description="Add a game to the event.")
    @app_commands.describe(game="Game name", roster_size="Players per team")
    async def add_game(
        self, interaction: discord.Interaction, game: str, roster_size: int
    ) -> None:
        if not is_head_or_owner(interaction, self.bot.settings):
            await interaction.response.send_message("Head only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        event_id = await self._active_event_id(interaction.guild_id)
        if event_id is None:
            await interaction.followup.send(
                "No active event. Run `/event create` first.", ephemeral=True
            )
            return
        try:
            async with db.session_scope() as s:
                svc = EventService(s)
                await svc.add_game(
                    event_id=event_id, game_name=game, roster_size=roster_size,
                    actor_discord_id=interaction.user.id, actor_username=str(interaction.user),
                )
                msg = f"Added **{game}** ({roster_size} players)."
        except (ServiceError, ValueError) as exc:
            msg = f"Could not add game: {exc}"
        await interaction.followup.send(msg, ephemeral=True)

    @configure.command(name="remove-game", description="Remove a misconfigured game (DRAFT/SETUP).")
    @app_commands.describe(game="The exact game name to remove")
    async def remove_game(self, interaction: discord.Interaction, game: str) -> None:
        if not is_head_or_owner(interaction, self.bot.settings):
            await interaction.response.send_message("Head only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        event_id = await self._active_event_id(interaction.guild_id)
        if event_id is None:
            await interaction.followup.send("No active event.", ephemeral=True)
            return
        try:
            async with db.session_scope() as s:
                game_slug = await EventService(s).remove_game(
                    event_id=event_id, game_name=game,
                    actor_discord_id=interaction.user.id, actor_username=str(interaction.user),
                )
        except (ServiceError, ValueError) as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
            return
        removed = await self._teardown_game(interaction.guild, event_id, game_slug)
        await interaction.followup.send(
            f"Removed **{game}** from the event and deleted {removed} of its Discord channels.",
            ephemeral=True,
        )

    async def _teardown_game(self, guild: discord.Guild, event_id: int, game_slug: str) -> int:
        """Delete the Discord category/channels that belong to a removed game."""
        removed = 0
        async with db.session_scope() as s:
            repo = SqlResourceRepository(s)
            resources = DiscordResourceService(DiscordResourceGateway(guild), repo)
            rows = [
                r for r in await repo.list_by_status(event_id, ResourceStatus.CREATED)
                if r.owner_type == ResourceOwnerType.GAME and r.purpose.endswith(f":{game_slug}")
            ]
            # Delete channels before the category.
            for row in sorted(rows, key=lambda r: r.purpose.startswith("cat_")):
                await resources.delete(row)
                removed += 1
        return removed

    @event.command(name="advance", description="Advance the event to the next lifecycle state.")
    async def advance(self, interaction: discord.Interaction) -> None:
        if not is_head_or_owner(interaction, self.bot.settings):
            await interaction.response.send_message("Head only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        event_id = await self._active_event_id(interaction.guild_id)
        if event_id is None:
            await interaction.followup.send("No active event.", ephemeral=True)
            return
        try:
            async with db.session_scope() as s:
                ev = await EventService(s).advance(
                    event_id=event_id, actor_discord_id=interaction.user.id,
                    actor_username=str(interaction.user),
                )
                msg = f"Event advanced to **{ev.state.value}**."
        except (ServiceError, ValueError) as exc:
            msg = f"Could not advance: {exc}"
        await interaction.followup.send(msg, ephemeral=True)

    @event.command(name="status", description="Show the current event status.")
    async def status(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        event_id = await self._active_event_id(interaction.guild_id)
        if event_id is None:
            await interaction.followup.send("No active event.", ephemeral=True)
            return
        async with db.session_scope() as s:
            data = await EventService(s).status(event_id)
        embed = discord.Embed(
            title=f"{data['name']} {data['year']}", colour=discord.Colour.blurple()
        )
        embed.add_field(name="State", value=data["state"], inline=True)
        embed.add_field(name="Games", value=str(data["games"]), inline=True)
        embed.add_field(name="Applicants", value=str(data["applicants"]), inline=True)
        embed.add_field(name="Approved", value=str(data["approved"]), inline=True)
        embed.add_field(name="Teams", value=str(data["teams"]), inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: EsportsBot) -> None:
    await bot.add_cog(EventCog(bot))
