"""Application submission & review use-cases (docs §9-10, FR-5/FR-6)."""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain import states, validators
from ..domain.enums import ApplicationStatus, EventState
from ..infra import audit
from ..models import Application
from ..repositories.applications import ApplicationRepository
from ..repositories.core import EventRepository, GameRepository, UserRepository
from .errors import ServiceError


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
        first_name: str, full_name: str, school_email: str,
        facebook_url: str, year_section: str, middle_initial: str | None = None,
    ) -> Application:
        event = await self.events.get(event_id)
        if event is None:
            raise ServiceError("No active event.")
        if event.state != EventState.APPLICATIONS_OPEN:
            raise ServiceError("Applications are not open right now.")
        if await self.games.get_event_game(event_id, game_id) is None:
            raise ServiceError("That game is not part of this event.")

        first_name = validators.sanitize_name(first_name, max_len=100, field="First name")
        full_name = validators.sanitize_name(full_name, max_len=200, field="Full name")
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

    async def withdraw(self, application_id: int, *, actor_discord_id: int, actor_username: str):
        return await self._transition(
            application_id, ApplicationStatus.WITHDRAWN,
            actor_discord_id=actor_discord_id, actor_username=actor_username,
        )
