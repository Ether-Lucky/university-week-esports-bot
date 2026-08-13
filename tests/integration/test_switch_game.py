"""ApplicationService.switch_game integration test (live Postgres, rolled back)."""

from __future__ import annotations

import os

import pytest

from esports_bot.services.errors import ServiceError
from tests.integration.conftest import make_event

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DB_TESTS") != "1",
    reason="Set RUN_DB_TESTS=1 to run live-DB tests.",
)


async def test_switch_game(session) -> None:
    from esports_bot.services.application_service import ApplicationService

    svc, ev = await make_event(session, state_advances=0)
    val = await svc.add_game(
        event_id=ev.id, game_name="Valorant", roster_size=5,
        actor_discord_id=1, actor_username="head",
    )
    await svc.add_game(
        event_id=ev.id, game_name="Mobile Legends", roster_size=5,
        actor_discord_id=1, actor_username="head",
    )
    await svc.advance(event_id=ev.id, actor_discord_id=1, actor_username="head")  # SETUP
    await svc.advance(event_id=ev.id, actor_discord_id=1, actor_username="head")  # APPS_OPEN

    apps = ApplicationService(session)
    app = await apps.submit(
        event_id=ev.id, game_id=val.game_id, discord_user_id=50, username="u50",
        display_name="u50", first_name="A", full_name="A B",
        school_email="a@uphsl.edu.ph", facebook_url="https://facebook.com/a", year_section="J4A",
    )

    old_slug, new_slug = await apps.switch_game(
        event_id=ev.id, discord_user_id=50, username="u50", new_game_name="Mobile Legends"
    )
    assert old_slug == "valorant" and new_slug == "mobile-legends"
    assert (await apps.apps.get(app.id)).game_id != val.game_id

    # Switching to a game not in the event, or the same game, is refused.
    with pytest.raises(ServiceError):
        await apps.switch_game(
            event_id=ev.id, discord_user_id=50, username="u50", new_game_name="Dota"
        )
    with pytest.raises(ServiceError):
        await apps.switch_game(
            event_id=ev.id, discord_user_id=50, username="u50", new_game_name="Mobile Legends"
        )
