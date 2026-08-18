"""Teams cog — create/join/leave/disband/rename, with Discord resource provisioning."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from ..bot import EsportsBot
from ..domain.enums import ResourceOwnerType, ResourceType, TeamMemberRole, TeamStatus
from ..domain.server_blueprint import slug
from ..infra import dashboard, db
from ..infra.discord_gateway import DiscordResourceGateway
from ..infra.discord_resources import DiscordResourceService
from ..infra.resource_repository import SqlResourceRepository
from ..models import Game, Team, User
from ..repositories.core import EventRepository, UserRepository
from ..repositories.recruitment import RecruitmentRepository
from ..repositories.teams import TeamRepository
from ..services.errors import ServiceError
from ..services.recruitment_service import RecruitmentService
from ..services.team_service import TeamService

log = logging.getLogger(__name__)


async def _team_display(session, team_id: int):
    """Return (team, game, roster_labels) for building the forum embed."""
    repo = TeamRepository(session)
    team = await repo.get(team_id)
    if team is None:
        return None, None, []
    game = await session.get(Game, team.game_id)
    labels = []
    for m in await repo.active_members(team.id):
        user = await session.get(User, m.user_id)
        label = (user.discord_display_name or user.discord_username) if user else "?"
        if m.role_in_team == TeamMemberRole.LEADER:
            label += " 👑"
        labels.append(label)
    return team, game, labels


def _team_embed(team, game_name: str, roster_labels: list[str]) -> discord.Embed:
    embed = discord.Embed(title=f"TEAM: {team.name}", colour=discord.Colour.blurple())
    if team.logo_url:
        embed.set_thumbnail(url=team.logo_url)
    embed.add_field(name="Game", value=game_name, inline=True)
    embed.add_field(name="Status", value=team.status.value, inline=True)
    roster = "\n".join(f"{i}. {n}" for i, n in enumerate(roster_labels, 1)) or "—"
    embed.add_field(
        name=f"Roster ({len(roster_labels)}/{team.roster_size})", value=roster, inline=False
    )
    embed.set_footer(text=f"Team #{team.id} · press Join Team to request a spot")
    return embed


class JoinTeamButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"esports:jointeam:(?P<team_id>\d+)",
):
    """Persistent per-team Join button on the forum post."""

    def __init__(self, team_id: int) -> None:
        self.team_id = team_id
        super().__init__(
            discord.ui.Button(
                label="Join Team", style=discord.ButtonStyle.success,
                custom_id=f"esports:jointeam:{team_id}",
            )
        )

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls(int(match["team_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        await submit_join_request(interaction, self.team_id)


async def submit_join_request(interaction: discord.Interaction, team_id: int) -> None:
    """Create a join request and DM the team leader for approval."""
    async with db.session_scope() as s:
        event = await EventRepository(s).get_active(interaction.guild_id)
        if event is None:
            await interaction.followup.send("No active event.", ephemeral=True)
            return
        try:
            request = await RecruitmentService(s).request_join(
                event_id=event.id, team_id=team_id,
                applicant_discord_id=interaction.user.id, username=str(interaction.user),
                timeout_minutes=interaction.client.settings.recruit_timeout_minutes,
            )
            request_id = request.id
            team = await TeamRepository(s).get(team_id)
            leader = await s.get(User, team.leader_user_id)
            leader_discord_id, team_name, guild_id = (
                leader.discord_user_id, team.name, interaction.guild_id
            )
            applicant = await UserRepository(s).get_or_create(
                interaction.user.id, str(interaction.user)
            )
            lft = await RecruitmentRepository(s).open_post_for_user(event.id, applicant.id)
            lft_thread_id = lft.forum_post_id if lft else None
        except (ServiceError, ValueError) as exc:
            await interaction.followup.send(f"❌ {exc}", ephemeral=True)
            return

    from .recruitment import send_request_dm

    embed = discord.Embed(
        title="📥 Join Request", colour=discord.Colour.blurple(),
        description=f"**{interaction.user.display_name}** wants to join your team **{team_name}**.",
    )
    if lft_thread_id:
        link = f"https://discord.com/channels/{guild_id}/{lft_thread_id}"
        embed.add_field(name="Their profile", value=f"[View their LFT post]({link})", inline=False)
    embed.set_footer(text="Accept to add them, or Reject with a reason.")
    delivered = await send_request_dm(interaction.client, leader_discord_id, embed, request_id)
    msg = (
        "✅ Your request to join was sent to the team leader for approval."
        if delivered
        else f"✅ Request sent (couldn't DM the leader — request #{request_id})."
    )
    await interaction.followup.send(msg, ephemeral=True)


def _join_view(team_id: int) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(JoinTeamButton(team_id))
    return view


async def post_team_forum(
    guild: discord.Guild, event_id: int, team_id: int, game_slug: str
) -> None:
    """Create the team's forum post with roster + Join button; record its thread ID."""
    async with db.session_scope() as s:
        resources = DiscordResourceService(DiscordResourceGateway(guild), SqlResourceRepository(s))
        forum_id = await resources.find(
            event_id, ResourceOwnerType.GAME, None, f"game_team_forum:{game_slug}"
        )
        team, game, labels = await _team_display(s, team_id)
    forum = guild.get_channel(forum_id) if forum_id else None
    if forum is None or team is None or not isinstance(forum, discord.ForumChannel):
        return
    embed = _team_embed(team, game.name, labels)
    created = await forum.create_thread(name=team.name[:100], embed=embed, view=_join_view(team_id))
    async with db.session_scope() as s:
        resources = DiscordResourceService(DiscordResourceGateway(guild), SqlResourceRepository(s))
        await resources.register_existing(
            event_id, ResourceType.FORUM_POST, ResourceOwnerType.TEAM, team_id,
            f"team_forum_post:{team_id}", created.thread.id,
        )


