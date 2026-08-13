"""Limit projection, blueprint, and setup-preview planning tests."""

from __future__ import annotations

from esports_bot.domain.limits import (
    MAX_CATEGORIES,
    community_satisfied,
    max_teams_per_game,
    project_setup,
)
from esports_bot.domain.server_blueprint import full_blueprint, game_category, slug
from esports_bot.domain.setup_plan import (
    ChannelInfo,
    GuildSnapshot,
    RoleInfo,
    plan_preview,
    serialise_backup,
)


def test_projection_ok_for_small_event() -> None:
    proj = project_setup(num_games=3, expected_teams_total=24)
    assert proj.ok, proj.violations
    assert proj.max_teams_per_game == max_teams_per_game()


def test_projection_flags_too_many_categories() -> None:
    proj = project_setup(num_games=MAX_CATEGORIES + 5)
    assert not proj.ok
    assert any("Categories" in v for v in proj.violations)


def test_projection_flags_team_capacity() -> None:
    # Far more teams than a single game's channel budget allows.
    proj = project_setup(num_games=1, expected_teams_total=max_teams_per_game() * 2)
    assert not proj.ok
    assert any("teams/game" in v for v in proj.violations)


def test_community_check() -> None:
    assert community_satisfied({"COMMUNITY", "NEWS"})
    assert not community_satisfied({"NEWS"})


def test_slug_and_blueprint() -> None:
    assert slug("Mobile Legends") == "mobile-legends"
    roles, cats = full_blueprint(["valorant", "mobile-legends"])
    assert len(roles) == 6
    # 4 base categories + 2 game categories.
    assert len(cats) == 6
    val = game_category("valorant")
    purposes = {c.purpose for c in val.channels}
    assert "game_team_forum:valorant" in purposes
    assert "game_lft_forum:valorant" in purposes


def _snapshot() -> GuildSnapshot:
    return GuildSnapshot(
        roles=(
            RoleInfo(1, "@everyone", is_default=True),
            RoleInfo(2, "E-Sports Head"),
            RoleInfo(3, "BotRole", managed=True),
            RoleInfo(4, "Random Role"),
        ),
        channels=(
            ChannelInfo(10, "announcements", "text", None),
            ChannelInfo(20, "TEXT CHANNELS", "category", None),
            ChannelInfo(21, "general", "text", 20),
            ChannelInfo(30, "Old Category", "category", None),
            ChannelInfo(31, "old-chat", "text", 30),
        ),
        features=frozenset({"COMMUNITY"}),
    )


def test_preview_preserve_and_remove() -> None:
    preview = plan_preview(_snapshot(), num_games=2)
    preserved_ids = {i for _, i, _ in preview.preserve}
    removed_ids = {i for _, i, _ in preview.remove}
    # Preserved: @everyone, Head, managed bot role, announcements, TEXT CHANNELS + child.
    assert {1, 2, 3, 10, 20, 21}.issubset(preserved_ids)
    # Removed: random role, old category + its channel.
    assert {4, 30, 31}.issubset(removed_ids)
    assert preview.community_ok
    assert preview.can_proceed


def test_preview_blocks_without_community() -> None:
    snap = _snapshot()
    snap = GuildSnapshot(roles=snap.roles, channels=snap.channels, features=frozenset())
    preview = plan_preview(snap, num_games=2)
    assert not preview.community_ok
    assert not preview.can_proceed
    assert any("Community" in w for w in preview.warnings)


def test_backup_serialises_json() -> None:
    payload = serialise_backup(_snapshot())
    assert '"roles"' in payload and '"channels"' in payload and "COMMUNITY" in payload
