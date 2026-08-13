"""Permission-matrix unit tests (docs/discord-server-design.md)."""

from __future__ import annotations

from esports_bot.domain.permissions import (
    APPLICANT,
    AUDIENCE,
    COMMITTEE,
    EVERYONE,
    PLAYER,
    archetype_for,
    overwrites_for,
)


def test_archetype_mapping() -> None:
    assert archetype_for("ch_verify") == "verify"
    assert archetype_for("game_team_forum:valorant") == "forum"
    assert archetype_for("game_players:valorant") == "players"
    assert archetype_for("log_errors") == "staff_only"
    assert archetype_for("game_staff:mobile-legends") == "staff_only"


def test_staff_channel_hidden_from_everyone() -> None:
    ow = overwrites_for("ch_application_review")
    assert ow[EVERYONE].view is False
    assert ow[COMMITTEE].view is True and ow[COMMITTEE].send is True
    # Non-staff roles are simply absent (no grant).
    assert AUDIENCE not in ow and APPLICANT not in ow


def test_apply_channel_visible_to_audience_hidden_from_everyone() -> None:
    ow = overwrites_for("ch_apply")
    assert ow[EVERYONE].view is False
    # Audience (the starting role) must see #apply to press the Apply button.
    assert ow[AUDIENCE].view is True
    assert ow[APPLICANT].view is True


def test_forum_audience_can_view_applicant_can_post() -> None:
    ow = overwrites_for("game_team_forum:valorant")
    assert ow[EVERYONE].view is False
    assert ow[AUDIENCE].view is True and ow[AUDIENCE].send is False
    assert ow[APPLICANT].send is True


def test_players_channel_excludes_audience_and_applicant() -> None:
    ow = overwrites_for("game_players:valorant")
    assert ow[EVERYONE].view is False
    assert ow[PLAYER].view is True and ow[PLAYER].send is True
    assert AUDIENCE not in ow and APPLICANT not in ow


def test_verify_visible_to_everyone() -> None:
    ow = overwrites_for("ch_verify")
    assert ow[EVERYONE].view is True and ow[EVERYONE].send is True
