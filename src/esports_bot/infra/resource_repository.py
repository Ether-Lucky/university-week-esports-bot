"""Persistence for the Discord resource map (discord_resources table).

A Protocol so the resource service can run against a fake in tests, plus a
SQLAlchemy-backed implementation for production.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.enums import ResourceOwnerType, ResourceStatus, ResourceType
from ..models import DiscordResource


@dataclass
class ResourceRow:
    id: int
    event_id: int
    resource_type: ResourceType
    discord_id: int | None
    owner_type: ResourceOwnerType
    owner_id: int | None
    purpose: str
    status: ResourceStatus


class ResourceRepository(Protocol):
    async def get(
        self, event_id: int, owner_type: ResourceOwnerType, owner_id: int | None, purpose: str
    ) -> ResourceRow | None: ...

    async def add_pending(
        self, event_id: int, resource_type: ResourceType,
        owner_type: ResourceOwnerType, owner_id: int | None, purpose: str,
    ) -> ResourceRow: ...

    async def set_created(self, row_id: int, discord_id: int) -> None: ...

    async def set_status(self, row_id: int, status: ResourceStatus) -> None: ...

    async def list_by_status(
        self, event_id: int, status: ResourceStatus
    ) -> list[ResourceRow]: ...


def _to_row(m: DiscordResource) -> ResourceRow:
    return ResourceRow(
        id=m.id, event_id=m.event_id, resource_type=m.resource_type,
        discord_id=m.discord_id, owner_type=m.owner_type, owner_id=m.owner_id,
        purpose=m.purpose, status=m.status,
    )


class SqlResourceRepository:
    """SQLAlchemy-backed repository."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get(
        self, event_id: int, owner_type: ResourceOwnerType, owner_id: int | None, purpose: str
    ) -> ResourceRow | None:
        stmt = select(DiscordResource).where(
            DiscordResource.event_id == event_id,
            DiscordResource.owner_type == owner_type,
            DiscordResource.purpose == purpose,
        )
        stmt = stmt.where(
            DiscordResource.owner_id.is_(None)
            if owner_id is None
            else DiscordResource.owner_id == owner_id
        )
        res = await self._s.execute(stmt)
        m = res.scalar_one_or_none()
        return _to_row(m) if m else None

    async def add_pending(
        self, event_id: int, resource_type: ResourceType,
        owner_type: ResourceOwnerType, owner_id: int | None, purpose: str,
    ) -> ResourceRow:
        m = DiscordResource(
            event_id=event_id, resource_type=resource_type, owner_type=owner_type,
            owner_id=owner_id, purpose=purpose, status=ResourceStatus.PENDING,
        )
        self._s.add(m)
        await self._s.flush()
        return _to_row(m)

    async def set_created(self, row_id: int, discord_id: int) -> None:
        m = await self._s.get(DiscordResource, row_id)
        if m is not None:
            m.discord_id = discord_id
            m.status = ResourceStatus.CREATED
            await self._s.flush()

    async def set_status(self, row_id: int, status: ResourceStatus) -> None:
        m = await self._s.get(DiscordResource, row_id)
        if m is not None:
            m.status = status
            await self._s.flush()

    async def list_by_status(
        self, event_id: int, status: ResourceStatus
    ) -> list[ResourceRow]:
        stmt = select(DiscordResource).where(
            DiscordResource.event_id == event_id,
            DiscordResource.status == status,
        )
        res = await self._s.execute(stmt)
        return [_to_row(m) for m in res.scalars().all()]
