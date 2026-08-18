"""/player lookup — show a member's full record from the database (staff)."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from ..bot import EsportsBot
from ..infra import db
from ..models import Application, Game, StaffAssignment, Team, User
from ..repositories.core import EventRepository
from ..repositories.recruitment import RecruitmentRepository
from ..repositories.teams import TeamRepository
from .checks import is_staff

log = logging.getLogger(__name__)


class PlayersCog(commands.Cog):
    def __init__(self, bot: EsportsBot) -> None:
        self.bot = bot

    player = app_commands.Group(
        name="player", description="Look up participant data (staff).",
        default_permissions=discord.Permissions(manage_guild=True), guild_only=True,
    )

    @player.command(name="lookup", description="Show a member's data from the database.")
    @app_commands.describe(member="The member to look up")
    async def lookup(
        self, interaction: discord.Interaction, member: discord.Member
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None or not await is_staff(interaction, s, event.id, self.bot.settings):
                await interaction.followup.send("Staff only.", ephemeral=True)
                return

            user = (
                await s.execute(select(User).where(User.discord_user_id == member.id))
            ).scalar_one_or_none()

            embed = discord.Embed(
                title=f"Player record — {member.display_name}",
                colour=discord.Colour.blurple(),
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.add_field(
                name="Discord", value=f"{member.mention}\n`{member.id}`", inline=True
            )

            if user is None:
                embed.description = "⚠️ No database record — this member hasn't been seen by the bot."
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            # Most recent application for this event.
            app = (
                await s.execute(
                    select(Application)
                    .where(
                        Application.event_id == event.id, Application.user_id == user.id
                    )
                    .order_by(Application.id.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if app is not None:
                game = await s.get(Game, app.game_id)
                lines = [
                    f"**Status:** {app.status.value}",
                    f"**Game:** {game.name if game else app.game_id}",
                    f"**Name:** {app.full_name}",
                    f"**Email:** {app.school_email}",
                    f"**Year/section:** {app.year_section}",
                    f"**Facebook:** [link]({app.facebook_url})",
                ]
                if app.rejection_reason:
                    lines.append(f"**Rejection reason:** {app.rejection_reason}")
                embed.add_field(
                    name=f"📝 Application #{app.id}", value="\n".join(lines), inline=False
                )
            else:
                embed.add_field(name="📝 Application", value="None", inline=False)

            # Active team membership.
            membership = await TeamRepository(s).active_membership(event.id, user.id)
            if membership is not None:
                team = await s.get(Team, membership.team_id)
                embed.add_field(
                    name="👥 Team",
                    value=(
                        f"**{team.name if team else membership.team_id}** "
                        f"(#{membership.team_id})\n"
                        f"Role: {membership.role_in_team.value}"
                        + (f" · Status: {team.status.value}" if team else "")
                    ),
                    inline=False,
                )
            else:
                embed.add_field(name="👥 Team", value="Not on a team", inline=False)

            # Staff assignments.
            staff_rows = (
                await s.execute(
                    select(StaffAssignment).where(
                        StaffAssignment.event_id == event.id,
                        StaffAssignment.user_id == user.id,
                        StaffAssignment.active.is_(True),
                    )
                )
            ).scalars().all()
            if staff_rows:
                embed.add_field(
                    name="🛠️ Staff roles",
                    value=", ".join(a.staff_role.value for a in staff_rows),
                    inline=False,
                )

            # Open looking-for-team post.
            lft = await RecruitmentRepository(s).open_post_for_user(event.id, user.id)
            if lft is not None:
                embed.add_field(
                    name="🔎 Looking-for-team post",
                    value=f"IGN **{lft.ign}** · role {lft.main_role or '—'} · {lft.status.value}",
                    inline=False,
                )

        # Current Discord roles (excludes @everyone), from the live member.
        roles = [r.mention for r in reversed(member.roles) if not r.is_default()]
        embed.add_field(
            name="🎭 Current Discord roles",
            value=" ".join(roles)[:1024] if roles else "None",
            inline=False,
        )
        embed.set_footer(text=f"Seen by the bot since • user #{user.id}")
        embed.timestamp = user.first_seen_at
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: EsportsBot) -> None:
    await bot.add_cog(PlayersCog(bot))
