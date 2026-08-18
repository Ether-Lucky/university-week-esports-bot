"""Discord resource map, audit log, and exports."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..domain.enums import (
    AuditResult,
    ResourceOwnerType,
    ResourceStatus,
    ResourceType,
)
from .base import Base, Snowflake, TimestampMixin


class DiscordResource(Base, TimestampMixin):
    """Maps application entities to Discord resource IDs (reconciliation backbone)."""

    __tablename__ = "discord_resources"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), nullable=False)
    resource_type: Mapped[ResourceType] = mapped_column(
        Enum(ResourceType, native_enum=False, length=20), nullable=False
    )
    discord_id: Mapped[int | None] = mapped_column(Snowflake)
    owner_type: Mapped[ResourceOwnerType] = mapped_column(
        Enum(ResourceOwnerType, native_enum=False, length=16), nullable=False
    )
    owner_id: Mapped[int | None] = mapped_column(Integer)
    purpose: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[ResourceStatus] = mapped_column(
        Enum(ResourceStatus, native_enum=False, length=16),
        nullable=False,
        default=ResourceStatus.PENDING,
        server_default=ResourceStatus.PENDING.value,
    )

    __table_args__ = (
        Index(
            "ix_resource_lookup",
            "event_id",
            "owner_type",
            "owner_id",
            "purpose",
        ),
    )


class AuditLog(Base):
    """Bot's own source-of-truth audit trail (independent of Discord's)."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int | None] = mapped_column(ForeignKey("events.id"))
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(50))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict | None] = mapped_column(JSONB)
    result: Mapped[AuditResult] = mapped_column(
        Enum(AuditResult, native_enum=False, length=10),
        nullable=False,
        default=AuditResult.SUCCESS,
    )
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_audit_event_created", "event_id", "created_at"),)


class DashboardSubscription(Base, TimestampMixin):
    """A guild that mirrors the event's live dashboard in one of its channels.

    Lets other servers follow the event: they invite the bot and pick a channel,
    and the periodic dashboard refresh keeps a message there up to date.
    """

    __tablename__ = "dashboard_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[int] = mapped_column(Snowflake, nullable=False, unique=True)
    channel_id: Mapped[int] = mapped_column(Snowflake, nullable=False)
    message_id: Mapped[int | None] = mapped_column(Snowflake)
    created_by: Mapped[int | None] = mapped_column(Snowflake)


class Export(Base):
    __tablename__ = "exports"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), nullable=False)
    export_type: Mapped[str] = mapped_column(String(40), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    generated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
