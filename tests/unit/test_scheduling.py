"""Tryout scheduling tests (OQ-3: floor(N/2), odd team waits)."""

from __future__ import annotations

import pytest

from esports_bot.domain.scheduling import match_channel_count, pair_teams


@pytest.mark.parametrize(
    "teams,expected",
    [(0, 0), (1, 0), (2, 1), (3, 1), (4, 2), (5, 2), (8, 4)],
)
def test_match_channel_count(teams: int, expected: int) -> None:
    assert match_channel_count(teams) == expected


def test_pair_even() -> None:
    pairs, bye = pair_teams([1, 2, 3, 4])
    assert pairs == [(1, 2), (3, 4)]
    assert bye is None


def test_pair_odd_last_team_waits() -> None:
    pairs, bye = pair_teams([1, 2, 3, 4, 5])
    assert pairs == [(1, 2), (3, 4)]
    assert bye == 5
