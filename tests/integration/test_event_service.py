"""EventService integration test against live Postgres (rolled back).

Skipped unless RUN_DB_TESTS=1. All writes are rolled back — nothing persists.
"""

from __future__ import annotations

import os
import random

import pytest
from dotenv import load_dotenv

from esports_bot.services.errors import ServiceError

load_dotenv(".env")

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DB_TESTS") != "1",
    reason="Set RUN_DB_TESTS=1 (and DATABASE_URL) to run live-DB tests.",
)


@pytest.fixture()
async def session():
    from esports_bot.infra import db

    db.init_engine(os.environ["DATABASE_URL"])
    maker = db.get_sessionmaker()
    async with maker() as s:
        yield s
        await s.rollback()
    await db.dispose()


async def test_event_create_configure_advance(session) -> None:
    from esports_bot.domain.enums import EventState
    from esports_bot.services.event_service import EventService

    guild = random.randint(10**17, 10**18)
    svc = EventService(session)
    ev = await svc.create_event(
        guild_id=guild, name="University Week E-Sports", year=2027,
        school_name="UPHSL", email_domain="uphsl.edu.ph", timezone="Asia/Manila",
        actor_discord_id=555, actor_username="head#0001",
    )
    assert ev.state == EventState.DRAFT

    # Duplicate active event for the same guild is refused.
    with pytest.raises(ServiceError):
        await svc.create_event(
            guild_id=guild, name="Dup", year=2028, school_name="X",
            email_domain="x.edu", timezone="Asia/Manila",
            actor_discord_id=555, actor_username="head#0001",
        )

    await svc.add_game(
        event_id=ev.id, game_name="Valorant", roster_size=5,
        actor_discord_id=555, actor_username="head#0001",
    )
    # Duplicate game refused.
    with pytest.raises(ServiceError):
        await svc.add_game(
            event_id=ev.id, game_name="Valorant", roster_size=5,
            actor_discord_id=555, actor_username="head#0001",
        )

    ev = await svc.advance(event_id=ev.id, actor_discord_id=555, actor_username="head#0001")
    assert ev.state == EventState.SETUP

    data = await svc.status(ev.id)
    assert data["games"] == 1 and data["state"] == "SETUP"
