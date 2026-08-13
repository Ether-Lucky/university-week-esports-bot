"""Service-layer errors — messages are safe to show users."""

from __future__ import annotations


class ServiceError(Exception):
    """A recoverable, user-facing service failure (friendly message)."""
