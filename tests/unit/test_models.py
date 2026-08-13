"""Model/metadata unit tests — no database required."""

from __future__ import annotations

from esports_bot.models import Base

EXPECTED_TABLES = {
    "events",
    "games",
    "event_games",
    "users",
    "staff_assignments",
    "applications",
    "application_history",
    "teams",
    "team_members",
    "recruitment_posts",
    "recruitment_requests",
    "matches",
    "match_results",
    "checkins",
    "mechanics",
    "tournaments",
    "discord_resources",
    "audit_logs",
    "exports",
}


def test_all_tables_registered() -> None:
    assert EXPECTED_TABLES.issubset(set(Base.metadata.tables))
    assert len(Base.metadata.tables) == len(EXPECTED_TABLES)


def test_active_application_partial_indexes_exist() -> None:
    idx = {i.name for i in Base.metadata.tables["applications"].indexes}
    assert "uq_app_active_per_user" in idx  # OQ-4
    assert "uq_app_active_per_email" in idx  # OQ-5


def test_rejection_reason_check_constraint() -> None:
    names = {c.name for c in Base.metadata.tables["applications"].constraints}
    assert "ck_applications_rejection_reason_required" in names


def test_member_one_active_team_index() -> None:
    idx = {i.name for i in Base.metadata.tables["team_members"].indexes}
    assert "uq_member_active_per_event" in idx


def test_discord_resource_lookup_index() -> None:
    idx = {i.name for i in Base.metadata.tables["discord_resources"].indexes}
    assert "ix_resource_lookup" in idx
