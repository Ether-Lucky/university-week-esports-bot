"""Dashboard cog: a periodic safety refresh + a manual /dashboard refresh.

Instant refreshes are fired from the commands that change counts (approve,
team create/leave/disband, schedule, advance). This loop is the fallback that
catches anything missed and keeps the tryout countdown current.
"""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

from ..bot import EsportsBot
from ..infra import dashboard, db
from ..repositories.core import EventRepository
from .checks import is_staff

log = logging.getLogger(__name__)


class DashboardCog(commands.Cog):
    def __init__(self, bot: EsportsBot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.refresh_loop.start()

    async def cog_unload(self) -> None:
        self.refresh_loop.cancel()

    @tasks.loop(minutes=1)
    async def refresh_loop(self) -> None:
        for guild in self.bot.guilds:
            await dashboard.refresh(guild)  # each guild's own event dashboard (home has one)
        await dashboard.refresh_followers(self.bot)  # mirrored dashboards in follower guilds

    @refresh_loop.before_loop
    async def _before(self) -> None:
        await self.bot.wait_until_ready()

    dashboard_group = app_commands.Group(
        name="dashboard", description="Event dashboard (staff).",
        default_permissions=discord.Permissions(manage_guild=True), guild_only=True,
    )

    @dashboard_group.command(name="refresh", description="Rebuild the dashboard now.")
    async def refresh_now(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None or not await is_staff(interaction, s, event.id, self.bot.settings):
                await interaction.followup.send("Staff only.", ephemeral=True)
                return
            event_id = event.id
        await dashboard.refresh(interaction.guild, event_id)
        await interaction.followup.send("Dashboard refreshed.", ephemeral=True)

    @dashboard_group.command(
        name="follow",
        description="Mirror the event's live dashboard into a channel on this server.",
    )
    @app_commands.describe(channel="Where to post the mirrored dashboard")
    async def follow(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        perms = channel.permissions_for(interaction.guild.me)
        if not (perms.view_channel and perms.send_messages):
            await interaction.followup.send(
                f"I can't post in {channel.mention} — I need View Channel + Send Messages there.",
                ephemeral=True,
            )
            return
        from ..models import DashboardSubscription

        async with db.session_scope() as s:
            from sqlalchemy import select

            sub = (
                await s.execute(
                    select(DashboardSubscription).where(
                        DashboardSubscription.guild_id == interaction.guild_id
                    )
                )
            ).scalar_one_or_none()
            if sub is None:
                s.add(
                    DashboardSubscription(
                        guild_id=interaction.guild_id, channel_id=channel.id,
                        created_by=interaction.user.id,
                    )
                )
            else:
                sub.channel_id = channel.id
                sub.message_id = None  # force a fresh post in the new channel
        await dashboard.refresh_followers(self.bot)
        await interaction.followup.send(
            f"✅ Now mirroring the event dashboard in {channel.mention}. "
            "It refreshes about once a minute.",
            ephemeral=True,
        )

    @dashboard_group.command(
        name="unfollow", description="Stop mirroring the event dashboard on this server."
    )
    async def unfollow(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        from sqlalchemy import delete, select

        from ..models import DashboardSubscription

        async with db.session_scope() as s:
            sub = (
                await s.execute(
                    select(DashboardSubscription).where(
                        DashboardSubscription.guild_id == interaction.guild_id
                    )
                )
            ).scalar_one_or_none()
            if sub is None:
                await interaction.followup.send(
                    "This server isn't following the dashboard.", ephemeral=True
                )
                return
            await s.execute(
                delete(DashboardSubscription).where(
                    DashboardSubscription.guild_id == interaction.guild_id
                )
            )
        await interaction.followup.send("Stopped mirroring the dashboard here.", ephemeral=True)


async def setup(bot: EsportsBot) -> None:
    await bot.add_cog(DashboardCog(bot))
