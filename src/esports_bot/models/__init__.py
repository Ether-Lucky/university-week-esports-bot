"""SQLAlchemy ORM models (see docs/database-design.md).

Importing this package registers every table on ``Base.metadata``.
"""

from __future__ import annotations

from .applications import Application, ApplicationHistory
from .base import Base
from .competition import Checkin, Match, MatchResult, Mechanics, Tournament
from .core import Event, EventGame, Game, StaffAssignment, User
from .system_tables import AuditLog, DiscordResource, Export
from .teams import (
    RecruitmentPost,
    RecruitmentRequest,
    Team,
    TeamMember,
)

__all__ = [
    "Base",
    "Event",
    "Game",
    "EventGame",
    "User",
    "StaffAssignment",
    "Application",
    "ApplicationHistory",
    "Team",
    "TeamMember",
    "RecruitmentPost",
    "RecruitmentRequest",
    "Match",
    "MatchResult",
    "Checkin",
    "Mechanics",
    "Tournament",
    "DiscordResource",
    "AuditLog",
    "Export",
]
