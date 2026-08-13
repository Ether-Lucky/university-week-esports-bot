"""TeamService integration tests against live Postgres (rolled back)."""

from __future__ import annotations

import os

import pytest

from esports_bot.services.errors import ServiceError
from tests.integration.conftest import approved_applicant, make_event

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DB_TESTS") != "1",
    reason="Set RUN_DB_TESTS=1 to run live-DB tests.",
)


async def _formation_event_with_game(session, roster_size=2):
    svc, ev = await make_event(session, state_advances=0)
    eg = await svc.add_game(
        event_id=ev.id, game_name="Valorant", roster_size=roster_size,
        actor_discord_id=1, actor_username="head",
    )
    # DRAFT -> SETUP -> APPLICATIONS_OPEN
    await svc.advance(event_id=ev.id, actor_discord_id=1, actor_username="head")
    await svc.advance(event_id=ev.id, actor_discord_id=1, actor_username="head")
    return svc, ev, eg


async def test_create_join_full_and_guards(session) -> None:
    from esports_bot.domain.enums import TeamStatus
    from esports_bot.services.team_service import TeamService

    svc, ev, eg = await _formation_event_with_game(session, roster_size=2)
    await approved_applicant(session, ev.id, eg.game_id, 100)  # leader
    await approved_applicant(session, ev.id, eg.game_id, 101)  # member
    await approved_applicant(session, ev.id, eg.game_id, 102)  # extra
    # APPLICATIONS_OPEN -> TEAM_FORMATION
    await svc.advance(event_id=ev.id, actor_discord_id=1, actor_username="head")

    t = TeamService(session)
    team = await t.create_team(
        event_id=ev.id, name="Alpha", logo_url=None,
        leader_discord_id=100, leader_username="u100",
    )
    assert team.status == TeamStatus.RECRUITING

    # Duplicate name refused.
    with pytest.raises(ServiceError):
        await t.create_team(
            event_id=ev.id, name="Alpha", logo_url=None,
            leader_discord_id=102, leader_username="u102",
        )

    team = await t.join_team(
        event_id=ev.id, team_id=team.id, user_discord_id=101, username="u101"
    )
    assert team.status == TeamStatus.FULL  # roster_size 2 reached

    # Third member refused (full).
    with pytest.raises(ServiceError):
        await t.join_team(
            event_id=ev.id, team_id=team.id, user_discord_id=102, username="u102"
        )

    # Leader can't leave while others remain.
    with pytest.raises(ServiceError):
        await t.leave_team(event_id=ev.id, user_discord_id=100, username="u100")

    # Member leaves -> team back to RECRUITING.
    await t.leave_team(event_id=ev.id, user_discord_id=101, username="u101")
    refreshed = await t.teams.get(team.id)
    assert refreshed.status == TeamStatus.RECRUITING


async def test_disband_frees_members(session) -> None:
    from esports_bot.domain.enums import ApplicationStatus, TeamStatus
    from esports_bot.services.team_service import TeamService

    svc, ev, eg = await _formation_event_with_game(session, roster_size=3)
    await approved_applicant(session, ev.id, eg.game_id, 200)
    await approved_applicant(session, ev.id, eg.game_id, 201)
    await svc.advance(event_id=ev.id, actor_discord_id=1, actor_username="head")

    t = TeamService(session)
    team = await t.create_team(
        event_id=ev.id, name="Bravo", logo_url=None,
        leader_discord_id=200, leader_username="u200",
    )
    await t.join_team(event_id=ev.id, team_id=team.id, user_discord_id=201, username="u201")
    await t.disband(
        event_id=ev.id, team_id=team.id, actor_discord_id=200, actor_username="u200",
        reason="test",
    )
    refreshed = await t.teams.get(team.id)
    assert refreshed.status == TeamStatus.DISBANDED
    # Freed members can join/create again — their applications revert to APPROVED.
    app = await t.teams.approved_application(ev.id, (await t.users.get_or_create(201, "u201")).id)
    assert app.status == ApplicationStatus.APPROVED
