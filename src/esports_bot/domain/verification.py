"""Verification logic (OQ-2: external bot's verified role -> Audience). Pure."""

from __future__ import annotations

from collections.abc import Iterable


def gained_role(before: Iterable[int], after: Iterable[int], role_id: int) -> bool:
    return role_id in set(after) and role_id not in set(before)


def lost_role(before: Iterable[int], after: Iterable[int], role_id: int) -> bool:
    return role_id in set(before) and role_id not in set(after)


def should_grant_audience(
    *, verified_role_id: int, audience_role_id: int,
    before: Iterable[int], after: Iterable[int],
) -> bool:
    after_ids = set(after)
    return gained_role(before, after_ids, verified_role_id) and audience_role_id not in after_ids


def should_revoke_audience(
    *, verified_role_id: int, audience_role_id: int,
    before: Iterable[int], after: Iterable[int], revoke_enabled: bool,
) -> bool:
    if not revoke_enabled:
        return False
    after_ids = set(after)
    return lost_role(before, after_ids, verified_role_id) and audience_role_id in after_ids
