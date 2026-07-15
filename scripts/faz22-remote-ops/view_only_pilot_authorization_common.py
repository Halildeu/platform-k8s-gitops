"""Canonical byte and digest helpers for bounded VIEW_ONLY authorization receipts."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def canonical_receipt_bytes(receipt: dict[str, Any]) -> bytes:
    return canonical_bytes(receipt) + b"\n"


def digest_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"
