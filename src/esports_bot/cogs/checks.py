"""Interaction authorization helpers.

Full role-based authorization (via stored role IDs) arrives in M5. For the
bootstrap commands (/event, /setup) that must run *before* roles are created,
authority is the pre-existing E-Sports Head role, the configured owner, or
Administrator (OQ-13).
"""

from __future__ import annotations

import discord
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings
from ..domain.authorization import Role
from ..services import authz

HEAD_ROLE_NAME = "E-Sports Head"


def _member_role_ids(user: discord.abc.User) -> list[int]:
    return [r.id for r in user.roles] if isinstance(user, discord.Member) else []


def is_head_or_owner(interaction: discord.Interaction, settings: Settings) -> bool:
    member = interaction.user
    if settings.owner_discord_id and member.id == settings.owner_discord_id:
        return True
    if isinstance(member, discord.Member):
        if member.guild_permissions.administrator:
            return True
        for role in member.roles:
            if role.name.casefold() == HEAD_ROLE_NAME.casefold():
                return True
    return False


async def is_head(
    interaction: discord.Interaction, session: AsyncSession, event_id: int, settings: Settings
) -> bool:
    if is_head_or_owner(interaction, settings):
        return True
    held = await authz.held_roles(session, event_id, _member_role_ids(interaction.user))
    return Role.HEAD in held


async def is_staff(
    interaction: discord.Interaction, session: AsyncSession, event_id: int, settings: Settings
) -> bool:
    if is_head_or_owner(interaction, settings):
        return True
    held = await authz.held_roles(session, event_id, _member_role_ids(interaction.user))
    return authz.is_staff(held)
