"""Authorization policy unit tests (docs/permissions.md)."""

from __future__ import annotations

from esports_bot.domain.authorization import Action, Role, evaluate
from esports_bot.domain.enums import EventState

HEAD = frozenset({Role.HEAD})
COMMITTEE = frozenset({Role.COMMITTEE})
APPLICANT = frozenset({Role.APPLICANT})
AUDIENCE = frozenset({Role.AUDIENCE})


def test_head_only_action() -> None:
    action = Action("setup", requires_head=True)
    assert evaluate(HEAD, action, None)
    assert not evaluate(COMMITTEE, action, None)
    assert not evaluate(APPLICANT, action, None)


def test_staff_only_action() -> None:
    action = Action("approve", staff_only=True)
    assert evaluate(COMMITTEE, action, None)
    assert evaluate(HEAD, action, None)
    assert not evaluate(APPLICANT, action, None)


def test_owner_scoped_allows_owner_and_staff() -> None:
    action = Action("team.rename", owner_scoped=True)
    assert evaluate(APPLICANT, action, None, is_owner=True)
    assert not evaluate(APPLICANT, action, None, is_owner=False)
    # Staff override even when not the owner.
    assert evaluate(COMMITTEE, action, None, is_owner=False)


def test_state_gating_with_staff_override() -> None:
    action = Action(
        "team.create",
        allowed_states=frozenset({EventState.TEAM_FORMATION}),
    )
    assert evaluate(APPLICANT, action, EventState.TEAM_FORMATION)
    # Wrong state: applicant denied, staff overrides by default.
    assert not evaluate(APPLICANT, action, EventState.TRYOUT_ACTIVE)
    assert evaluate(COMMITTEE, action, EventState.TRYOUT_ACTIVE)


def test_state_gating_without_staff_override() -> None:
    action = Action(
        "tryout.start",
        staff_only=True,
        allowed_states=frozenset({EventState.PRE_TRYOUT}),
        allow_staff_state_override=False,
    )
    assert evaluate(COMMITTEE, action, EventState.PRE_TRYOUT)
    assert not evaluate(COMMITTEE, action, EventState.RESULTS)


def test_decision_reason_present_on_deny() -> None:
    action = Action("setup", requires_head=True)
    decision = evaluate(AUDIENCE, action, None)
    assert not decision
    assert "Head" in decision.reason
