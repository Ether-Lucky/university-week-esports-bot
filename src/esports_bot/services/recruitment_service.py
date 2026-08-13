"""Recruitment use-cases (docs §13, FR-9). Requests expire after a timeout."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from ..domain import validators
from ..domain.enums import EventState, RecruitmentPostStatus, RecruitRequestStatus
from ..infra import audit
from ..models import RecruitmentPost, RecruitmentRequest
from ..repositories.core import EventRepository, UserRepository
from ..repositories.recruitment import RecruitmentRepository
from ..repositories.teams import TeamRepository
from .errors import ServiceError
from .team_service import TeamService


class RecruitmentService:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session
        self.repo = RecruitmentRepository(session)
        self.events = EventRepository(session)
        self.users = UserRepository(session)
        self.teams = TeamRepository(session)

    async def create_lft_post(
        self, *, event_id: int, game_id: int, user_discord_id: int, username: str,
        ign: str, main_role: str | None, profile_url: str | None, stats_url: str | None,
    ) -> RecruitmentPost:
        event = await self.events.get(event_id)
        if event is None or event.state != EventState.TEAM_FORMATION:
            raise ServiceError("Team formation is not open right now.")
        user = await self.users.get_or_create(user_discord_id, username)
        if await self.teams.approved_application(event_id, user.id) is None:
            raise ServiceError("Only approved applicants can post a looking-for-team profile.")
        if await self.teams.active_membership(event_id, user.id) is not None:
            raise ServiceError("You are already on a team.")
        ign = validators.sanitize_name(ign, max_len=100, field="IGN")
        post = RecruitmentPost(
            event_id=event_id, game_id=game_id, user_id=user.id, ign=ign,
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

    async def accept(
        self, *, event_id: int, request_id: int, actor_discord_id: int, actor_username: str
    ):
        user = await self.users.get_or_create(actor_discord_id, actor_username)
        request = await self._resolve(request_id, user.id)
        if request.target_user_id != user.id:
            raise ServiceError("This request isn't for you.")
        team = await self.teams.get(request.team_id)
        # Reuse the join guards/logic.
        await TeamService(self._s).join_team(
            event_id=event_id, team_id=team.id,
            user_discord_id=actor_discord_id, username=actor_username,
        )
        request.status = RecruitRequestStatus.ACCEPTED
        request.resolved_at = datetime.now(UTC)
        await self._s.flush()
        await audit.record(
            self._s, action="recruit.accept", event_id=event_id, actor_user_id=user.id,
            entity_type="recruitment_request", entity_id=request.id,
        )
        return request

    async def decline(
        self, *, event_id: int, request_id: int, actor_discord_id: int, actor_username: str
    ):
        user = await self.users.get_or_create(actor_discord_id, actor_username)
        request = await self._resolve(request_id, user.id)
        if request.target_user_id != user.id:
            raise ServiceError("This request isn't for you.")
        request.status = RecruitRequestStatus.DECLINED
        request.resolved_at = datetime.now(UTC)
        await self._s.flush()
        await audit.record(
            self._s, action="recruit.decline", event_id=event_id, actor_user_id=user.id,
            entity_type="recruitment_request", entity_id=request.id,
        )
        return request


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
