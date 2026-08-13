"""Teams cog — create/join/leave/disband/rename, with Discord resource provisioning."""

from __future__ import annotations

import logging

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
from ..models import Game, User
from ..repositories.core import EventRepository
from ..repositories.teams import TeamRepository
from ..services.errors import ServiceError
from ..services.team_service import TeamService

log = logging.getLogger(__name__)


async def _provision_team(guild: discord.Guild, event_id: int, team, game_name: str) -> None:
    """Create team role + text/voice channels under the game category; grant the role."""
    s_slug = slug(game_name)
    async with db.session_scope() as s:
        resources = DiscordResourceService(
            DiscordResourceGateway(guild), SqlResourceRepository(s)
        )
        cat_id = await resources.find(
            event_id, ResourceOwnerType.GAME, None, f"cat_game:{s_slug}"
        )
        role_id = await resources.ensure_role(
            event_id, ResourceOwnerType.TEAM, team.id, f"team_role:{team.id}",
            f"Team {team.name}",
        )
        text_id = await resources.ensure_text_channel(
            event_id, ResourceOwnerType.TEAM, team.id, f"team_text:{team.id}",
            f"team-{slug(team.name)}", category_id=cat_id,
        )
        await resources.ensure_voice_channel(
            event_id, ResourceOwnerType.TEAM, team.id, f"team_voice:{team.id}",
            f"team-{slug(team.name)}", category_id=cat_id,
        )
    # Lock the team channels to the team role + staff.
    role = guild.get_role(role_id)
    if role:
        for ch_id in (text_id,):
            ch = guild.get_channel(ch_id)
            if ch:
                await ch.set_permissions(guild.default_role, view_channel=False)
                await ch.set_permissions(role, view_channel=True, send_messages=True)


async def _grant_team_role(guild: discord.Guild, event_id: int, team_id: int, member) -> None:
    async with db.session_scope() as s:
        resources = DiscordResourceService(
            DiscordResourceGateway(guild), SqlResourceRepository(s)
        )
        role_id = await resources.find(
            event_id, ResourceOwnerType.TEAM, team_id, f"team_role:{team_id}"
        )
    if role_id and (role := guild.get_role(role_id)) and member:
        await member.add_roles(role, reason="Team membership")


class TeamsCog(commands.Cog):
    def __init__(self, bot: EsportsBot) -> None:
        self.bot = bot

    team = app_commands.Group(name="team", description="Team management.", guild_only=True)

    async def _game_choices(self, event_id: int) -> list[tuple[int, str]]:
        async with db.session_scope() as s:
            from ..repositories.core import GameRepository

            games = await GameRepository(s).list_games_for_event(event_id)
            return [(g.id, g.name) for g in games]

    @team.command(name="create", description="Create a team for the game you applied for.")
    @app_commands.describe(name="Team name", logo="Logo image URL (optional)")
    async def create(
        self, interaction: discord.Interaction, name: str, logo: str | None = None
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None:
                await interaction.followup.send("No active event.", ephemeral=True)
                return
            try:
                team = await TeamService(s).create_team(
                    event_id=event.id, name=name, logo_url=logo,
                    leader_discord_id=interaction.user.id,
                    leader_username=str(interaction.user),
                )
                game = await s.get(Game, team.game_id)
                team_id, team_name, game_name, event_id = team.id, team.name, game.name, event.id
            except (ServiceError, ValueError) as exc:
                await interaction.followup.send(f"❌ {exc}", ephemeral=True)
                return
        await _provision_team(interaction.guild, event_id, team, game_name)
        await _grant_team_role(interaction.guild, event_id, team_id, interaction.user)
        async with db.session_scope() as s:
            from ..infra.logchannel import post_log

            await post_log(
                s, interaction.guild, event_id, "teams",
                f"🆕 Team '{team_name}' created", f"by {interaction.user.mention}",
            )
        await interaction.followup.send(
            f"✅ Created team **{team_name}**. You're the leader.", ephemeral=True
        )

    @team.command(name="join", description="Join a team by its ID.")
    async def join(self, interaction: discord.Interaction, team_id: int) -> None:
        await interaction.response.defer(ephemeral=True)
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None:
                await interaction.followup.send("No active event.", ephemeral=True)
                return
            try:
                team = await TeamService(s).join_team(
                    event_id=event.id, team_id=team_id,
                    user_discord_id=interaction.user.id, username=str(interaction.user),
                )
                name, event_id = team.name, event.id
            except (ServiceError, ValueError) as exc:
                await interaction.followup.send(f"❌ {exc}", ephemeral=True)
                return
        await _grant_team_role(interaction.guild, event_id, team_id, interaction.user)
        await interaction.followup.send(f"✅ Joined team **{name}**.", ephemeral=True)

    @team.command(name="leave", description="Leave your team.")
    async def leave(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None:
                await interaction.followup.send("No active event.", ephemeral=True)
                return
            try:
                await TeamService(s).leave_team(
                    event_id=event.id, user_discord_id=interaction.user.id,
                    username=str(interaction.user),
                )
            except (ServiceError, ValueError) as exc:
                await interaction.followup.send(f"❌ {exc}", ephemeral=True)
                return
        await interaction.followup.send("You left your team.", ephemeral=True)

    @team.command(name="view", description="View a team's roster.")
    async def view(self, interaction: discord.Interaction, team_id: int) -> None:
        await interaction.response.defer(ephemeral=True)
        async with db.session_scope() as s:
            repo = TeamRepository(s)
            team = await repo.get(team_id)
            if team is None:
                await interaction.followup.send("Team not found.", ephemeral=True)
                return
            members = await repo.active_members(team.id)
            names = []
            for m in members:
                user = await s.get(User, m.user_id)
                names.append(f"<@{user.discord_user_id}> ({m.role_in_team.value})")
            game = await s.get(Game, team.game_id)
        embed = discord.Embed(title=f"Team {team.name}", colour=discord.Colour.blurple())
        embed.add_field(name="Game", value=game.name, inline=True)
        embed.add_field(name="Status", value=team.status.value, inline=True)
        embed.add_field(
            name=f"Roster ({len(names)}/{team.roster_size})",
            value="\n".join(names) or "—", inline=False,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @team.command(name="disband", description="Disband a team (leader or staff).")
    async def disband(
        self, interaction: discord.Interaction, team_id: int, reason: str | None = None
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        from .checks import is_staff

        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None:
                await interaction.followup.send("No active event.", ephemeral=True)
                return
            staff = await is_staff(interaction, s, event.id, self.bot.settings)
            try:
                await TeamService(s).disband(
                    event_id=event.id, team_id=team_id, reason=reason,
                    actor_discord_id=interaction.user.id, actor_username=str(interaction.user),
                    staff=staff,
                )
                event_id = event.id
            except (ServiceError, ValueError) as exc:
                await interaction.followup.send(f"❌ {exc}", ephemeral=True)
                return
        await self._teardown_team(interaction.guild, event_id, team_id)
        await interaction.followup.send("Team disbanded.", ephemeral=True)

    async def _teardown_team(self, guild: discord.Guild, event_id: int, team_id: int) -> None:
        async with db.session_scope() as s:
            repo = SqlResourceRepository(s)
            resources = DiscordResourceService(DiscordResourceGateway(guild), repo)
            from ..domain.enums import ResourceStatus

            for row in await repo.list_by_status(event_id, ResourceStatus.CREATED):
                if row.owner_type == ResourceOwnerType.TEAM and row.owner_id == team_id:
                    await resources.delete(row)


async def setup(bot: EsportsBot) -> None:
    await bot.add_cog(TeamsCog(bot))
