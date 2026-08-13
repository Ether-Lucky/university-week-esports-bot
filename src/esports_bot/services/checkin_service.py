"""Team check-in use-cases (docs §20, FR-13)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.enums import CheckinState
from ..infra import audit
from ..models import Checkin
from ..repositories.competition import CheckinRepository
from ..repositories.core import UserRepository
from ..repositories.teams import TeamRepository
from .errors import ServiceError


class CheckinService:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session
        self.repo = CheckinRepository(session)
        self.teams = TeamRepository(session)
        self.users = UserRepository(session)

    async def check_in(
        self, *, event_id: int, member_discord_id: int, username: str,
        state: CheckinState = CheckinState.CHECKED_IN, actor_discord_id: int | None = None,
    ) -> Checkin:
        user = await self.users.get_or_create(member_discord_id, username)
        membership = await self.teams.active_membership(event_id, user.id)
        if membership is None:
            raise ServiceError("You are not on a team.")
        team = await self.teams.get(membership.team_id)
        actor = None
        if actor_discord_id is not None:
            actor = await self.users.get_or_create(actor_discord_id, username)
        existing = await self.repo.get(team.id, user.id)
        if existing is None:
            existing = Checkin(
                event_id=event_id, game_id=team.game_id, team_id=team.id, user_id=user.id,
                state=state, actor_user_id=actor.id if actor else None,
            )
            self.repo.add(existing)
        else:
            existing.state = state
            existing.actor_user_id = actor.id if actor else None
        await self._s.flush()
        await audit.record(
            self._s, action="checkin.set", event_id=event_id, actor_user_id=user.id,
            entity_type="checkin", entity_id=existing.id, after={"state": state.value},
        )
        return existing

    async def team_readiness(self, team_id: int) -> tuple[int, int]:
        team = await self.teams.get(team_id)
        checked = await self.repo.count_checked_in(team_id)
        return checked, team.roster_size if team else 0
