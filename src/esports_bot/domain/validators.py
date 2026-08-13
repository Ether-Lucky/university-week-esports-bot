"""Input validation & sanitization (see docs/security.md §2).

Pure functions, unit-testable. Raise ``ValidationError`` with a user-safe
message on invalid input.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_WHITESPACE = re.compile(r"\s+")
_MENTION = re.compile(r"@(everyone|here)|<@[!&]?\d+>")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DOMAIN_RE = re.compile(r"^(?=.{1,255}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$")

_FACEBOOK_HOSTS = {"facebook.com", "www.facebook.com", "m.facebook.com", "fb.com"}


class ValidationError(ValueError):
    """User-facing validation failure."""


def sanitize_name(value: str, *, max_len: int = 100, field: str = "name") -> str:
    """Strip control chars, collapse whitespace, block mention/markdown injection."""
    cleaned = _CONTROL_CHARS.sub("", value or "")
    cleaned = _WHITESPACE.sub(" ", cleaned).strip()
    if not cleaned:
        raise ValidationError(f"{field} cannot be empty.")
    if _MENTION.search(cleaned):
        raise ValidationError(f"{field} may not contain mentions.")
    # Neutralise Discord markdown/backtick/formatting characters.
    cleaned = cleaned.replace("`", "").replace("\\", "")
    if len(cleaned) > max_len:
        raise ValidationError(f"{field} must be at most {max_len} characters.")
    return cleaned


def validate_email_domain(domain: str) -> str:
    d = (domain or "").strip().lower().lstrip("@")
    if not _DOMAIN_RE.match(d):
        raise ValidationError(f"'{domain}' is not a valid email domain.")
    return d


def validate_school_email(email: str, domain: str) -> str:
    e = (email or "").strip().lower()
    if not _EMAIL_RE.match(e):
        raise ValidationError("That is not a valid email address.")
    if not e.endswith("@" + domain.lower()):
        raise ValidationError(f"Email must end with @{domain}.")
    return e


def validate_timezone(tz: str) -> str:
    name = (tz or "").strip()
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, ModuleNotFoundError):
        raise ValidationError(f"'{tz}' is not a valid IANA timezone (e.g. Asia/Manila).") from None
    return name


def validate_year(year: int) -> int:
    if not (2000 <= int(year) <= 2100):
        raise ValidationError("Year must be between 2000 and 2100.")
    return int(year)


def validate_roster_size(size: int) -> int:
    if not (1 <= int(size) <= 20):
        raise ValidationError("Roster size must be between 1 and 20.")
    return int(size)


def validate_https_url(
    url: str, *, allowed_hosts: set[str] | None = None, field: str = "URL"
) -> str:
    u = (url or "").strip()
    parsed = urlparse(u)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValidationError(f"{field} must be a valid https:// URL.")
    if allowed_hosts is not None and parsed.netloc.lower() not in allowed_hosts:
        raise ValidationError(f"{field} host is not allowed.")
    return u


def validate_facebook_url(url: str) -> str:
    return validate_https_url(url, allowed_hosts=_FACEBOOK_HOSTS, field="Facebook URL")
