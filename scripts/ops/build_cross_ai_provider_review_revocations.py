#!/usr/bin/env python3
"""Issue the fixed signed public revocation set for direct-Codex reviews.

The command can sign only the revocation payload type with the fixed TEST
``cross-ai/revocation`` Transit route.  It never accepts an arbitrary payload
type, signing key name, mount or pre-built DSSE envelope.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.github_apps.cross_ai_deployment_policy.canonical import (
    canonical_bytes,
    sha256_digest,
)
from scripts.github_apps.cross_ai_deployment_policy.contract import (
    REVOCATIONS_PAYLOAD_TYPE,
)
from scripts.github_apps.cross_ai_deployment_policy.dsse import (
    decode_public_key,
    verify_json_envelope,
)
from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError, reject
from scripts.github_apps.cross_ai_deployment_policy.jsonutil import load_json_file
from scripts.github_apps.cross_ai_deployment_policy.timeutil import parse_utc
from scripts.github_apps.cross_ai_deployment_policy.transit import VaultTransitSigner


REVOCATIONS_SCHEMA = ROOT / "schema/cross-ai-deployment-revocations-v1.schema.json"
TRUST_ROOT_SCHEMA = ROOT / "schema/cross-ai-deployment-trust-root-v2.schema.json"
RELEASE_INPUT_SCHEMA = "acik.cross-ai-provider-review-revocation-input.v1"
MAX_REVOCATION_LIFETIME = timedelta(minutes=60)
EXPECTED_ROOT_PROVIDER_FAMILIES = ["openai"]


class EnvelopeSigner(Protocol):
    @property
    def key_id(self) -> str: ...

    def sign_json_envelope(
        self, *, payload_type: str, payload: dict[str, Any]
    ) -> dict[str, Any]: ...


def _schema(value: object, path: Path, label: str) -> None:
    schema = load_json_file(path)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
        key=lambda item: list(item.path),
    )
    if errors:
        reject("REVOCATION_RELEASE_SCHEMA_INVALID", f"{label} is schema-invalid")


def _canonical_utc(value: str, label: str) -> datetime:
    parsed = parse_utc(value, label)
    canonical = (
        parsed.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    if value != canonical:
        reject("REVOCATION_RELEASE_TIME_INVALID", f"{label} must be canonical UTC")
    return parsed


def _entries(value: dict[str, Any]) -> list[dict[str, Any]]:
    if set(value) != {"schemaVersion", "entries"} or value.get(
        "schemaVersion"
    ) != RELEASE_INPUT_SCHEMA:
        reject(
            "REVOCATION_RELEASE_INPUT_INVALID",
            "revocation release input fields are not exact",
        )
    entries = value.get("entries")
    if not isinstance(entries, list):
        reject("REVOCATION_RELEASE_INPUT_INVALID", "revocation entries must be a list")
    normalized: list[dict[str, Any]] = []
    identities: set[tuple[str, str]] = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {
            "type",
            "id",
            "effectiveAt",
            "reasonCode",
        }:
            reject(
                "REVOCATION_RELEASE_INPUT_INVALID",
                "revocation entry fields are not exact",
            )
        identity = (entry.get("type"), entry.get("id"))
        if not all(isinstance(item, str) for item in identity) or identity in identities:
            reject(
                "REVOCATION_RELEASE_INPUT_INVALID",
                "revocation type/id pairs must be unique strings",
            )
        identities.add(identity)
        _canonical_utc(entry.get("effectiveAt"), "revocation.effectiveAt")
        normalized.append(dict(entry))
    return sorted(
        normalized,
        key=lambda item: (
            item["type"],
            item["id"],
            item["effectiveAt"],
            item["reasonCode"],
        ),
    )


def build_signed_revocations(
    *,
    trust_root: dict[str, Any],
    expected_trust_root_sha256: str,
    release_input: dict[str, Any],
    revocation_set_id: str,
    issued_at: str,
    next_update: str,
    signer: EnvelopeSigner,
) -> dict[str, Any]:
    _schema(trust_root, TRUST_ROOT_SCHEMA, "trust root")
    if (
        trust_root.get("requiredProviderFamilies")
        != EXPECTED_ROOT_PROVIDER_FAMILIES
        or trust_root.get("minimumProviderFamilies") != 1
        or trust_root.get("minimumDirectProviderRoutes") != 1
    ):
        reject(
            "REVOCATION_RELEASE_AUTHORITY_INVALID",
            "trust root is not the exact Codex-only authority",
        )
    if (
        not isinstance(expected_trust_root_sha256, str)
        or sha256_digest(trust_root) != expected_trust_root_sha256
    ):
        reject(
            "REVOCATION_RELEASE_ROOT_PIN_MISMATCH",
            "trust root differs from the independently supplied pin",
        )
    try:
        parsed_id = UUID(revocation_set_id)
    except (ValueError, AttributeError):
        reject("REVOCATION_RELEASE_ID_INVALID", "revocation set ID is not a UUID")
    if str(parsed_id) != revocation_set_id:
        reject("REVOCATION_RELEASE_ID_INVALID", "revocation set ID is not canonical")

    issued = _canonical_utc(issued_at, "revocations.issuedAt")
    next_time = _canonical_utc(next_update, "revocations.nextUpdate")
    if not timedelta(0) < next_time - issued <= MAX_REVOCATION_LIFETIME:
        reject(
            "REVOCATION_RELEASE_LIFETIME_INVALID",
            "signed revocations must refresh within 60 minutes",
        )
    root_start = _canonical_utc(trust_root["issuedAt"], "trustRoot.issuedAt")
    root_end = _canonical_utc(trust_root["expiresAt"], "trustRoot.expiresAt")
    if issued < root_start or next_time > root_end:
        reject(
            "REVOCATION_RELEASE_LIFETIME_INVALID",
            "revocation set falls outside trust-root validity",
        )

    revocation_keys = [
        item for item in trust_root["keys"] if item.get("role") == "revocation"
    ]
    if len(revocation_keys) != 1 or signer.key_id != revocation_keys[0].get("keyId"):
        reject(
            "REVOCATION_RELEASE_SIGNER_INVALID",
            "signer is not the sole pinned revocation authority",
        )
    key = revocation_keys[0]
    key_start = _canonical_utc(key["notBefore"], "revocationKey.notBefore")
    key_end = _canonical_utc(key["notAfter"], "revocationKey.notAfter")
    if issued < key_start or next_time > key_end:
        reject(
            "REVOCATION_RELEASE_SIGNER_INVALID",
            "revocation signer is not valid for the release interval",
        )

    payload = {
        "schemaVersion": "acik.cross-ai-deployment-revocations.v1",
        "revocationSetId": revocation_set_id,
        "issuedAt": issued_at,
        "nextUpdate": next_update,
        "entries": _entries(release_input),
    }
    _schema(payload, REVOCATIONS_SCHEMA, "revocation payload")
    envelope = signer.sign_json_envelope(
        payload_type=REVOCATIONS_PAYLOAD_TYPE,
        payload=payload,
    )
    verified = verify_json_envelope(
        envelope,
        expected_payload_type=REVOCATIONS_PAYLOAD_TYPE,
        allowed_keys={
            signer.key_id: decode_public_key(key["publicKeyBase64"], signer.key_id)
        },
        required_key_ids={signer.key_id},
        exactly_one_signature=True,
    )
    if verified.payload != payload:
        reject(
            "REVOCATION_RELEASE_SIGNATURE_INVALID",
            "signed revocation payload differs after verification",
        )
    return envelope


def _write_exclusive(path: Path, payload: bytes) -> None:
    target = path.expanduser().absolute()
    target.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(target, flags, 0o600)
    except OSError:
        reject(
            "REVOCATION_RELEASE_OUTPUT_INVALID",
            "revocation output must be a new regular file",
        )
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Issue fixed signed public direct-Codex revocations"
    )
    parser.add_argument("--trust-root", type=Path, required=True)
    parser.add_argument("--expected-trust-root-sha256", required=True)
    parser.add_argument("--entries", type=Path, required=True)
    parser.add_argument("--revocation-set-id", required=True)
    parser.add_argument("--issued-at", required=True)
    parser.add_argument("--next-update", required=True)
    parser.add_argument("--vault-origin", required=True)
    parser.add_argument("--vault-token-file", type=Path, required=True)
    parser.add_argument("--vault-key-version", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        signer = VaultTransitSigner(
            vault_origin=args.vault_origin,
            token_file=args.vault_token_file,
            mount="cross-ai",
            key_name="revocation",
            key_version=args.vault_key_version,
        )
        envelope = build_signed_revocations(
            trust_root=load_json_file(args.trust_root),
            expected_trust_root_sha256=args.expected_trust_root_sha256,
            release_input=load_json_file(args.entries),
            revocation_set_id=args.revocation_set_id,
            issued_at=args.issued_at,
            next_update=args.next_update,
            signer=signer,
        )
        payload = canonical_bytes(envelope)
        _write_exclusive(args.out, payload)
    except (PolicyError, ValueError) as exc:
        message = exc.message if isinstance(exc, PolicyError) else str(exc)
        print(f"revocation_release_error={message}", file=sys.stderr)
        return 2
    print(f"revocations_sha256={sha256_digest(envelope)}")
    print(f"revocations={args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
