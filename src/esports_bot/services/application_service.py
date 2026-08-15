"""Application submission & review use-cases (docs §9-10, FR-5/FR-6)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain import states, validators
from ..domain.enums import ApplicationStatus, EventState
from ..domain.server_blueprint import slug
from ..infra import audit
from ..models import Application, Game
from ..repositories.applications import ApplicationRepository
from ..repositories.core import EventRepository, GameRepository, UserRepository
from ..repositories.teams import TeamRepository
from .errors import ServiceError

_TEAM_OR_APP_STATES = {EventState.APPLICATIONS_OPEN, EventState.TEAM_FORMATION}


class ApplicationService:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session
        self.apps = ApplicationRepository(session)
        self.events = EventRepository(session)
        self.games = GameRepository(session)
        self.users = UserRepository(session)

    async def submit(
        self, *, event_id: int, game_id: int,
        discord_user_id: int, username: str, display_name: str | None,
        full_name: str, school_email: str,
        facebook_url: str, year_section: str, middle_initial: str | None = None,
        first_name: str | None = None,
    ) -> Application:
        event = await self.events.get(event_id)
        if event is None:
            raise ServiceError("No active event.")
        if event.state != EventState.APPLICATIONS_OPEN:
            raise ServiceError("Applications are not open right now.")
        if await self.games.get_event_game(event_id, game_id) is None:
            raise ServiceError("That game is not part of this event.")

        full_name = validators.sanitize_name(full_name, max_len=200, field="Full name")
        # First name is no longer collected separately — derive it from the full name.
        first_name = (
            validators.sanitize_name(first_name, max_len=100, field="First name")
            if first_name
            else full_name.split()[0][:100]
        )
        year_section = validators.sanitize_name(year_section, max_len=50, field="Year & section")
        school_email = validators.validate_school_email(school_email, event.email_domain)
        facebook_url = validators.validate_facebook_url(facebook_url)
        if middle_initial:
            middle_initial = validators.sanitize_name(
                middle_initial, max_len=10, field="Middle initial"
            )

        user = await self.users.get_or_create(discord_user_id, username, display_name)
        if await self.apps.active_for_user(event_id, user.id) is not None:
            raise ServiceError("You already have an active application for this event.")

        app = Application(
            event_id=event_id, game_id=game_id, user_id=user.id,
            first_name=first_name, full_name=full_name, middle_initial=middle_initial,
            school_email=school_email, facebook_url=facebook_url, year_section=year_section,
            status=ApplicationStatus.PENDING,
        )
        self.apps.add(app)
        try:
            await self._s.flush()
        except IntegrityError as exc:
            raise ServiceError(
                "A duplicate application already exists (email or account already used)."
            ) from exc
        self.apps.add_history(app.id, None, ApplicationStatus.PENDING, None, user.id)
        await audit.record(
            self._s, action="application.submit", event_id=event_id, actor_user_id=user.id,
            entity_type="application", entity_id=app.id,
            after={"game_id": game_id, "status": "PENDING"},
        )
        return app

    async def set_review_message(
        self, application_id: int, channel_id: int, message_id: int
    ) -> None:
        """Record the staff-review message so approve/reject can edit it later."""
        app = await self.apps.get(application_id)
        if app is not None:
            app.review_channel_id = channel_id
            app.review_message_id = message_id
            await self._s.flush()

    async def _transition(
        self, application_id: int, to_status: ApplicationStatus, *,
        actor_discord_id: int, actor_username: str, reason: str | None = None,
    ) -> Application:
        app = await self.apps.get(application_id)
        if app is None:
            raise ServiceError("Application not found.")
        states.assert_transition("application", app.status, to_status)
        actor = await self.users.get_or_create(actor_discord_id, actor_username)
        before = app.status
        app.status = to_status
        if to_status in (ApplicationStatus.REJECTED, ApplicationStatus.DISQUALIFIED):
            app.rejection_reason = reason
        if to_status in (ApplicationStatus.APPROVED, ApplicationStatus.REJECTED):
            app.reviewed_by = actor.id
        await self._s.flush()
        self.apps.add_history(app.id, before, to_status, reason, actor.id)
        await audit.record(
            self._s, action=f"application.{to_status.value.lower()}", event_id=app.event_id,
            actor_user_id=actor.id, entity_type="application", entity_id=app.id,
            before={"status": before.value}, after={"status": to_status.value, "reason": reason},
        )
        return app

    async def approve(self, application_id: int, *, actor_discord_id: int, actor_username: str):
        return await self._transition(
            application_id, ApplicationStatus.APPROVED,
            actor_discord_id=actor_discord_id, actor_username=actor_username,
        )

    async def reject(
        self, application_id: int, reason: str, *, actor_discord_id: int, actor_username: str
    ):
        if not reason or not reason.strip():
            raise ServiceError("A rejection reason is required.")
        return await self._transition(
            application_id, ApplicationStatus.REJECTED, reason=reason.strip(),
            actor_discord_id=actor_discord_id, actor_username=actor_username,
        )

    async def switch_game(
        self, *, event_id: int, discord_user_id: int, username: str, new_game_name: str
    ) -> tuple[str | None, str]:
        """Change the applicant's game. Returns (old_game_slug, new_game_slug)."""
        event = await self.events.get(event_id)
        if event is None or event.state not in _TEAM_OR_APP_STATES:
            raise ServiceError("You can't switch games right now.")
        user = await self.users.get_or_create(discord_user_id, username)
        app = await self.apps.active_for_user(event_id, user.id)
        if app is None:
            raise ServiceError("You don't have an active application.")
        if await TeamRepository(self._s).active_membership(event_id, user.id) is not None:
            raise ServiceError("Leave your team before switching games.")
        new_game_name = validators.sanitize_name(new_game_name, max_len=100, field="Game name")
        game = (
            await self._s.execute(select(Game).where(Game.name == new_game_name))
        ).scalar_one_or_none()
        if game is None:
            raise ServiceError(f"No game named '{new_game_name}'.")
        if await self.games.get_event_game(event_id, game.id) is None:
            raise ServiceError("That game is not part of this event.")
        if app.game_id == game.id:
            raise ServiceError("You already applied for that game.")

        old_game = await self._s.get(Game, app.game_id)
        old_slug = slug(old_game.name) if old_game else None
        app.game_id = game.id
        await self._s.flush()
        self.apps.add_history(
            app.id, app.status, app.status, f"switched game to {game.name}", user.id
        )
        await audit.record(
            self._s, action="application.switch_game", event_id=event_id, actor_user_id=user.id,
            entity_type="application", entity_id=app.id,
            before={"game": old_game.name if old_game else None}, after={"game": game.name},
        )
        return old_slug, slug(game.name)

    async def withdraw(self, application_id: int, *, actor_discord_id: int, actor_username: str):
        return await self._transition(
            application_id, ApplicationStatus.WITHDRAWN,
            actor_discord_id=actor_discord_id, actor_username=actor_username,
        )
