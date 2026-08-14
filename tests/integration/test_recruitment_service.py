"""RecruitmentService integration tests (live Postgres, rolled back)."""

from __future__ import annotations

import os

import pytest

from esports_bot.services.errors import ServiceError
from tests.integration.conftest import approved_applicant, make_event

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DB_TESTS") != "1",
    reason="Set RUN_DB_TESTS=1 to run live-DB tests.",
)


async def _formation_with_team(session):
    from esports_bot.services.team_service import TeamService

    svc, ev = await make_event(session, state_advances=0)
    eg = await svc.add_game(
        event_id=ev.id, game_name="Valorant", roster_size=4,
        actor_discord_id=1, actor_username="head",
    )
    await svc.advance(event_id=ev.id, actor_discord_id=1, actor_username="head")  # SETUP
    await svc.advance(event_id=ev.id, actor_discord_id=1, actor_username="head")  # APPS_OPEN
    for did in (300, 301, 302, 303):
        await approved_applicant(session, ev.id, eg.game_id, did)
    await svc.advance(event_id=ev.id, actor_discord_id=1, actor_username="head")  # TEAM_FORMATION
    team = await TeamService(session).create_team(
        event_id=ev.id, name="Gamma", logo_url=None,
        leader_discord_id=300, leader_username="u300",
    )
    return ev, eg, team


async def test_recruit_then_player_accepts(session) -> None:
    from esports_bot.services.recruitment_service import RecruitmentService
    from esports_bot.services.team_service import TeamService

    ev, eg, team = await _formation_with_team(session)
    r = RecruitmentService(session)
    request = await r.recruit(
        event_id=ev.id, team_id=team.id, target_discord_id=301, target_username="u301",
        requester_discord_id=300, requester_username="u300", timeout_minutes=120,
    )
    info = await r.accept_request(
        request_id=request.id, actor_discord_id=301, actor_username="u301"
    )
    assert info.kind == "RECRUIT" and info.joining_discord_id == 301

    membership = await TeamService(session).teams.active_membership(
        ev.id, (await TeamService(session).users.get_or_create(301, "u301")).id
    )
    assert membership is not None and membership.team_id == team.id

    # A non-target cannot accept someone else's recruit request.
    request2 = await r.recruit(
        event_id=ev.id, team_id=team.id, target_discord_id=302, target_username="u302",
        requester_discord_id=300, requester_username="u300", timeout_minutes=120,
    )
    with pytest.raises(ServiceError):
        await r.accept_request(request_id=request2.id, actor_discord_id=301, actor_username="u301")


async def test_join_request_needs_profile_then_leader_accepts(session) -> None:
    from esports_bot.services.recruitment_service import RecruitmentService
    from esports_bot.services.team_service import TeamService

    ev, eg, team = await _formation_with_team(session)
    r = RecruitmentService(session)

    # No LFT profile -> refused with advice to /findteam.
    with pytest.raises(ServiceError):
        await r.request_join(
            event_id=ev.id, team_id=team.id, applicant_discord_id=302,
            username="u302", timeout_minutes=120,
        )

    # Create a profile, then request to join.
    await r.create_lft_post(
        event_id=ev.id, user_discord_id=302, username="u302", ign="Ace", main_role="Duelist",
    )
    request = await r.request_join(
        event_id=ev.id, team_id=team.id, applicant_discord_id=302,
        username="u302", timeout_minutes=120,
    )

    # The applicant (not the leader) cannot approve their own join.
    with pytest.raises(ServiceError):
        await r.accept_request(request_id=request.id, actor_discord_id=302, actor_username="u302")

    # The leader accepts -> applicant joins.
    info = await r.accept_request(
        request_id=request.id, actor_discord_id=300, actor_username="u300"
    )
    assert info.kind == "JOIN" and info.joining_discord_id == 302
    membership = await TeamService(session).teams.active_membership(
        ev.id, (await TeamService(session).users.get_or_create(302, "u302")).id
    )
    assert membership is not None and membership.team_id == team.id


async def test_reject_requires_reason(session) -> None:
    from esports_bot.services.recruitment_service import RecruitmentService

    ev, eg, team = await _formation_with_team(session)
    r = RecruitmentService(session)
    request = await r.recruit(
        event_id=ev.id, team_id=team.id, target_discord_id=301, target_username="u301",
        requester_discord_id=300, requester_username="u300", timeout_minutes=120,
    )
    with pytest.raises(ServiceError):
        await r.reject_request(
            request_id=request.id, actor_discord_id=301, actor_username="u301", reason="  "
        )
    info = await r.reject_request(
        request_id=request.id, actor_discord_id=301, actor_username="u301", reason="not a fit"
    )
    assert info.reason == "not a fit" and info.requester_discord_id == 300
