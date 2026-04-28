"""Minimal shared utilities used by ci/ check scripts ported from owning repo.

This module is the smallest viable shim to unblock the import dependency
of `ci/check_enforcement_rules.py:22` and `ci/check_test_quality.py:22` —
both import `from src.shared.utils import now_iso8601`.

Original source: platform-ssot (or whichever repo originally owned the
ci/ scripts). This shim ships a minimal compatible implementation so the
ci/ scripts can be imported and exercised in this repo's context.

PR-A of the ci/ Python check script workflow port (Faz 19.11.D).
Codex consensus thread `019dd322` (PARTIAL — PR-A approved standalone).

When more scripts/utilities are ported here, this module may grow; keep
each addition minimal and avoid pulling in unrelated dev-repo helpers.
"""

from __future__ import annotations

from datetime import datetime, timezone


def now_iso8601() -> str:
    """Return the current UTC time as an ISO 8601 string.

    Returns
    -------
    str
        Current UTC time formatted as ISO 8601 (e.g. "2026-04-28T07:42:13.123456+00:00").

    Notes
    -----
    Used by ci/ scripts to stamp report JSON outputs. Seconds-precision is
    not enforced; downstream callers may further format if needed.
    """
    return datetime.now(timezone.utc).isoformat()


__all__ = ["now_iso8601"]
