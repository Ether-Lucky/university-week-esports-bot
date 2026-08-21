"""Battle result recording & correction (docs §23-24, FR-16/FR-17)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..domain import states
from ..domain.enums import MatchStatus, TeamStatus
from ..infra import audit
from ..models import Match, MatchResult
from ..repositories.competition import MatchRepository
from ..repositories.core import UserRepository
from ..repositories.teams import TeamRepository
from .errors import ServiceError


class MatchService:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session
        self.matches = MatchRepository(session)
        self.teams = TeamRepository(session)
        self.users = UserRepository(session)

    async def create_match(
        self, *, event_id: int, game_id: int, team_a_id: int, team_b_id: int | None
    ) -> Match:
        match = Match(
            event_id=event_id, game_id=game_id, team_a_id=team_a_id,
            team_b_id=team_b_id, status=MatchStatus.SCHEDULED,
        )
        self.matches.add(match)
        await self._s.flush()
        return match

    async def record_result(
        self, *, event_id: int, match_id: int, winner_team_id: int,
        screenshot_url: str | None, notes: str | None,
        reporter_discord_id: int, reporter_username: str,
    ) -> MatchResult:
        match = await self.matches.get(match_id)
        if match is None:
            raise ServiceError("Match not found.")
        if winner_team_id not in (match.team_a_id, match.team_b_id):
            raise ServiceError("Winner must be one of the two teams in the match.")
        reporter = await self.users.get_or_create(reporter_discord_id, reporter_username)

        match.winner_team_id = winner_team_id
        match.status = MatchStatus.COMPLETED
        # NB: recording a result does NOT eliminate the loser — a "battle" may be one
        # game of a best-of-N series, and the bracket/advancement lives in Challonge.

        result = await self.matches.result_for(match_id)
        if result is None:
            result = MatchResult(
                match_id=match_id, winner_team_id=winner_team_id,
                screenshot_url=screenshot_url, notes=notes, reported_by=reporter.id,
            )
            self.matches.add_result(result)
        else:
            result.winner_team_id = winner_team_id
            result.screenshot_url = screenshot_url
            result.notes = notes
        await self._s.flush()
        await audit.record(
            self._s, action="match.result", event_id=event_id, actor_user_id=reporter.id,
            entity_type="match", entity_id=match_id, after={"winner": winner_team_id},
        )
        return result

    async def retract(
        self, *, event_id: int, match_id: int, reason: str,
        actor_discord_id: int, actor_username: str,
    ) -> Match:
        """Undo a recorded result: reopen the match and un-eliminate the loser."""
        if not reason or not reason.strip():
            raise ServiceError("A reason is required to retract a result.")
        match = await self.matches.get(match_id)
        if match is None:
            raise ServiceError("Match not found.")
        result = await self.matches.result_for(match_id)
        if match.status != MatchStatus.COMPLETED and result is None:
            raise ServiceError("That match has no recorded result to retract.")
        actor = await self.users.get_or_create(actor_discord_id, actor_username)
        before_winner = match.winner_team_id

        # Bring the eliminated loser back into the tournament.
        if before_winner is not None:
            loser_id = (
                match.team_b_id if before_winner == match.team_a_id else match.team_a_id
            )
            if loser_id is not None:
                loser = await self.teams.get(loser_id)
                if loser and loser.status == TeamStatus.ELIMINATED:
                    loser.status = TeamStatus.COMPETING

        match.winner_team_id = None
        match.status = MatchStatus.SCHEDULED
        if result is not None:
            await self._s.delete(result)
        await self._s.flush()
        await audit.record(
            self._s, action="match.retract", event_id=event_id, actor_user_id=actor.id,
            entity_type="match", entity_id=match_id,
            before={"winner": before_winner}, after={"reason": reason.strip()},
        )
        return match

    async def correct(
        self, *, event_id: int, match_id: int, winner_team_id: int, reason: str,
        actor_discord_id: int, actor_username: str,
    ) -> MatchResult:
        if not reason or not reason.strip():
            raise ServiceError("A correction reason is required.")
        match = await self.matches.get(match_id)
        result = await self.matches.result_for(match_id)
        if match is None or result is None:
            raise ServiceError("Match result not found.")
        if winner_team_id not in (match.team_a_id, match.team_b_id):
            raise ServiceError("Winner must be one of the two teams in the match.")
        actor = await self.users.get_or_create(actor_discord_id, actor_username)
        before = result.winner_team_id
        result.winner_team_id = winner_team_id
        result.corrected = True
        result.correction_reason = reason.strip()
        match.winner_team_id = winner_team_id
        if match.status == MatchStatus.DISPUTED:
            states.assert_transition("match", MatchStatus.DISPUTED, MatchStatus.COMPLETED)
            match.status = MatchStatus.COMPLETED
        await self._s.flush()
        await audit.record(
            self._s, action="match.correct", event_id=event_id, actor_user_id=actor.id,
            entity_type="match", entity_id=match_id,
            before={"winner": before}, after={"winner": winner_team_id, "reason": reason},
        )
        return result
