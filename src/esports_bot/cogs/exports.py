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
from ..infra import db
from ..infra.exporter import EXPORTERS
from ..models import Export
from ..repositories.core import EventRepository
from .checks import is_staff

_EXPORT_DIR = Path("data/exports")
_CHOICES = [app_commands.Choice(name=k, value=k) for k in [*EXPORTERS.keys(), "all"]]


class ExportsCog(commands.Cog):
    def __init__(self, bot: EsportsBot) -> None:
        self.bot = bot

    @app_commands.command(name="export", description="Export event data as CSV (staff).")
    @app_commands.choices(kind=_CHOICES)
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def export(
        self, interaction: discord.Interaction, kind: app_commands.Choice[str]
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        _EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        async with db.session_scope() as s:
            event = await EventRepository(s).get_active(interaction.guild_id)
            if event is None or not await is_staff(interaction, s, event.id, self.bot.settings):
                await interaction.followup.send("Staff only.", ephemeral=True)
                return
            targets = list(EXPORTERS) if kind.value == "all" else [kind.value]
            files: list[Path] = []
            for name in targets:
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
