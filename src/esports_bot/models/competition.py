"""Matches, results, check-ins, mechanics, tournaments."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..domain.enums import CheckinState, MatchStatus
from .base import Base, Snowflake, TimestampMixin


class Match(Base, TimestampMixin):
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), nullable=False)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"), nullable=False)
    round: Mapped[int | None] = mapped_column(Integer)
    team_a_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    team_b_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))
    winner_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))
    status: Mapped[MatchStatus] = mapped_column(
        Enum(MatchStatus, native_enum=False, length=16),
        nullable=False,
        default=MatchStatus.SCHEDULED,
        server_default=MatchStatus.SCHEDULED.value,
    )
    voice_channel_ref: Mapped[int | None] = mapped_column(Snowflake)


class MatchResult(Base, TimestampMixin):
    __tablename__ = "match_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), nullable=False, unique=True)
    winner_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    screenshot_url: Mapped[str | None] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(Text)
    reported_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    corrected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    correction_reason: Mapped[str | None] = mapped_column(Text)


class Checkin(Base, TimestampMixin):
    __tablename__ = "checkins"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), nullable=False)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"), nullable=False)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    state: Mapped[CheckinState] = mapped_column(
        Enum(CheckinState, native_enum=False, length=20),
        nullable=False,
        default=CheckinState.NOT_CHECKED_IN,
        server_default=CheckinState.NOT_CHECKED_IN.value,
    )
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    __table_args__ = (UniqueConstraint("team_id", "user_id", name="team_user"),)


class Mechanics(Base):
    __tablename__ = "mechanics"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_game_id: Mapped[int] = mapped_column(ForeignKey("event_games.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    body: Mapped[dict] = mapped_column(JSONB, nullable=False)
    published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (UniqueConstraint("event_game_id", "version", name="event_game_version"),)


class Tournament(Base):
    __tablename__ = "tournaments"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_game_id: Mapped[int] = mapped_column(
        ForeignKey("event_games.id"), nullable=False, unique=True
    )
    challonge_url: Mapped[str | None] = mapped_column(String(500))
    published_message_ref: Mapped[int | None] = mapped_column(Snowflake)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
