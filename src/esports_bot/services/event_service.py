"""Event lifecycle & configuration use-cases (docs/event-lifecycle.md)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain import states, validators
from ..domain.enums import ApplicationStatus, EventState, TeamStatus
from ..infra import audit
from ..models import Application, Event, Team
from ..repositories.core import EventRepository, GameRepository, UserRepository
from .errors import ServiceError

_CONFIGURABLE_STATES = {EventState.DRAFT, EventState.SETUP}


class EventService:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session
        self.events = EventRepository(session)
        self.games = GameRepository(session)
        self.users = UserRepository(session)

    async def create_event(
        self,
        *,
        guild_id: int,
        name: str,
        year: int,
        school_name: str,
        email_domain: str,
        timezone: str,
        actor_discord_id: int,
        actor_username: str,
    ) -> Event:
        existing = await self.events.get_active(guild_id)
        if existing is not None:
            raise ServiceError(
                f"An active event already exists ({existing.name} {existing.year}). "
                "Archive it before creating a new one."
            )
        name = validators.sanitize_name(name, max_len=200, field="Event name")
        school_name = validators.sanitize_name(school_name, max_len=200, field="School name")
        year = validators.validate_year(year)
        email_domain = validators.validate_email_domain(email_domain)
        timezone = validators.validate_timezone(timezone)

        actor = await self.users.get_or_create(actor_discord_id, actor_username)
        event = Event(
            guild_id=guild_id, name=name, year=year, school_name=school_name,
            email_domain=email_domain, timezone=timezone, state=EventState.DRAFT,
        )
        self.events.add(event)
        await self._s.flush()
        await audit.record(
            self._s, action="event.create", event_id=event.id,
            actor_user_id=actor.id, entity_type="event", entity_id=event.id,
            after={"name": name, "year": year, "state": EventState.DRAFT.value},
        )
        return event

    async def _require_event(self, event_id: int) -> Event:
        event = await self.events.get(event_id)
        if event is None:
            raise ServiceError("Event not found.")
        return event

    async def add_game(
        self, *, event_id: int, game_name: str, roster_size: int,
        actor_discord_id: int, actor_username: str,
    ):
        event = await self._require_event(event_id)
        if event.state not in _CONFIGURABLE_STATES:
            raise ServiceError(
                f"Games can only be configured while in DRAFT/SETUP (now {event.state})."
            )
        game_name = validators.sanitize_name(game_name, max_len=100, field="Game name")
        roster_size = validators.validate_roster_size(roster_size)

        game = await self.games.get_or_create(game_name, roster_size)
        if await self.games.get_event_game(event_id, game.id) is not None:
            raise ServiceError(f"{game_name} is already configured for this event.")
        eg = await self.games.add_event_game(event_id, game.id, roster_size)
        actor = await self.users.get_or_create(actor_discord_id, actor_username)
        await audit.record(
            self._s, action="event.add_game", event_id=event_id,
            actor_user_id=actor.id, entity_type="event_game", entity_id=eg.id,
            after={"game": game_name, "roster_size": roster_size},
        )
        return eg

    async def set_schedule(
        self, *, event_id: int, actor_discord_id: int, actor_username: str,
        applications_open_at: datetime | None = None,
        applications_close_at: datetime | None = None,
        team_creation_deadline: datetime | None = None,
        recruitment_deadline: datetime | None = None,
        tryout_at: datetime | None = None,
    ) -> Event:
        event = await self._require_event(event_id)
        before = {
            "applications_open_at": str(event.applications_open_at),
            "tryout_at": str(event.tryout_at),
        }
        for field_name, value in (
            ("applications_open_at", applications_open_at),
            ("applications_close_at", applications_close_at),
            ("team_creation_deadline", team_creation_deadline),
            ("recruitment_deadline", recruitment_deadline),
            ("tryout_at", tryout_at),
        ):
            if value is not None:
                setattr(event, field_name, value)
        await self._s.flush()
        actor = await self.users.get_or_create(actor_discord_id, actor_username)
        await audit.record(
            self._s, action="event.set_schedule", event_id=event_id,
            actor_user_id=actor.id, entity_type="event", entity_id=event_id,
            before=before,
            after={"tryout_at": str(event.tryout_at)},
        )
        return event

    async def advance(self, *, event_id: int, actor_discord_id: int, actor_username: str) -> Event:
        event = await self._require_event(event_id)
        nxt = states.next_event_state(event.state)
        if nxt is None:
            raise ServiceError(f"Event is already at the final state ({event.state}).")
        states.assert_transition("event", event.state, nxt)
        before = event.state
        event.state = nxt
        await self._s.flush()
        actor = await self.users.get_or_create(actor_discord_id, actor_username)
        await audit.record(
            self._s, action="event.advance", event_id=event_id, actor_user_id=actor.id,
            entity_type="event", entity_id=event_id,
            before={"state": before.value}, after={"state": nxt.value},
        )
        return event

    async def rollback(
        self, *, event_id: int, reason: str, actor_discord_id: int, actor_username: str
    ) -> Event:
        event = await self._require_event(event_id)
        if not states.can_rollback_event(event.state):
            raise ServiceError(f"Cannot roll back from {event.state}.")
        prev = states.previous_event_state(event.state)
        assert prev is not None
        before = event.state
        event.state = prev
        await self._s.flush()
        actor = await self.users.get_or_create(actor_discord_id, actor_username)
        await audit.record(
            self._s, action="event.rollback", event_id=event_id, actor_user_id=actor.id,
            entity_type="event", entity_id=event_id,
            before={"state": before.value}, after={"state": prev.value, "reason": reason},
        )
        return event

    async def status(self, event_id: int) -> dict:
        event = await self._require_event(event_id)
        applicants = await self._s.scalar(
            select(func.count()).select_from(Application).where(Application.event_id == event_id)
        )
        approved = await self._s.scalar(
            select(func.count()).select_from(Application).where(
                Application.event_id == event_id,
                Application.status == ApplicationStatus.APPROVED,
            )
        )
        teams = await self._s.scalar(
            select(func.count()).select_from(Team).where(
                Team.event_id == event_id, Team.status != TeamStatus.DISBANDED
            )
        )
        games = await self.games.list_for_event(event_id)
        return {
            "name": event.name,
            "year": event.year,
            "state": event.state.value,
            "games": len(games),
            "applicants": applicants or 0,
            "approved": approved or 0,
            "teams": teams or 0,
        }
