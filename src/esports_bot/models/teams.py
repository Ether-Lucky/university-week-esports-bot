"""Teams, memberships, and recruitment (find-a-team + requests)."""

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
from sqlalchemy.orm import Mapped, mapped_column

from ..domain.enums import (
    RecruitmentPostStatus,
    RecruitRequestStatus,
    TeamMemberRole,
    TeamStatus,
)
from .base import Base, Snowflake, TimestampMixin


class Team(Base, TimestampMixin):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), nullable=False)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    logo_url: Mapped[str | None] = mapped_column(String(500))
    leader_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[TeamStatus] = mapped_column(
        Enum(TeamStatus, native_enum=False, length=16),
        nullable=False,
        default=TeamStatus.RECRUITING,
        server_default=TeamStatus.RECRUITING.value,
    )
    roster_size: Mapped[int] = mapped_column(Integer, nullable=False)
    disbanded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("event_id", "game_id", "name", name="name"),
    )


class TeamMember(Base):
    __tablename__ = "team_members"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), nullable=False)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    role_in_team: Mapped[TeamMemberRole] = mapped_column(
        Enum(TeamMemberRole, native_enum=False, length=16),
        nullable=False,
        default=TeamMemberRole.MEMBER,
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        # A user may be active on only one team per event.
        Index(
            "uq_member_active_per_event",
            "event_id",
            "user_id",
            unique=True,
            postgresql_where=text("active"),
        ),
        # No duplicate active membership row within the same team.
        Index(
            "uq_member_active_per_team",
            "team_id",
            "user_id",
            unique=True,
            postgresql_where=text("active"),
        ),
    )


class RecruitmentPost(Base, TimestampMixin):
    __tablename__ = "recruitment_posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), nullable=False)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    ign: Mapped[str] = mapped_column(String(100), nullable=False)
    main_role: Mapped[str | None] = mapped_column(String(100))
    profile_screenshot_url: Mapped[str | None] = mapped_column(String(500))
    stats_screenshot_url: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[RecruitmentPostStatus] = mapped_column(
        Enum(RecruitmentPostStatus, native_enum=False, length=16),
        nullable=False,
        default=RecruitmentPostStatus.OPEN,
        server_default=RecruitmentPostStatus.OPEN.value,
    )
    forum_post_id: Mapped[int | None] = mapped_column(Snowflake)


class RecruitmentRequest(Base):
    __tablename__ = "recruitment_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    recruitment_post_id: Mapped[int | None] = mapped_column(
        ForeignKey("recruitment_posts.id")
    )
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    target_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    requested_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[RecruitRequestStatus] = mapped_column(
        Enum(RecruitRequestStatus, native_enum=False, length=16),
        nullable=False,
        default=RecruitRequestStatus.PENDING,
        server_default=RecruitRequestStatus.PENDING.value,
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
