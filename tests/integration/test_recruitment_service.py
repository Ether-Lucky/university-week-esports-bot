"""RecruitmentService integration test (live Postgres, rolled back)."""

from __future__ import annotations

import os

import pytest

from esports_bot.services.errors import ServiceError
from tests.integration.conftest import approved_applicant, make_event

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DB_TESTS") != "1",
    reason="Set RUN_DB_TESTS=1 to run live-DB tests.",
)


async def test_recruit_then_accept_joins_team(session) -> None:
    from esports_bot.domain.enums import RecruitRequestStatus
    from esports_bot.services.recruitment_service import RecruitmentService
    from esports_bot.services.team_service import TeamService

    svc, ev = await make_event(session, state_advances=0)
    eg = await svc.add_game(
        event_id=ev.id, game_name="Valorant", roster_size=3,
        actor_discord_id=1, actor_username="head",
    )
    await svc.advance(event_id=ev.id, actor_discord_id=1, actor_username="head")  # SETUP
    await svc.advance(event_id=ev.id, actor_discord_id=1, actor_username="head")  # APPS_OPEN
    await approved_applicant(session, ev.id, eg.game_id, 300)  # leader
    await approved_applicant(session, ev.id, eg.game_id, 301)  # recruit target
    await svc.advance(event_id=ev.id, actor_discord_id=1, actor_username="head")  # TEAM_FORMATION

    team = await TeamService(session).create_team(
        event_id=ev.id, name="Gamma", logo_url=None,
        leader_discord_id=300, leader_username="u300",
    )
    r = RecruitmentService(session)
    request = await r.recruit(
        event_id=ev.id, team_id=team.id, target_discord_id=301, target_username="u301",
        requester_discord_id=300, requester_username="u300", timeout_minutes=120,
    )
    accepted = await r.accept(
        event_id=ev.id, request_id=request.id, actor_discord_id=301, actor_username="u301"
    )
    assert accepted.status == RecruitRequestStatus.ACCEPTED

    membership = await TeamService(session).teams.active_membership(
        ev.id, (await TeamService(session).users.get_or_create(301, "u301")).id
    )
    assert membership is not None and membership.team_id == team.id

    # A non-target cannot accept someone else's request.
    request2 = await r.recruit(
        event_id=ev.id, team_id=team.id, target_discord_id=999, target_username="u999",
        requester_discord_id=300, requester_username="u300", timeout_minutes=120,
    )
    with pytest.raises(ServiceError):
        await r.accept(
            event_id=ev.id, request_id=request2.id, actor_discord_id=301, actor_username="u301"
        )
