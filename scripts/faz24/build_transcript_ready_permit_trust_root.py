#!/usr/bin/env python3
"""Build the pinned public trust root from a TEST Vault Transit receipt."""

from __future__ import annotations

import argparse
import base64
import binascii
import datetime as dt
import hashlib
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import urlsplit

from transcript_ready_pre_enable_contract import (
    APP_ENVIRONMENTS,
    KEY_ID_RE,
    PERMIT_TRUST_ROOT_SCHEMA,
    ContractError,
    canonical_json,
    load_strict_json,
    parse_utc,
)

TRANSIT_RECEIPT_SCHEMA = "faz24.transcriptReadyPermitTransitReceipt.v1"
TRANSIT_MOUNT = "meeting-ai"
TRANSIT_KEY_NAME = "transcript-ready-permit"
RECEIPT_FIELDS = frozenset(
    {
        "schemaVersion",
        "scope",
        "vaultOrigin",
        "vaultClusterId",
        "mount",
        "keyName",
        "keyVersion",
        "keyId",
        "publicKeyBase64",
        "keyType",
        "derived",
        "exportable",
        "allowPlaintextBackup",
        "deletionAllowed",
        "supportsSigning",
        "verifiedAt",
        "requiresOutOfBandOwnerPin",
    }
)


def _public_key(value: Any) -> bytes:
    if not isinstance(value, str):
        raise ContractError("receipt public key must be canonical Base64")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ContractError("receipt public key must be canonical Base64") from exc
    if (
        len(decoded) != 32
        or base64.b64encode(decoded).decode("ascii") != value
    ):
        raise ContractError("receipt public key must be raw Ed25519")
    return decoded


def _https_origin(value: Any) -> str:
    if not isinstance(value, str):
        raise ContractError("receipt Vault origin is invalid")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ContractError("receipt Vault origin must be canonical HTTPS")
    return value


def validate_receipt(
    receipt: dict[str, Any], *, expected_receipt_sha256: str, raw: bytes
) -> tuple[str, str, dt.datetime]:
    if re.fullmatch(r"[0-9a-f]{64}", expected_receipt_sha256) is None:
        raise ContractError("expected receipt SHA-256 is invalid")
    if hashlib.sha256(raw).hexdigest() != expected_receipt_sha256:
        raise ContractError("receipt SHA-256 does not match the out-of-band pin")
    if set(receipt) != RECEIPT_FIELDS:
        raise ContractError("Transit receipt has missing or unknown fields")
    if (
        receipt.get("schemaVersion") != TRANSIT_RECEIPT_SCHEMA
        or receipt.get("scope") != "test-only"
        or receipt.get("mount") != TRANSIT_MOUNT
        or receipt.get("keyName") != TRANSIT_KEY_NAME
        or receipt.get("keyType") != "ed25519"
        or receipt.get("derived") is not False
        or receipt.get("exportable") is not False
        or receipt.get("allowPlaintextBackup") is not False
        or receipt.get("deletionAllowed") is not False
        or receipt.get("supportsSigning") is not True
        or receipt.get("requiresOutOfBandOwnerPin") is not True
    ):
        raise ContractError("Transit receipt does not prove a safe dedicated key")
    _https_origin(receipt.get("vaultOrigin"))
    cluster_id = receipt.get("vaultClusterId")
    if not isinstance(cluster_id, str) or not 1 <= len(cluster_id) <= 200:
        raise ContractError("Transit receipt cluster ID is invalid")
    version = receipt.get("keyVersion")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ContractError("Transit receipt key version is invalid")
    key_id = receipt.get("keyId")
    expected_key_id = (
        f"vault-transit://{TRANSIT_MOUNT}/{TRANSIT_KEY_NAME}#v{version}"
    )
    if (
        not isinstance(key_id, str)
        or KEY_ID_RE.fullmatch(key_id) is None
        or key_id != expected_key_id
    ):
        raise ContractError("Transit receipt key ID is inconsistent")
    _public_key(receipt.get("publicKeyBase64"))
    verified_at = parse_utc(receipt.get("verifiedAt"))
    return key_id, receipt["publicKeyBase64"], verified_at


def build_trust_root(
    *,
    receipt_path: Path,
    expected_receipt_sha256: str,
    allowed_app_environments: list[str],
    not_before: str,
    not_after: str,
    now: dt.datetime,
) -> dict[str, Any]:
    raw, receipt = load_strict_json(receipt_path, "Transit receipt")
    key_id, public_key, verified_at = validate_receipt(
        receipt, expected_receipt_sha256=expected_receipt_sha256, raw=raw
    )
    environments = sorted(set(allowed_app_environments))
    if (
        not environments
        or environments != allowed_app_environments
        or any(value not in APP_ENVIRONMENTS for value in environments)
        or environments != ["test"]
    ):
        raise ContractError("Faz 24 initial trust root must be test-only")
    start = parse_utc(not_before)
    end = parse_utc(not_after)
    if now.tzinfo is None or now.utcoffset() != dt.timedelta(0):
        raise ContractError("builder time must be UTC")
    if (
        not start < end
        or not start <= now <= end
        or start < verified_at - dt.timedelta(minutes=5)
        or end - start > dt.timedelta(days=366)
    ):
        raise ContractError("trust-root validity window is invalid")
    return {
        "schemaVersion": PERMIT_TRUST_ROOT_SCHEMA,
        "keyId": key_id,
        "algorithm": "ed25519",
        "publicKeyBase64": public_key,
        "allowedAppEnvironments": environments,
        "notBefore": not_before,
        "notAfter": not_after,
    }


def _write_public(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.is_symlink():
        raise ContractError("trust-root output cannot replace a symlink")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o644)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--expected-receipt-sha256", required=True)
    parser.add_argument(
        "--allowed-app-environment",
        action="append",
        required=True,
        choices=sorted(APP_ENVIRONMENTS),
    )
    parser.add_argument("--not-before", required=True)
    parser.add_argument("--not-after", required=True)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        root = build_trust_root(
            receipt_path=args.receipt,
            expected_receipt_sha256=args.expected_receipt_sha256,
            allowed_app_environments=args.allowed_app_environment,
            not_before=args.not_before,
            not_after=args.not_after,
            now=dt.datetime.now(dt.timezone.utc),
        )
        root_bytes = canonical_json(root)
        _write_public(args.output, root_bytes)
    except ContractError as exc:
        print(f"trust-root build rejected: {exc}", file=sys.stderr)
        return 2
    print(f"key_id={root['keyId']}")
    print(f"trust_root_sha256={hashlib.sha256(root_bytes).hexdigest()}")
    print("requires_out_of_band_owner_pin=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
