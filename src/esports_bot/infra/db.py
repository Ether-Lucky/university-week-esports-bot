"""Async database engine/session for Supabase Postgres.

Uses asyncpg over the Supabase session-mode pooler. SSL is required by Supabase;
we pass an SSL context equivalent to ``sslmode=require`` (encrypt, no CA
verification) so connection succeeds regardless of local trust store.
"""

from __future__ import annotations

import ssl
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _normalise(url: str) -> str:
    """Ensure the asyncpg driver and strip libpq-only query args asyncpg rejects."""
    u = make_url(url)
    if u.drivername in ("postgresql", "postgres"):
        u = u.set(drivername="postgresql+asyncpg")
    # asyncpg doesn't understand libpq's sslmode/ssl query params; we handle SSL
    # via connect_args instead.
    query = {k: v for k, v in u.query.items() if k not in ("sslmode", "ssl")}
    return u.set(query=query).render_as_string(hide_password=False)


def init_engine(database_url: str) -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        _engine = create_async_engine(
            _normalise(database_url),
            pool_size=5,
            max_overflow=5,
            pool_pre_ping=True,
            connect_args={"ssl": _ssl_context()},
        )
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        raise RuntimeError("Database engine not initialised; call init_engine() first.")
    return _sessionmaker


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Transactional session: commit on success, rollback on error."""
    maker = get_sessionmaker()
    async with maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def ping() -> bool:
    """Lightweight connectivity check for /system status."""
    from sqlalchemy import text

    engine = _engine
    if engine is None:
        return False
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return True


async def dispose() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _sessionmaker = None
