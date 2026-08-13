"""End-to-end lifecycle test against live Postgres (rolled back).

Setup -> Applications -> Teams -> Mechanics/Challonge -> Tryout start ->
Battle result -> Champion -> Exports -> Cleanup -> Archive.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from tests.integration.conftest import approved_applicant, make_event

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DB_TESTS") != "1",
    reason="Set RUN_DB_TESTS=1 to run live-DB tests.",
)


async def test_full_lifecycle(session) -> None:
    from esports_bot.domain.enums import EventState, TeamStatus
    from esports_bot.infra import exporter
    from esports_bot.models import Match
    from esports_bot.services.cleanup_service import CleanupService
    from esports_bot.services.match_service import MatchService
    from esports_bot.services.mechanics_service import MechanicsService, TournamentService
    from esports_bot.services.team_service import TeamService
    from esports_bot.services.tryout_service import TryoutService

    ev_svc, ev = await make_event(session, state_advances=0)
    eg = await ev_svc.add_game(
        event_id=ev.id, game_name="Valorant", roster_size=2,
        actor_discord_id=1, actor_username="head",
    )
    # DRAFT -> SETUP -> APPLICATIONS_OPEN
    await ev_svc.advance(event_id=ev.id, actor_discord_id=1, actor_username="head")
    await ev_svc.advance(event_id=ev.id, actor_discord_id=1, actor_username="head")
    for did in (100, 101, 102, 103):
        await approved_applicant(session, ev.id, eg.game_id, did)
    # -> TEAM_FORMATION
    await ev_svc.advance(event_id=ev.id, actor_discord_id=1, actor_username="head")

    ts = TeamService(session)
    team_a = await ts.create_team(
        event_id=ev.id, name="Alpha", logo_url=None,
        leader_discord_id=100, leader_username="u100",
    )
    await ts.join_team(event_id=ev.id, team_id=team_a.id, user_discord_id=101, username="u101")
    team_b = await ts.create_team(
        event_id=ev.id, name="Bravo", logo_url=None,
        leader_discord_id=102, leader_username="u102",
    )
    await ts.join_team(event_id=ev.id, team_id=team_b.id, user_discord_id=103, username="u103")
    assert team_a.status == TeamStatus.FULL and team_b.status == TeamStatus.FULL

    # Mechanics + Challonge + tryout date.
    await MechanicsService(session).create(
        event_id=ev.id, event_game_id=eg.id, title="Rules", body={"description": "Best of 3"},
        actor_discord_id=1, actor_username="staff", publish=True,
    )
    await TournamentService(session).set_challonge(
        event_id=ev.id, event_game_id=eg.id, url="https://challonge.com/uw",
        actor_discord_id=1, actor_username="staff",
    )
    await ev_svc.set_schedule(
        event_id=ev.id, actor_discord_id=1, actor_username="head",
        tryout_at=datetime(2027, 2, 14, 9, tzinfo=UTC),
    )
    # TEAM_FORMATION -> REGISTRATION_LOCKED -> PRE_TRYOUT
    await ev_svc.advance(event_id=ev.id, actor_discord_id=1, actor_username="head")
    await ev_svc.advance(event_id=ev.id, actor_discord_id=1, actor_username="head")

    tryout = TryoutService(session)
    readiness, overall = await tryout.validate(ev.id)
    assert overall, readiness

    plans = await tryout.start(event_id=ev.id, actor_discord_id=1, actor_username="head")
    assert plans[0].channel_count == 1  # floor(2/2)
    matches = (await session.execute(select(Match).where(Match.event_id == ev.id))).scalars().all()
    assert len(matches) == 1

    # Record the battle result; Alpha wins.
    await MatchService(session).record_result(
        event_id=ev.id, match_id=matches[0].id, winner_team_id=team_a.id,
        screenshot_url=None, notes="gg", reporter_discord_id=1, reporter_username="staff",
    )

    member_ids = await tryout.crown_champion(
        event_id=ev.id, game_id=eg.game_id, team_id=team_a.id,
        actor_discord_id=1, actor_username="head",
    )
    assert set(member_ids) == {100, 101}
    await tryout.finish(event_id=ev.id, actor_discord_id=1, actor_username="head")

    # Exports contain data.
    applicants_csv = await exporter.export_applicants(session, ev.id)
    assert "uphsl.edu.ph" in applicants_csv and "application_id" in applicants_csv
    teams_csv = await exporter.export_teams(session, ev.id)
    assert "Alpha" in teams_csv and "Bravo" in teams_csv

    # Cleanup: Bravo disbanded, Alpha (champion) preserved.
    cleanup = CleanupService(session)
    disbanded = await cleanup.cleanup(event_id=ev.id, actor_discord_id=1, actor_username="head")
    assert team_b.id in disbanded and team_a.id not in disbanded
    refreshed_a = await ts.teams.get(team_a.id)
    assert refreshed_a.status == TeamStatus.CHAMPION

    await cleanup.archive(event_id=ev.id, actor_discord_id=1, actor_username="head")
    archived = await ev_svc.events.get(ev.id)
    assert archived.state == EventState.ARCHIVED
