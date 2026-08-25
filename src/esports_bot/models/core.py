"""Core tables: events, games, event_games, users, staff_assignments."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..domain.enums import EventState, StaffRole
from .base import Base, Snowflake, TimestampMixin


class Event(Base, TimestampMixin):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[int] = mapped_column(Snowflake, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    school_name: Mapped[str] = mapped_column(String(200), nullable=False)
    email_domain: Mapped[str] = mapped_column(String(255), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Manila")
    state: Mapped[EventState] = mapped_column(
        Enum(EventState, native_enum=False, length=32),
        nullable=False,
        default=EventState.DRAFT,
        server_default=EventState.DRAFT.value,
    )
    applications_open_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applications_close_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    team_creation_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recruitment_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tryout_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cleanup_policy: Mapped[dict | None] = mapped_column(JSONB)
    # When true, no new teams can be created; existing teams can still fill up.
    team_creation_locked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    __table_args__ = (
        # At most one active (non-archived) event per guild.
        Index(
            "uq_events_active_per_guild",
            "guild_id",
            unique=True,
            postgresql_where=text("state <> 'ARCHIVED'"),
        ),
    )


class Game(Base, TimestampMixin):
    __tablename__ = "games"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    short_code: Mapped[str | None] = mapped_column(String(20))
    default_roster_size: Mapped[int] = mapped_column(Integer, nullable=False, default=5)


class EventGame(Base, TimestampMixin):
    __tablename__ = "event_games"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), nullable=False)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"), nullable=False)
    roster_size: Mapped[int] = mapped_column(Integer, nullable=False)
    challonge_url: Mapped[str | None] = mapped_column(String(500))
    tryout_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stage_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (UniqueConstraint("event_id", "game_id", name="event_game"),)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    discord_user_id: Mapped[int] = mapped_column(Snowflake, nullable=False, unique=True)
    discord_username: Mapped[str] = mapped_column(String(100), nullable=False)
    discord_display_name: Mapped[str | None] = mapped_column(String(100))
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Appointment(Base):
    """A player staff appointed for a game that formed no teams (Player granted directly)."""

    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), nullable=False)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    appointed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("event_id", "game_id", "user_id", name="appointment_unique"),
    )


class StaffAssignment(Base):
    __tablename__ = "staff_assignments"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    staff_role: Mapped[StaffRole] = mapped_column(
        Enum(StaffRole, native_enum=False, length=16), nullable=False
    )
    assigned_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index(
            "uq_staff_active",
            "event_id",
            "user_id",
            "staff_role",
            unique=True,
            postgresql_where=text("active"),
        ),
    )
