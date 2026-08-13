"""DiscordResourceService — idempotent creation + reconciliation.

Bridges the DB resource map (ResourceRepository) and the Discord API
(ResourceGateway). All creation is idempotent: a resource already recorded as
CREATED and still present on Discord is returned as-is rather than duplicated
(supports interrupted-setup recovery, docs/error-handling.md).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from ..domain.enums import ResourceOwnerType, ResourceStatus, ResourceType
from .discord_gateway import ResourceGateway
from .resource_repository import ResourceRepository, ResourceRow


@dataclass
class ReconcileReport:
    checked: int = 0
    missing: list[ResourceRow] = field(default_factory=list)

    @property
    def missing_count(self) -> int:
        return len(self.missing)


class DiscordResourceService:
    def __init__(self, gateway: ResourceGateway, repo: ResourceRepository) -> None:
        self._gw = gateway
        self._repo = repo

    async def _ensure(
        self,
        event_id: int,
        resource_type: ResourceType,
        owner_type: ResourceOwnerType,
        owner_id: int | None,
        purpose: str,
        create: Callable[[], Awaitable[int]],
    ) -> int:
        row = await self._repo.get(event_id, owner_type, owner_id, purpose)
        if (
            row is not None
            and row.status == ResourceStatus.CREATED
            and row.discord_id is not None
            and await self._gw.exists(resource_type, row.discord_id)
        ):
            return row.discord_id  # already exists — idempotent no-op

        if row is None:
            row = await self._repo.add_pending(
                event_id, resource_type, owner_type, owner_id, purpose
            )

        discord_id = await create()
        await self._repo.set_created(row.id, discord_id)
        return discord_id

    # --- typed convenience wrappers --------------------------------------
    async def ensure_role(
        self, event_id: int, owner_type: ResourceOwnerType, owner_id: int | None,
        purpose: str, name: str, **kwargs: Any,
    ) -> int:
        return await self._ensure(
            event_id, ResourceType.ROLE, owner_type, owner_id, purpose,
            lambda: self._gw.create_role(name, **kwargs),
        )

    async def ensure_category(
        self, event_id: int, owner_type: ResourceOwnerType, owner_id: int | None,
        purpose: str, name: str, overwrites: Any | None = None,
    ) -> int:
        return await self._ensure(
            event_id, ResourceType.CATEGORY, owner_type, owner_id, purpose,
            lambda: self._gw.create_category(name, overwrites=overwrites),
        )

    async def ensure_text_channel(
        self, event_id: int, owner_type: ResourceOwnerType, owner_id: int | None,
        purpose: str, name: str, *, category_id: int | None = None,
        overwrites: Any | None = None, topic: str | None = None,
    ) -> int:
        return await self._ensure(
            event_id, ResourceType.TEXT_CHANNEL, owner_type, owner_id, purpose,
            lambda: self._gw.create_text_channel(
                name, category_id=category_id, overwrites=overwrites, topic=topic
            ),
        )

    async def ensure_voice_channel(
        self, event_id: int, owner_type: ResourceOwnerType, owner_id: int | None,
        purpose: str, name: str, *, category_id: int | None = None,
        overwrites: Any | None = None,
    ) -> int:
        return await self._ensure(
            event_id, ResourceType.VOICE_CHANNEL, owner_type, owner_id, purpose,
            lambda: self._gw.create_voice_channel(
                name, category_id=category_id, overwrites=overwrites
            ),
        )

    async def ensure_forum_channel(
        self, event_id: int, owner_type: ResourceOwnerType, owner_id: int | None,
        purpose: str, name: str, *, category_id: int | None = None,
        overwrites: Any | None = None, topic: str | None = None,
    ) -> int:
        return await self._ensure(
            event_id, ResourceType.FORUM_CHANNEL, owner_type, owner_id, purpose,
            lambda: self._gw.create_forum_channel(
                name, category_id=category_id, overwrites=overwrites, topic=topic
            ),
        )

    async def ensure_stage_channel(
        self, event_id: int, owner_type: ResourceOwnerType, owner_id: int | None,
        purpose: str, name: str, *, category_id: int | None = None,
        overwrites: Any | None = None,
    ) -> int:
        return await self._ensure(
            event_id, ResourceType.STAGE_CHANNEL, owner_type, owner_id, purpose,
            lambda: self._gw.create_stage_channel(
                name, category_id=category_id, overwrites=overwrites
            ),
        )

    async def register_existing(
        self, event_id: int, resource_type: ResourceType, owner_type: ResourceOwnerType,
        owner_id: int | None, purpose: str, discord_id: int,
    ) -> int:
        """Record a pre-existing (e.g. preserved) Discord resource as CREATED."""
        row = await self._repo.get(event_id, owner_type, owner_id, purpose)
        if row is not None and row.status == ResourceStatus.CREATED and row.discord_id:
            return row.discord_id
        if row is None:
            row = await self._repo.add_pending(
                event_id, resource_type, owner_type, owner_id, purpose
            )
        await self._repo.set_created(row.id, discord_id)
        return discord_id

    # --- lookup / reconcile / delete -------------------------------------
    async def find(
        self, event_id: int, owner_type: ResourceOwnerType, owner_id: int | None, purpose: str
    ) -> int | None:
        row = await self._repo.get(event_id, owner_type, owner_id, purpose)
        return row.discord_id if row and row.status == ResourceStatus.CREATED else None

    async def role_map(self, event_id: int) -> dict[str, int]:
        """Return {purpose: discord_id} for CREATED role resources."""
        rows = await self._repo.list_by_status(event_id, ResourceStatus.CREATED)
        return {
            r.purpose: r.discord_id
            for r in rows
            if r.resource_type == ResourceType.ROLE and r.discord_id is not None
        }

    async def reconcile(self, event_id: int) -> ReconcileReport:
        """Detect resources recorded as CREATED but missing on Discord."""
        report = ReconcileReport()
        for row in await self._repo.list_by_status(event_id, ResourceStatus.CREATED):
            report.checked += 1
            if row.discord_id is None or not await self._gw.exists(
                row.resource_type, row.discord_id
            ):
                await self._repo.set_status(row.id, ResourceStatus.MISSING)
                report.missing.append(row)
        return report

    async def delete(self, row: ResourceRow) -> None:
        await self._repo.set_status(row.id, ResourceStatus.DELETING)
        if row.discord_id is not None:
            await self._gw.delete(row.resource_type, row.discord_id)
        await self._repo.set_status(row.id, ResourceStatus.DELETED)
