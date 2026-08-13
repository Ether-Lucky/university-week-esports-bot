"""Bot subclass: cog loading and guild-scoped command sync.

M1 scaffold. Database wiring (Supabase) arrives in M2; startup reconcile of
Discord resources arrives with M3/M4.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import discord
from discord import app_commands
from discord.ext import commands

from .config import Settings
from .infra import db

log = logging.getLogger(__name__)

# Cogs loaded at startup. Grows as milestones land.
INITIAL_EXTENSIONS: tuple[str, ...] = (
    "esports_bot.cogs.system",
    "esports_bot.cogs.event",
    "esports_bot.cogs.setup",
    "esports_bot.cogs.staff",
    "esports_bot.cogs.verification",
    "esports_bot.cogs.applications",
    "esports_bot.cogs.teams",
    "esports_bot.cogs.recruitment",
    "esports_bot.cogs.mechanics",
    "esports_bot.cogs.tryout",
    "esports_bot.cogs.matches",
    "esports_bot.cogs.exports",
)


class EsportsBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.default()
        intents.members = True  # needed for role/member management + verification role watch
        intents.message_content = False  # interaction-first bot; no message scraping
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.settings = settings
        self.started_at: datetime = datetime.now(UTC)
        self.tree.on_error = self._on_app_command_error

    async def _on_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        """Fail quiet to users, loud to logs. Never leak internals/secrets."""
        # Friendly, user-facing message for expected authorization/check failures.
        if isinstance(error, app_commands.CheckFailure):
            message = "You don't have permission to do that."
            log.info("Check failed for %s: %s", interaction.command, error)
        else:
            message = "Something went wrong — staff have been notified."
            log.exception("Unhandled app command error in %s", interaction.command,
                          exc_info=error)
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            pass

    async def setup_hook(self) -> None:
        # Initialise the Supabase Postgres engine and verify connectivity early.
        db.init_engine(self.settings.database_url)
        try:
            await db.ping()
            log.info("Database connected (Supabase Postgres).")
        except Exception:  # noqa: BLE001 - log; retries happen per-operation
            log.exception("Initial database connectivity check failed.")

        for ext in INITIAL_EXTENSIONS:
            try:
                await self.load_extension(ext)
                log.info("Loaded extension %s", ext)
            except Exception:  # noqa: BLE001 - log and continue so one bad cog doesn't kill boot
                log.exception("Failed to load extension %s", ext)

        # Guild-scoped sync = near-instant command propagation (vs. up to 1h global).
        guild = discord.Object(id=self.settings.guild_id)
        try:
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info("Slash commands synced to guild %s", self.settings.guild_id)
        except discord.Forbidden:
            log.error(
                "Could not register slash commands (403 Missing Access). The bot was most "
                "likely invited WITHOUT the 'applications.commands' scope. Re-invite it via "
                "Developer Portal -> OAuth2 -> URL Generator with BOTH the 'bot' and "
                "'applications.commands' scopes, then restart. See README step 5. "
                "The bot will keep running, but its slash commands won't appear until this is fixed."
            )
        except discord.HTTPException:
            log.exception("Failed to sync slash commands; the bot will keep running.")

    async def on_ready(self) -> None:
        assert self.user is not None
        log.info("Connected as %s (id=%s)", self.user, self.user.id)
        guild = self.get_guild(self.settings.guild_id)
        if guild is None:
            log.warning(
                "Configured GUILD_ID %s not found among the bot's guilds. "
                "Is the bot invited to that server?",
                self.settings.guild_id,
            )
        else:
            log.info("Operating in guild: %s (id=%s)", guild.name, guild.id)
        log.info("No active event loaded yet (event lifecycle wiring lands in M4).")

    async def close(self) -> None:
        await db.dispose()
        await super().close()
