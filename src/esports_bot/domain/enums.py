"""Domain enumerations.

Stored in the DB as VARCHAR + CHECK (via SQLAlchemy Enum(native_enum=False)),
so values are validated at the DB layer and easy to extend via migration.
See docs/state-machine.md.
"""

from __future__ import annotations

from enum import StrEnum


class EventState(StrEnum):
    DRAFT = "DRAFT"
    SETUP = "SETUP"
    APPLICATIONS_OPEN = "APPLICATIONS_OPEN"
    TEAM_FORMATION = "TEAM_FORMATION"
    REGISTRATION_LOCKED = "REGISTRATION_LOCKED"
    PRE_TRYOUT = "PRE_TRYOUT"
    TRYOUT_ACTIVE = "TRYOUT_ACTIVE"
    RESULTS = "RESULTS"
    CLEANUP = "CLEANUP"
    ARCHIVED = "ARCHIVED"


class ApplicationStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    ASSIGNED_TO_TEAM = "ASSIGNED_TO_TEAM"
    DISQUALIFIED = "DISQUALIFIED"


# Statuses that count as an "active" application for uniqueness (OQ-4/OQ-5).
ACTIVE_APPLICATION_STATUSES: tuple[ApplicationStatus, ...] = (
    ApplicationStatus.PENDING,
    ApplicationStatus.APPROVED,
    ApplicationStatus.ASSIGNED_TO_TEAM,
)


class TeamStatus(StrEnum):
    RECRUITING = "RECRUITING"
    FULL = "FULL"
    REGISTERED = "REGISTERED"
    CHECKED_IN = "CHECKED_IN"
    COMPETING = "COMPETING"
    ELIMINATED = "ELIMINATED"
    CHAMPION = "CHAMPION"
    DISBANDED = "DISBANDED"


class TeamMemberRole(StrEnum):
    LEADER = "LEADER"
    MEMBER = "MEMBER"


class MatchStatus(StrEnum):
    SCHEDULED = "SCHEDULED"
    READY = "READY"
    LIVE = "LIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    DISPUTED = "DISPUTED"


class CheckinState(StrEnum):
    CHECKED_IN = "CHECKED_IN"
    NOT_CHECKED_IN = "NOT_CHECKED_IN"
    EXCUSED = "EXCUSED"
    OVERRIDDEN = "OVERRIDDEN"


class RecruitmentPostStatus(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class RecruitRequestStatus(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class StaffRole(StrEnum):
    HEAD = "HEAD"
    COMMITTEE = "COMMITTEE"
    OIC = "OIC"
    FIC = "FIC"


class ResourceType(StrEnum):
    ROLE = "ROLE"
    CATEGORY = "CATEGORY"
    TEXT_CHANNEL = "TEXT_CHANNEL"
    VOICE_CHANNEL = "VOICE_CHANNEL"
    FORUM_CHANNEL = "FORUM_CHANNEL"
    STAGE_CHANNEL = "STAGE_CHANNEL"
    FORUM_POST = "FORUM_POST"
    MESSAGE = "MESSAGE"


class ResourceOwnerType(StrEnum):
    EVENT = "EVENT"
    GAME = "GAME"
    TEAM = "TEAM"
    SYSTEM = "SYSTEM"
    LOG = "LOG"


class ResourceStatus(StrEnum):
    PENDING = "PENDING"
    CREATED = "CREATED"
    DELETING = "DELETING"
    DELETED = "DELETED"
    MISSING = "MISSING"


class AuditResult(StrEnum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
