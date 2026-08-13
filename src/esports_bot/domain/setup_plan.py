"""Setup preview planning: decide what to preserve vs remove, and serialise a
backup of the current server structure (docs/discord-server-design.md §Setup).

Works on a plain ``GuildSnapshot`` so it is testable without discord.py.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from .limits import Projection, community_satisfied, project_setup


@dataclass(frozen=True)
class RoleInfo:
    id: int
    name: str
    managed: bool = False  # bot/integration roles — never deletable
    is_default: bool = False  # @everyone


@dataclass(frozen=True)
class ChannelInfo:
    id: int
    name: str
    kind: str  # category | text | voice | forum | stage
    category_id: int | None = None


@dataclass(frozen=True)
class GuildSnapshot:
    roles: tuple[RoleInfo, ...]
    channels: tuple[ChannelInfo, ...]
    features: frozenset[str] = frozenset()


@dataclass(frozen=True)
class PreserveConfig:
    head_role_name: str = "E-Sports Head"
    announcement_channel_name: str = "announcements"
    preserved_category_name: str = "TEXT CHANNELS"


@dataclass
class SetupPreview:
    preserve: list[tuple[str, int, str]] = field(default_factory=list)  # (kind, id, name)
    remove: list[tuple[str, int, str]] = field(default_factory=list)
    projection: Projection | None = None
    community_ok: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def can_proceed(self) -> bool:
        proj_ok = self.projection.ok if self.projection else False
        return self.community_ok and proj_ok


def _norm(name: str) -> str:
    return name.strip().casefold()


def plan_preview(
    snapshot: GuildSnapshot,
    *,
    num_games: int,
    expected_teams_total: int = 0,
    preserve: PreserveConfig | None = None,
) -> SetupPreview:
    cfg = preserve or PreserveConfig()
    result = SetupPreview()

    # Determine the preserved category id (by name) so its children are kept too.
    preserved_cat_id: int | None = None
    for ch in snapshot.channels:
        if ch.kind == "category" and _norm(ch.name) == _norm(cfg.preserved_category_name):
            preserved_cat_id = ch.id
            break

    # Roles: preserve @everyone, managed roles, and the E-Sports Head role.
    for r in snapshot.roles:
        keep = r.is_default or r.managed or _norm(r.name) == _norm(cfg.head_role_name)
        target = result.preserve if keep else result.remove
        target.append(("role", r.id, r.name))

    # Channels: preserve the announcement channel and the preserved category + children.
    for ch in snapshot.channels:
        keep = (
            _norm(ch.name) == _norm(cfg.announcement_channel_name)
            or (ch.kind == "category" and ch.id == preserved_cat_id)
            or (ch.category_id is not None and ch.category_id == preserved_cat_id)
        )
        target = result.preserve if keep else result.remove
        target.append((ch.kind, ch.id, ch.name))

    # Community + limit projection (based on the resources that will remain).
    result.community_ok = community_satisfied(set(snapshot.features))
    if not result.community_ok:
        result.warnings.append(
            "Server is not Community-enabled; Forum and Stage channels require it. "
            "Enable Community in Server Settings before running setup."
        )

    remaining_roles = sum(1 for k, _, _ in result.preserve if k == "role")
    remaining_categories = sum(1 for k, _, _ in result.preserve if k == "category")
    remaining_channels = sum(1 for k, _, _ in result.preserve if k not in ("role", "category"))
    result.projection = project_setup(
        num_games=num_games,
        existing_roles=remaining_roles,
        existing_categories=remaining_categories,
        existing_channels=remaining_channels,
        expected_teams_total=expected_teams_total,
    )
    result.warnings.extend(result.projection.violations)
    return result


def serialise_backup(snapshot: GuildSnapshot) -> str:
    """JSON backup of the current server structure (pre-destruction)."""
    payload = {
        "roles": [asdict(r) for r in snapshot.roles],
        "channels": [asdict(c) for c in snapshot.channels],
        "features": sorted(snapshot.features),
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)
