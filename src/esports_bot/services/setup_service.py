"""Setup execution: build the event structure and remove non-preserved resources.

Creation is idempotent (via DiscordResourceService), so an interrupted setup
can be safely re-run (docs/error-handling.md).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..domain.enums import ResourceOwnerType, ResourceType
from ..domain.permissions import EVERYONE, overwrites_for
from ..domain.server_blueprint import CategorySpec, full_blueprint
from ..infra.discord_gateway import ResourceGateway
from ..infra.discord_resources import DiscordResourceService

log = logging.getLogger(__name__)

_KIND_TO_TYPE = {
    "text": ResourceType.TEXT_CHANNEL,
    "voice": ResourceType.VOICE_CHANNEL,
    "forum": ResourceType.FORUM_CHANNEL,
    "stage": ResourceType.STAGE_CHANNEL,
    "category": ResourceType.CATEGORY,
    "role": ResourceType.ROLE,
}

# Delete order: children before parents before roles.
_REMOVE_ORDER = {"text": 0, "voice": 0, "forum": 0, "stage": 0, "category": 1, "role": 2}


@dataclass
class BuildReport:
    roles: int = 0
    categories: int = 0
    channels: int = 0
    errors: list[str] = field(default_factory=list)


class SetupService:
    def __init__(self, resources: DiscordResourceService, gateway: ResourceGateway) -> None:
        self._res = resources
        self._gw = gateway

    async def build(self, event_id: int, game_shorts: list[str]) -> BuildReport:
        report = BuildReport()
        roles, categories = full_blueprint(game_shorts)

        for role in roles:
            await self._res.ensure_role(
                event_id, ResourceOwnerType.SYSTEM, None, role.purpose, role.name,
                hoist=role.hoist,
            )
            report.roles += 1

        for cat in categories:
            await self._build_category(event_id, cat, report)
        return report

    async def _build_category(
        self, event_id: int, cat: CategorySpec, report: BuildReport
    ) -> None:
        is_game = cat.purpose.startswith("cat_game:")
        owner = ResourceOwnerType.GAME if is_game else ResourceOwnerType.SYSTEM
        cat_id = await self._res.ensure_category(
            event_id, owner, None, cat.purpose, cat.name
        )
        report.categories += 1

        for ch in cat.channels:
            if ch.kind == "text":
                await self._res.ensure_text_channel(
                    event_id, owner, None, ch.purpose, ch.name, category_id=cat_id
                )
            elif ch.kind == "voice":
                await self._res.ensure_voice_channel(
                    event_id, owner, None, ch.purpose, ch.name, category_id=cat_id
                )
            elif ch.kind == "forum":
                await self._res.ensure_forum_channel(
                    event_id, owner, None, ch.purpose, ch.name, category_id=cat_id
                )
            elif ch.kind == "stage":
                await self._res.ensure_stage_channel(
                    event_id, owner, None, ch.purpose, ch.name, category_id=cat_id
                )
            report.channels += 1

    async def apply_permissions(self, event_id: int, game_shorts: list[str]) -> tuple[int, int]:
        """Apply the permission-overwrite matrix to every created channel/category.

        Returns (applied, failed). A permission failure on one channel (e.g. the bot
        role sitting below @E-Sports Head, or missing Manage Roles) is logged and
        skipped so setup still completes; re-running after fixing the bot's
        permissions re-applies everything.
        """
        roles = await self._res.role_map(event_id)
        _, categories = full_blueprint(game_shorts)
        applied = failed = 0
        for cat in categories:
            owner = (
                ResourceOwnerType.GAME
                if cat.purpose.startswith("cat_game:")
                else ResourceOwnerType.SYSTEM
            )
            for purpose in (cat.purpose, *(ch.purpose for ch in cat.channels)):
                try:
                    if await self._apply_one(event_id, purpose, owner, roles):
                        applied += 1
                except Exception as exc:  # noqa: BLE001 - keep going; log what we skipped
                    failed += 1
                    log.warning("Could not apply permissions to %s: %s", purpose, exc)
        return applied, failed

    async def _apply_one(
        self, event_id: int, purpose: str, owner: ResourceOwnerType, roles: dict[str, int]
    ) -> bool:
        channel_id = await self._res.find(event_id, owner, None, purpose)
        if channel_id is None:
            return False
        entries: list[tuple[int | None, object]] = []
        for role_key, flags in overwrites_for(purpose).items():
            if role_key == EVERYONE:
                entries.append((None, flags))
            elif role_key in roles:
                entries.append((roles[role_key], flags))
        await self._gw.set_overwrites(channel_id, entries)
        return True

    async def remove_preexisting(self, remove: list[tuple[str, int, str]]) -> int:
        """Delete non-preserved pre-existing resources (children first).

        Skips resources Discord refuses to delete (e.g. Community-required Rules /
        Updates channels, error 50074) so one undeletable item can't abort setup.
        """
        removed = 0
        for kind, discord_id, name in sorted(remove, key=lambda r: _REMOVE_ORDER.get(r[0], 0)):
            rtype = _KIND_TO_TYPE.get(kind)
            if rtype is None:
                continue
            try:
                await self._gw.delete(rtype, discord_id)
                removed += 1
            except Exception as exc:  # noqa: BLE001 - keep going; log what we skipped
                log.warning(
                    "Skipping deletion of %s '%s' (%s): %s", kind, name, discord_id, exc
                )
        return removed
