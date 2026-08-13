"""Administrative data operations (destructive — Head only)."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Base


async def reset_all_data(session: AsyncSession) -> int:
    """Wipe ALL event data from every table and reset ID counters.

    Truncates every application table (keeps the Alembic version, i.e. the schema).
    Irreversible — used to reuse the same server + database for a fresh event.
    Returns the number of tables cleared.
    """
    tables = list(Base.metadata.tables)
    quoted = ", ".join(f'"{t}"' for t in tables)
    await session.execute(text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE"))
    return len(tables)
