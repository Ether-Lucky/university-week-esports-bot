"""Discord resource-limit projection (see docs/discord-limitations.md).

Pure calculation: given the event configuration and the current server, project
how many roles/channels/categories setup will need and flag any limit breach
*before* creating anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Current Discord platform limits.
MAX_ROLES = 250
MAX_CHANNELS = 500
MAX_CATEGORIES = 50
MAX_CHANNELS_PER_CATEGORY = 50

# Base roles setup creates (E-Sports Head is preserved, not created):
# Committee, OIC, FIC, Player, Applicant, Audience.
BASE_ROLES_CREATED = 6

# Non-game categories: WELCOME/VERIFICATION, APPLICATIONS, STAFF, STAFF LOGS.
BASE_CATEGORIES = 4
# Non-game channels: verify, rules, apply, staff-general, application-review,
# staff-commands, + 9 staff-log channels = 15.
BASE_CHANNELS = 15

# Channels created per game category at setup (tryout voice + stage are created later):
# staff, general, apply-info, team-forum, lft-forum, players, mechanics,
# tournament, battle-results.
CHANNELS_PER_GAME = 9
# Reserve room in each game category for a stage + a couple of tryout voice channels.
GAME_CATEGORY_RESERVED = 3


@dataclass
class Projection:
    roles: int
    categories: int
    channels: int
    max_teams_per_game: int
    violations: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations


def max_teams_per_game() -> int:
    """Each team adds a text + voice channel under its game category (cap 50)."""
    room = MAX_CHANNELS_PER_CATEGORY - CHANNELS_PER_GAME - GAME_CATEGORY_RESERVED
    return max(room // 2, 0)


def project_setup(
    *,
    num_games: int,
    existing_roles: int = 0,
    existing_categories: int = 0,
    existing_channels: int = 0,
    expected_teams_total: int = 0,
) -> Projection:
    """Project resource usage after setup + expected teams; collect violations."""
    roles = existing_roles + BASE_ROLES_CREATED + expected_teams_total
    categories = existing_categories + BASE_CATEGORIES + num_games
    channels = (
        existing_channels
        + BASE_CHANNELS
        + num_games * CHANNELS_PER_GAME
        + expected_teams_total * 2  # each team: text + voice
    )
    per_game_cap = max_teams_per_game()

    violations: list[str] = []
    if roles > MAX_ROLES:
        violations.append(f"Roles: need ~{roles}, limit is {MAX_ROLES}.")
    if categories > MAX_CATEGORIES:
        violations.append(f"Categories: need ~{categories}, limit is {MAX_CATEGORIES}.")
    if channels > MAX_CHANNELS:
        violations.append(f"Channels: need ~{channels}, limit is {MAX_CHANNELS}.")
    if num_games > 0 and expected_teams_total > 0:
        avg = -(-expected_teams_total // num_games)  # ceil
        if avg > per_game_cap:
            violations.append(
                f"~{avg} teams/game exceeds the {per_game_cap}-team-per-game "
                "capacity (channels per category)."
            )

    return Projection(
        roles=roles,
        categories=categories,
        channels=channels,
        max_teams_per_game=per_game_cap,
        violations=violations,
    )


def community_required() -> bool:
    """Forums (team-forum, lft-forum) require a Community-enabled server — always."""
    return True


def community_satisfied(guild_features: set[str]) -> bool:
    return "COMMUNITY" in {f.upper() for f in guild_features}
