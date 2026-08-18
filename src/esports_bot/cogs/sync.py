"""Sync cog — reflect manual Discord changes back into the database.

The bot normally drives Discord from the DB. These listeners handle the reverse
for the safe cases: a resource deleted on Discord is marked MISSING, a deleted
looking-for-team post is closed, and a member who has a team/staff role stripped
by hand is updated to match. Only *removals* are synced — additions should go
through the proper commands so we never fight the bot's own grants.
"""

from __future__ import annotations

import logging

import discord
from discord.ext import commands
from sqlalchemy import select, update

from ..bot import EsportsBot
from ..domain.enums import (
    RecruitmentPostStatus,
    ResourceStatus,
    ResourceType,
    StaffRole,
)
from ..infra import dashboard, db
from ..infra.logchannel import post_log
from ..infra.resource_repository import SqlResourceRepository
from ..models import RecruitmentPost, StaffAssignment, User
from ..repositories.core import EventRepository
from ..services.errors import ServiceError
from ..services.team_service import TeamService

log = logging.getLogger(__name__)

_STAFF_PURPOSE_TO_ROLE = {
    "role_committee": StaffRole.COMMITTEE,
    "role_oic": StaffRole.OIC,
    "role_fic": StaffRole.FIC,
}


class SyncCog(commands.Cog):
    def __init__(self, bot: EsportsBot) -> None:
        self.bot = bot

    async def _mark_missing(self, discord_id: int) -> str | None:
        """Flag a tracked resource as MISSING. Returns its purpose if it was tracked."""
        async with db.session_scope() as s:
            repo = SqlResourceRepository(s)
            row = await repo.by_discord_id(discord_id)
            if row is None or row.status != ResourceStatus.CREATED:
                return None
            await repo.set_status(row.id, ResourceStatus.MISSING)
            return row.purpose

    @commands.Cog.listener()
    async def on_guild_channel_delete(
        self, channel: discord.abc.GuildChannel
    ) -> None:
        purpose = await self._mark_missing(channel.id)
        if purpose:
            log.info("Channel %s (%s) deleted -> marked MISSING", purpose, channel.id)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role) -> None:
        purpose = await self._mark_missing(role.id)
        if purpose:
            log.info("Role %s (%s) deleted -> marked MISSING", purpose, role.id)

    @commands.Cog.listener()
    async def on_raw_thread_delete(self, payload: discord.RawThreadDeleteEvent) -> None:
        thread_id = payload.thread_id
        await self._mark_missing(thread_id)
        async with db.session_scope() as s:
            post = (
                await s.execute(
                    select(RecruitmentPost).where(
                        RecruitmentPost.forum_post_id == thread_id,
                        RecruitmentPost.status == RecruitmentPostStatus.OPEN,
                    )
                )
            ).scalar_one_or_none()
            if post is None:
                return
            post.status = RecruitmentPostStatus.CLOSED
            await s.flush()
            log.info("LFT post %s closed (forum thread %s deleted)", post.id, thread_id)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        removed = {r.id for r in before.roles} - {r.id for r in after.roles}
        if not removed:
            return  # additions/other updates are ignored — no DB work on the hot path
        guild = after.guild
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(guild.id)
            if event is None:
                return
            event_id = event.id
            # Map the removed role IDs to the purposes we care about.
            rows = await SqlResourceRepository(s).list_by_status(
                event_id, ResourceStatus.CREATED
            )
            purposes = [
                r.purpose for r in rows
                if r.resource_type == ResourceType.ROLE and r.discord_id in removed
            ]
        if not purposes:
            return

        for purpose in purposes:
            if purpose.startswith("team_role:"):
                await self._handle_team_role_removed(guild, event_id, after)
            elif purpose in _STAFF_PURPOSE_TO_ROLE:
                await self._handle_staff_role_removed(
                    guild, event_id, after, _STAFF_PURPOSE_TO_ROLE[purpose]
                )

    async def _handle_team_role_removed(
        self, guild: discord.Guild, event_id: int, member: discord.Member
    ) -> None:
        async with db.session_scope() as s:
            try:
                await TeamService(s).leave_team(
                    event_id=event_id, user_discord_id=member.id, username=str(member),
                )
            except (ServiceError, ValueError):
                return  # already not on a team (e.g. the bot removed the role itself)
            await post_log(
                s, guild, event_id, "teams",
                "↩️ Member left a team (role removed manually)",
                f"{member.mention}", colour=discord.Colour.orange(),
            )
        await dashboard.refresh(guild, event_id)
        log.info("Team role removed from %s -> left team in DB", member.id)

    async def _handle_staff_role_removed(
        self, guild: discord.Guild, event_id: int, member: discord.Member, role: StaffRole
    ) -> None:
        async with db.session_scope() as s:
            user = (
                await s.execute(select(User).where(User.discord_user_id == member.id))
            ).scalar_one_or_none()
            if user is None:
                return
            result = await s.execute(
                update(StaffAssignment)
                .where(
                    StaffAssignment.event_id == event_id,
                    StaffAssignment.user_id == user.id,
                    StaffAssignment.staff_role == role,
                    StaffAssignment.active.is_(True),
                )
                .values(active=False)
            )
            if result.rowcount:
                await post_log(
                    s, guild, event_id, "members",
                    "🔧 Staff role removed manually",
                    f"{member.mention} — {role.value}", colour=discord.Colour.orange(),
                )
                log.info("Staff role %s removed from %s -> deactivated", role.value, member.id)


async def setup(bot: EsportsBot) -> None:
    await bot.add_cog(SyncCog(bot))
