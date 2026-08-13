"""Repositories for core aggregates: users, events, games, staff."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.enums import EventState, StaffRole
from ..models import Event, EventGame, Game, StaffAssignment, User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get_or_create(
        self, discord_user_id: int, username: str, display_name: str | None = None
    ) -> User:
        res = await self._s.execute(
            select(User).where(User.discord_user_id == discord_user_id)
        )
        user = res.scalar_one_or_none()
        if user is None:
            user = User(
                discord_user_id=discord_user_id,
                discord_username=username,
                discord_display_name=display_name,
            )
            self._s.add(user)
            await self._s.flush()
        else:
            # Keep the cached username/display fresh.
            user.discord_username = username
            if display_name is not None:
                user.discord_display_name = display_name
        return user


class EventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get_active(self, guild_id: int) -> Event | None:
        res = await self._s.execute(
            select(Event).where(
                Event.guild_id == guild_id, Event.state != EventState.ARCHIVED
            )
        )
        return res.scalar_one_or_none()

    async def get(self, event_id: int) -> Event | None:
        return await self._s.get(Event, event_id)

    def add(self, event: Event) -> None:
        self._s.add(event)


class GameRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get_or_create(self, name: str, default_roster_size: int = 5) -> Game:
        res = await self._s.execute(select(Game).where(Game.name == name))
        game = res.scalar_one_or_none()
        if game is None:
            game = Game(name=name, default_roster_size=default_roster_size)
            self._s.add(game)
            await self._s.flush()
        return game

    async def list_for_event(self, event_id: int) -> list[EventGame]:
        res = await self._s.execute(
            select(EventGame).where(EventGame.event_id == event_id)
        )
        return list(res.scalars().all())

    async def list_games_for_event(self, event_id: int) -> list[Game]:
        res = await self._s.execute(
            select(Game)
            .join(EventGame, EventGame.game_id == Game.id)
            .where(EventGame.event_id == event_id)
        )
        return list(res.scalars().all())

    async def add_event_game(
        self, event_id: int, game_id: int, roster_size: int
    ) -> EventGame:
        eg = EventGame(event_id=event_id, game_id=game_id, roster_size=roster_size)
        self._s.add(eg)
        await self._s.flush()
        return eg

    async def get_event_game(self, event_id: int, game_id: int) -> EventGame | None:
        res = await self._s.execute(
            select(EventGame).where(
                EventGame.event_id == event_id, EventGame.game_id == game_id
            )
        )
        return res.scalar_one_or_none()


class StaffRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def list_active(self, event_id: int) -> list[StaffAssignment]:
        res = await self._s.execute(
            select(StaffAssignment).where(
                StaffAssignment.event_id == event_id, StaffAssignment.active.is_(True)
            )
        )
        return list(res.scalars().all())

    async def assign(
        self, event_id: int, user_id: int, staff_role: StaffRole, assigned_by: int | None
    ) -> StaffAssignment:
        sa = StaffAssignment(
            event_id=event_id, user_id=user_id, staff_role=staff_role,
            assigned_by=assigned_by, active=True,
        )
        self._s.add(sa)
        await self._s.flush()
        return sa
