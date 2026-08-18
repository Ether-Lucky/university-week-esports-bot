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
    "esports_bot.cogs.dashboard",
    "esports_bot.cogs.announce",
    "esports_bot.cogs.membership",
    "esports_bot.cogs.sync",
    "esports_bot.cogs.players",
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
        self._synced_guilds: set[int] = set()

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
        # The home guild is synced here; every other guild the bot is in is synced in
        # on_ready, and any guild invited later is synced in on_guild_join.
        await self._sync_commands_to_guild(self.settings.guild_id)

    async def _sync_commands_to_guild(self, guild_id: int) -> None:
        """Register all commands in one guild (instant), once per process."""
        if guild_id in self._synced_guilds:
            return
        guild = discord.Object(id=guild_id)
        try:
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            self._synced_guilds.add(guild_id)
            log.info("Slash commands synced to guild %s", guild_id)
        except discord.Forbidden:
            log.error(
                "Could not register slash commands in guild %s (403 Missing Access). The bot "
                "was likely invited WITHOUT the 'applications.commands' scope. Re-invite it via "
                "an OAuth2 URL that includes BOTH 'bot' and 'applications.commands'.",
                guild_id,
            )
        except discord.HTTPException:
            log.exception("Failed to sync slash commands to guild %s.", guild_id)

    async def on_guild_join(self, guild: discord.Guild) -> None:
        """A new server invited the bot — register its commands there immediately."""
        await self._sync_commands_to_guild(guild.id)

    async def on_ready(self) -> None:
        assert self.user is not None
        log.info("Connected as %s (id=%s)", self.user, self.user.id)
        guild = self.get_guild(self.settings.guild_id)
        if guild is None:
            log.warning(
                "Configured GUILD_ID %s not found among the bot's guilds.",
                self.settings.guild_id,
            )
            if self.guilds:
                joined = ", ".join(f"'{g.name}' (id={g.id})" for g in self.guilds)
                log.warning(
                    "The bot IS currently in: %s. Either set GUILD_ID in .env to one of these "
                    "IDs, or re-open your invite URL and authorize the bot to the correct server.",
                    joined,
                )
            else:
                log.warning(
                    "The bot is not in ANY server yet. Open your invite URL and click Authorize "
                    "for the target server."
                )
        else:
            log.info("Operating in guild: %s (id=%s)", guild.name, guild.id)

        # Register commands in every guild the bot is already in (e.g. servers that
        # invited it before this ran). Home guild was synced in setup_hook; the set
        # guard makes this a no-op for anything already done.
        for g in self.guilds:
            await self._sync_commands_to_guild(g.id)

    async def close(self) -> None:
        await db.dispose()
        await super().close()
