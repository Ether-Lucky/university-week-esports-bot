"""CSV exporters (docs/export-specification.md).

Each function returns CSV text (UTF-8 with BOM, RFC-4180 quoting) so it can be
unit-tested; the cog writes the text to files under data/exports/.
"""

from __future__ import annotations

import csv
import io
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    Application,
    AuditLog,
    Checkin,
    Game,
    Match,
    MatchResult,
    Team,
    TeamMember,
    User,
)

BOM = "﻿"


def to_csv(headers: list[str], rows: list[list]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    writer.writerow(headers)
    for row in rows:
        writer.writerow(["" if c is None else c for c in row])
    return BOM + buf.getvalue()


async def _user(session: AsyncSession, user_id: int | None) -> User | None:
    return await session.get(User, user_id) if user_id else None


async def export_applicants(session: AsyncSession, event_id: int) -> str:
    res = await session.execute(
        select(Application, User, Game)
        .join(User, Application.user_id == User.id)
        .join(Game, Application.game_id == Game.id)
        .where(Application.event_id == event_id)
    )
    headers = [
        "application_id", "discord_user_id", "discord_username", "first_name", "full_name",
        "middle_initial", "school_email", "facebook_url", "year_section", "game", "status",
        "team_id", "rejection_reason", "created_at", "updated_at",
    ]
    rows = [
        [a.id, u.discord_user_id, u.discord_username, a.first_name, a.full_name,
         a.middle_initial, a.school_email, a.facebook_url, a.year_section, g.name,
         a.status.value, a.team_id, a.rejection_reason, a.created_at, a.updated_at]
        for a, u, g in res.all()
    ]
    return to_csv(headers, rows)


async def export_teams(session: AsyncSession, event_id: int) -> str:
    res = await session.execute(
        select(Team, Game).join(Game, Team.game_id == Game.id).where(Team.event_id == event_id)
    )
    headers = [
        "team_id", "game", "team_name", "leader_user_id", "roster_size", "status",
        "created_at", "disbanded_at",
    ]
    rows = [
        [t.id, g.name, t.name, t.leader_user_id, t.roster_size, t.status.value,
         t.created_at, t.disbanded_at]
        for t, g in res.all()
    ]
    return to_csv(headers, rows)


async def export_members(session: AsyncSession, event_id: int) -> str:
    res = await session.execute(
        select(TeamMember, User, Team)
        .join(User, TeamMember.user_id == User.id)
        .join(Team, TeamMember.team_id == Team.id)
        .where(TeamMember.event_id == event_id)
    )
    headers = [
        "team_member_id", "team_id", "team_name", "discord_user_id", "discord_username",
        "role_in_team", "joined_at", "left_at", "active",
    ]
    rows = [
        [tm.id, t.id, t.name, u.discord_user_id, u.discord_username,
         tm.role_in_team.value, tm.joined_at, tm.left_at, tm.active]
        for tm, u, t in res.all()
    ]
    return to_csv(headers, rows)


async def export_matches(session: AsyncSession, event_id: int) -> str:
    res = await session.execute(
        select(Match, MatchResult)
        .outerjoin(MatchResult, MatchResult.match_id == Match.id)
        .where(Match.event_id == event_id)
    )
    headers = [
        "match_id", "game_id", "round", "team_a_id", "team_b_id", "winner_team_id",
        "status", "screenshot_url", "corrected", "correction_reason", "notes",
    ]
    rows = [
        [m.id, m.game_id, m.round, m.team_a_id, m.team_b_id, m.winner_team_id, m.status.value,
         r.screenshot_url if r else None, r.corrected if r else None,
         r.correction_reason if r else None, r.notes if r else None]
        for m, r in res.all()
    ]
    return to_csv(headers, rows)


async def export_checkins(session: AsyncSession, event_id: int) -> str:
    res = await session.execute(
        select(Checkin, User)
        .join(User, Checkin.user_id == User.id)
        .where(Checkin.event_id == event_id)
    )
    headers = ["checkin_id", "team_id", "discord_user_id", "state", "created_at", "updated_at"]
    rows = [
        [c.id, c.team_id, u.discord_user_id, c.state.value, c.created_at, c.updated_at]
        for c, u in res.all()
    ]
    return to_csv(headers, rows)


async def export_logs(session: AsyncSession, event_id: int) -> str:
    res = await session.execute(
        select(AuditLog).where(AuditLog.event_id == event_id).order_by(AuditLog.id)
    )
    headers = [
        "audit_id", "timestamp", "actor_user_id", "action", "entity_type", "entity_id",
        "before", "after", "result", "error",
    ]
    rows = [
        [a.id, a.created_at, a.actor_user_id, a.action, a.entity_type, a.entity_id,
         json.dumps(a.before) if a.before else "", json.dumps(a.after) if a.after else "",
         a.result.value, a.error]
        for a in res.scalars().all()
    ]
    return to_csv(headers, rows)


EXPORTERS = {
    "applicants": export_applicants,
    "teams": export_teams,
    "members": export_members,
    "matches": export_matches,
    "checkins": export_checkins,
    "logs": export_logs,
}
