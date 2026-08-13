"""Channel permission-overwrite matrix (docs/discord-server-design.md).

Pure data: maps each blueprint ``purpose`` to an archetype, and each archetype
to per-role permission flags. Infra translates role *keys* to real Discord role
IDs at apply time, so this stays testable without discord.py.
"""

from __future__ import annotations

from dataclasses import dataclass

# Canonical role keys (match discord_resources purposes; "everyone" is @everyone).
EVERYONE = "everyone"
HEAD = "role_head"
COMMITTEE = "role_committee"
OIC = "role_oic"
FIC = "role_fic"
PLAYER = "role_player"
APPLICANT = "role_applicant"
AUDIENCE = "role_audience"

STAFF_KEYS = (HEAD, COMMITTEE, OIC, FIC)


@dataclass(frozen=True)
class PermFlags:
    view: bool | None = None
    send: bool | None = None
    connect: bool | None = None


def _staff(view: bool = True, send: bool = True) -> dict[str, PermFlags]:
    return {k: PermFlags(view=view, send=send) for k in STAFF_KEYS}


def _archetypes() -> dict[str, dict[str, PermFlags]]:
    staff_only = {EVERYONE: PermFlags(view=False), **_staff()}

    verify = {EVERYONE: PermFlags(view=True, send=True)}

    rules = {EVERYONE: PermFlags(view=True, send=False), **_staff()}

    readonly_public = {
        EVERYONE: PermFlags(view=False),
        AUDIENCE: PermFlags(view=True, send=False),
        APPLICANT: PermFlags(view=True, send=False),
        PLAYER: PermFlags(view=True, send=False),
        **_staff(),
    }

    game_general = {
        EVERYONE: PermFlags(view=False),
        AUDIENCE: PermFlags(view=True, send=False),
        APPLICANT: PermFlags(view=True, send=True),
        PLAYER: PermFlags(view=True, send=True),
        **_staff(),
    }

    apply = {
        EVERYONE: PermFlags(view=False),
        APPLICANT: PermFlags(view=True, send=True),
        PLAYER: PermFlags(view=True, send=False),
        **_staff(),
    }

    forum = {
        EVERYONE: PermFlags(view=False),
        AUDIENCE: PermFlags(view=True, send=False),
        APPLICANT: PermFlags(view=True, send=True),
        PLAYER: PermFlags(view=True, send=False),
        **_staff(),
    }

    players = {
        EVERYONE: PermFlags(view=False),
        PLAYER: PermFlags(view=True, send=True),
        **_staff(),
    }

    category_default = {EVERYONE: PermFlags(view=False)}

    return {
        "staff_only": staff_only,
        "verify": verify,
        "rules": rules,
        "readonly_public": readonly_public,
        "game_general": game_general,
        "apply": apply,
        "forum": forum,
        "players": players,
        "category_default": category_default,
    }


_ARCHETYPES = _archetypes()


def archetype_for(purpose: str) -> str:
    """Map a blueprint purpose (possibly with a ':<game>' suffix) to an archetype."""
    base = purpose.split(":", 1)[0]
    mapping = {
        "ch_verify": "verify",
        "ch_rules": "rules",
        "ch_apply": "apply",
        "ch_staff_general": "staff_only",
        "ch_application_review": "staff_only",
        "ch_staff_commands": "staff_only",
        "game_staff": "staff_only",
        "game_general": "game_general",
        "game_apply_info": "readonly_public",
        "game_mechanics": "readonly_public",
        "game_tournament": "readonly_public",
        "game_battle_results": "readonly_public",
        "game_team_forum": "forum",
        "game_lft_forum": "forum",
        "game_players": "players",
        "cat_staff": "staff_only",
        "cat_staff_logs": "staff_only",
    }
    if base.startswith("log_"):
        return "staff_only"
    if base.startswith("cat_"):
        return mapping.get(base, "category_default")
    return mapping.get(base, "readonly_public")


def overwrites_for(purpose: str) -> dict[str, PermFlags]:
    """Return {role_key: PermFlags} for a channel/category purpose."""
    return _ARCHETYPES[archetype_for(purpose)]
