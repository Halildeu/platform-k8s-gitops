"""Negative test fixture for ADR-0011 DD-2 — ETL contract regression.

This file deliberately regresses make_source_pk() canonical contract:
- Uses delimiter-based template instead of json.dumps
- Drops ensure_ascii=False
- Drops None preservation

DO NOT use as real ETL transform; bait for DD-2 negative test.
"""
from __future__ import annotations

from typing import Any


def make_source_pk(row: dict[str, Any], idempotency_key: list[str]) -> str:
    """Returns delimiter-based PK string. WRONG: should be canonical JSON."""
    parts: list[str] = []
    for col in idempotency_key:
        v = row.get(col)
        # No None preservation, no str(v) cast
        parts.append(repr(v))
    # Delimiter-based template (Codex iter-6 explicitly rejected)
    return "|".join(parts)
