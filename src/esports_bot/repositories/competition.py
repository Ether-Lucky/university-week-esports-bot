"""Repositories for mechanics, tournaments, check-ins, and matches."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.enums import CheckinState, TeamStatus
from ..models import Checkin, Match, MatchResult, Mechanics, Team, TeamMember, Tournament


class MechanicsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def latest_version(self, event_game_id: int) -> int:
        return await self._s.scalar(
            select(func.coalesce(func.max(Mechanics.version), 0)).where(
                Mechanics.event_game_id == event_game_id
            )
        ) or 0

    def add(self, mechanics: Mechanics) -> None:
        self._s.add(mechanics)

    async def current_published(self, event_game_id: int) -> Mechanics | None:
        res = await self._s.execute(
            select(Mechanics)
            .where(Mechanics.event_game_id == event_game_id, Mechanics.published.is_(True))
            .order_by(Mechanics.version.desc())
            .limit(1)
        )
        return res.scalar_one_or_none()

    async def latest(self, event_game_id: int) -> Mechanics | None:
        res = await self._s.execute(
            select(Mechanics)
            .where(Mechanics.event_game_id == event_game_id)
            .order_by(Mechanics.version.desc())
            .limit(1)
        )
        return res.scalar_one_or_none()


class TournamentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get(self, event_game_id: int) -> Tournament | None:
        res = await self._s.execute(
            select(Tournament).where(Tournament.event_game_id == event_game_id)
        )
        return res.scalar_one_or_none()

    def add(self, tournament: Tournament) -> None:
        self._s.add(tournament)


class CheckinRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get(self, team_id: int, user_id: int) -> Checkin | None:
        res = await self._s.execute(
            select(Checkin).where(Checkin.team_id == team_id, Checkin.user_id == user_id)
        )
        return res.scalar_one_or_none()

    def add(self, checkin: Checkin) -> None:
        self._s.add(checkin)

    async def count_checked_in(self, team_id: int) -> int:
        return await self._s.scalar(
            select(func.count()).select_from(Checkin).where(
                Checkin.team_id == team_id, Checkin.state == CheckinState.CHECKED_IN
            )
        ) or 0


class MatchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    def add(self, match: Match) -> None:
        self._s.add(match)

    async def get(self, match_id: int) -> Match | None:
        return await self._s.get(Match, match_id)

    def add_result(self, result: MatchResult) -> None:
        self._s.add(result)

    async def result_for(self, match_id: int) -> MatchResult | None:
        res = await self._s.execute(
            select(MatchResult).where(MatchResult.match_id == match_id)
        )
        return res.scalar_one_or_none()


async def complete_teams(session: AsyncSession, event_id: int, game_id: int) -> list[Team]:
    """Teams for a game eligible to compete.

    A team qualifies with at least ``roster_size - 1`` active members — the roster
    size includes one reserve slot, so a team that's one short can still play (e.g.
    5 of 6). Disbanded teams are excluded.
    """
    member_count = (
        select(func.count())
        .select_from(TeamMember)
        .where(TeamMember.team_id == Team.id, TeamMember.active.is_(True))
        .scalar_subquery()
    )
    res = await session.execute(
        select(Team).where(
            Team.event_id == event_id,
            Team.game_id == game_id,
            Team.status != TeamStatus.DISBANDED,
            member_count >= func.greatest(Team.roster_size - 1, 1),
        )
    )
    return list(res.scalars().all())
