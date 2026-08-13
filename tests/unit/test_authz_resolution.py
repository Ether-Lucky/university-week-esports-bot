"""Role-resolution unit tests (member role IDs -> held Roles)."""

from __future__ import annotations

from esports_bot.domain.authorization import Role
from esports_bot.domain.enums import ResourceOwnerType, ResourceStatus, ResourceType
from esports_bot.infra.resource_repository import ResourceRow
from esports_bot.services.authz import is_staff, roles_from_rows


def _role_row(purpose: str, discord_id: int) -> ResourceRow:
    return ResourceRow(
        id=1, event_id=1, resource_type=ResourceType.ROLE, discord_id=discord_id,
        owner_type=ResourceOwnerType.SYSTEM, owner_id=None, purpose=purpose,
        status=ResourceStatus.CREATED,
    )


ROWS = [
    _role_row("role_head", 100),
    _role_row("role_committee", 101),
    _role_row("role_applicant", 102),
    _role_row("role_audience", 103),
    ResourceRow(  # a non-role resource must be ignored
        id=9, event_id=1, resource_type=ResourceType.TEXT_CHANNEL, discord_id=101,
        owner_type=ResourceOwnerType.SYSTEM, owner_id=None, purpose="ch_apply",
        status=ResourceStatus.CREATED,
    ),
]


def test_resolves_committee() -> None:
    held = roles_from_rows(ROWS, member_role_ids=[101, 999])
    assert held == frozenset({Role.COMMITTEE})
    assert is_staff(held)


def test_resolves_applicant_not_staff() -> None:
    held = roles_from_rows(ROWS, member_role_ids=[102])
    assert held == frozenset({Role.APPLICANT})
    assert not is_staff(held)


def test_head_is_staff() -> None:
    held = roles_from_rows(ROWS, member_role_ids=[100])
    assert Role.HEAD in held and is_staff(held)


def test_no_matching_roles() -> None:
    assert roles_from_rows(ROWS, member_role_ids=[555]) == frozenset()
