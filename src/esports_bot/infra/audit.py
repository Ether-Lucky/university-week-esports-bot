"""Audit logging — the bot's own source-of-truth trail (docs/logging-and-audit.md)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.enums import AuditResult
from ..models import AuditLog


async def record(
    session: AsyncSession,
    *,
    action: str,
    event_id: int | None = None,
    actor_user_id: int | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    before: dict | None = None,
    after: dict | None = None,
    result: AuditResult = AuditResult.SUCCESS,
    error: str | None = None,
) -> AuditLog:
    """Append an audit entry within the caller's transaction.

    Never store secrets or raw PII beyond identifying IDs (docs/security.md).
    """
    entry = AuditLog(
        event_id=event_id,
        actor_user_id=actor_user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before=before,
        after=after,
        result=result,
        error=error,
    )
    session.add(entry)
    await session.flush()
    return entry
