"""Tryout match scheduling (OQ-3: floor(N/2) channels; odd team waits). Pure."""

from __future__ import annotations


def match_channel_count(complete_teams: int) -> int:
    """Number of round-1 match voice channels = floor(teams / 2)."""
    return max(complete_teams, 0) // 2


def pair_teams(team_ids: list[int]) -> tuple[list[tuple[int, int]], int | None]:
    """Pair teams for round 1. Odd count -> last team gets a bye (returned separately)."""
    pairs: list[tuple[int, int]] = []
    bye: int | None = None
    remaining = list(team_ids)
    if len(remaining) % 2 == 1:
        bye = remaining.pop()  # odd team out waits
    for i in range(0, len(remaining), 2):
        pairs.append((remaining[i], remaining[i + 1]))
    return pairs, bye
