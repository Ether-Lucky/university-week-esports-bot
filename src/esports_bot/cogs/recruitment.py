"""Recruitment cog — looking-for-team posts and recruit requests."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from ..bot import EsportsBot
from ..infra import db
from ..repositories.core import EventRepository
from ..repositories.teams import TeamRepository
from ..services.errors import ServiceError
from ..services.recruitment_service import RecruitmentService


class RecruitmentCog(commands.Cog):
    def __init__(self, bot: EsportsBot) -> None:
        self.bot = bot

    recruit = app_commands.Group(name="recruit", description="Recruitment.", guild_only=True)

    @recruit.command(name="player", description="Recruit a player to your team (leader).")
    async def player(self, interaction: discord.Interaction, member: discord.Member) -> None:
        await interaction.response.defer(ephemeral=True)
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None:
                await interaction.followup.send("No active event.", ephemeral=True)
                return
            membership = await TeamRepository(s).active_membership(
                event.id, (await _uid(s, interaction.user.id, str(interaction.user)))
            )
            if membership is None:
                await interaction.followup.send("You are not on a team.", ephemeral=True)
                return
            try:
                request = await RecruitmentService(s).recruit(
                    event_id=event.id, team_id=membership.team_id,
                    target_discord_id=member.id, target_username=str(member),
                    requester_discord_id=interaction.user.id,
                    requester_username=str(interaction.user),
                    timeout_minutes=self.bot.settings.recruit_timeout_minutes,
                )
                request_id = request.id
            except (ServiceError, ValueError) as exc:
                await interaction.followup.send(f"❌ {exc}", ephemeral=True)
                return
        try:
            await member.send(
                f"You've been recruited! Use `/recruit accept {request_id}` or "
                f"`/recruit decline {request_id}` (expires soon)."
            )
        except discord.HTTPException:
            pass
        await interaction.followup.send(f"Recruitment request #{request_id} sent.", ephemeral=True)

    @recruit.command(name="accept", description="Accept a recruitment request.")
    async def accept(self, interaction: discord.Interaction, request_id: int) -> None:
        await self._resolve(interaction, request_id, accept=True)

    @recruit.command(name="decline", description="Decline a recruitment request.")
    async def decline(self, interaction: discord.Interaction, request_id: int) -> None:
        await self._resolve(interaction, request_id, accept=False)

    async def _resolve(self, interaction, request_id: int, *, accept: bool) -> None:
        await interaction.response.defer(ephemeral=True)
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None:
                await interaction.followup.send("No active event.", ephemeral=True)
                return
            svc = RecruitmentService(s)
            try:
                if accept:
                    await svc.accept(
                        event_id=event.id, request_id=request_id,
                        actor_discord_id=interaction.user.id,
                        actor_username=str(interaction.user),
                    )
                    msg = "✅ You joined the team!"
                else:
                    await svc.decline(
                        event_id=event.id, request_id=request_id,
                        actor_discord_id=interaction.user.id,
                        actor_username=str(interaction.user),
                    )
                    msg = "Declined."
            except (ServiceError, ValueError) as exc:
                await interaction.followup.send(f"❌ {exc}", ephemeral=True)
                return
        await interaction.followup.send(msg, ephemeral=True)


async def _uid(session, discord_id: int, username: str) -> int:
    from ..repositories.core import UserRepository

    user = await UserRepository(session).get_or_create(discord_id, username)
    return user.id


async def setup(bot: EsportsBot) -> None:
    await bot.add_cog(RecruitmentCog(bot))
