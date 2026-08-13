"""System/observability cog.

M1: `/system status` reports uptime and Discord connectivity. Database,
event state, and entity counts are added in later milestones (see
docs/command-specification.md and FR-24).
"""

from __future__ import annotations

from datetime import UTC, datetime

import discord
from discord import app_commands
from discord.ext import commands

from ..bot import EsportsBot
from ..domain.enums import ResourceOwnerType, ResourceStatus
from ..infra import db
from ..infra.discord_gateway import DiscordResourceGateway
from ..infra.discord_resources import DiscordResourceService
from ..infra.resource_repository import SqlResourceRepository
from ..repositories.core import EventRepository
from ..services.cleanup_service import CleanupService
from ..services.errors import ServiceError
from .checks import is_head, is_staff


def _format_uptime(started_at: datetime) -> str:
    delta = datetime.now(UTC) - started_at
    total = int(delta.total_seconds())
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts)


class System(commands.Cog):
    def __init__(self, bot: EsportsBot) -> None:
        self.bot = bot

    system_group = app_commands.Group(
        name="system", description="Bot health and administration."
    )

    @system_group.command(name="status", description="Show bot health and connectivity.")
    async def status(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        latency_ms = round(self.bot.latency * 1000) if self.bot.latency else None
        event_line = "None"
        try:
            db_ok = await db.ping()
            async with db.session_scope() as s:
                from ..services.event_service import EventService

                event = await EventRepository(s).get_active(interaction.guild_id)
                if event:
                    data = await EventService(s).status(event.id)
                    event_line = (
                        f"**{data['name']} {data['year']}** — {data['state']}\n"
                        f"{data['applicants']} applicants · {data['approved']} approved · "
                        f"{data['teams']} teams · {data['games']} games"
                    )
        except Exception:  # noqa: BLE001 - report as down rather than raising
            db_ok = False

        embed = discord.Embed(
            title="System Status",
            colour=discord.Colour.green() if db_ok else discord.Colour.orange(),
            timestamp=datetime.now(UTC),
        )
        embed.add_field(name="Uptime", value=_format_uptime(self.bot.started_at), inline=True)
        embed.add_field(
            name="Discord",
            value=f"Connected ({latency_ms} ms)" if latency_ms is not None else "Connected",
            inline=True,
        )
        embed.add_field(
            name="Database",
            value="Connected (Supabase)" if db_ok else "Unavailable",
            inline=True,
        )
        embed.add_field(name="Active event", value=event_line, inline=False)
        embed.set_footer(text="University Week E-Sports Bot v0.1.0")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @system_group.command(
        name="health", description="Reconcile Discord resources against the database."
    )
    async def health(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None:
                await interaction.followup.send("No active event.", ephemeral=True)
                return
            if not await is_staff(interaction, s, event.id, self.bot.settings):
                await interaction.followup.send("Staff only.", ephemeral=True)
                return
            resources = DiscordResourceService(
                DiscordResourceGateway(interaction.guild), SqlResourceRepository(s)
            )
            report = await resources.reconcile(event.id)

        if report.missing_count == 0:
            msg = f"✅ All {report.checked} tracked resources are present."
        else:
            names = ", ".join(r.purpose for r in report.missing[:20])
            msg = (
                f"⚠️ {report.missing_count} of {report.checked} resources are MISSING: {names}. "
                "Re-run `/setup preview` → `/setup confirm` to recreate the base structure."
            )
        await interaction.followup.send(msg, ephemeral=True)

    @system_group.command(
        name="cleanup", description="Delete temporary resources of non-champion teams (Head)."
    )
    @app_commands.describe(confirm="Set to True to actually perform the destructive cleanup.")
    async def cleanup(self, interaction: discord.Interaction, confirm: bool = False) -> None:
        await interaction.response.defer(ephemeral=True)
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None or not await is_head(interaction, s, event.id, self.bot.settings):
                await interaction.followup.send("E-Sports Head only.", ephemeral=True)
                return
            if not confirm:
                await interaction.followup.send(
                    "⚠️ This deletes non-champion team roles/channels and tryout voice channels. "
                    "DB history is kept. Re-run with `confirm:True` to proceed.",
                    ephemeral=True,
                )
                return
            try:
                disbanded = await CleanupService(s).cleanup(
                    event_id=event.id, actor_discord_id=interaction.user.id,
                    actor_username=str(interaction.user),
                )
                event_id = event.id
            except (ServiceError, ValueError) as exc:
                await interaction.followup.send(f"❌ {exc}", ephemeral=True)
                return
        removed = await self._teardown(interaction.guild, event_id, set(disbanded))
        async with db.session_scope() as s:
            from ..infra.logchannel import post_log

            await post_log(
                s, interaction.guild, event_id, "system",
                "🧹 Cleanup executed",
                f"{len(disbanded)} teams disbanded, {removed} resources removed, "
                f"by {interaction.user.mention}",
            )
        await interaction.followup.send(
            f"Cleanup done. Disbanded {len(disbanded)} teams; removed {removed} Discord resources. "
            "Run `/system archive` to finish.",
            ephemeral=True,
        )

    async def _teardown(self, guild, event_id: int, disbanded: set[int]) -> int:
        removed = 0
        async with db.session_scope() as s:
            repo = SqlResourceRepository(s)
            resources = DiscordResourceService(DiscordResourceGateway(guild), repo)
            for row in await repo.list_by_status(event_id, ResourceStatus.CREATED):
                is_disbanded_team = (
                    row.owner_type == ResourceOwnerType.TEAM and row.owner_id in disbanded
                )
                is_tryout_voice = row.purpose.startswith("tryout_voice:")
                if is_disbanded_team or is_tryout_voice:
                    await resources.delete(row)
                    removed += 1
        return removed

    @system_group.command(name="archive", description="Archive the event (Head).")
    async def archive(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None or not await is_head(interaction, s, event.id, self.bot.settings):
                await interaction.followup.send("E-Sports Head only.", ephemeral=True)
                return
            try:
                await CleanupService(s).archive(
                    event_id=event.id, actor_discord_id=interaction.user.id,
                    actor_username=str(interaction.user),
                )
            except (ServiceError, ValueError) as exc:
                await interaction.followup.send(f"❌ {exc}", ephemeral=True)
                return
        await interaction.followup.send(
            "✅ Event archived. Records are preserved in the database for future reference.",
            ephemeral=True,
        )


async def setup(bot: EsportsBot) -> None:
    await bot.add_cog(System(bot))
