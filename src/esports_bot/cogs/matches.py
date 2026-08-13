"""Matches cog — record and correct battle results (docs §23-24)."""

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
from ..models import Game, Team
from ..repositories.core import EventRepository
from ..services.errors import ServiceError
from ..services.match_service import MatchService
from .checks import is_staff


class MatchesCog(commands.Cog):
    def __init__(self, bot: EsportsBot) -> None:
        self.bot = bot

    match = app_commands.Group(
        name="match", description="Match results (staff).",
        default_permissions=discord.Permissions(manage_guild=True), guild_only=True,
    )

    @match.command(name="battle-ended", description="Record a battle result.")
    @app_commands.describe(
        match_id="Match ID", winner_team_id="Winning team ID",
        screenshot="Result screenshot URL (optional)", notes="Optional notes",
    )
    async def battle_ended(
        self, interaction: discord.Interaction, match_id: int, winner_team_id: int,
        screenshot: str | None = None, notes: str | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None or not await is_staff(interaction, s, event.id, self.bot.settings):
                await interaction.followup.send("Staff only.", ephemeral=True)
                return
            try:
                await MatchService(s).record_result(
                    event_id=event.id, match_id=match_id, winner_team_id=winner_team_id,
                    screenshot_url=screenshot, notes=notes,
                    reporter_discord_id=interaction.user.id,
                    reporter_username=str(interaction.user),
                )
            except (ServiceError, ValueError) as exc:
                await interaction.followup.send(f"❌ {exc}", ephemeral=True)
                return
            winner = await s.get(Team, winner_team_id)
            game = await s.get(Game, winner.game_id) if winner else None
            game_name = game.name if game else "game"
            event_id = event.id
            resources = DiscordResourceService(
                DiscordResourceGateway(interaction.guild), SqlResourceRepository(s)
            )
            channel_id = await resources.find(
                event_id, ResourceOwnerType.GAME, None, f"game_battle_results:{slug(game_name)}"
            )
        if channel_id and (ch := interaction.guild.get_channel(channel_id)):
            embed = discord.Embed(
                title=f"Match #{match_id} result", colour=discord.Colour.green(),
                description=f"Winner: **{winner.name if winner else winner_team_id}**",
            )
            if screenshot:
                embed.set_image(url=screenshot)
            if notes:
                embed.add_field(name="Notes", value=notes[:1024], inline=False)
            await ch.send(embed=embed)
        await interaction.followup.send("Result recorded.", ephemeral=True)

    @match.command(name="correct", description="Correct a match result (staff, reason required).")
    async def correct(
        self, interaction: discord.Interaction, match_id: int, winner_team_id: int, reason: str
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None or not await is_staff(interaction, s, event.id, self.bot.settings):
                await interaction.followup.send("Staff only.", ephemeral=True)
                return
            try:
                await MatchService(s).correct(
                    event_id=event.id, match_id=match_id, winner_team_id=winner_team_id,
                    reason=reason, actor_discord_id=interaction.user.id,
                    actor_username=str(interaction.user),
                )
            except (ServiceError, ValueError) as exc:
                await interaction.followup.send(f"❌ {exc}", ephemeral=True)
                return
        await interaction.followup.send(f"Corrected match #{match_id}.", ephemeral=True)


async def setup(bot: EsportsBot) -> None:
    await bot.add_cog(MatchesCog(bot))
