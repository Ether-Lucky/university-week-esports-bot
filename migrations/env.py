"""Alembic environment — sync migrations via psycopg against Supabase."""

from __future__ import annotations

import os

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import create_engine, pool
from sqlalchemy.engine import make_url

from esports_bot.models import Base

load_dotenv(".env")

config = context.config
target_metadata = Base.metadata


def _migration_url() -> str:
    url = os.environ.get("MIGRATION_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("MIGRATION_DATABASE_URL (or DATABASE_URL) must be set.")
    u = make_url(url)
    # Migrations use the sync psycopg driver.
    if u.drivername in ("postgresql", "postgres", "postgresql+asyncpg"):
        u = u.set(drivername="postgresql+psycopg")
    return u.render_as_string(hide_password=False)


def run_migrations_offline() -> None:
    context.configure(
        url=_migration_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Build the engine directly from the URL so configparser never sees the
    # percent-encoded password (its interpolation would choke on `%`).
    connectable = create_engine(_migration_url(), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
