#!/usr/bin/env python3
"""Build a deterministic TEST trust root from a public Vault Transit receipt.

The input is the public v2 bootstrap receipt. The output contains no Vault
credential, token, SecretID or signing capability. This tool deliberately does
not edit deployment policy, workflow pins or Kubernetes overlays.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from jsonschema import Draft202012Validator, FormatChecker


MAX_RECEIPT_BYTES = 2 * 1024 * 1024
ROOT = Path(__file__).resolve().parents[2]
TRUST_ROOT_SCHEMA = ROOT / "schema/cross-ai-deployment-trust-root-v2.schema.json"
RECEIPT_SCHEMA_VERSION = "acik.cross-ai-transit-bootstrap-receipt.v2"
TRUST_ROOT_SCHEMA_VERSION = "acik.cross-ai-deployment-trust-root.v2"
EXPECTED_KEY_NAMES = (
    "anthropic",
    "openai",
    "coordinator",
    "revocation",
    "runner-management",
)
RECEIPT_FIELDS = frozenset(
    {
        "schemaVersion",
        "scope",
        "vaultOrigin",
        "vaultClusterId",
        "vaultClusterName",
        "mount",
        "keys",
        "reconcilerPolicyName",
        "reconcilerPolicySha256",
        "createdResources",
        "updatedResources",
        "verifiedAbsentResources",
        "verifiedAt",
        "requiresOutOfBandOwnerPin",
    }
)
KEY_FIELDS = frozenset(
    {
        "keyId",
        "keyName",
        "keyVersion",
        "publicKeyBase64",
        "keyType",
        "derived",
        "exportable",
        "allowPlaintextBackup",
        "deletionAllowed",
        "supportsSigning",
        "versionHistory",
    }
)
HISTORY_FIELDS = frozenset({"version", "publicKeyBase64"})
MIN_TRUST_ROOT_LIFETIME = timedelta(hours=168)
MAX_TRUST_ROOT_LIFETIME = timedelta(hours=720)
MAX_PROVIDER_KEY_LIFETIME = timedelta(hours=168)
MIN_PROVIDER_KEY_OVERLAP = timedelta(hours=24)


class TrustRootBuildError(RuntimeError):
    pass


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _mapping(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise TrustRootBuildError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _load_receipt(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise TrustRootBuildError("public Transit receipt is unavailable") from exc
    if not raw or len(raw) > MAX_RECEIPT_BYTES or b"\x00" in raw:
        raise TrustRootBuildError("public Transit receipt size is invalid")
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_mapping,
            parse_float=lambda _value: (_ for _ in ()).throw(
                TrustRootBuildError("floating-point JSON values are forbidden")
            ),
            parse_constant=lambda _value: (_ for _ in ()).throw(
                TrustRootBuildError("non-finite JSON values are forbidden")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TrustRootBuildError("public Transit receipt is not valid JSON") from exc
    if not isinstance(value, dict):
        raise TrustRootBuildError("public Transit receipt must be an object")
    return value


def _load_previous_trust_root(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise TrustRootBuildError("previous trust root is unavailable") from exc
    if not raw or len(raw) > MAX_RECEIPT_BYTES or b"\x00" in raw:
        raise TrustRootBuildError("previous trust-root size is invalid")
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_mapping,
            parse_float=lambda _value: (_ for _ in ()).throw(
                TrustRootBuildError("floating-point JSON values are forbidden")
            ),
            parse_constant=lambda _value: (_ for _ in ()).throw(
                TrustRootBuildError("non-finite JSON values are forbidden")
            ),
        )
        schema = json.loads(TRUST_ROOT_SCHEMA.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TrustRootBuildError("previous trust root is not valid JSON") from exc
    if not isinstance(value, dict):
        raise TrustRootBuildError("previous trust root must be an object")
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(
            value
        ),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        raise TrustRootBuildError("previous trust root fails the strict v2 schema")
    return value


def _utc(value: str, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise TrustRootBuildError(f"{label} must be canonical UTC")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise TrustRootBuildError(f"{label} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise TrustRootBuildError(f"{label} must be UTC")
    canonical = (
        parsed.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    if value != canonical:
        raise TrustRootBuildError(f"{label} must omit fractional seconds")
    return parsed


def _public_key(value: object, label: str) -> bytes:
    if not isinstance(value, str):
        raise TrustRootBuildError(f"{label} is missing")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise TrustRootBuildError(f"{label} is not canonical Base64") from exc
    if len(decoded) != 32 or base64.b64encode(decoded).decode("ascii") != value:
        raise TrustRootBuildError(f"{label} is not an Ed25519 public key")
    return decoded


def _validate_receipt(receipt: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    if set(receipt) != RECEIPT_FIELDS:
        raise TrustRootBuildError("public Transit receipt fields are not exact")
    if receipt["schemaVersion"] != RECEIPT_SCHEMA_VERSION:
        raise TrustRootBuildError("public Transit receipt version is unsupported")
    if (
        receipt["scope"] != "test-only"
        or receipt["mount"] != "cross-ai"
        or receipt["requiresOutOfBandOwnerPin"] is not True
        or receipt["reconcilerPolicyName"] != "vault-config-reconciler"
    ):
        raise TrustRootBuildError("public Transit receipt is outside the TEST trust scope")
    if receipt["verifiedAbsentResources"] != [
        "approle:cross-ai-issuer-anthropic-test",
        "policy:cross-ai-issuer-anthropic-test",
        "approle:cross-ai-issuer-minimax-test",
        "policy:cross-ai-issuer-minimax-test",
    ]:
        raise TrustRootBuildError("retired provider signing authority absence is unverified")
    for field in ("vaultOrigin", "vaultClusterId", "vaultClusterName"):
        value = receipt[field]
        if (
            not isinstance(value, str)
            or not value
            or len(value) > 512
            or any(character in value for character in "\r\n\x00")
        ):
            raise TrustRootBuildError(f"public Transit receipt {field} is invalid")
    _utc(receipt["verifiedAt"], "receipt.verifiedAt")
    for field in ("createdResources", "updatedResources"):
        values = receipt[field]
        if (
            not isinstance(values, list)
            or any(
                not isinstance(value, str)
                or not value
                or len(value) > 200
                or any(character in value for character in "\r\n\x00")
                for value in values
            )
            or values != sorted(values)
            or len(values) != len(set(values))
        ):
            raise TrustRootBuildError(f"public Transit receipt {field} is invalid")
    digest = receipt["reconcilerPolicySha256"]
    if (
        not isinstance(digest, str)
        or len(digest) != 71
        or not digest.startswith("sha256:")
    ):
        raise TrustRootBuildError("reconciler policy digest is invalid")
    try:
        bytes.fromhex(digest.removeprefix("sha256:"))
    except ValueError as exc:
        raise TrustRootBuildError("reconciler policy digest is invalid") from exc
    keys = receipt["keys"]
    if not isinstance(keys, list) or len(keys) != len(EXPECTED_KEY_NAMES):
        raise TrustRootBuildError("exactly five public Transit keys are required")

    parsed: dict[str, dict[str, Any]] = {}
    public_keys: set[bytes] = set()
    for key in keys:
        if not isinstance(key, dict) or set(key) != KEY_FIELDS:
            raise TrustRootBuildError("public Transit key fields are not exact")
        name = key["keyName"]
        if not isinstance(name, str) or name not in EXPECTED_KEY_NAMES or name in parsed:
            raise TrustRootBuildError("public Transit key name is duplicate or unknown")
        version = key["keyVersion"]
        expected_id = f"vault-transit://cross-ai/{name}#v{version}"
        if (
            not isinstance(version, int)
            or isinstance(version, bool)
            or version < 1
            or key["keyId"] != expected_id
        ):
            raise TrustRootBuildError("public Transit key identity/version is inconsistent")
        if (
            key["keyType"] != "ed25519"
            or key["derived"] is not False
            or key["exportable"] is not False
            or key["allowPlaintextBackup"] is not False
            or key["deletionAllowed"] is not False
            or key["supportsSigning"] is not True
        ):
            raise TrustRootBuildError("public Transit key settings are unsafe")
        history = key["versionHistory"]
        if not isinstance(history, list) or len(history) != version:
            raise TrustRootBuildError("public Transit key history is incomplete")
        history_keys: list[bytes] = []
        for index, item in enumerate(history, start=1):
            if (
                not isinstance(item, dict)
                or set(item) != HISTORY_FIELDS
                or item["version"] != index
            ):
                raise TrustRootBuildError("public Transit key history is not canonical")
            historical_key = _public_key(
                item["publicKeyBase64"], f"{name} history v{index}"
            )
            if historical_key in public_keys:
                raise TrustRootBuildError(
                    "one public key cannot serve two versions or trust roles"
                )
            public_keys.add(historical_key)
            history_keys.append(historical_key)
        latest = _public_key(key["publicKeyBase64"], f"{name} latest public key")
        if latest != history_keys[-1]:
            raise TrustRootBuildError("latest public key differs from version history")
        parsed[name] = key

    if set(parsed) != set(EXPECTED_KEY_NAMES):
        raise TrustRootBuildError("public Transit key set is incomplete")
    stable_source = {
        "domain": "acik.cross-ai-transit-public-keyset.v1",
        "scope": receipt["scope"],
        "vaultClusterId": receipt["vaultClusterId"],
        "mount": receipt["mount"],
        "reconcilerPolicyName": receipt["reconcilerPolicyName"],
        "reconcilerPolicySha256": receipt["reconcilerPolicySha256"],
        "verifiedAbsentResources": receipt["verifiedAbsentResources"],
        "keys": [parsed[name] for name in EXPECTED_KEY_NAMES],
    }
    source_digest = f"sha256:{hashlib.sha256(_canonical_bytes(stable_source)).hexdigest()}"
    return [parsed[name] for name in EXPECTED_KEY_NAMES], source_digest


def validate_public_bootstrap_receipt(
    receipt: dict[str, Any],
) -> tuple[list[dict[str, Any]], str]:
    """Expose the strict public receipt projection to genesis verification."""

    return _validate_receipt(receipt)


def build_trust_root(
    receipt: dict[str, Any],
    *,
    trust_root_id: str,
    issued_at: str,
    expires_at: str,
    issuer_image_digest: str,
    launcher_source_sha256: str,
    previous_trust_root: dict[str, Any] | None = None,
    max_clock_skew_seconds: int = 60,
) -> dict[str, Any]:
    keys, source_digest = _validate_receipt(receipt)
    try:
        parsed_id = UUID(trust_root_id)
    except (ValueError, AttributeError) as exc:
        raise TrustRootBuildError("trust root ID must be a canonical UUID") from exc
    if str(parsed_id) != trust_root_id:
        raise TrustRootBuildError("trust root ID must be a canonical UUID")
    start = _utc(issued_at, "issuedAt")
    end = _utc(expires_at, "expiresAt")
    lifetime = end - start
    if not MIN_TRUST_ROOT_LIFETIME <= lifetime <= MAX_TRUST_ROOT_LIFETIME:
        raise TrustRootBuildError(
            "trust root lifetime must be between 168 and 720 hours"
        )
    if (
        not isinstance(max_clock_skew_seconds, int)
        or isinstance(max_clock_skew_seconds, bool)
        or not 0 <= max_clock_skew_seconds <= 300
    ):
        raise TrustRootBuildError("clock skew must be between 0 and 300 seconds")
    for label, value in (
        ("issuer image digest", issuer_image_digest),
        ("launcher source digest", launcher_source_sha256),
    ):
        if (
            not isinstance(value, str)
            or not value.startswith("sha256:")
            or len(value) != 71
        ):
            raise TrustRootBuildError(f"{label} is invalid")
        try:
            bytes.fromhex(value.removeprefix("sha256:"))
        except ValueError as exc:
            raise TrustRootBuildError(f"{label} is invalid") from exc

    def trust_key(
        source: dict[str, Any],
        role: str,
        family: str | None,
        channel: str | None = None,
        models: list[str] | None = None,
        identity_class: str | None = None,
        *,
        key_id: str | None = None,
        public_key: str | None = None,
        not_before: datetime | None = None,
        not_after: datetime | None = None,
    ) -> dict[str, Any]:
        key_start = not_before or start
        key_end = not_after or end
        return {
            "keyId": key_id or source["keyId"],
            "role": role,
            "publicKeyBase64": public_key or source["publicKeyBase64"],
            "notBefore": key_start.astimezone(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
            "notAfter": key_end.astimezone(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
            "providerFamily": family,
            "allowedChannels": [channel] if channel else [],
            "allowedModelIds": models or [],
            "allowedModelIdentityClasses": [identity_class] if identity_class else [],
            "directProviderCli": True if family else None,
        }

    by_name = {key["keyName"]: key for key in keys}
    openai = by_name["openai"]
    current_provider_end = min(end, start + MAX_PROVIDER_KEY_LIFETIME)
    provider_entries: list[dict[str, Any]] = []
    previous_keys_by_role: dict[str, list[dict[str, Any]]] = {}
    if previous_trust_root is not None:
        if (
            previous_trust_root["trustRootId"] == trust_root_id
            or _utc(previous_trust_root["issuedAt"], "previous root issuedAt")
            >= start
            or _utc(previous_trust_root["expiresAt"], "previous root expiresAt")
            <= start
        ):
            raise TrustRootBuildError("previous trust-root boundary is invalid")
        for entry in previous_trust_root["keys"]:
            previous_keys_by_role.setdefault(entry["role"], []).append(entry)

    if previous_trust_root is None:
        if openai["keyVersion"] != 1:
            raise TrustRootBuildError(
                "OpenAI rotation requires the exact previous trust root"
            )
        provider_entries.append(
            trust_key(
                openai,
                "provider-review",
                "openai",
                "openai-codex",
                ["gpt-5.3-codex-spark", "gpt-5.6-sol"],
                "trusted-launch-attested",
                not_before=start,
                not_after=current_provider_end,
            )
        )
    else:
        previous_providers = previous_keys_by_role.get("provider-review", [])
        if not previous_providers:
            raise TrustRootBuildError("previous trust root lacks an OpenAI key")
        try:
            previous_provider = max(
                previous_providers,
                key=lambda entry: int(entry["keyId"].rsplit("#v", 1)[1]),
            )
            previous_version = int(previous_provider["keyId"].rsplit("#v", 1)[1])
        except (KeyError, ValueError, IndexError) as exc:
            raise TrustRootBuildError(
                "previous OpenAI key identity is invalid"
            ) from exc
        if openai["keyVersion"] not in {previous_version, previous_version + 1}:
            raise TrustRootBuildError("OpenAI key rotation is not consecutive")
        previous_history = openai["versionHistory"][previous_version - 1]
        if (
            previous_provider["publicKeyBase64"]
            != previous_history["publicKeyBase64"]
        ):
            raise TrustRootBuildError(
                "previous trust-root key differs from Transit history"
            )
        previous_not_before = _utc(
            previous_provider["notBefore"], "previous provider notBefore"
        )
        previous_not_after = _utc(
            previous_provider["notAfter"], "previous provider notAfter"
        )
        if (
            previous_not_before > start
            or previous_not_after < start + MIN_PROVIDER_KEY_OVERLAP
        ):
            raise TrustRootBuildError(
                "previous OpenAI key cannot provide the required 24-hour overlap"
            )
        provider_entries.append(dict(previous_provider))
        if openai["keyVersion"] == previous_version + 1:
            provider_entries.append(
                trust_key(
                    openai,
                    "provider-review",
                    "openai",
                    "openai-codex",
                    ["gpt-5.3-codex-spark", "gpt-5.6-sol"],
                    "trusted-launch-attested",
                    not_before=start,
                    not_after=current_provider_end,
                )
            )

    def management_key(name: str, role: str) -> dict[str, Any]:
        source = by_name[name]
        if previous_trust_root is None:
            return trust_key(source, role, None)
        previous_entries = previous_keys_by_role.get(role, [])
        if len(previous_entries) != 1:
            raise TrustRootBuildError(
                f"previous trust root lacks the exact {role} key"
            )
        previous_entry = previous_entries[0]
        if (
            previous_entry["keyId"] == source["keyId"]
            and previous_entry["publicKeyBase64"] == source["publicKeyBase64"]
        ):
            if _utc(previous_entry["notAfter"], f"previous {role} notAfter") < end:
                raise TrustRootBuildError(
                    f"carried {role} key does not cover the replacement root"
                )
            return dict(previous_entry)
        try:
            previous_version = int(previous_entry["keyId"].rsplit("#v", 1)[1])
        except (ValueError, IndexError) as exc:
            raise TrustRootBuildError(
                f"previous {role} key identity is invalid"
            ) from exc
        if source["keyVersion"] != previous_version + 1:
            raise TrustRootBuildError(f"{role} key rotation is not consecutive")
        previous_history = source["versionHistory"][previous_version - 1]
        if previous_entry["publicKeyBase64"] != previous_history["publicKeyBase64"]:
            raise TrustRootBuildError(
                f"previous {role} key differs from Transit history"
            )
        return trust_key(source, role, None)
    return {
        "schemaVersion": TRUST_ROOT_SCHEMA_VERSION,
        "trustRootId": trust_root_id,
        "sourcePublicKeysetSha256": source_digest,
        "issuedAt": issued_at,
        "expiresAt": expires_at,
        "maxClockSkewSeconds": max_clock_skew_seconds,
        "requiredProviderFamilies": ["openai"],
        "minimumProviderFamilies": 1,
        "minimumDirectProviderRoutes": 1,
        "providerReviewRuntimePolicy": {
            "schemaVersion": "acik.cross-ai-provider-review-runtime-policy.v1",
            "workloadIdentity": (
                "spiffe://testai.acik.com/ns/cross-ai/sa/provider-review-issuer"
            ),
            "issuerImageDigest": issuer_image_digest,
            "launcherSourceSha256": launcher_source_sha256,
            "attestorKeyId": by_name["runner-management"]["keyId"],
            "maxAttestationLifetimeSeconds": 600,
        },
        "keys": provider_entries
        + [
            management_key("coordinator", "coordinator"),
            management_key("revocation", "revocation"),
            management_key("runner-management", "runner-management"),
        ],
    }


def _write_exclusive(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise TrustRootBuildError("trust root output must be a new file") from exc
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a deterministic public TEST Cross-AI trust root"
    )
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--trust-root-id", required=True)
    parser.add_argument("--issued-at", required=True)
    parser.add_argument("--expires-at", required=True)
    parser.add_argument("--issuer-image-digest", required=True)
    parser.add_argument("--launcher-source-sha256", required=True)
    parser.add_argument("--previous-trust-root", type=Path)
    parser.add_argument("--max-clock-skew-seconds", type=int, default=60)
    parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        trust_root = build_trust_root(
            _load_receipt(args.receipt),
            trust_root_id=args.trust_root_id,
            issued_at=args.issued_at,
            expires_at=args.expires_at,
            issuer_image_digest=args.issuer_image_digest,
            launcher_source_sha256=args.launcher_source_sha256,
            previous_trust_root=(
                _load_previous_trust_root(args.previous_trust_root)
                if args.previous_trust_root is not None
                else None
            ),
            max_clock_skew_seconds=args.max_clock_skew_seconds,
        )
        payload = _canonical_bytes(trust_root)
        _write_exclusive(args.out, payload)
    except TrustRootBuildError as exc:
        print(f"trust_root_build_error={exc}", file=sys.stderr)
        return 2
    print(f"trust_root_sha256=sha256:{hashlib.sha256(payload).hexdigest()}")
    print(f"trust_root={args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
