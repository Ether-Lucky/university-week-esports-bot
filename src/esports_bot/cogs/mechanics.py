"""Mechanics & tournament (Challonge) cog (docs §17-18)."""

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
from ..services.errors import ServiceError
from ..services.mechanics_service import MechanicsService, TournamentService
from .checks import is_staff


async def _resolve_event_game(session, guild_id: int, game_name: str):
    event = await EventRepository(session).get_active(guild_id)
    if event is None:
        return None, None, None
    game_list = await GameRepository(session).list_games_for_event(event.id)
    games = {g.name.lower(): g for g in game_list}
    game = games.get(game_name.lower())
    if game is None:
        return event, None, None
    eg = await GameRepository(session).get_event_game(event.id, game.id)
    return event, game, eg


def _mechanics_embed(title: str, body: dict) -> discord.Embed:
    embed = discord.Embed(title=title, colour=discord.Colour.teal())
    if desc := body.get("description"):
        embed.description = desc[:4000]
    for field in body.get("fields", [])[:25]:
        embed.add_field(
            name=str(field.get("name", "—"))[:256],
            value=str(field.get("value", "—"))[:1024],
            inline=bool(field.get("inline", False)),
        )
    return embed


class MechanicsCog(commands.Cog):
    def __init__(self, bot: EsportsBot) -> None:
        self.bot = bot

    mechanics = app_commands.Group(
        name="mechanics", description="Game mechanics (staff).",
        default_permissions=discord.Permissions(manage_guild=True), guild_only=True,
    )
    tournament = app_commands.Group(
        name="tournament", description="Tournament links (staff).",
        default_permissions=discord.Permissions(manage_guild=True), guild_only=True,
    )

    @mechanics.command(name="create", description="Create/replace mechanics for a game.")
    @app_commands.describe(game="Game", title="Title", description="Body text")
    async def create(
        self, interaction: discord.Interaction, game: str, title: str, description: str
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        async with db.session_scope() as s:
            event, g, eg = await _resolve_event_game(s, interaction.guild_id, game)
            if eg is None:
                await interaction.followup.send("Unknown game / no event.", ephemeral=True)
                return
            if not await is_staff(interaction, s, event.id, self.bot.settings):
                await interaction.followup.send("Staff only.", ephemeral=True)
                return
            try:
                await MechanicsService(s).create(
                    event_id=event.id, event_game_id=eg.id, title=title,
                    body={"description": description},
                    actor_discord_id=interaction.user.id, actor_username=str(interaction.user),
                )
            except (ServiceError, ValueError) as exc:
                await interaction.followup.send(f"❌ {exc}", ephemeral=True)
                return
        await interaction.followup.send(
            "Mechanics saved (unpublished). Use `/mechanics publish` to post them.", ephemeral=True
        )

    @mechanics.command(name="publish", description="Publish the latest mechanics to its channel.")
    async def publish(self, interaction: discord.Interaction, game: str) -> None:
        await interaction.response.defer(ephemeral=True)
        async with db.session_scope() as s:
            event, g, eg = await _resolve_event_game(s, interaction.guild_id, game)
            if eg is None:
                await interaction.followup.send("Unknown game / no event.", ephemeral=True)
                return
            if not await is_staff(interaction, s, event.id, self.bot.settings):
                await interaction.followup.send("Staff only.", ephemeral=True)
                return
            try:
                mech = await MechanicsService(s).publish(
                    event_id=event.id, event_game_id=eg.id,
                    actor_discord_id=interaction.user.id, actor_username=str(interaction.user),
                )
                title, body, event_id, game_name = mech.title, mech.body, event.id, g.name
            except (ServiceError, ValueError) as exc:
                await interaction.followup.send(f"❌ {exc}", ephemeral=True)
                return
            resources = DiscordResourceService(
                DiscordResourceGateway(interaction.guild), SqlResourceRepository(s)
            )
            channel_id = await resources.find(
                event_id, ResourceOwnerType.GAME, None, f"game_mechanics:{slug(game_name)}"
            )
        if channel_id and (ch := interaction.guild.get_channel(channel_id)):
            await ch.send(embed=_mechanics_embed(title, body))
        await interaction.followup.send("Mechanics published.", ephemeral=True)

    @tournament.command(name="set", description="Set the Challonge URL for a game.")
    async def set_challonge(self, interaction: discord.Interaction, game: str, url: str) -> None:
        await interaction.response.defer(ephemeral=True)
        async with db.session_scope() as s:
            event, g, eg = await _resolve_event_game(s, interaction.guild_id, game)
            if eg is None:
                await interaction.followup.send("Unknown game / no event.", ephemeral=True)
                return
            if not await is_staff(interaction, s, event.id, self.bot.settings):
                await interaction.followup.send("Staff only.", ephemeral=True)
                return
            try:
                await TournamentService(s).set_challonge(
                    event_id=event.id, event_game_id=eg.id, url=url,
                    actor_discord_id=interaction.user.id, actor_username=str(interaction.user),
                )
                event_id, game_name = event.id, g.name
            except (ServiceError, ValueError) as exc:
                await interaction.followup.send(f"❌ {exc}", ephemeral=True)
                return
            resources = DiscordResourceService(
                DiscordResourceGateway(interaction.guild), SqlResourceRepository(s)
            )
            channel_id = await resources.find(
                event_id, ResourceOwnerType.GAME, None, f"game_tournament:{slug(game_name)}"
            )
        if channel_id and (ch := interaction.guild.get_channel(channel_id)):
            await ch.send(f"🏆 Tournament bracket for **{game_name}**: {url}")
        await interaction.followup.send("Challonge link set.", ephemeral=True)


async def setup(bot: EsportsBot) -> None:
    await bot.add_cog(MechanicsCog(bot))
