"""M1 smoke tests: package imports and pure helpers work without Discord/DB."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


def test_version_importable() -> None:
    import esports_bot

    assert esports_bot.__version__ == "0.1.0"


def test_format_uptime() -> None:
    from esports_bot.cogs.system import _format_uptime

    started = datetime.now(UTC) - timedelta(days=1, hours=2, minutes=3, seconds=4)
    result = _format_uptime(started)
    assert result.startswith("1d 2h 3m")
