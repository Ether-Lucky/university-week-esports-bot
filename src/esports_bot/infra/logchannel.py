"""Mirror important actions to the staff log channels (docs/logging-and-audit.md).

The DB ``audit_logs`` table is the source of truth; this posts a compact,
human-readable copy to the matching #log-* channel. PII is kept minimal.
"""

from __future__ import annotations

import logging

import discord

from ..domain.enums import ResourceOwnerType
from .discord_gateway import DiscordResourceGateway
from .discord_resources import DiscordResourceService
from .resource_repository import SqlResourceRepository

log = logging.getLogger(__name__)

# Map a log category to its channel purpose.
LOG_CHANNELS = {
    "system": "log_system",
    "applications": "log_applications",
    "teams": "log_teams",
    "members": "log_members",
    "moderation": "log_moderation",
    "commands": "log_commands",
    "tryout": "log_tryout",
    "errors": "log_errors",
    "exports": "log_exports",
}


async def post_log(
    session, guild: discord.Guild, event_id: int, category: str, title: str,
    description: str = "", *, colour: discord.Colour | None = None,
) -> None:
    """Best-effort post to the staff log channel for ``category``. Never raises."""
    purpose = LOG_CHANNELS.get(category)
    if purpose is None:
        return
    try:
        resources = DiscordResourceService(
            DiscordResourceGateway(guild), SqlResourceRepository(session)
        )
        channel_id = await resources.find(event_id, ResourceOwnerType.SYSTEM, None, purpose)
        if channel_id and (channel := guild.get_channel(channel_id)):
            embed = discord.Embed(
                title=title, description=description or None,
                colour=colour or discord.Colour.dark_grey(),
                timestamp=discord.utils.utcnow(),
            )
            await channel.send(embed=embed)
    except Exception:  # noqa: BLE001 - logging must never break the action
        log.debug("Failed to mirror log to #%s", category, exc_info=True)