async def refresh_team_forum(guild: discord.Guild, event_id: int, team_id: int) -> None:
    """Update the team's forum post embed to reflect the current roster/status."""
    async with db.session_scope() as s:
        resources = DiscordResourceService(DiscordResourceGateway(guild), SqlResourceRepository(s))
        thread_id = await resources.find(
            event_id, ResourceOwnerType.TEAM, team_id, f"team_forum_post:{team_id}"
        )
        team, game, labels = await _team_display(s, team_id)
    if thread_id is None or team is None:
        return
    thread = guild.get_thread(thread_id)
    if thread is None:
        try:
            thread = await guild.fetch_channel(thread_id)
        except discord.HTTPException:
            return
    # Drop the Join button once the team can't take anyone else.
    full = (
        team.status in (TeamStatus.FULL, TeamStatus.DISBANDED)
        or len(labels) >= team.roster_size
    )
    view = None if full else _join_view(team_id)
    try:
        starter = await thread.fetch_message(thread.id)  # forum starter message id == thread id
        await starter.edit(embed=_team_embed(team, game.name, labels), view=view)
    except discord.HTTPException:
        pass


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
        voice_id = await resources.ensure_voice_channel(
            event_id, ResourceOwnerType.TEAM, team.id, f"team_voice:{team.id}",
            f"team-{slug(team.name)}", category_id=cat_id,
        )
    # Lock both team channels to the team role (staff inherit via game category).
    role = guild.get_role(role_id)
    if role:
        text = guild.get_channel(text_id)
        if text:
            await text.set_permissions(guild.default_role, view_channel=False)
            await text.set_permissions(role, view_channel=True, send_messages=True)
        voice = guild.get_channel(voice_id)
        if voice:
            await voice.set_permissions(guild.default_role, view_channel=False, connect=False)
            await voice.set_permissions(role, view_channel=True, connect=True)


async def _delete_forum_thread(guild: discord.Guild, thread_id: int | None) -> None:
    if thread_id is None:
        return
    thread = guild.get_thread(thread_id)
    if thread is None:
        try:
            thread = await guild.fetch_channel(thread_id)
        except discord.HTTPException:
            return
    try:
        await thread.delete()
    except discord.HTTPException:
        pass


async def close_own_lft(
    guild: discord.Guild, event_id: int, discord_user_id: int, name: str
) -> None:
    """If the user has an open LFT post, close it + delete its thread (they're on a team now)."""
    async with db.session_scope() as s:
        try:
            thread_id = await RecruitmentService(s).cancel_lft(
                event_id=event_id, target_discord_id=discord_user_id, target_username=name,
                actor_discord_id=discord_user_id, actor_username=name,
            )
        except ServiceError:
            thread_id = None
    await _delete_forum_thread(guild, thread_id)


async def grant_team_role(
    guild: discord.Guild, event_id: int, team_id: int, discord_user_id: int
) -> None:
    async with db.session_scope() as s:
        resources = DiscordResourceService(
            DiscordResourceGateway(guild), SqlResourceRepository(s)
        )
        role_id = await resources.find(
            event_id, ResourceOwnerType.TEAM, team_id, f"team_role:{team_id}"
        )
    member = guild.get_member(discord_user_id)
    role = guild.get_role(role_id) if role_id else None
    if member and role:
        await member.add_roles(role, reason="Team membership")


