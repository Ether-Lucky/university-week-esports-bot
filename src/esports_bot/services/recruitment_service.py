"""Recruitment use-cases (docs §13, FR-9). Requests expire after a timeout."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from ..domain import validators
from ..domain.enums import (
    EventState,
    RecruitmentPostStatus,
    RecruitRequestStatus,
    TeamStatus,
)
from ..infra import audit
from ..models import RecruitmentPost, RecruitmentRequest, User
from ..repositories.core import EventRepository, UserRepository
from ..repositories.recruitment import RecruitmentRepository
from ..repositories.teams import TeamRepository
from .errors import ServiceError
from .team_service import TeamService


@dataclass
class RequestInfo:
    """Everything the cog needs to route DMs after resolving a request."""

    request_id: int
    kind: str  # "JOIN" or "RECRUIT"
    guild_id: int
    event_id: int
    team_id: int
    team_name: str
    game_slug: str
    joining_discord_id: int  # who ends up on the team (applicant/player)
    joining_name: str
    requester_discord_id: int  # who initiated the request
    decider_discord_id: int  # who accepts/rejects
    reason: str | None = None


class RecruitmentService:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session
        self.repo = RecruitmentRepository(session)
        self.events = EventRepository(session)
        self.users = UserRepository(session)
        self.teams = TeamRepository(session)

    async def create_lft_post(
        self, *, event_id: int, user_discord_id: int, username: str,
        ign: str, main_role: str | None, profile_url: str | None = None,
        stats_url: str | None = None,
    ) -> RecruitmentPost:
        """The game is taken from the applicant's approved application."""
        event = await self.events.get(event_id)
        if event is None or event.state not in (
            EventState.APPLICATIONS_OPEN, EventState.TEAM_FORMATION
        ):
            raise ServiceError("Team formation is not open right now.")
        user = await self.users.get_or_create(user_discord_id, username)
        application = await self.teams.approved_application(event_id, user.id)
        if application is None:
            raise ServiceError("Only approved applicants can post a looking-for-team profile.")
        if await self.teams.active_membership(event_id, user.id) is not None:
            raise ServiceError("You are already on a team.")
        if await self.repo.open_post_for_user(event_id, user.id) is not None:
            raise ServiceError(
                "You already have an active looking-for-team post. Cancel it with "
                "`/lft cancel` before posting a new one."
            )
        ign = validators.sanitize_name(ign, max_len=100, field="IGN")
        if main_role:
            main_role = validators.sanitize_name(main_role, max_len=100, field="Role")
        post = RecruitmentPost(
            event_id=event_id, game_id=application.game_id, user_id=user.id, ign=ign,
            main_role=main_role, profile_screenshot_url=profile_url,
            stats_screenshot_url=stats_url, status=RecruitmentPostStatus.OPEN,
        )
        self.repo.add_post(post)
        await self._s.flush()
        await audit.record(
            self._s, action="recruit.post", event_id=event_id, actor_user_id=user.id,
            entity_type="recruitment_post", entity_id=post.id,
        )
        return post

    async def set_forum_post(self, post_id: int, thread_id: int) -> None:
        post = await self.repo.get_post(post_id)
        if post is not None:
            post.forum_post_id = thread_id
            await self._s.flush()

    async def cancel_lft(
        self, *, event_id: int, target_discord_id: int, target_username: str,
        actor_discord_id: int, actor_username: str, staff: bool = False,
    ) -> int | None:
        """Close a user's open LFT post. Returns its forum thread ID (to delete)."""
        target = await self.users.get_or_create(target_discord_id, target_username)
        post = await self.repo.open_post_for_user(event_id, target.id)
        if post is None:
            raise ServiceError("No active looking-for-team post found.")
        thread_id = post.forum_post_id
        post.status = RecruitmentPostStatus.CLOSED
        await self._s.flush()
        actor = await self.users.get_or_create(actor_discord_id, actor_username)
        await audit.record(
            self._s, action="recruit.cancel_lft", event_id=event_id, actor_user_id=actor.id,
            entity_type="recruitment_post", entity_id=post.id,
            after={"by_staff": staff, "target": target.id},
        )
        return thread_id

    async def recruit(
        self, *, event_id: int, team_id: int, target_discord_id: int, target_username: str,
        requester_discord_id: int, requester_username: str, timeout_minutes: int,
    ) -> RecruitmentRequest:
        team = await self.teams.get(team_id)
        if team is None:
            raise ServiceError("Team not found.")
        requester = await self.users.get_or_create(requester_discord_id, requester_username)
        if team.leader_user_id != requester.id:
            raise ServiceError("Only the team leader can recruit.")
        if await self.teams.active_member_count(team.id) >= team.roster_size:
            raise ServiceError("Your team is already full.")
        target = await self.users.get_or_create(target_discord_id, target_username)
        if await self.teams.active_membership(event_id, target.id) is not None:
            raise ServiceError("That player is already on a team.")
        request = RecruitmentRequest(
            team_id=team.id, target_user_id=target.id, requested_by=requester.id,
            status=RecruitRequestStatus.PENDING,
            expires_at=datetime.now(UTC) + timedelta(minutes=timeout_minutes),
        )
        self.repo.add_request(request)
        await self._s.flush()
        await audit.record(
            self._s, action="recruit.request", event_id=event_id, actor_user_id=requester.id,
            entity_type="recruitment_request", entity_id=request.id,
            after={"target": target.id, "team": team.id},
        )
        return request

    async def _resolve(self, request_id: int, actor_id: int) -> RecruitmentRequest:
        request = await self.repo.get_request(request_id)
        if request is None:
            raise ServiceError("Recruitment request not found.")
        if request.status != RecruitRequestStatus.PENDING:
            raise ServiceError("This request is no longer pending.")
        if request.expires_at and datetime.now(UTC) > _aware(request.expires_at):
            request.status = RecruitRequestStatus.EXPIRED
            await self._s.flush()
            raise ServiceError("This recruitment request has expired.")
        return request

    async def request_join(
        self, *, event_id: int, team_id: int, applicant_discord_id: int,
        username: str, timeout_minutes: int,
    ) -> RecruitmentRequest:
        """An applicant asks to join a team; the leader must approve.

        Requires the applicant to have an LFT profile so the leader has something
        to look at (self-request is signalled by target == requester).
        """
        event = await self.events.get(event_id)
        if event is None or event.state not in (
            EventState.APPLICATIONS_OPEN, EventState.TEAM_FORMATION
        ):
            raise ServiceError("Team formation is not open right now.")
        team = await self.teams.get(team_id)
        if team is None or team.status == TeamStatus.DISBANDED:
            raise ServiceError("Team not found.")
        applicant = await self.users.get_or_create(applicant_discord_id, username)
        app = await self.teams.approved_application(event_id, applicant.id)
        if app is None:
            raise ServiceError("Only approved applicants can join a team.")
        if app.game_id != team.game_id:
            raise ServiceError("You can only join a team for the game you applied for.")
        if await self.teams.active_membership(event_id, applicant.id) is not None:
            raise ServiceError("You are already on a team.")
        if await self.teams.active_member_count(team.id) >= team.roster_size:
            raise ServiceError("That team is already full.")
        if await self.repo.open_post_for_user(event_id, applicant.id) is None:
            raise ServiceError(
                "Create your looking-for-team profile with `/findteam` first, then try to join "
                "again — leaders review your profile before accepting."
            )
        request = RecruitmentRequest(
            team_id=team.id, target_user_id=applicant.id, requested_by=applicant.id,
            status=RecruitRequestStatus.PENDING,
            expires_at=datetime.now(UTC) + timedelta(minutes=timeout_minutes),
        )
        self.repo.add_request(request)
        await self._s.flush()
        await audit.record(
            self._s, action="recruit.join_request", event_id=event_id,
            actor_user_id=applicant.id, entity_type="recruitment_request", entity_id=request.id,
            after={"team": team.id},
        )
        return request

    async def _classify(self, request: RecruitmentRequest):
        """Return (team, event, is_join). is_join means the applicant self-requested."""
        team = await self.teams.get(request.team_id)
        if team is None:
            raise ServiceError("Team not found.")
        event = await self.events.get(team.event_id)
        is_join = request.target_user_id == request.requested_by
        return team, event, is_join

    async def _check_decider(self, request, team, actor_id: int, is_join: bool) -> None:
        if is_join and actor_id != team.leader_user_id:
            raise ServiceError("Only the team leader can decide this request.")
        if not is_join and actor_id != request.target_user_id:
            raise ServiceError("This recruitment request isn't yours to decide.")

    async def _info(self, request, team, event, is_join, reason=None) -> RequestInfo:
        from ..domain.server_blueprint import slug

        joining_id = request.requested_by if is_join else request.target_user_id
        joining = await self._s.get(User, joining_id)
        requester = await self._s.get(User, request.requested_by)
        decider_internal = team.leader_user_id if is_join else request.target_user_id
        decider = await self._s.get(User, decider_internal)
        from ..models import Game

        game = await self._s.get(Game, team.game_id)
        return RequestInfo(
            request_id=request.id, kind="JOIN" if is_join else "RECRUIT",
            guild_id=event.guild_id, event_id=event.id, team_id=team.id, team_name=team.name,
            game_slug=slug(game.name) if game else "",
            joining_discord_id=joining.discord_user_id, joining_name=joining.discord_username,
            requester_discord_id=requester.discord_user_id,
            decider_discord_id=decider.discord_user_id, reason=reason,
        )

    async def accept_request(
        self, *, request_id: int, actor_discord_id: int, actor_username: str
    ) -> RequestInfo:
        actor = await self.users.get_or_create(actor_discord_id, actor_username)
        request = await self._resolve(request_id, actor.id)
        team, event, is_join = await self._classify(request)
        await self._check_decider(request, team, actor.id, is_join)
        joining_id = request.requested_by if is_join else request.target_user_id
        joining = await self._s.get(User, joining_id)
        await TeamService(self._s).join_team(
            event_id=event.id, team_id=team.id,
            user_discord_id=joining.discord_user_id, username=joining.discord_username,
        )
        request.status = RecruitRequestStatus.ACCEPTED
        request.resolved_at = datetime.now(UTC)
        await self._s.flush()
        await audit.record(
            self._s, action="recruit.accept", event_id=event.id, actor_user_id=actor.id,
            entity_type="recruitment_request", entity_id=request.id,
        )
        return await self._info(request, team, event, is_join)

    async def reject_request(
        self, *, request_id: int, actor_discord_id: int, actor_username: str, reason: str
    ) -> RequestInfo:
        if not reason or not reason.strip():
            raise ServiceError("A reason is required to reject.")
        actor = await self.users.get_or_create(actor_discord_id, actor_username)
        request = await self._resolve(request_id, actor.id)
        team, event, is_join = await self._classify(request)
        await self._check_decider(request, team, actor.id, is_join)
        request.status = RecruitRequestStatus.DECLINED
        request.resolved_at = datetime.now(UTC)
        await self._s.flush()
        await audit.record(
            self._s, action="recruit.reject", event_id=event.id, actor_user_id=actor.id,
            entity_type="recruitment_request", entity_id=request.id,
            after={"reason": reason.strip()},
        )
        return await self._info(request, team, event, is_join, reason=reason.strip())


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
