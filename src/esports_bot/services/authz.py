"""Bridge from Discord members to the pure authorization policy.

Resolves a member's held event roles via stored role IDs (discord_resources),
then defers to ``domain.authorization.evaluate``. This is the application layer
of the dual-layer check (docs/permissions.md).
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.authorization import STAFF_ROLES, Action, Decision, Role, evaluate
from ..domain.enums import EventState, ResourceStatus, ResourceType
from ..infra.resource_repository import SqlResourceRepository

PURPOSE_TO_ROLE: dict[str, Role] = {
    "role_head": Role.HEAD,
    "role_committee": Role.COMMITTEE,
    "role_oic": Role.OIC,
    "role_fic": Role.FIC,
    "role_player": Role.PLAYER,
    "role_applicant": Role.APPLICANT,
    "role_audience": Role.AUDIENCE,
}

STAFF_ROLE_TO_PURPOSE = {
    Role.HEAD: "role_head",
    Role.COMMITTEE: "role_committee",
    Role.OIC: "role_oic",
    Role.FIC: "role_fic",
}


def roles_from_rows(rows, member_role_ids: Iterable[int]) -> frozenset[Role]:
    """Pure mapping: stored role resources + member role IDs -> held Roles."""
    ids = set(member_role_ids)
    held: set[Role] = set()
    for r in rows:
        if r.resource_type == ResourceType.ROLE and r.discord_id in ids:
            role = PURPOSE_TO_ROLE.get(r.purpose)
            if role is not None:
                held.add(role)
    return frozenset(held)


async def held_roles(
    session: AsyncSession, event_id: int, member_role_ids: Iterable[int]
) -> frozenset[Role]:
    """Map a member's Discord role IDs to the event Roles they hold."""
    repo = SqlResourceRepository(session)
    rows = await repo.list_by_status(event_id, ResourceStatus.CREATED)
    return roles_from_rows(rows, member_role_ids)


def authorize(
    held: frozenset[Role],
    action: Action,
    event_state: EventState | None,
    *,
    is_owner: bool = False,
) -> Decision:
    return evaluate(held, action, event_state, is_owner=is_owner)


def is_staff(held: frozenset[Role]) -> bool:
    return bool(held & STAFF_ROLES)
