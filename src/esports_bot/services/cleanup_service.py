"""Event cleanup & archival (docs §27-28, FR-20/FR-21).

DB is the source of truth: cleanup deletes *Discord* resources only — historical
DB records are always retained.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain import states
from ..domain.enums import EventState, TeamStatus
from ..infra import audit
from ..models import Team
from ..repositories.core import EventRepository, UserRepository
from .errors import ServiceError


class CleanupService:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session
        self.events = EventRepository(session)
        self.users = UserRepository(session)

    async def cleanup(self, *, event_id: int, actor_discord_id: int, actor_username: str
                      ) -> list[int]:
        """Disband non-champion teams and move to CLEANUP. Returns disbanded team IDs."""
        event = await self.events.get(event_id)
        if event is None or event.state != EventState.RESULTS:
            raise ServiceError("Cleanup can only run from RESULTS.")
        res = await self._s.execute(
            select(Team).where(
                Team.event_id == event_id,
                Team.status.notin_([TeamStatus.CHAMPION, TeamStatus.DISBANDED]),
            )
        )
        disbanded: list[int] = []
        for team in res.scalars().all():
            team.status = TeamStatus.DISBANDED
            team.disbanded_at = datetime.now(UTC)
            disbanded.append(team.id)
        states.assert_transition("event", event.state, EventState.CLEANUP)
        event.state = EventState.CLEANUP
        await self._s.flush()
        actor = await self.users.get_or_create(actor_discord_id, actor_username)
        await audit.record(
            self._s, action="system.cleanup", event_id=event_id, actor_user_id=actor.id,
            entity_type="event", entity_id=event_id, after={"disbanded_teams": disbanded},
        )
        return disbanded

    async def archive(self, *, event_id: int, actor_discord_id: int, actor_username: str) -> None:
        event = await self.events.get(event_id)
        if event is None or event.state != EventState.CLEANUP:
            raise ServiceError("Archive can only run from CLEANUP.")
        states.assert_transition("event", event.state, EventState.ARCHIVED)
        event.state = EventState.ARCHIVED
        await self._s.flush()
        actor = await self.users.get_or_create(actor_discord_id, actor_username)
        await audit.record(
            self._s, action="event.archive", event_id=event_id, actor_user_id=actor.id,
            entity_type="event", entity_id=event_id,
        )
