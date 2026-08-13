"""Team management use-cases (docs §11-14, FR-7/FR-8)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from ..domain import states, validators
from ..domain.enums import ApplicationStatus, EventState, TeamMemberRole, TeamStatus
from ..infra import audit
from ..models import Team, TeamMember
from ..repositories.core import EventRepository, GameRepository, UserRepository
from ..repositories.teams import TeamRepository
from .errors import ServiceError

# Teams can form while applications are still open AND during dedicated team
# formation — so approved applicants can start teaming up immediately.
_TEAM_STATES = {EventState.APPLICATIONS_OPEN, EventState.TEAM_FORMATION}


class TeamService:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session
        self.teams = TeamRepository(session)
        self.events = EventRepository(session)
        self.games = GameRepository(session)
        self.users = UserRepository(session)

    async def _require_formation(self, event_id: int, *, staff: bool):
        event = await self.events.get(event_id)
        if event is None:
            raise ServiceError("No active event.")
        if event.state not in _TEAM_STATES and not staff:
            raise ServiceError(f"Teams can't be changed while the event is {event.state}.")
        return event

    async def create_team(
        self, *, event_id: int, game_id: int, name: str, logo_url: str | None,
        leader_discord_id: int, leader_username: str, staff: bool = False,
    ) -> Team:
        await self._require_formation(event_id, staff=staff)
        eg = await self.games.get_event_game(event_id, game_id)
        if eg is None:
            raise ServiceError("That game is not part of this event.")
        name = validators.sanitize_name(name, max_len=100, field="Team name")
        if logo_url:
            logo_url = validators.validate_https_url(logo_url, field="Logo URL")
        if await self.teams.get_by_name(event_id, game_id, name) is not None:
            raise ServiceError(f"A team named '{name}' already exists for this game.")

        leader = await self.users.get_or_create(leader_discord_id, leader_username)
        application = await self.teams.approved_application(event_id, leader.id)
        if application is None:
            raise ServiceError("Only approved applicants can create a team.")
        if application.game_id != game_id:
            raise ServiceError("You can only create a team for the game you applied for.")
        if await self.teams.active_membership(event_id, leader.id) is not None:
            raise ServiceError("You are already on a team.")

        team = Team(
            event_id=event_id, game_id=game_id, name=name, logo_url=logo_url,
            leader_user_id=leader.id, roster_size=eg.roster_size,
            status=TeamStatus.RECRUITING,
        )
        self.teams.add(team)
        await self._s.flush()
        self.teams.add_member(
            TeamMember(
                event_id=event_id, team_id=team.id, user_id=leader.id,
                role_in_team=TeamMemberRole.LEADER, active=True,
            )
        )
        application.status = ApplicationStatus.ASSIGNED_TO_TEAM
        application.team_id = team.id
        await self._s.flush()
        await audit.record(
            self._s, action="team.create", event_id=event_id, actor_user_id=leader.id,
            entity_type="team", entity_id=team.id, after={"name": name, "game_id": game_id},
        )
        return team

    async def join_team(
        self, *, event_id: int, team_id: int, user_discord_id: int, username: str,
    ) -> Team:
        await self._require_formation(event_id, staff=False)
        team = await self.teams.get(team_id)
        if team is None or team.status == TeamStatus.DISBANDED:
            raise ServiceError("Team not found.")
        user = await self.users.get_or_create(user_discord_id, username)
        application = await self.teams.approved_application(event_id, user.id)
        if application is None:
            raise ServiceError("Only approved applicants can join a team.")
        if application.game_id != team.game_id:
            raise ServiceError("You can only join a team for the game you applied for.")
        if await self.teams.active_membership(event_id, user.id) is not None:
            raise ServiceError("You are already on a team.")
        if await self.teams.active_member_count(team.id) >= team.roster_size:
            raise ServiceError("That team is already full.")

        self.teams.add_member(
            TeamMember(
                event_id=event_id, team_id=team.id, user_id=user.id,
                role_in_team=TeamMemberRole.MEMBER, active=True,
            )
        )
        application.status = ApplicationStatus.ASSIGNED_TO_TEAM
        application.team_id = team.id
        await self._s.flush()
        if await self.teams.active_member_count(team.id) >= team.roster_size:
            states.assert_transition("team", team.status, TeamStatus.FULL)
            team.status = TeamStatus.FULL
        await self._s.flush()
        await audit.record(
            self._s, action="team.join", event_id=event_id, actor_user_id=user.id,
            entity_type="team", entity_id=team.id, after={"user_id": user.id},
        )
        return team

    async def _free_member(self, event_id: int, member: TeamMember) -> None:
        member.active = False
        member.left_at = datetime.now(UTC)
        app = await self.teams.approved_application(event_id, member.user_id)
        if app is not None and app.status == ApplicationStatus.ASSIGNED_TO_TEAM:
            app.status = ApplicationStatus.APPROVED
            app.team_id = None

    async def leave_team(self, *, event_id: int, user_discord_id: int, username: str) -> None:
        await self._require_formation(event_id, staff=False)
        user = await self.users.get_or_create(user_discord_id, username)
        membership = await self.teams.active_membership(event_id, user.id)
        if membership is None:
            raise ServiceError("You are not on a team.")
        team = await self.teams.get(membership.team_id)
        members = await self.teams.active_members(team.id)
        if membership.role_in_team == TeamMemberRole.LEADER and len(members) > 1:
            raise ServiceError("Transfer leadership before leaving, or disband the team.")
        await self._free_member(event_id, membership)
        await self._s.flush()
        if len(members) <= 1:
            team.status = TeamStatus.DISBANDED
            team.disbanded_at = datetime.now(UTC)
        elif team.status == TeamStatus.FULL:
            team.status = TeamStatus.RECRUITING
        await self._s.flush()
        await audit.record(
            self._s, action="team.leave", event_id=event_id, actor_user_id=user.id,
            entity_type="team", entity_id=team.id,
        )

    async def disband(
        self, *, event_id: int, team_id: int, actor_discord_id: int, actor_username: str,
        reason: str | None = None, staff: bool = False,
    ) -> Team:
        team = await self.teams.get(team_id)
        if team is None:
            raise ServiceError("Team not found.")
        actor = await self.users.get_or_create(actor_discord_id, actor_username)
        if not staff and team.leader_user_id != actor.id:
            raise ServiceError("Only the team leader or staff can disband this team.")
        for member in await self.teams.active_members(team.id):
            await self._free_member(event_id, member)
        team.status = TeamStatus.DISBANDED
        team.disbanded_at = datetime.now(UTC)
        await self._s.flush()
        await audit.record(
            self._s, action="team.disband", event_id=event_id, actor_user_id=actor.id,
            entity_type="team", entity_id=team.id, after={"reason": reason},
        )
        return team

    async def rename(
        self, *, event_id: int, team_id: int, new_name: str,
        actor_discord_id: int, actor_username: str, staff: bool = False,
    ) -> Team:
        team = await self.teams.get(team_id)
        if team is None:
            raise ServiceError("Team not found.")
        actor = await self.users.get_or_create(actor_discord_id, actor_username)
        if not staff and team.leader_user_id != actor.id:
            raise ServiceError("Only the leader or staff can rename this team.")
        new_name = validators.sanitize_name(new_name, max_len=100, field="Team name")
        if await self.teams.get_by_name(event_id, team.game_id, new_name):
            raise ServiceError("A team with that name already exists.")
        before = team.name
        team.name = new_name
        await self._s.flush()
        await audit.record(
            self._s, action="team.rename", event_id=event_id, actor_user_id=actor.id,
            entity_type="team", entity_id=team.id,
            before={"name": before}, after={"name": new_name},
        )
        return team

    async def transfer_leadership(
        self, *, event_id: int, team_id: int, new_leader_user_id: int,
        actor_discord_id: int, actor_username: str, staff: bool = False,
    ) -> Team:
        team = await self.teams.get(team_id)
        if team is None:
            raise ServiceError("Team not found.")
        actor = await self.users.get_or_create(actor_discord_id, actor_username)
        if not staff and team.leader_user_id != actor.id:
            raise ServiceError("Only the current leader or staff can transfer leadership.")
        members = {m.user_id: m for m in await self.teams.active_members(team.id)}
        if new_leader_user_id not in members:
            raise ServiceError("The new leader must be an active team member.")
        if team.leader_user_id in members:
            members[team.leader_user_id].role_in_team = TeamMemberRole.MEMBER
        members[new_leader_user_id].role_in_team = TeamMemberRole.LEADER
        team.leader_user_id = new_leader_user_id
        await self._s.flush()
        await audit.record(
            self._s, action="team.transfer", event_id=event_id, actor_user_id=actor.id,
            entity_type="team", entity_id=team.id, after={"new_leader": new_leader_user_id},
        )
        return team
