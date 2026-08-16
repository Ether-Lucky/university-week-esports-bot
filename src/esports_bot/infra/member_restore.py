"""Re-attach a returning member to the roles their preserved data implies.

Nothing is ever deleted when a member leaves, so their application, team
membership, and staff assignment all survive keyed to their Discord account ID.
Discord itself strips a member's roles on leave, though — so when they rejoin we
recompute which event roles they had earned and grant them back. Purely additive:
it reads the DB and adds roles, never creating or deleting data.
"""

from __future__ import annotations

import logging

import discord
from sqlalchemy import select

from ..domain.enums import (
    ApplicationStatus,
    ResourceOwnerType,
    StaffRole,
    TeamStatus,
)
from ..domain.server_blueprint import slug
from ..models import Application, Game, StaffAssignment, Team, TeamMember, User
from ..infra import db
from ..infra.discord_gateway import DiscordResourceGateway
from ..infra.discord_resources import DiscordResourceService
from ..infra.resource_repository import SqlResourceRepository
from ..repositories.core import EventRepository

log = logging.getLogger(__name__)

_APPROVED = (ApplicationStatus.APPROVED, ApplicationStatus.ASSIGNED_TO_TEAM)
_STAFF_ROLE_PURPOSE = {
    StaffRole.HEAD: "role_head",
    StaffRole.COMMITTEE: "role_committee",
    StaffRole.OIC: "role_oic",
    StaffRole.FIC: "role_fic",
}


async def _earned_role_purposes(
    session, event_id: int, user_id: int
) -> list[tuple[ResourceOwnerType, int | None, str]]:
    """Return (owner_type, owner_id, purpose) for every role the member had earned."""
    purposes: list[tuple[ResourceOwnerType, int | None, str]] = []

    # Approved application -> Applicant + that game's role.
    app = (
        await session.execute(
            select(Application).where(
                Application.event_id == event_id,
                Application.user_id == user_id,
                Application.status.in_(_APPROVED),
            )
        )
    ).scalar_one_or_none()
    if app is not None:
        purposes.append((ResourceOwnerType.SYSTEM, None, "role_applicant"))
        game = await session.get(Game, app.game_id)
        if game is not None:
            purposes.append(
                (ResourceOwnerType.SYSTEM, None, f"game_role:{slug(game.name)}")
            )

    # Active team membership -> team role (+ Player if the team is a champion).
    membership = (
        await session.execute(
            select(TeamMember).where(
                TeamMember.event_id == event_id,
                TeamMember.user_id == user_id,
                TeamMember.active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if membership is not None:
        tid = membership.team_id
        purposes.append((ResourceOwnerType.TEAM, tid, f"team_role:{tid}"))
        team = await session.get(Team, tid)
        if team is not None and team.status == TeamStatus.CHAMPION:
            purposes.append((ResourceOwnerType.SYSTEM, None, "role_player"))

    # Active staff assignment(s) -> their staff role(s).
    staff_rows = (
        await session.execute(
            select(StaffAssignment).where(
                StaffAssignment.event_id == event_id,
                StaffAssignment.user_id == user_id,
                StaffAssignment.active.is_(True),
            )
        )
    ).scalars().all()
    for sa in staff_rows:
        purpose = _STAFF_ROLE_PURPOSE.get(sa.staff_role)
        if purpose:
            purposes.append((ResourceOwnerType.SYSTEM, None, purpose))

    return purposes


async def restore(guild: discord.Guild, member: discord.Member) -> list[str]:
    """Re-grant the returning member's earned roles. Returns the role names granted."""
    if member.bot:
        return []
    try:
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(guild.id)
            if event is None:
                return []
            user = (
                await s.execute(
                    select(User).where(User.discord_user_id == member.id)
                )
            ).scalar_one_or_none()
            if user is None:
                return []  # no record of them — nothing to restore
            purposes = await _earned_role_purposes(s, event.id, user.id)
            if not purposes:
                return []
            resources = DiscordResourceService(
                DiscordResourceGateway(guild), SqlResourceRepository(s)
            )
            role_ids = []
            for owner_type, owner_id, purpose in purposes:
                rid = await resources.find(event.id, owner_type, owner_id, purpose)
                if rid is not None:
                    role_ids.append(rid)

        roles = [r for rid in role_ids if (r := guild.get_role(rid)) is not None]
        to_add = [r for r in roles if r not in member.roles]
        if not to_add:
            return []
        await member.add_roles(*to_add, reason="Restored roles on rejoin")
        names = [r.name for r in to_add]
        log.info("Restored roles for %s (%s): %s", member, member.id, names)
        return names
    except discord.HTTPException as exc:
        log.warning("Could not restore roles for %s: %s", member.id, exc)
        return []
    except Exception:  # noqa: BLE001 - restoration must never crash a join handler
        log.exception("Role restore failed for member %s", member.id)
        return []