async def revoke_team_role(
    guild: discord.Guild, event_id: int, team_id: int, discord_user_id: int
) -> None:
    async with db.session_scope() as s:
        resources = DiscordResourceService(
            DiscordResourceGateway(guild), SqlResourceRepository(s)
        )
        role_id = await resources.find(
            event_id, ResourceOwnerType.TEAM, team_id, f"team_role:{team_id}"
        )
    member = guild.get_member(discord_user_id)
    role = guild.get_role(role_id) if role_id else None
    if member and role and role in member.roles:
        try:
            await member.remove_roles(role, reason="Removed from team")
        except discord.HTTPException:
            pass


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
        await grant_team_role(interaction.guild, event_id, team_id, interaction.user.id)
        await post_team_forum(interaction.guild, event_id, team_id, slug(game_name))
        # Leader now has a team — close their own LFT post if they had one.
        await close_own_lft(
            interaction.guild, event_id, interaction.user.id, str(interaction.user)
        )
        async with db.session_scope() as s:
            from ..infra.logchannel import post_log

            await post_log(
                s, interaction.guild, event_id, "teams",
                f"🆕 Team '{team_name}' created", f"by {interaction.user.mention}",
            )
        await dashboard.refresh(interaction.guild, event_id)
        await interaction.followup.send(
            f"✅ Created team **{team_name}** and posted it to the team forum. You're the leader.",
            ephemeral=True,
        )

    @team.command(name="join", description="Request to join a team by its ID (leader approves).")
    async def join(self, interaction: discord.Interaction, team_id: int) -> None:
        await interaction.response.defer(ephemeral=True)
        await submit_join_request(interaction, team_id)

    @team.command(name="leave", description="Leave your team.")
    async def leave(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None:
                await interaction.followup.send("No active event.", ephemeral=True)
                return
            from ..repositories.core import UserRepository

            user = await UserRepository(s).get_or_create(
                interaction.user.id, str(interaction.user)
            )
            membership = await TeamRepository(s).active_membership(event.id, user.id)
            team_id = membership.team_id if membership else None
            try:
                await TeamService(s).leave_team(
                    event_id=event.id, user_discord_id=interaction.user.id,
                    username=str(interaction.user),
                )
                event_id = event.id
                team = await TeamRepository(s).get(team_id) if team_id else None
                disbanded = team is not None and team.status == TeamStatus.DISBANDED
            except (ServiceError, ValueError) as exc:
                await interaction.followup.send(f"❌ {exc}", ephemeral=True)
                return
        if team_id is not None:
            if disbanded:
                # Last member left -> tear down the team's channels, role, and forum post.
                await self._teardown_team(interaction.guild, event_id, team_id)
            else:
                await refresh_team_forum(interaction.guild, event_id, team_id)
            await dashboard.refresh(interaction.guild, event_id)
        await interaction.followup.send("You left your team.", ephemeral=True)

    @team.command(name="kick", description="Remove a member from your team (leader only).")
    @app_commands.describe(member="The team member to remove")
    async def kick(
        self, interaction: discord.Interaction, member: discord.Member
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None:
                await interaction.followup.send("No active event.", ephemeral=True)
                return
            try:
                team_id = await TeamService(s).kick_member(
                    event_id=event.id,
                    actor_discord_id=interaction.user.id, actor_username=str(interaction.user),
                    target_discord_id=member.id, target_username=str(member),
                )
                event_id = event.id
            except (ServiceError, ValueError) as exc:
                await interaction.followup.send(f"❌ {exc}", ephemeral=True)
                return
            from ..infra.logchannel import post_log

            await post_log(
                s, interaction.guild, event_id, "teams",
                "👢 Member kicked from a team",
                f"{member.mention} — by {interaction.user.mention}",
                colour=discord.Colour.orange(),
            )
        await revoke_team_role(interaction.guild, event_id, team_id, member.id)
        await refresh_team_forum(interaction.guild, event_id, team_id)
        try:
            await member.send(
                "You've been removed from your team. You can join another team with "
                "`/team join` or post yourself with `/findteam`."
            )
        except discord.HTTPException:
            pass
        await interaction.followup.send(
            f"✅ Removed {member.mention} from the team.", ephemeral=True
        )

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

    @team.command(
        name="resync-posts",
        description="Re-sync every team's forum post (roster + Join button) — staff.",
    )
    async def resync_posts(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        from sqlalchemy import select

        from .checks import is_staff

        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None or not await is_staff(interaction, s, event.id, self.bot.settings):
                await interaction.followup.send("Staff only.", ephemeral=True)
                return
            event_id = event.id
            team_ids = list(
                (
                    await s.execute(
                        select(Team.id).where(
                            Team.event_id == event_id, Team.status != TeamStatus.DISBANDED
                        )
                    )
                ).scalars()
            )
        for tid in team_ids:
            await refresh_team_forum(interaction.guild, event_id, tid)
        await interaction.followup.send(
            f"Re-synced {len(team_ids)} team forum post(s).", ephemeral=True
        )

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
        await dashboard.refresh(interaction.guild, event_id)
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
    bot.add_dynamic_items(JoinTeamButton)  # persistent per-team Join buttons
    await bot.add_cog(TeamsCog(bot))
