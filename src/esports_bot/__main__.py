"""Entrypoint: load config, set up logging, start the bot."""

from __future__ import annotations

import logging

from .bot import EsportsBot
from .config import get_settings
from .logging_setup import setup_logging


def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    log = logging.getLogger("esports_bot")
    log.info("Starting University Week E-Sports bot (v0.1.0)")
    log.info("Target guild: %s | DB: Supabase Postgres (remote)", settings.guild_id)

    bot = EsportsBot(settings)
    # discord.py manages its own logging handlers; we pass ours in.
    bot.run(settings.discord_token, log_handler=None)


if __name__ == "__main__":
    main()
