"""Staff assignment use-cases (docs/permissions.md, /staff commands)."""

from __future__ import annotations

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.enums import StaffRole
from ..infra import audit
from ..models import StaffAssignment
from ..repositories.core import StaffRepository, UserRepository
from .authz import STAFF_ROLE_TO_PURPOSE
from .errors import ServiceError


class StaffService:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session
        self.staff = StaffRepository(session)
        self.users = UserRepository(session)

    async def assign(
        self, *, event_id: int, target_discord_id: int, target_username: str,
        staff_role: StaffRole, actor_discord_id: int, actor_username: str,
    ) -> str | None:
        """Create the staff assignment; return the role *purpose* to grant on Discord."""
        target = await self.users.get_or_create(target_discord_id, target_username)
        existing = await self.staff.list_active(event_id)
        if any(a.user_id == target.id and a.staff_role == staff_role for a in existing):
            raise ServiceError(f"{target_username} is already {staff_role.value}.")
        actor = await self.users.get_or_create(actor_discord_id, actor_username)
        assignment = await self.staff.assign(
            event_id, target.id, staff_role, assigned_by=actor.id
        )
        await audit.record(
            self._s, action="staff.add", event_id=event_id, actor_user_id=actor.id,
            entity_type="staff_assignment", entity_id=assignment.id,
            after={"user": target_username, "role": staff_role.value},
        )
        return STAFF_ROLE_TO_PURPOSE.get(staff_role)

    async def remove(
        self, *, event_id: int, target_discord_id: int, target_username: str,
        actor_discord_id: int, actor_username: str,
    ) -> list[str]:
        """Deactivate all staff roles for a user; return the role purposes to revoke."""
        target = await self.users.get_or_create(target_discord_id, target_username)
        active = [a for a in await self.staff.list_active(event_id) if a.user_id == target.id]
        if not active:
            raise ServiceError(f"{target_username} is not a staff member.")
        await self._s.execute(
            update(StaffAssignment)
            .where(
                StaffAssignment.event_id == event_id,
                StaffAssignment.user_id == target.id,
                StaffAssignment.active.is_(True),
            )
            .values(active=False)
        )
        actor = await self.users.get_or_create(actor_discord_id, actor_username)
        await audit.record(
            self._s, action="staff.remove", event_id=event_id, actor_user_id=actor.id,
            entity_type="user", entity_id=target.id,
            before={"roles": [a.staff_role.value for a in active]},
        )
        return [
            STAFF_ROLE_TO_PURPOSE[a.staff_role]
            for a in active
            if a.staff_role in STAFF_ROLE_TO_PURPOSE
        ]

    async def list_active(self, event_id: int) -> list[tuple[int, StaffRole]]:
        rows = await self.staff.list_active(event_id)
        out: list[tuple[int, StaffRole]] = []
        for a in rows:
            user = await self.users_by_id(a.user_id)
            out.append((user, a.staff_role))
        return out

    async def users_by_id(self, user_id: int) -> int:
        from ..models import User

        user = await self._s.get(User, user_id)
        return user.discord_user_id if user else 0
