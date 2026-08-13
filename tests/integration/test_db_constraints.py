"""Integration tests against a live Postgres.

Skipped unless RUN_DB_TESTS=1 is set (so ordinary `pytest` never touches a
remote database). Uses DATABASE_URL from the environment/.env; all writes are
rolled back — nothing is committed.
"""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv
from sqlalchemy.exc import IntegrityError

load_dotenv(".env")

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DB_TESTS") != "1",
    reason="Set RUN_DB_TESTS=1 (and DATABASE_URL) to run live-DB tests.",
)


@pytest.fixture()
async def sessionmaker():
    from esports_bot.infra import db

    db.init_engine(os.environ["DATABASE_URL"])
    yield db.get_sessionmaker()
    await db.dispose()


async def _seed(session):
    from esports_bot.domain.enums import EventState
    from esports_bot.models import Event, Game, User

    ev = Event(
        guild_id=1,
        name="Test",
        year=2027,
        school_name="S",
        email_domain="x.edu",
        timezone="Asia/Manila",
        state=EventState.APPLICATIONS_OPEN,
    )
    game = Game(name="ITestGame", default_roster_size=5)
    user = User(discord_user_id=1234567, discord_username="t")
    session.add_all([ev, game, user])
    await session.flush()
    return ev, game, user


async def test_one_active_application_per_user(sessionmaker) -> None:
    from esports_bot.models import Application

    async with sessionmaker() as s:
        ev, game, user = await _seed(s)
        s.add(
            Application(
                event_id=ev.id, game_id=game.id, user_id=user.id, first_name="a",
                full_name="a", school_email="a@x.edu", facebook_url="https://facebook.com/a",
                year_section="J4A",
            )
        )
        await s.flush()
        s.add(
            Application(
                event_id=ev.id, game_id=game.id, user_id=user.id, first_name="b",
                full_name="b", school_email="b@x.edu", facebook_url="https://facebook.com/b",
                year_section="J4A",
            )
        )
        with pytest.raises(IntegrityError):
            await s.flush()
        await s.rollback()
