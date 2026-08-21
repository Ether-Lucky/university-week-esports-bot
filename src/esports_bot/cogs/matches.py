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
from ..models import Game, Match, Team
from ..repositories.competition import MatchRepository
from ..repositories.core import EventRepository, GameRepository
from ..services.errors import ServiceError
from ..services.match_service import MatchService
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
        for g in games if cur in g.name.lower()
    ][:25]


async def _winner_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Only the teams that still have a pending match in the chosen game."""
    game_name = getattr(interaction.namespace, "game", None)
    if not game_name:
        return []
    cur = current.lower()
    async with db.session_scope() as s:
        event = await EventRepository(s).get_active(interaction.guild_id)
        if event is None:
            return []
        games = await GameRepository(s).list_games_for_event(event.id)
        g = next((x for x in games if x.name.lower() == game_name.lower()), None)
        if g is None:
            return []
        matches = await MatchRepository(s).scheduled_for_game(event.id, g.id)
        team_ids = {m.team_a_id for m in matches} | {
            m.team_b_id for m in matches if m.team_b_id
        }
        choices = []
        for tid in team_ids:
            team = await s.get(Team, tid)
            if team and cur in team.name.lower():
                choices.append(app_commands.Choice(name=team.name, value=str(tid)))
    return choices[:25]


async def _completed_match_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """List the *completed* matches in the chosen game, so staff pick which to act on."""
    game_name = getattr(interaction.namespace, "game", None)
    if not game_name:
        return []
    cur = current.lower()
    async with db.session_scope() as s:
        event = await EventRepository(s).get_active(interaction.guild_id)
        if event is None:
            return []
        games = await GameRepository(s).list_games_for_event(event.id)
        g = next((x for x in games if x.name.lower() == game_name.lower()), None)
        if g is None:
            return []
        matches = await MatchRepository(s).completed_for_game(event.id, g.id)
        choices = []
        for m in matches:
            a = await s.get(Team, m.team_a_id)
            b = await s.get(Team, m.team_b_id) if m.team_b_id else None
            w = await s.get(Team, m.winner_team_id) if m.winner_team_id else None
            label = (
                f"#{m.id}: {a.name if a else '?'} vs {b.name if b else 'BYE'} "
                f"— won: {w.name if w else '?'}"
            )
            if cur in label.lower():
                choices.append(app_commands.Choice(name=label[:100], value=str(m.id)))
    return choices[:25]


def _result_embed(match_id, winner_name, screenshot=None, notes=None) -> discord.Embed:
    embed = discord.Embed(
        title=f"Match #{match_id} result", colour=discord.Colour.green(),
        description=f"Winner: **{winner_name}**",
    )
    if screenshot:
        embed.set_image(url=screenshot)
    if notes:
        embed.add_field(name="Notes", value=str(notes)[:1024], inline=False)
    return embed


async def _edit_announcement(guild, channel_id, message_id, embed) -> None:
    if not channel_id or not message_id:
        return
    ch = guild.get_channel(channel_id)
    if ch is None:
        return
    try:
        msg = await ch.fetch_message(message_id)
        await msg.edit(embed=embed)
    except discord.HTTPException:
        pass


async def _delete_announcement(guild, channel_id, message_id) -> None:
    if not channel_id or not message_id:
        return
    ch = guild.get_channel(channel_id)
    if ch is None:
        return
    try:
        msg = await ch.fetch_message(message_id)
        await msg.delete()
    except discord.HTTPException:
        pass


class MatchesCog(commands.Cog):
    def __init__(self, bot: EsportsBot) -> None:
        self.bot = bot

    match = app_commands.Group(
        name="match", description="Match results (staff).",
        default_permissions=discord.Permissions(manage_guild=True), guild_only=True,
    )

    @match.command(name="battle-ended", description="Record a battle result.")
    @app_commands.describe(
        game="The game", winner="The winning team (only that game's teams with a pending match)",
        screenshot="Result screenshot URL (optional)", notes="Optional notes",
    )
    @app_commands.autocomplete(game=_game_autocomplete, winner=_winner_autocomplete)
    async def battle_ended(
        self, interaction: discord.Interaction, game: str, winner: str,
        screenshot: str | None = None, notes: str | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            winner_team_id = int(winner)
        except ValueError:
            await interaction.followup.send(
                "Pick the winning team from the list.", ephemeral=True
            )
            return
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None or not await is_staff(interaction, s, event.id, self.bot.settings):
                await interaction.followup.send("Staff only.", ephemeral=True)
                return
            match = await MatchRepository(s).scheduled_for_team(event.id, winner_team_id)
            if match is None:
                await interaction.followup.send(
                    "That team has no pending match to record.", ephemeral=True
                )
                return
            match_id = match.id
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
            winner_team = await s.get(Team, winner_team_id)
            g = await s.get(Game, winner_team.game_id) if winner_team else None
            game_name = g.name if g else "game"
            event_id = event.id
            resources = DiscordResourceService(
                DiscordResourceGateway(interaction.guild), SqlResourceRepository(s)
            )
            channel_id = await resources.find(
                event_id, ResourceOwnerType.GAME, None, f"game_battle_results:{slug(game_name)}"
            )
        winner_name = winner_team.name if winner_team else winner_team_id
        if channel_id and (ch := interaction.guild.get_channel(channel_id)):
            sent = await ch.send(embed=_result_embed(match_id, winner_name, screenshot, notes))
            async with db.session_scope() as s:
                res = await MatchRepository(s).result_for(match_id)
                if res is not None:
                    res.announce_channel_id = ch.id
                    res.announce_message_id = sent.id
        await interaction.followup.send(
            f"✅ Result recorded for match #{match_id} — **{winner_name}** won.",
            ephemeral=True,
        )

    @match.command(
        name="retract",
        description="Undo a recorded result — reopens the chosen match for a replay (staff).",
    )
    @app_commands.describe(
        game="The game", match="The completed match to reopen", reason="Why (required)",
    )
    @app_commands.autocomplete(game=_game_autocomplete, match=_completed_match_autocomplete)
    async def retract(
        self, interaction: discord.Interaction, game: str, match: str, reason: str
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            match_id = int(match)
        except ValueError:
            await interaction.followup.send("Pick a match from the list.", ephemeral=True)
            return
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None or not await is_staff(interaction, s, event.id, self.bot.settings):
                await interaction.followup.send("Staff only.", ephemeral=True)
                return
            m = await s.get(Match, match_id)
            game_name = "game"
            if m is not None:
                g = await s.get(Game, m.game_id)
                game_name = g.name if g else "game"
            # Capture the announcement message before the result row is deleted.
            res = await MatchRepository(s).result_for(match_id)
            ann_channel = res.announce_channel_id if res else None
            ann_message = res.announce_message_id if res else None
            try:
                await MatchService(s).retract(
                    event_id=event.id, match_id=match_id, reason=reason,
                    actor_discord_id=interaction.user.id, actor_username=str(interaction.user),
                )
            except (ServiceError, ValueError) as exc:
                await interaction.followup.send(f"❌ {exc}", ephemeral=True)
                return
            event_id = event.id
            resources = DiscordResourceService(
                DiscordResourceGateway(interaction.guild), SqlResourceRepository(s)
            )
            channel_id = await resources.find(
                event_id, ResourceOwnerType.GAME, None, f"game_battle_results:{slug(game_name)}"
            )
        # Delete the original result announcement, then post a retraction notice.
        await _delete_announcement(interaction.guild, ann_channel, ann_message)
        if channel_id and (ch := interaction.guild.get_channel(channel_id)):
            await ch.send(
                embed=discord.Embed(
                    title=f"↩️ Match #{match_id} result retracted",
                    colour=discord.Colour.orange(),
                    description=f"The result was voided — replay pending.\n**Reason:** {reason}",
                )
            )
        await interaction.followup.send(
            f"↩️ Retracted match #{match_id}. It's reopened — record it again with "
            "`/match battle-ended`.",
            ephemeral=True,
        )

    @match.command(
        name="undo-correction",
        description="Step back the last correction on a match, restoring its previous winner (staff).",
    )
    @app_commands.describe(
        game="The game", match="The corrected match", reason="Why (required)",
    )
    @app_commands.autocomplete(game=_game_autocomplete, match=_completed_match_autocomplete)
    async def undo_correction(
        self, interaction: discord.Interaction, game: str, match: str, reason: str
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            match_id = int(match)
        except ValueError:
            await interaction.followup.send("Pick a match from the list.", ephemeral=True)
            return
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None or not await is_staff(interaction, s, event.id, self.bot.settings):
                await interaction.followup.send("Staff only.", ephemeral=True)
                return
            try:
                restored = await MatchService(s).undo_correction(
                    event_id=event.id, match_id=match_id, reason=reason,
                    actor_discord_id=interaction.user.id, actor_username=str(interaction.user),
                )
            except (ServiceError, ValueError) as exc:
                await interaction.followup.send(f"❌ {exc}", ephemeral=True)
                return
            team = await s.get(Team, restored)
            res = await MatchRepository(s).result_for(match_id)
            ann_channel = res.announce_channel_id if res else None
            ann_message = res.announce_message_id if res else None
            screenshot = res.screenshot_url if res else None
            notes = res.notes if res else None
        team_name = team.name if team else restored
        await _edit_announcement(
            interaction.guild, ann_channel, ann_message,
            _result_embed(match_id, team_name, screenshot, notes),
        )
        await interaction.followup.send(
            f"↩️ Undid the last correction on match #{match_id} — winner restored to "
            f"**{team_name}**.",
            ephemeral=True,
        )

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
            res = await MatchRepository(s).result_for(match_id)
            ann_channel = res.announce_channel_id if res else None
            ann_message = res.announce_message_id if res else None
            screenshot = res.screenshot_url if res else None
            notes = res.notes if res else None
            winner_team = await s.get(Team, winner_team_id)
        winner_name = winner_team.name if winner_team else winner_team_id
        await _edit_announcement(
            interaction.guild, ann_channel, ann_message,
            _result_embed(match_id, winner_name, screenshot, notes),
        )
        await interaction.followup.send(
            f"Corrected match #{match_id} — winner is now **{winner_name}**.", ephemeral=True
        )


async def setup(bot: EsportsBot) -> None:
    await bot.add_cog(MatchesCog(bot))
