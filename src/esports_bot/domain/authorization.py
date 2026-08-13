"""Dual-layer authorization policy (see docs/permissions.md).

This module holds the *pure* policy: given the set of event roles an actor
holds, an action's requirements, the current event state, and ownership, it
returns Allow/Deny. Resolving a Discord member to their held roles (via stored
role IDs) is done by the caller and passed in as ``held_roles``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from .enums import EventState


class Role(StrEnum):
    HEAD = "HEAD"
    COMMITTEE = "COMMITTEE"
    OIC = "OIC"
    FIC = "FIC"
    PLAYER = "PLAYER"
    APPLICANT = "APPLICANT"
    AUDIENCE = "AUDIENCE"


STAFF_ROLES: frozenset[Role] = frozenset({Role.HEAD, Role.COMMITTEE, Role.OIC, Role.FIC})


@dataclass(frozen=True)
class Action:
    """Authorization requirements for a command/interaction."""

    name: str
    requires_head: bool = False
    staff_only: bool = False
    owner_scoped: bool = False  # actor must own the target (staff may override)
    allowed_states: frozenset[EventState] | None = None  # None = any state
    allow_staff_state_override: bool = True


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str = ""

    def __bool__(self) -> bool:  # convenient truthiness
        return self.allowed


_ALLOW = Decision(True)


def _has_staff(held: frozenset[Role]) -> bool:
    return bool(held & STAFF_ROLES)


def evaluate(
    held_roles: frozenset[Role],
    action: Action,
    event_state: EventState | None,
    *,
    is_owner: bool = False,
) -> Decision:
    """Return an Allow/Deny decision for ``action`` given the actor's context."""
    staff = _has_staff(held_roles)

    if action.requires_head and Role.HEAD not in held_roles:
        return Decision(False, "requires the E-Sports Head role")

    if action.staff_only and not staff:
        return Decision(False, "staff only")

    if action.owner_scoped and not is_owner and not staff:
        return Decision(False, "you do not own this")

    if action.allowed_states is not None and event_state is not None:
        if event_state not in action.allowed_states:
            if not (action.allow_staff_state_override and staff):
                return Decision(
                    False, f"not permitted while the event is in {event_state}"
                )

    return _ALLOW


@dataclass
class ActionRegistry:
    """Optional registry so cogs can share named action definitions."""

    _actions: dict[str, Action] = field(default_factory=dict)

    def register(self, action: Action) -> Action:
        self._actions[action.name] = action
        return action

    def get(self, name: str) -> Action:
        return self._actions[name]


# A starter set; extended as commands are implemented (see command-specification.md).
REGISTRY = ActionRegistry()
STAFF_ANY = REGISTRY.register(Action("staff.any", staff_only=True))
HEAD_ANY = REGISTRY.register(Action("head.any", requires_head=True))
