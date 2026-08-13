"""StaffService integration test against live Postgres (rolled back)."""

from __future__ import annotations

import os
import random

import pytest
from dotenv import load_dotenv

from esports_bot.domain.enums import StaffRole
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
    async with db.get_sessionmaker()() as s:
        yield s
        await s.rollback()
    await db.dispose()


async def test_staff_assign_list_remove(session) -> None:
    from esports_bot.services.event_service import EventService
    from esports_bot.services.staff_service import StaffService

    ev = await EventService(session).create_event(
        guild_id=random.randint(10**17, 10**18), name="UW", year=2027,
        school_name="UPHSL", email_domain="uphsl.edu.ph", timezone="Asia/Manila",
        actor_discord_id=1, actor_username="head",
    )
    svc = StaffService(session)
    purpose = await svc.assign(
        event_id=ev.id, target_discord_id=42, target_username="member#1",
        staff_role=StaffRole.COMMITTEE, actor_discord_id=1, actor_username="head",
    )
    assert purpose == "role_committee"

    rows = await svc.list_active(ev.id)
    assert (42, StaffRole.COMMITTEE) in rows

    with pytest.raises(ServiceError):  # duplicate role
        await svc.assign(
            event_id=ev.id, target_discord_id=42, target_username="member#1",
            staff_role=StaffRole.COMMITTEE, actor_discord_id=1, actor_username="head",
        )

    revoked = await svc.remove(
        event_id=ev.id, target_discord_id=42, target_username="member#1",
        actor_discord_id=1, actor_username="head",
    )
    assert "role_committee" in revoked
    assert await svc.list_active(ev.id) == []
