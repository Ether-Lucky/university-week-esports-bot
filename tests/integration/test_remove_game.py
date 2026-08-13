"""EventService.remove_game integration test (live Postgres, rolled back)."""

from __future__ import annotations

import os

import pytest

from esports_bot.services.errors import ServiceError
from tests.integration.conftest import approved_applicant, make_event

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DB_TESTS") != "1",
    reason="Set RUN_DB_TESTS=1 to run live-DB tests.",
)


async def test_remove_game_then_readd(session) -> None:
    svc, ev = await make_event(session, state_advances=0)  # DRAFT
    await svc.add_game(
        event_id=ev.id, game_name="Valorant", roster_size=5,
        actor_discord_id=1, actor_username="head",
    )
    # Unknown game / not-configured errors.
    with pytest.raises(ServiceError):
        await svc.remove_game(
            event_id=ev.id, game_name="Dota", actor_discord_id=1, actor_username="head"
        )
    # Remove the misconfigured game.
    game_slug = await svc.remove_game(
        event_id=ev.id, game_name="Valorant", actor_discord_id=1, actor_username="head"
    )
    assert game_slug == "valorant"
    assert await svc.games.list_for_event(ev.id) == []
    # Can re-add it afterwards.
    await svc.add_game(
        event_id=ev.id, game_name="Valorant", roster_size=5,
        actor_discord_id=1, actor_username="head",
    )
    assert len(await svc.games.list_for_event(ev.id)) == 1


async def test_remove_game_blocked_with_applications(session) -> None:
    svc, ev = await make_event(session, state_advances=0)
    eg = await svc.add_game(
        event_id=ev.id, game_name="Valorant", roster_size=5,
        actor_discord_id=1, actor_username="head",
    )
    await svc.advance(event_id=ev.id, actor_discord_id=1, actor_username="head")  # SETUP
    await svc.advance(event_id=ev.id, actor_discord_id=1, actor_username="head")  # APPS_OPEN
    await approved_applicant(session, ev.id, eg.game_id, 700)
    # Back to a configurable state to attempt removal (rollback), then it must refuse
    # because an application now references the game.
    await svc.rollback(
        event_id=ev.id, reason="test", actor_discord_id=1, actor_username="head"
    )  # -> SETUP
    with pytest.raises(ServiceError):
        await svc.remove_game(
            event_id=ev.id, game_name="Valorant", actor_discord_id=1, actor_username="head"
        )
