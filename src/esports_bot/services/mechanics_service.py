"""Mechanics & tournament (Challonge link) use-cases (docs §17-18)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..domain import validators
from ..infra import audit
from ..models import Mechanics, Tournament
from ..repositories.competition import MechanicsRepository, TournamentRepository
from ..repositories.core import UserRepository
from .errors import ServiceError


class MechanicsService:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session
        self.repo = MechanicsRepository(session)
        self.users = UserRepository(session)

    async def create(
        self, *, event_id: int, event_game_id: int, title: str, body: dict,
        actor_discord_id: int, actor_username: str, publish: bool = False,
    ) -> Mechanics:
        title = validators.sanitize_name(title, max_len=256, field="Title")
        if not isinstance(body, dict) or not body:
            raise ServiceError("Mechanics body must be non-empty.")
        actor = await self.users.get_or_create(actor_discord_id, actor_username)
        version = await self.repo.latest_version(event_game_id) + 1
        m = Mechanics(
            event_game_id=event_game_id, version=version, title=title, body=body,
            published=publish, created_by=actor.id,
        )
        self.repo.add(m)
        await self._s.flush()
        await audit.record(
            self._s, action="mechanics.create", event_id=event_id, actor_user_id=actor.id,
            entity_type="mechanics", entity_id=m.id,
            after={"version": version, "published": publish},
        )
        return m

    async def publish(self, *, event_id: int, event_game_id: int, actor_discord_id: int,
                      actor_username: str) -> Mechanics:
        latest = await self.repo.latest(event_game_id)
        if latest is None:
            raise ServiceError("No mechanics to publish. Create them first.")
        latest.published = True
        await self._s.flush()
        actor = await self.users.get_or_create(actor_discord_id, actor_username)
        await audit.record(
            self._s, action="mechanics.publish", event_id=event_id, actor_user_id=actor.id,
            entity_type="mechanics", entity_id=latest.id,
        )
        return latest

    async def has_published(self, event_game_id: int) -> bool:
        return await self.repo.current_published(event_game_id) is not None

    async def latest(self, event_game_id: int) -> Mechanics | None:
        """The most recent mechanics for a game (published or not), for previewing."""
        return await self.repo.latest(event_game_id)


class TournamentService:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session
        self.repo = TournamentRepository(session)
        self.users = UserRepository(session)

    async def set_challonge(
        self, *, event_id: int, event_game_id: int, url: str,
        actor_discord_id: int, actor_username: str,
    ) -> Tournament:
        url = validators.validate_https_url(url, field="Challonge URL")
        actor = await self.users.get_or_create(actor_discord_id, actor_username)
        tournament = await self.repo.get(event_game_id)
        if tournament is None:
            tournament = Tournament(event_game_id=event_game_id, challonge_url=url,
                                    updated_by=actor.id)
            self.repo.add(tournament)
        else:
            tournament.challonge_url = url
            tournament.updated_by = actor.id
        await self._s.flush()
        await audit.record(
            self._s, action="tournament.set_challonge", event_id=event_id,
            actor_user_id=actor.id, entity_type="tournament", entity_id=tournament.id,
            after={"url": url},
        )
        return tournament

    async def has_challonge(self, event_game_id: int) -> bool:
        t = await self.repo.get(event_game_id)
        return t is not None and bool(t.challonge_url)
