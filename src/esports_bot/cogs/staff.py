"""/staff commands — manage E-Sports staff (docs/command-specification.md)."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from ..bot import EsportsBot
from ..domain.enums import StaffRole
from ..infra import db
from ..infra.discord_gateway import DiscordResourceGateway
from ..infra.discord_resources import DiscordResourceService
from ..infra.resource_repository import SqlResourceRepository
from ..repositories.core import EventRepository
from ..services.errors import ServiceError
from ..services.staff_service import StaffService
from .checks import is_head, is_staff

_ROLE_CHOICES = [
    app_commands.Choice(name="E-Sports Committee", value=StaffRole.COMMITTEE.value),
    app_commands.Choice(name="Officer in Charge", value=StaffRole.OIC.value),
    app_commands.Choice(name="Faculty in Charge", value=StaffRole.FIC.value),
]


class StaffCog(commands.Cog):
    def __init__(self, bot: EsportsBot) -> None:
        self.bot = bot

    staff = app_commands.Group(
        name="staff", description="Manage E-Sports staff.",
        default_permissions=discord.Permissions(manage_guild=True), guild_only=True,
    )

    async def _grant_role(self, guild: discord.Guild, event_id: int, purpose: str, member) -> None:
        async with db.session_scope() as s:
            resources = DiscordResourceService(
                DiscordResourceGateway(guild), SqlResourceRepository(s)
            )
            role_id = (await resources.role_map(event_id)).get(purpose)
        if role_id:
            role = guild.get_role(role_id)
            if role:
                await member.add_roles(role, reason="Staff assignment")

    @staff.command(name="add", description="Assign a staff role to a member (Head only).")
    @app_commands.describe(member="The member", role="Which staff role")
    @app_commands.choices(role=_ROLE_CHOICES)
    async def add(
        self, interaction: discord.Interaction, member: discord.Member,
        role: app_commands.Choice[str],
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None:
                await interaction.followup.send("No active event.", ephemeral=True)
                return
            if not await is_head(interaction, s, event.id, self.bot.settings):
                await interaction.followup.send("E-Sports Head only.", ephemeral=True)
                return
            try:
                purpose = await StaffService(s).assign(
                    event_id=event.id, target_discord_id=member.id,
                    target_username=str(member), staff_role=StaffRole(role.value),
                    actor_discord_id=interaction.user.id, actor_username=str(interaction.user),
                )
            except ServiceError as exc:
                await interaction.followup.send(str(exc), ephemeral=True)
                return
            event_id = event.id

        if purpose:
            await self._grant_role(interaction.guild, event_id, purpose, member)
        await interaction.followup.send(
            f"Assigned **{role.name}** to {member.mention}.", ephemeral=True
        )

    @staff.command(name="remove", description="Remove all staff roles from a member (Head only).")
    async def remove(self, interaction: discord.Interaction, member: discord.Member) -> None:
        await interaction.response.defer(ephemeral=True)
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None:
                await interaction.followup.send("No active event.", ephemeral=True)
                return
            if not await is_head(interaction, s, event.id, self.bot.settings):
                await interaction.followup.send("E-Sports Head only.", ephemeral=True)
                return
            try:
                purposes = await StaffService(s).remove(
                    event_id=event.id, target_discord_id=member.id,
                    target_username=str(member),
                    actor_discord_id=interaction.user.id, actor_username=str(interaction.user),
                )
            except ServiceError as exc:
                await interaction.followup.send(str(exc), ephemeral=True)
                return
            event_id = event.id
            role_map = await DiscordResourceService(
                DiscordResourceGateway(interaction.guild), SqlResourceRepository(s)
            ).role_map(event_id)

        for purpose in purposes:
            role_id = role_map.get(purpose)
            role = interaction.guild.get_role(role_id) if role_id else None
            if role:
                await member.remove_roles(role, reason="Staff removal")
        await interaction.followup.send(
            f"Removed staff roles from {member.mention}.", ephemeral=True
        )

    @staff.command(name="list", description="List active staff.")
    async def list_staff(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None:
                await interaction.followup.send("No active event.", ephemeral=True)
                return
            if not await is_staff(interaction, s, event.id, self.bot.settings):
                await interaction.followup.send("Staff only.", ephemeral=True)
                return
            rows = await StaffService(s).list_active(event.id)
        if not rows:
            await interaction.followup.send("No staff assigned yet.", ephemeral=True)
            return
        lines = [f"<@{discord_id}> — {role.value}" for discord_id, role in rows]
        await interaction.followup.send("\n".join(lines), ephemeral=True)


async def setup(bot: EsportsBot) -> None:
    await bot.add_cog(StaffCog(bot))
