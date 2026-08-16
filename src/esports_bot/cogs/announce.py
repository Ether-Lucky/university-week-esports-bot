"""/announce — let staff post a message as the bot (announcements & notices)."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from ..bot import EsportsBot
from ..infra import db
from ..repositories.core import EventRepository
from .checks import is_head_or_owner, is_staff

log = logging.getLogger(__name__)


class AnnounceCog(commands.Cog):
    def __init__(self, bot: EsportsBot) -> None:
        self.bot = bot

    async def _staff_ok(self, interaction: discord.Interaction) -> bool:
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None:
                return is_head_or_owner(interaction, self.bot.settings)
            return await is_staff(interaction, s, event.id, self.bot.settings)

    @app_commands.command(
        name="announce", description="Post a message as the bot in a channel (staff)."
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    @app_commands.describe(
        channel="Where to post the announcement",
        message="What to say (use \\n for line breaks)",
        title="Optional heading shown above the message",
        ping="Optionally notify @here or @everyone",
    )
    @app_commands.choices(
        ping=[
            app_commands.Choice(name="No ping", value="none"),
            app_commands.Choice(name="@here", value="here"),
            app_commands.Choice(name="@everyone", value="everyone"),
        ]
    )
    async def announce(
        self, interaction: discord.Interaction, channel: discord.TextChannel, message: str,
        title: str | None = None, ping: app_commands.Choice[str] | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        if not await self._staff_ok(interaction):
            await interaction.followup.send("Staff only.", ephemeral=True)
            return

        me = interaction.guild.me
        perms = channel.permissions_for(me)
        if not (perms.view_channel and perms.send_messages):
            await interaction.followup.send(
                f"I can't post in {channel.mention} — I'm missing View/Send there.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title=title or "📢 Announcement",
            description=message.replace("\\n", "\n")[:4000],
            colour=discord.Colour.gold(),
        )
        embed.set_footer(
            text=f"Posted by {interaction.user.display_name}",
            icon_url=interaction.user.display_avatar.url,
        )
        embed.timestamp = discord.utils.utcnow()

        ping_value = ping.value if ping else "none"
        content = None
        allowed = discord.AllowedMentions.none()
        if ping_value == "everyone":
            content, allowed = "@everyone", discord.AllowedMentions(everyone=True)
        elif ping_value == "here":
            content, allowed = "@here", discord.AllowedMentions(everyone=True)

        try:
            sent = await channel.send(content=content, embed=embed, allowed_mentions=allowed)
        except discord.HTTPException as exc:
            await interaction.followup.send(f"Couldn't post: {exc}", ephemeral=True)
            return
        log.info(
            "Announcement by %s in #%s (%s)", interaction.user, channel.name, channel.id
        )
        await interaction.followup.send(
            f"✅ Posted in {channel.mention}. [Jump to message]({sent.jump_url})", ephemeral=True
        )


async def setup(bot: EsportsBot) -> None:
    await bot.add_cog(AnnounceCog(bot))
