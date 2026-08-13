"""Exports cog — CSV exports for staff (docs §26)."""

from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from ..bot import EsportsBot
from ..domain.enums import ApplicationStatus as _S
from ..infra import db
from ..infra.exporter import EXPORTERS, export_applicants
from ..models import Export
from ..repositories.core import EventRepository
from .checks import is_staff

_EXPORT_DIR = Path("data/exports")
_CHOICES = [app_commands.Choice(name=k, value=k) for k in [*EXPORTERS.keys(), "all"]]

# Applicant status filter (only affects the applicants export).
_STATUS_CHOICES = [
    app_commands.Choice(name="All (default)", value="all"),
    app_commands.Choice(name="Active (no rejected/withdrawn)", value="active"),
    app_commands.Choice(name="Approved only", value="approved"),
    app_commands.Choice(name="Pending only", value="pending"),
    app_commands.Choice(name="Rejected only", value="rejected"),
]
_STATUS_MAP: dict[str, list] = {
    "active": [_S.PENDING, _S.APPROVED, _S.ASSIGNED_TO_TEAM],
    "approved": [_S.APPROVED, _S.ASSIGNED_TO_TEAM],
    "pending": [_S.PENDING],
    "rejected": [_S.REJECTED],
}


class ExportsCog(commands.Cog):
    def __init__(self, bot: EsportsBot) -> None:
        self.bot = bot

    @app_commands.command(name="export", description="Export event data as CSV (staff).")
    @app_commands.choices(kind=_CHOICES, applicant_status=_STATUS_CHOICES)
    @app_commands.describe(
        applicant_status="Filter for the applicants export only (default: all)."
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def export(
        self, interaction: discord.Interaction, kind: app_commands.Choice[str],
        applicant_status: app_commands.Choice[str] | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        _EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        status_filter = _STATUS_MAP.get(applicant_status.value) if applicant_status else None
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None or not await is_staff(interaction, s, event.id, self.bot.settings):
                await interaction.followup.send("Staff only.", ephemeral=True)
                return
            targets = list(EXPORTERS) if kind.value == "all" else [kind.value]
            files: list[Path] = []
            for name in targets:
                if name == "applicants" and status_filter is not None:
                    text = await export_applicants(s, event.id, statuses=status_filter)
                else:
                    text = await EXPORTERS[name](s, event.id)
                path = _EXPORT_DIR / f"{event.name}-{name}-{ts}.csv"
                path.write_text(text, encoding="utf-8")
                files.append(path)
                s.add(Export(
                    event_id=event.id, export_type=name, file_path=str(path),
                    row_count=max(text.count("\r\n") - 1, 0),
                ))

        if kind.value == "all":
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for p in files:
                    zf.write(p, arcname=p.name)
            buf.seek(0)
            await interaction.followup.send(
                "Full export:", file=discord.File(buf, filename=f"export-{ts}.zip"),
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                f"Export ready ({files[0].name}):", file=discord.File(files[0]), ephemeral=True
            )


async def setup(bot: EsportsBot) -> None:
    await bot.add_cog(ExportsCog(bot))
