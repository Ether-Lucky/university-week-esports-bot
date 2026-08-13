"""Shared fixtures/helpers for live-DB integration tests."""

from __future__ import annotations

import os
import random

import pytest
from dotenv import load_dotenv

load_dotenv(".env")


@pytest.fixture()
async def session():
    from esports_bot.infra import db

    db.init_engine(os.environ["DATABASE_URL"])
    async with db.get_sessionmaker()() as s:
        yield s
        await s.rollback()
    await db.dispose()


async def make_event(session, *, state_advances: int = 0):
    """Create an event and advance it ``state_advances`` times."""
    from esports_bot.services.event_service import EventService

    svc = EventService(session)
    ev = await svc.create_event(
        guild_id=random.randint(10**17, 10**18), name="UW", year=2027,
        school_name="UPHSL", email_domain="uphsl.edu.ph", timezone="Asia/Manila",
        actor_discord_id=1, actor_username="head",
    )
    for _ in range(state_advances):
        await svc.advance(event_id=ev.id, actor_discord_id=1, actor_username="head")
    return svc, ev


async def approved_applicant(session, event_id, game_id, discord_id):
    """Submit + approve an application (event must be APPLICATIONS_OPEN)."""
    from esports_bot.services.application_service import ApplicationService

    a = ApplicationService(session)
    app = await a.submit(
        event_id=event_id, game_id=game_id, discord_user_id=discord_id,
        username=f"u{discord_id}", display_name=f"u{discord_id}",
        first_name="F", full_name="Full Name", school_email=f"u{discord_id}@uphsl.edu.ph",
        facebook_url="https://facebook.com/x", year_section="J4A",
    )
    await a.approve(app.id, actor_discord_id=1, actor_username="staff")
    return app
