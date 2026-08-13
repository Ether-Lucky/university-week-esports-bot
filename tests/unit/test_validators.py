"""Validator unit tests (docs/security.md §2)."""

from __future__ import annotations

import pytest

from esports_bot.domain.validators import (
    ValidationError,
    sanitize_name,
    validate_email_domain,
    validate_facebook_url,
    validate_https_url,
    validate_roster_size,
    validate_school_email,
    validate_timezone,
    validate_year,
)


def test_sanitize_name_blocks_mentions_and_control() -> None:
    assert sanitize_name("  Team   Alpha ") == "Team Alpha"
    with pytest.raises(ValidationError):
        sanitize_name("@everyone")
    with pytest.raises(ValidationError):
        sanitize_name("   ")
    with pytest.raises(ValidationError):
        sanitize_name("x" * 200, max_len=100)


def test_email_domain_and_school_email() -> None:
    assert validate_email_domain("UPHSL.edu.ph") == "uphsl.edu.ph"
    assert validate_school_email("c23-1435@uphsl.edu.ph", "uphsl.edu.ph")
    with pytest.raises(ValidationError):
        validate_school_email("c23@gmail.com", "uphsl.edu.ph")
    with pytest.raises(ValidationError):
        validate_school_email("not-an-email", "uphsl.edu.ph")


def test_timezone() -> None:
    assert validate_timezone("Asia/Manila") == "Asia/Manila"
    with pytest.raises(ValidationError):
        validate_timezone("Mars/Phobos")


def test_year_and_roster() -> None:
    assert validate_year(2027) == 2027
    with pytest.raises(ValidationError):
        validate_year(1999)
    assert validate_roster_size(5) == 5
    with pytest.raises(ValidationError):
        validate_roster_size(0)


def test_urls() -> None:
    assert validate_facebook_url("https://www.facebook.com/example")
    with pytest.raises(ValidationError):
        validate_facebook_url("http://facebook.com/x")  # not https
    with pytest.raises(ValidationError):
        validate_facebook_url("https://evil.com/x")  # wrong host
    assert validate_https_url("https://imgur.com/a.png")
    with pytest.raises(ValidationError):
        validate_https_url("ftp://x/y")
