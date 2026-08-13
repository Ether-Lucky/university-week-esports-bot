"""Verification cog — maps the external verification bot's role to Audience (OQ-2)."""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

from ..bot import EsportsBot
from ..domain.enums import ResourceOwnerType
from ..domain.verification import should_grant_audience, should_revoke_audience
from ..infra import db
from ..infra.discord_gateway import DiscordResourceGateway
from ..infra.discord_resources import DiscordResourceService
from ..infra.resource_repository import SqlResourceRepository
from ..repositories.core import EventRepository, UserRepository

log = logging.getLogger(__name__)


class VerificationCog(commands.Cog):
    def __init__(self, bot: EsportsBot) -> None:
        self.bot = bot

    async def _audience_role_id(self, guild: discord.Guild, event_id: int) -> int | None:
        async with db.session_scope() as s:
            resources = DiscordResourceService(
                DiscordResourceGateway(guild), SqlResourceRepository(s)
            )
            return await resources.find(
                event_id, ResourceOwnerType.SYSTEM, None, "role_audience"
            )

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        verified_id = self.bot.settings.verified_source_role_id
        if not verified_id:
            return
        # Fast path: only act when the *verified* role itself was gained or lost.
        # This avoids any database work for unrelated role changes (e.g. the bulk
        # Audience grant, team roles, etc.), which would otherwise storm Supabase.
        before_ids = {r.id for r in before.roles}
        after_ids = {r.id for r in after.roles}
        gained = verified_id in after_ids and verified_id not in before_ids
        lost = verified_id in before_ids and verified_id not in after_ids
        if not (gained or lost):
            return

        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(after.guild.id)
            if event is None:
                return
            event_id = event.id
        audience_id = await self._audience_role_id(after.guild, event_id)
        if audience_id is None:
            return

        audience_role = after.guild.get_role(audience_id)
        if audience_role is None:
            return

        if should_grant_audience(
            verified_role_id=verified_id, audience_role_id=audience_id,
            before=before_ids, after=after_ids,
        ):
            await after.add_roles(audience_role, reason="Verified -> Audience")
            async with db.session_scope() as s:
                await UserRepository(s).get_or_create(
                    after.id, str(after), after.display_name
                )
            log.info("Granted Audience to %s (%s)", after, after.id)
        elif should_revoke_audience(
            verified_role_id=verified_id, audience_role_id=audience_id,
            before=before_ids, after=after_ids, revoke_enabled=True,
        ):
            await after.remove_roles(audience_role, reason="Verified role removed")
            log.info("Revoked Audience from %s (%s)", after, after.id)


async def setup(bot: EsportsBot) -> None:
    await bot.add_cog(VerificationCog(bot))
