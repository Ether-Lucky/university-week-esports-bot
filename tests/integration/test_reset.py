"""reset_all_data integration test (live Postgres, rolled back — TRUNCATE is
transactional in Postgres, so nothing actually persists)."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import func, select

from tests.integration.conftest import make_event

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DB_TESTS") != "1",
    reason="Set RUN_DB_TESTS=1 to run live-DB tests.",
)


async def test_reset_clears_all_tables(session) -> None:
    from esports_bot.models import Event, Game
    from esports_bot.services.admin_service import reset_all_data

    svc, ev = await make_event(session, state_advances=0)
    await svc.add_game(
        event_id=ev.id, game_name="Valorant", roster_size=5,
        actor_discord_id=1, actor_username="head",
    )
    assert await session.scalar(select(func.count()).select_from(Event)) >= 1

    cleared = await reset_all_data(session)
    assert cleared >= 19
    assert await session.scalar(select(func.count()).select_from(Event)) == 0
    assert await session.scalar(select(func.count()).select_from(Game)) == 0

    # A fresh event can be created right after a wipe.
    _, ev2 = await make_event(session, state_advances=0)
    assert ev2.id is not None
