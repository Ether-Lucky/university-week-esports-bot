"""Applications and their state history."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..domain.enums import ApplicationStatus
from .base import Base, Snowflake, TimestampMixin

_ACTIVE = "status IN ('PENDING','APPROVED','ASSIGNED_TO_TEAM')"


class Application(Base, TimestampMixin):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), nullable=False)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    middle_initial: Mapped[str | None] = mapped_column(String(10))
    school_email: Mapped[str] = mapped_column(String(255), nullable=False)
    facebook_url: Mapped[str] = mapped_column(String(500), nullable=False)
    year_section: Mapped[str] = mapped_column(String(50), nullable=False)

    status: Mapped[ApplicationStatus] = mapped_column(
        Enum(ApplicationStatus, native_enum=False, length=24),
        nullable=False,
        default=ApplicationStatus.PENDING,
        server_default=ApplicationStatus.PENDING.value,
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))

    # Discord message posted to the staff review channel, so approve/reject can edit it.
    review_channel_id: Mapped[int | None] = mapped_column(Snowflake)
    review_message_id: Mapped[int | None] = mapped_column(Snowflake)

    __table_args__ = (
        CheckConstraint(
            "status <> 'REJECTED' OR rejection_reason IS NOT NULL",
            name="rejection_reason_required",
        ),
        # OQ-4: one active application per user per event (any game).
        Index(
            "uq_app_active_per_user",
            "event_id",
            "user_id",
            unique=True,
            postgresql_where=text(_ACTIVE),
        ),
        # OQ-5: one active application per school email per event.
        Index(
            "uq_app_active_per_email",
            "event_id",
            "school_email",
            unique=True,
            postgresql_where=text(_ACTIVE),
        ),
    )


class ApplicationHistory(Base):
    __tablename__ = "application_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), nullable=False)
    from_status: Mapped[ApplicationStatus | None] = mapped_column(
        Enum(ApplicationStatus, native_enum=False, length=24)
    )
    to_status: Mapped[ApplicationStatus] = mapped_column(
        Enum(ApplicationStatus, native_enum=False, length=24), nullable=False
    )
    reason: Mapped[str | None] = mapped_column(Text)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
