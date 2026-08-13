"""DiscordResourceService idempotency/reconcile tests with in-memory fakes."""

from __future__ import annotations

import pytest

from esports_bot.domain.enums import ResourceOwnerType, ResourceStatus, ResourceType
from esports_bot.infra.discord_resources import DiscordResourceService
from esports_bot.infra.resource_repository import ResourceRow


class FakeGateway:
    def __init__(self) -> None:
        self._existing: set[tuple[ResourceType, int]] = set()
        self._next_id = 1000
        self.create_calls = 0

    def bot_top_role_position(self) -> int:
        return 50

    async def _make(self, rtype: ResourceType) -> int:
        self.create_calls += 1
        self._next_id += 1
        self._existing.add((rtype, self._next_id))
        return self._next_id

    async def create_role(self, name: str, **kwargs) -> int:
        return await self._make(ResourceType.ROLE)

    async def create_category(self, name: str, overwrites=None) -> int:
        return await self._make(ResourceType.CATEGORY)

    async def create_text_channel(self, name: str, **kwargs) -> int:
        return await self._make(ResourceType.TEXT_CHANNEL)

    async def create_voice_channel(self, name: str, **kwargs) -> int:
        return await self._make(ResourceType.VOICE_CHANNEL)

    async def create_forum_channel(self, name: str, **kwargs) -> int:
        return await self._make(ResourceType.FORUM_CHANNEL)

    async def create_stage_channel(self, name: str, **kwargs) -> int:
        return await self._make(ResourceType.STAGE_CHANNEL)

    async def delete(self, resource_type: ResourceType, discord_id: int) -> None:
        self._existing.discard((resource_type, discord_id))

    async def exists(self, resource_type: ResourceType, discord_id: int) -> bool:
        return (resource_type, discord_id) in self._existing


class FakeRepo:
    def __init__(self) -> None:
        self._rows: dict[int, ResourceRow] = {}
        self._next = 1

    async def get(self, event_id, owner_type, owner_id, purpose):
        for r in self._rows.values():
            if (
                r.event_id == event_id
                and r.owner_type == owner_type
                and r.owner_id == owner_id
                and r.purpose == purpose
            ):
                return r
        return None

    async def add_pending(self, event_id, resource_type, owner_type, owner_id, purpose):
        row = ResourceRow(
            id=self._next, event_id=event_id, resource_type=resource_type,
            discord_id=None, owner_type=owner_type, owner_id=owner_id,
            purpose=purpose, status=ResourceStatus.PENDING,
        )
        self._rows[self._next] = row
        self._next += 1
        return row

    async def set_created(self, row_id, discord_id):
        r = self._rows[row_id]
        r.discord_id = discord_id
        r.status = ResourceStatus.CREATED

    async def set_status(self, row_id, status):
        self._rows[row_id].status = status

    async def list_by_status(self, event_id, status):
        return [
            r for r in self._rows.values()
            if r.event_id == event_id and r.status == status
        ]


@pytest.fixture()
def service():
    gw = FakeGateway()
    repo = FakeRepo()
    return DiscordResourceService(gw, repo), gw, repo


async def test_ensure_is_idempotent(service) -> None:
    svc, gw, repo = service
    first = await svc.ensure_role(1, ResourceOwnerType.SYSTEM, None, "audience", "Audience")
    second = await svc.ensure_role(1, ResourceOwnerType.SYSTEM, None, "audience", "Audience")
    assert first == second
    assert gw.create_calls == 1  # not recreated
    assert len(repo._rows) == 1


async def test_reconcile_marks_missing(service) -> None:
    svc, gw, repo = service
    rid = await svc.ensure_role(1, ResourceOwnerType.SYSTEM, None, "player", "Player")
    # Simulate manual deletion on Discord.
    await gw.delete(ResourceType.ROLE, rid)
    report = await svc.reconcile(1)
    assert report.checked == 1
    assert report.missing_count == 1
    # Ensuring again recreates it with a new id.
    new_id = await svc.ensure_role(1, ResourceOwnerType.SYSTEM, None, "player", "Player")
    assert new_id != rid
    assert gw.create_calls == 2


async def test_delete_flow(service) -> None:
    svc, gw, repo = service
    await svc.ensure_category(1, ResourceOwnerType.GAME, 7, "game_category", "Valorant")
    row = await repo.get(1, ResourceOwnerType.GAME, 7, "game_category")
    await svc.delete(row)
    assert repo._rows[row.id].status == ResourceStatus.DELETED
    assert not await gw.exists(ResourceType.CATEGORY, row.discord_id)


async def test_find_returns_none_until_created(service) -> None:
    svc, gw, repo = service
    assert await svc.find(1, ResourceOwnerType.SYSTEM, None, "audience") is None
    await svc.ensure_role(1, ResourceOwnerType.SYSTEM, None, "audience", "Audience")
    assert await svc.find(1, ResourceOwnerType.SYSTEM, None, "audience") is not None
