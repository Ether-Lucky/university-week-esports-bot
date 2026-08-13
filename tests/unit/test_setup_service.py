"""SetupService build/removal tests with in-memory fakes (no live Discord/DB)."""

from __future__ import annotations

import pytest

from esports_bot.domain.enums import ResourceStatus, ResourceType
from esports_bot.infra.discord_resources import DiscordResourceService
from esports_bot.infra.resource_repository import ResourceRow
from esports_bot.services.setup_service import SetupService


class FakeGateway:
    def __init__(self) -> None:
        self.existing: set[tuple[ResourceType, int]] = set()
        self._next = 5000
        self.create_calls = 0
        self.deleted: list[tuple[ResourceType, int]] = []

    def bot_top_role_position(self) -> int:
        return 99

    async def _make(self, rtype: ResourceType) -> int:
        self.create_calls += 1
        self._next += 1
        self.existing.add((rtype, self._next))
        return self._next

    async def create_role(self, name, **kw):
        return await self._make(ResourceType.ROLE)

    async def create_category(self, name, overwrites=None):
        return await self._make(ResourceType.CATEGORY)

    async def create_text_channel(self, name, **kw):
        return await self._make(ResourceType.TEXT_CHANNEL)

    async def create_voice_channel(self, name, **kw):
        return await self._make(ResourceType.VOICE_CHANNEL)

    async def create_forum_channel(self, name, **kw):
        return await self._make(ResourceType.FORUM_CHANNEL)

    async def create_stage_channel(self, name, **kw):
        return await self._make(ResourceType.STAGE_CHANNEL)

    async def delete(self, rtype, discord_id):
        self.existing.discard((rtype, discord_id))
        self.deleted.append((rtype, discord_id))

    async def exists(self, rtype, discord_id):
        return (rtype, discord_id) in self.existing


class FakeRepo:
    def __init__(self) -> None:
        self.rows: dict[int, ResourceRow] = {}
        self._next = 1

    async def get(self, event_id, owner_type, owner_id, purpose):
        for r in self.rows.values():
            if (r.event_id, r.owner_type, r.owner_id, r.purpose) == (
                event_id, owner_type, owner_id, purpose
            ):
                return r
        return None

    async def add_pending(self, event_id, resource_type, owner_type, owner_id, purpose):
        row = ResourceRow(
            id=self._next, event_id=event_id, resource_type=resource_type,
            discord_id=None, owner_type=owner_type, owner_id=owner_id,
            purpose=purpose, status=ResourceStatus.PENDING,
        )
        self.rows[self._next] = row
        self._next += 1
        return row

    async def set_created(self, row_id, discord_id):
        self.rows[row_id].discord_id = discord_id
        self.rows[row_id].status = ResourceStatus.CREATED

    async def set_status(self, row_id, status):
        self.rows[row_id].status = status

    async def list_by_status(self, event_id, status):
        return [r for r in self.rows.values() if r.event_id == event_id and r.status == status]


@pytest.fixture()
def svc():
    gw = FakeGateway()
    service = SetupService(DiscordResourceService(gw, FakeRepo()), gw)
    return service, gw


async def test_build_creates_full_structure(svc) -> None:
    service, gw = svc
    report = await service.build(1, ["valorant", "mobile-legends"])
    # 6 base roles.
    assert report.roles == 6
    # 4 base categories + 2 game categories.
    assert report.categories == 6
    # 15 base channels + 2 games * 9 = 33.
    assert report.channels == 33
    assert gw.create_calls == report.roles + report.categories + report.channels


async def test_build_is_idempotent(svc) -> None:
    service, gw = svc
    await service.build(1, ["valorant"])
    calls_after_first = gw.create_calls
    await service.build(1, ["valorant"])  # re-run: nothing new
    assert gw.create_calls == calls_after_first


async def test_remove_orders_children_before_roles(svc) -> None:
    service, gw = svc
    remove = [
        ("role", 1, "Random"),
        ("category", 2, "Old"),
        ("text", 3, "old-chat"),
    ]
    removed = await service.remove_preexisting(remove)
    assert removed == 3
    kinds_in_order = [rtype for rtype, _ in gw.deleted]
    # Channel (text) deleted before category, category before role.
    assert kinds_in_order.index(ResourceType.TEXT_CHANNEL) < kinds_in_order.index(
        ResourceType.CATEGORY
    )
    assert kinds_in_order.index(ResourceType.CATEGORY) < kinds_in_order.index(ResourceType.ROLE)
