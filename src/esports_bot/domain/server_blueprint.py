"""Declarative blueprint of the Discord structure setup creates.

Pure data (no Discord, no DB). ``SetupService`` executes it via the resource
service. Each spec has a stable ``purpose`` used as the key in discord_resources
so resources are found by ID, never by name (docs/discord-server-design.md).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slug(name: str) -> str:
    """Channel-safe short code for a game name (e.g. 'Mobile Legends' -> 'mobile-legends')."""
    s = _SLUG_RE.sub("-", (name or "").strip().lower()).strip("-")
    return s or "game"


@dataclass(frozen=True)
class RoleSpec:
    purpose: str
    name: str
    hoist: bool = False


@dataclass(frozen=True)
class ChannelSpec:
    purpose: str
    name: str
    kind: str  # text | voice | forum | stage


@dataclass(frozen=True)
class CategorySpec:
    purpose: str
    name: str
    channels: tuple[ChannelSpec, ...] = field(default_factory=tuple)


# Roles setup creates (E-Sports Head is preserved, not created).
BASE_ROLES: tuple[RoleSpec, ...] = (
    RoleSpec("role_committee", "E-Sports Committee", hoist=True),
    RoleSpec("role_oic", "Officer in Charge", hoist=True),
    RoleSpec("role_fic", "Faculty in Charge", hoist=True),
    RoleSpec("role_player", "Player", hoist=True),
    RoleSpec("role_applicant", "Applicant"),
    RoleSpec("role_audience", "Audience"),
)

_LOG_CHANNELS = (
    "system", "applications", "teams", "members", "moderation",
    "commands", "tryout", "errors", "exports",
)

# Non-game categories + their channels.
BASE_CATEGORIES: tuple[CategorySpec, ...] = (
    CategorySpec(
        "cat_dashboard", "📊 EVENT DASHBOARD",
        (ChannelSpec("ch_dashboard", "dashboard", "text"),),
    ),
    CategorySpec(
        "cat_welcome", "WELCOME",
        (
            ChannelSpec("ch_verify", "verify", "text"),
            ChannelSpec("ch_rules", "rules", "text"),
            ChannelSpec("ch_info", "how-it-works", "text"),
        ),
    ),
    CategorySpec(
        "cat_applications", "APPLICATIONS",
        (ChannelSpec("ch_apply", "apply", "text"),),
    ),
    CategorySpec(
        "cat_staff", "STAFF",
        (
            ChannelSpec("ch_staff_general", "staff-general", "text"),
            ChannelSpec("ch_application_review", "application-review", "text"),
            ChannelSpec("ch_staff_commands", "staff-commands", "text"),
        ),
    ),
    CategorySpec(
        "cat_staff_logs", "STAFF LOGS",
        tuple(ChannelSpec(f"log_{n}", f"log-{n}", "text") for n in _LOG_CHANNELS),
    ),
)


def game_category(game_short: str) -> CategorySpec:
    """Build the per-game category blueprint for a game (short code, e.g. 'valorant')."""
    s = game_short
    return CategorySpec(
        f"cat_game:{s}",
        game_short.upper(),
        (
            ChannelSpec(f"game_staff:{s}", f"{s}-staff", "text"),
            ChannelSpec(f"game_general:{s}", f"{s}-general", "text"),
            ChannelSpec(f"game_apply_info:{s}", f"{s}-apply-info", "text"),
            ChannelSpec(f"game_team_forum:{s}", f"{s}-team-forum", "forum"),
            ChannelSpec(f"game_lft_forum:{s}", f"{s}-lft-forum", "forum"),
            ChannelSpec(f"game_players:{s}", f"{s}-players", "text"),
            ChannelSpec(f"game_mechanics:{s}", f"{s}-mechanics", "text"),
            ChannelSpec(f"game_tournament:{s}", f"{s}-tournament", "text"),
            ChannelSpec(f"game_battle_results:{s}", f"{s}-battle-results", "text"),
        ),
    )


def full_blueprint(
    game_shorts: list[str],
) -> tuple[tuple[RoleSpec, ...], tuple[CategorySpec, ...]]:
    """Return (roles, categories) for the full server structure."""
    categories = list(BASE_CATEGORIES) + [game_category(s) for s in game_shorts]
    return BASE_ROLES, tuple(categories)
