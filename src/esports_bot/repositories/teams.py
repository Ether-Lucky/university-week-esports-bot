"""Team & membership repository."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Application, Team, TeamMember


class TeamRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get(self, team_id: int) -> Team | None:
        return await self._s.get(Team, team_id)

    async def get_by_name(self, event_id: int, game_id: int, name: str) -> Team | None:
        res = await self._s.execute(
            select(Team).where(
                Team.event_id == event_id, Team.game_id == game_id, Team.name == name
            )
        )
        return res.scalar_one_or_none()

    def add(self, team: Team) -> None:
        self._s.add(team)

    async def active_member_count(self, team_id: int) -> int:
        return await self._s.scalar(
            select(func.count()).select_from(TeamMember).where(
                TeamMember.team_id == team_id, TeamMember.active.is_(True)
            )
        ) or 0

    async def active_members(self, team_id: int) -> list[TeamMember]:
        res = await self._s.execute(
            select(TeamMember).where(
                TeamMember.team_id == team_id, TeamMember.active.is_(True)
            )
        )
        return list(res.scalars().all())

    async def active_membership(self, event_id: int, user_id: int) -> TeamMember | None:
        res = await self._s.execute(
            select(TeamMember).where(
                TeamMember.event_id == event_id,
                TeamMember.user_id == user_id,
                TeamMember.active.is_(True),
            )
        )
        return res.scalar_one_or_none()

    def add_member(self, member: TeamMember) -> None:
        self._s.add(member)

    async def approved_application(
        self, event_id: int, user_id: int
    ) -> Application | None:
        from ..domain.enums import ApplicationStatus

        res = await self._s.execute(
            select(Application).where(
                Application.event_id == event_id,
                Application.user_id == user_id,
                Application.status.in_(
                    [ApplicationStatus.APPROVED, ApplicationStatus.ASSIGNED_TO_TEAM]
                ),
            )
        )
        return res.scalar_one_or_none()
