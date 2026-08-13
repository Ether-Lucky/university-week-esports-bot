"""Application repository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.enums import ACTIVE_APPLICATION_STATUSES, ApplicationStatus
from ..models import Application, ApplicationHistory


class ApplicationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get(self, application_id: int) -> Application | None:
        return await self._s.get(Application, application_id)

    async def active_for_user(self, event_id: int, user_id: int) -> Application | None:
        res = await self._s.execute(
            select(Application).where(
                Application.event_id == event_id,
                Application.user_id == user_id,
                Application.status.in_(list(ACTIVE_APPLICATION_STATUSES)),
            )
        )
        return res.scalar_one_or_none()

    async def list_by_status(
        self, event_id: int, status: ApplicationStatus
    ) -> list[Application]:
        res = await self._s.execute(
            select(Application).where(
                Application.event_id == event_id, Application.status == status
            )
        )
        return list(res.scalars().all())

    def add(self, application: Application) -> None:
        self._s.add(application)

    def add_history(
        self, application_id: int, from_status, to_status, reason, actor_user_id
    ) -> None:
        self._s.add(
            ApplicationHistory(
                application_id=application_id, from_status=from_status,
                to_status=to_status, reason=reason, actor_user_id=actor_user_id,
            )
        )
