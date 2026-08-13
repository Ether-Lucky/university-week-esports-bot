"""Verification logic tests (OQ-2)."""

from __future__ import annotations

from esports_bot.domain.verification import should_grant_audience, should_revoke_audience

VERIFIED = 500
AUDIENCE = 600


def test_grant_when_verified_role_gained() -> None:
    assert should_grant_audience(
        verified_role_id=VERIFIED, audience_role_id=AUDIENCE, before=[1], after=[1, VERIFIED]
    )


def test_no_grant_if_already_audience() -> None:
    assert not should_grant_audience(
        verified_role_id=VERIFIED, audience_role_id=AUDIENCE,
        before=[1], after=[1, VERIFIED, AUDIENCE],
    )


def test_no_grant_if_role_not_gained() -> None:
    assert not should_grant_audience(
        verified_role_id=VERIFIED, audience_role_id=AUDIENCE,
        before=[VERIFIED], after=[VERIFIED, 2],
    )


def test_revoke_when_verified_lost_and_revoke_enabled() -> None:
    assert should_revoke_audience(
        verified_role_id=VERIFIED, audience_role_id=AUDIENCE,
        before=[VERIFIED, AUDIENCE], after=[AUDIENCE], revoke_enabled=True,
    )
    assert not should_revoke_audience(
        verified_role_id=VERIFIED, audience_role_id=AUDIENCE,
        before=[VERIFIED, AUDIENCE], after=[AUDIENCE], revoke_enabled=False,
    )
