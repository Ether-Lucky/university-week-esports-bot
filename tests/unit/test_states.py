"""State-machine unit tests (docs/state-machine.md)."""

from __future__ import annotations

import pytest

from esports_bot.domain.enums import (
    ApplicationStatus,
    EventState,
    MatchStatus,
    TeamStatus,
)
from esports_bot.domain.states import (
    IllegalTransition,
    assert_transition,
    can_rollback_event,
    can_transition,
    previous_event_state,
)


def test_event_forward_legal() -> None:
    assert can_transition("event", EventState.DRAFT, EventState.SETUP)
    assert can_transition("event", EventState.TRYOUT_ACTIVE, EventState.RESULTS)


def test_event_illegal_skip() -> None:
    assert not can_transition("event", EventState.DRAFT, EventState.TRYOUT_ACTIVE)
    with pytest.raises(IllegalTransition):
        assert_transition("event", EventState.ARCHIVED, EventState.SETUP)


def test_event_rollback_helpers() -> None:
    assert previous_event_state(EventState.TEAM_FORMATION) == EventState.APPLICATIONS_OPEN
    assert previous_event_state(EventState.DRAFT) is None
    assert can_rollback_event(EventState.RESULTS)
    assert not can_rollback_event(EventState.ARCHIVED)
    assert not can_rollback_event(EventState.DRAFT)


def test_application_transitions() -> None:
    assert can_transition("application", ApplicationStatus.PENDING, ApplicationStatus.APPROVED)
    assert can_transition(
        "application", ApplicationStatus.APPROVED, ApplicationStatus.ASSIGNED_TO_TEAM
    )
    # Terminal states go nowhere.
    assert not can_transition(
        "application", ApplicationStatus.REJECTED, ApplicationStatus.APPROVED
    )


def test_team_transitions() -> None:
    assert can_transition("team", TeamStatus.RECRUITING, TeamStatus.FULL)
    assert can_transition("team", TeamStatus.COMPETING, TeamStatus.CHAMPION)
    assert can_transition("team", TeamStatus.FULL, TeamStatus.DISBANDED)
    assert not can_transition("team", TeamStatus.CHAMPION, TeamStatus.DISBANDED)


def test_match_transitions() -> None:
    assert can_transition("match", MatchStatus.LIVE, MatchStatus.COMPLETED)
    assert can_transition("match", MatchStatus.COMPLETED, MatchStatus.DISPUTED)
    assert can_transition("match", MatchStatus.DISPUTED, MatchStatus.COMPLETED)
    assert not can_transition("match", MatchStatus.COMPLETED, MatchStatus.LIVE)
