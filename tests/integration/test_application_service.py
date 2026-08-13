"""ApplicationService integration tests against live Postgres (rolled back)."""

from __future__ import annotations

import os
import random

import pytest
from dotenv import load_dotenv

from esports_bot.domain.validators import ValidationError
from esports_bot.services.errors import ServiceError

load_dotenv(".env")

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DB_TESTS") != "1",
    reason="Set RUN_DB_TESTS=1 to run live-DB tests.",
)


@pytest.fixture()
async def session():
    from esports_bot.infra import db

    db.init_engine(os.environ["DATABASE_URL"])
    async with db.get_sessionmaker()() as s:
        yield s
        await s.rollback()
    await db.dispose()


async def _open_event(session):
    from esports_bot.services.event_service import EventService

    svc = EventService(session)
    ev = await svc.create_event(
        guild_id=random.randint(10**17, 10**18), name="UW", year=2027,
        school_name="UPHSL", email_domain="uphsl.edu.ph", timezone="Asia/Manila",
        actor_discord_id=1, actor_username="head",
    )
    eg = await svc.add_game(
        event_id=ev.id, game_name="Valorant", roster_size=5,
        actor_discord_id=1, actor_username="head",
    )
    await svc.advance(event_id=ev.id, actor_discord_id=1, actor_username="head")  # -> SETUP
    await svc.advance(event_id=ev.id, actor_discord_id=1, actor_username="head")  # -> APPS_OPEN
    return ev, eg


async def test_submit_validation_and_duplicates(session) -> None:
    from esports_bot.domain.enums import ApplicationStatus
    from esports_bot.services.application_service import ApplicationService

    ev, eg = await _open_event(session)
    svc = ApplicationService(session)

    # Wrong email domain rejected.
    with pytest.raises(ValidationError):
        await svc.submit(
            event_id=ev.id, game_id=eg.game_id, discord_user_id=10, username="a",
            display_name="a", first_name="Juan", full_name="Juan Dela Cruz",
            school_email="juan@gmail.com", facebook_url="https://facebook.com/juan",
            year_section="J4A",
        )

    app = await svc.submit(
        event_id=ev.id, game_id=eg.game_id, discord_user_id=10, username="a",
        display_name="a", first_name="Juan", full_name="Juan Dela Cruz",
        school_email="juan@uphsl.edu.ph", facebook_url="https://facebook.com/juan",
        year_section="J4A",
    )
    assert app.status == ApplicationStatus.PENDING

    # Duplicate active application for same user refused.
    with pytest.raises(ServiceError):
        await svc.submit(
            event_id=ev.id, game_id=eg.game_id, discord_user_id=10, username="a",
            display_name="a", first_name="Juan", full_name="Juan Dela Cruz",
            school_email="juan2@uphsl.edu.ph", facebook_url="https://facebook.com/juan",
            year_section="J4A",
        )


async def test_approve_and_reject_flow(session) -> None:
    from esports_bot.domain.enums import ApplicationStatus
    from esports_bot.services.application_service import ApplicationService

    ev, eg = await _open_event(session)
    svc = ApplicationService(session)

    app = await svc.submit(
        event_id=ev.id, game_id=eg.game_id, discord_user_id=20, username="b",
        display_name="b", first_name="Mark", full_name="Mark Reyes",
        school_email="mark@uphsl.edu.ph", facebook_url="https://facebook.com/mark",
        year_section="J4B",
    )
    approved = await svc.approve(app.id, actor_discord_id=1, actor_username="staff")
    assert approved.status == ApplicationStatus.APPROVED

    other = await svc.submit(
        event_id=ev.id, game_id=eg.game_id, discord_user_id=30, username="c",
        display_name="c", first_name="Ana", full_name="Ana Cruz",
        school_email="ana@uphsl.edu.ph", facebook_url="https://facebook.com/ana",
        year_section="J4C",
    )
    with pytest.raises(ServiceError):  # reason required
        await svc.reject(other.id, "  ", actor_discord_id=1, actor_username="staff")
    rejected = await svc.reject(
        other.id, "Incomplete info", actor_discord_id=1, actor_username="staff"
    )
    assert rejected.status == ApplicationStatus.REJECTED
    assert rejected.rejection_reason == "Incomplete info"
