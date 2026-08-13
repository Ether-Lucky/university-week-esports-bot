"""Formal state machines (see docs/state-machine.md).

Pure logic: no Discord, no DB. Services call ``assert_transition`` before any
persisted state change; illegal transitions raise ``IllegalTransition``.
"""

from __future__ import annotations

from .enums import ApplicationStatus, EventState, MatchStatus, TeamStatus

E = EventState
A = ApplicationStatus
T = TeamStatus
M = MatchStatus


class IllegalTransition(ValueError):
    """Raised when a state transition is not permitted by the machine."""


# --- Event ----------------------------------------------------------------
# Forward lifecycle. Backward moves are handled via rollback (Head override).
_EVENT_FORWARD: dict[EventState, set[EventState]] = {
    E.DRAFT: {E.SETUP},
    E.SETUP: {E.APPLICATIONS_OPEN},
    E.APPLICATIONS_OPEN: {E.TEAM_FORMATION},
    E.TEAM_FORMATION: {E.REGISTRATION_LOCKED},
    E.REGISTRATION_LOCKED: {E.PRE_TRYOUT},
    E.PRE_TRYOUT: {E.TRYOUT_ACTIVE},
    E.TRYOUT_ACTIVE: {E.RESULTS},
    E.RESULTS: {E.CLEANUP},
    E.CLEANUP: {E.ARCHIVED},
    E.ARCHIVED: set(),
}
# Ordered lifecycle used for rollback (one step back).
_EVENT_ORDER: list[EventState] = [
    E.DRAFT, E.SETUP, E.APPLICATIONS_OPEN, E.TEAM_FORMATION, E.REGISTRATION_LOCKED,
    E.PRE_TRYOUT, E.TRYOUT_ACTIVE, E.RESULTS, E.CLEANUP, E.ARCHIVED,
]

# --- Application ----------------------------------------------------------
_APPLICATION: dict[ApplicationStatus, set[ApplicationStatus]] = {
    A.PENDING: {A.APPROVED, A.REJECTED, A.WITHDRAWN},
    A.APPROVED: {A.ASSIGNED_TO_TEAM, A.WITHDRAWN, A.DISQUALIFIED},
    A.ASSIGNED_TO_TEAM: {A.APPROVED, A.DISQUALIFIED},
    A.REJECTED: set(),
    A.WITHDRAWN: set(),
    A.DISQUALIFIED: set(),
}

# --- Team -----------------------------------------------------------------
_TEAM: dict[TeamStatus, set[TeamStatus]] = {
    T.RECRUITING: {T.FULL, T.REGISTERED, T.DISBANDED},
    T.FULL: {T.RECRUITING, T.REGISTERED, T.DISBANDED},
    T.REGISTERED: {T.CHECKED_IN, T.RECRUITING, T.DISBANDED},
    T.CHECKED_IN: {T.COMPETING, T.DISBANDED},
    T.COMPETING: {T.ELIMINATED, T.CHAMPION, T.DISBANDED},
    T.ELIMINATED: {T.DISBANDED},
    T.CHAMPION: set(),
    T.DISBANDED: set(),
}

# --- Match ----------------------------------------------------------------
_MATCH: dict[MatchStatus, set[MatchStatus]] = {
    M.SCHEDULED: {M.READY, M.CANCELLED},
    M.READY: {M.LIVE, M.CANCELLED},
    M.LIVE: {M.COMPLETED, M.CANCELLED},
    M.COMPLETED: {M.DISPUTED},
    M.DISPUTED: {M.COMPLETED, M.CANCELLED},
    M.CANCELLED: set(),
}

_MACHINES = {
    "event": _EVENT_FORWARD,
    "application": _APPLICATION,
    "team": _TEAM,
    "match": _MATCH,
}


def can_transition(machine: str, frm, to) -> bool:
    table = _MACHINES[machine]
    return to in table.get(frm, set())


def assert_transition(machine: str, frm, to) -> None:
    if not can_transition(machine, frm, to):
        raise IllegalTransition(f"{machine}: cannot move {frm} -> {to}")


def next_event_state(state: EventState) -> EventState | None:
    """The single forward successor of ``state`` in the lifecycle, or None."""
    succ = _EVENT_FORWARD.get(state, set())
    return next(iter(succ)) if succ else None


# --- Event rollback (Head override) --------------------------------------
def previous_event_state(state: EventState) -> EventState | None:
    """The state immediately before ``state`` in the lifecycle, or None."""
    idx = _EVENT_ORDER.index(state)
    if idx == 0:
        return None
    return _EVENT_ORDER[idx - 1]


def can_rollback_event(state: EventState) -> bool:
    """Rollback is allowed for any state except DRAFT and ARCHIVED."""
    return state not in (E.DRAFT, E.ARCHIVED)
