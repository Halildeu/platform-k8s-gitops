"""Strict UTC timestamp helpers shared by evidence and webhook policy."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .errors import reject


def parse_utc(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        reject("TIMESTAMP_INVALID", f"{field} must be an RFC3339 UTC Z timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        reject("TIMESTAMP_INVALID", f"{field} must be an RFC3339 UTC Z timestamp")
    if parsed.utcoffset() != timedelta(0):
        reject("TIMESTAMP_INVALID", f"{field} must use UTC")
    return parsed.astimezone(timezone.utc)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_seconds(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
