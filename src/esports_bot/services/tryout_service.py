"""Tryout lifecycle: validation, start (match provisioning), end (champions)."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from ..domain import states
from ..domain.enums import EventState, MatchStatus, TeamStatus
from ..domain.scheduling import match_channel_count, pair_teams
from ..infra import audit
from ..models import Game, Match
from ..repositories.competition import (
    MechanicsRepository,
    TournamentRepository,
    complete_teams,
)
from ..repositories.core import EventRepository, GameRepository, UserRepository
from ..repositories.teams import TeamRepository
from .errors import ServiceError


@dataclass
class GameReadiness:
    game_id: int
    game_name: str
    mechanics: bool
    challonge: bool
    complete_teams: int
    date_ok: bool

    @property
    def ready(self) -> bool:
        return self.mechanics and self.challonge and self.complete_teams >= 2 and self.date_ok


@dataclass
class GamePlan:
    game_id: int
    channel_count: int
    pairs: list[tuple[int, int]] = field(default_factory=list)
    bye: int | None = None


class TryoutService:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session
        self.events = EventRepository(session)
        self.games = GameRepository(session)
        self.teams = TeamRepository(session)
        self.users = UserRepository(session)
        self.mechanics = MechanicsRepository(session)
        self.tournaments = TournamentRepository(session)

    async def validate(self, event_id: int) -> tuple[list[GameReadiness], bool]:
        event = await self.events.get(event_id)
        if event is None:
            raise ServiceError("No active event.")
        readiness: list[GameReadiness] = []
        event_games = await self.games.list_for_event(event_id)
        for eg in event_games:
            game = await self._s.get(Game, eg.game_id)
            mechanics = await self.mechanics.current_published(eg.id) is not None
            tournament = await self.tournaments.get(eg.id)
            challonge = tournament is not None and bool(tournament.challonge_url)
            teams = len(await complete_teams(self._s, event_id, eg.game_id))
            date_ok = bool(event.tryout_at or eg.tryout_at)
            readiness.append(
                GameReadiness(eg.game_id, game.name, mechanics, challonge, teams, date_ok)
            )
        overall = bool(event_games) and all(r.ready for r in readiness)
        return readiness, overall

    async def start(self, *, event_id: int, actor_discord_id: int, actor_username: str
                    ) -> list[GamePlan]:
        event = await self.events.get(event_id)
        if event is None or event.state != EventState.PRE_TRYOUT:
            raise ServiceError("Tryout can only start from PRE_TRYOUT.")
        _, overall = await self.validate(event_id)
        if not overall:
            raise ServiceError("Not all games are ready. Run /tryout status.")

        plans: list[GamePlan] = []
        for eg in await self.games.list_for_event(event_id):
            teams = await complete_teams(self._s, event_id, eg.game_id)
            team_ids = [t.id for t in teams]
            pairs, bye = pair_teams(team_ids)
            for a, b in pairs:
                self._s.add(Match(
                    event_id=event_id, game_id=eg.game_id, round=1,
                    team_a_id=a, team_b_id=b, status=MatchStatus.SCHEDULED,
                ))
            for t in teams:
                t.status = TeamStatus.COMPETING
            plans.append(GamePlan(eg.game_id, match_channel_count(len(team_ids)), pairs, bye))

        event.state = EventState.TRYOUT_ACTIVE
        await self._s.flush()
        actor = await self.users.get_or_create(actor_discord_id, actor_username)
        await audit.record(
            self._s, action="tryout.start", event_id=event_id, actor_user_id=actor.id,
            entity_type="event", entity_id=event_id,
        )
        return plans

    async def crown_champion(
        self, *, event_id: int, game_id: int, team_id: int,
        actor_discord_id: int, actor_username: str,
    ) -> list[int]:
        """Mark a team CHAMPION. Returns the champion members' Discord IDs (for Player role)."""
        event = await self.events.get(event_id)
        if event is None or event.state != EventState.TRYOUT_ACTIVE:
            raise ServiceError("Tryout is not in progress.")
        team = await self.teams.get(team_id)
        if team is None or team.game_id != game_id:
            raise ServiceError("Champion team does not match the game.")
        if team.status != TeamStatus.CHAMPION:
            states.assert_transition("team", team.status, TeamStatus.CHAMPION)
            team.status = TeamStatus.CHAMPION
        discord_ids = [
            await self.users_by_id(m.user_id) for m in await self.teams.active_members(team.id)
        ]
        await self._s.flush()
        actor = await self.users.get_or_create(actor_discord_id, actor_username)
        await audit.record(
            self._s, action="tryout.champion", event_id=event_id, actor_user_id=actor.id,
            entity_type="team", entity_id=team_id, after={"game_id": game_id},
        )
        return discord_ids

    async def finish(self, *, event_id: int, actor_discord_id: int, actor_username: str) -> None:
        """Move the event from TRYOUT_ACTIVE to RESULTS."""
        event = await self.events.get(event_id)
        if event is None or event.state != EventState.TRYOUT_ACTIVE:
            raise ServiceError("Tryout is not in progress.")
        states.assert_transition("event", event.state, EventState.RESULTS)
        event.state = EventState.RESULTS
        await self._s.flush()
        actor = await self.users.get_or_create(actor_discord_id, actor_username)
        await audit.record(
            self._s, action="tryout.end", event_id=event_id, actor_user_id=actor.id,
            entity_type="event", entity_id=event_id,
        )

    async def end(
        self, *, event_id: int, champions: dict[int, int],
        actor_discord_id: int, actor_username: str,
    ) -> dict[int, list[int]]:
        """Crown all champions then finish. Returns {game_id: [champion Discord IDs]}."""
        member_ids: dict[int, list[int]] = {}
        for game_id, team_id in champions.items():
            member_ids[game_id] = await self.crown_champion(
                event_id=event_id, game_id=game_id, team_id=team_id,
                actor_discord_id=actor_discord_id, actor_username=actor_username,
            )
        await self.finish(
            event_id=event_id, actor_discord_id=actor_discord_id, actor_username=actor_username
        )
        return member_ids

    async def users_by_id(self, user_id: int) -> int:
        from ..models import User

        user = await self._s.get(User, user_id)
        return user.discord_user_id if user else 0
