"""Membership cog — restore a returning member's roles from their kept data.

Leaving the server deletes nothing (there is deliberately no member-remove
handler). Discord strips roles on leave, so ``on_member_join`` reattaches the
roles the member had earned. ``/member restore`` does the same on demand for
anyone who rejoined before this existed, or as a manual re-sync.
"""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from ..bot import EsportsBot
from ..infra import db, member_restore
from ..repositories.core import EventRepository
from .checks import is_staff

log = logging.getLogger(__name__)


class MembershipCog(commands.Cog):
    def __init__(self, bot: EsportsBot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        await member_restore.restore(member.guild, member)

    member = app_commands.Group(
        name="member", description="Member management (staff).",
        default_permissions=discord.Permissions(manage_guild=True), guild_only=True,
    )

    @member.command(
        name="restore",
        description="Re-grant earned roles from kept data (one member, or all present).",
    )
    @app_commands.describe(member="Leave empty to restore every current member")
    async def restore(
        self, interaction: discord.Interaction, member: discord.Member | None = None
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None or not await is_staff(interaction, s, event.id, self.bot.settings):
                await interaction.followup.send("Staff only.", ephemeral=True)
                return

        if member is not None:
            granted = await member_restore.restore(interaction.guild, member)
            if granted:
                await interaction.followup.send(
                    f"Restored for {member.mention}: {', '.join(granted)}.", ephemeral=True
                )
            else:
                await interaction.followup.send(
                    f"Nothing to restore for {member.mention} "
                    "(no kept roles, or they already have them).",
                    ephemeral=True,
                )
            return

        # Restore everyone currently in the server.
        if not interaction.guild.chunked:
            await interaction.guild.chunk()
        changed = 0
        for m in interaction.guild.members:
            if m.bot:
                continue
            if await member_restore.restore(interaction.guild, m):
                changed += 1
        await interaction.followup.send(
            f"Restored roles for {changed} member(s) from their kept data.", ephemeral=True
        )


async def setup(bot: EsportsBot) -> None:
    await bot.add_cog(MembershipCog(bot))
