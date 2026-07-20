#!/usr/bin/env python3
"""Owner-gated TEST Vault bootstrap for the Faz 24 activation permit key."""

from __future__ import annotations

import argparse
import base64
import binascii
import datetime as dt
import hashlib
import json
import os
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = (
    ROOT
    / "bootstrap/vault-policies/test/faz24-transcript-ready-permit-signer.hcl"
)
MOUNT = "meeting-ai"
KEY_NAME = "transcript-ready-permit"
POLICY_NAME = "faz24-transcript-ready-permit-signer-test"
RECEIPT_SCHEMA = "faz24.transcriptReadyPermitTransitReceipt.v1"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
SIGNER_TTL_SECONDS = 1800
SIGNER_TOKEN_USES = 1
EXPECTED_POLICY = b'''# TEST-only Faz 24 transcript-ready pre-enable permit signer.
#
# This token can sign with one dedicated non-exportable Ed25519 Transit key. It
# cannot read/export/delete/rotate keys, mint tokens, access KV, or use the
# cross-ai signing domain.

path "meeting-ai/sign/transcript-ready-permit" {
  capabilities = ["update"]
}

path "auth/token/lookup-self" {
  capabilities = ["read"]
}

path "auth/token/revoke-self" {
  capabilities = ["update"]
}
'''


class BootstrapError(RuntimeError):
    pass


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BootstrapError(f"Vault response contains duplicate key: {key}")
        result[key] = value
    return result


def _reject_json_scalar(value: str) -> None:
    raise BootstrapError(f"Vault response scalar is forbidden: {value}")


def json_object(raw: bytes, label: str) -> dict[str, Any]:
    if not raw or len(raw) > MAX_RESPONSE_BYTES or b"\x00" in raw:
        raise BootstrapError(f"{label} response byte contract is invalid")
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_unique_object,
            parse_float=_reject_json_scalar,
            parse_constant=_reject_json_scalar,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BootstrapError(f"{label} response is not strict JSON") from exc
    if not isinstance(value, dict):
        raise BootstrapError(f"{label} response root must be an object")
    return value


def secure_token(path: Path, label: str) -> str:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise BootstrapError(f"{label} is unavailable") from exc
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) & 0o077
            or not 20 <= metadata.st_size <= 4096
        ):
            raise BootstrapError(f"{label} must be an owner-only regular file")
        raw = os.read(descriptor, 4097)
    finally:
        os.close(descriptor)
    if len(raw) > 4096 or b"\x00" in raw:
        raise BootstrapError(f"{label} content is invalid")
    token = raw.rstrip(b"\r\n")
    if not token or any(byte in b" \t\r\n" for byte in token):
        raise BootstrapError(f"{label} must contain one token")
    try:
        return token.decode("ascii")
    except UnicodeDecodeError as exc:
        raise BootstrapError(f"{label} must be ASCII") from exc


def canonical_https_origin(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise BootstrapError("Vault origin must be canonical HTTPS")
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    return f"https://{host}{f':{parsed.port}' if parsed.port else ''}"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


@dataclass(frozen=True)
class VaultResponse:
    status: int
    payload: dict[str, Any] | None


class VaultClient:
    def __init__(self, *, origin: str, token: str) -> None:
        self.origin = origin
        self._token = token
        self._opener = urllib.request.build_opener(NoRedirect())

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        expected: frozenset[int] = frozenset({200, 204}),
    ) -> VaultResponse:
        body = canonical_json(payload) if payload is not None else None
        request = urllib.request.Request(
            f"{self.origin}/v1/{path}",
            data=body,
            method=method,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-Vault-Token": self._token,
                "User-Agent": "acik-faz24-permit-bootstrap/1",
            },
        )
        try:
            response = self._opener.open(request, timeout=15)
            status = response.status
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            status = exc.code
            raw = exc.read(MAX_RESPONSE_BYTES + 1)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise BootstrapError("Vault request failed") from exc
        if status not in expected:
            raise BootstrapError(f"Vault rejected {method} {path} with HTTP {status}")
        if len(raw) > MAX_RESPONSE_BYTES:
            raise BootstrapError("Vault response is too large")
        return VaultResponse(status, json_object(raw, path) if raw else None)


def response_data(response: VaultResponse, label: str) -> dict[str, Any]:
    if response.payload is None or not isinstance(response.payload.get("data"), dict):
        raise BootstrapError(f"{label} response data is missing")
    return response.payload["data"]


def public_key_record(
    *,
    data: dict[str, Any],
    vault_origin: str,
    cluster_id: str,
    verified_at: dt.datetime,
) -> dict[str, Any]:
    if (
        data.get("type") != "ed25519"
        or data.get("derived") is not False
        or data.get("exportable") is not False
        or data.get("allow_plaintext_backup") is not False
        or data.get("deletion_allowed") is not False
        or data.get("supports_signing") is not True
    ):
        raise BootstrapError("Transit key immutable safety properties are invalid")
    version = data.get("latest_version")
    keys = data.get("keys")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise BootstrapError("Transit key version is invalid")
    if not isinstance(keys, dict) or set(keys) != {
        str(item) for item in range(1, version + 1)
    }:
        raise BootstrapError("Transit public-key history is incomplete")
    version_data = keys.get(str(version))
    public_value = (
        version_data.get("public_key") if isinstance(version_data, dict) else None
    )
    if not isinstance(public_value, str):
        raise BootstrapError("Transit public key is missing")
    try:
        public = base64.b64decode(public_value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise BootstrapError("Transit public key is invalid") from exc
    if (
        len(public) != 32
        or base64.b64encode(public).decode("ascii") != public_value
    ):
        raise BootstrapError("Transit public key is not raw Ed25519")
    return {
        "schemaVersion": RECEIPT_SCHEMA,
        "scope": "test-only",
        "vaultOrigin": vault_origin,
        "vaultClusterId": cluster_id,
        "mount": MOUNT,
        "keyName": KEY_NAME,
        "keyVersion": version,
        "keyId": f"vault-transit://{MOUNT}/{KEY_NAME}#v{version}",
        "publicKeyBase64": public_value,
        "keyType": "ed25519",
        "derived": False,
        "exportable": False,
        "allowPlaintextBackup": False,
        "deletionAllowed": False,
        "supportsSigning": True,
        "verifiedAt": verified_at.replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "requiresOutOfBandOwnerPin": True,
    }


def write_exclusive(path: Path, payload: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    parent_metadata = path.parent.stat()
    if (
        not stat.S_ISDIR(parent_metadata.st_mode)
        or parent_metadata.st_uid != os.getuid()
        or stat.S_IMODE(parent_metadata.st_mode) & 0o022
    ):
        raise BootstrapError("bootstrap output directory must be owner controlled")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, mode)
    except OSError as exc:
        raise BootstrapError("bootstrap output must be a new file") from exc
    try:
        os.fchmod(descriptor, mode)
        written = 0
        while written < len(payload):
            count = os.write(descriptor, payload[written:])
            if count <= 0:
                raise BootstrapError("bootstrap output write was incomplete")
            written += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def unlink_if_created(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise BootstrapError("failed to remove partial bootstrap output") from exc


def bootstrap(
    *,
    client: VaultClient,
    vault_origin: str,
    expected_cluster_id: str,
    signer_token_out: Path,
    receipt_out: Path,
    now: dt.datetime,
) -> dict[str, Any]:
    health = client.request(
        "GET", "sys/health", expected=frozenset({200, 429, 472, 473})
    ).payload
    if (
        not isinstance(health, dict)
        or health.get("initialized") is not True
        or health.get("sealed") is not False
        or health.get("standby") is not False
        or health.get("cluster_id") != expected_cluster_id
    ):
        raise BootstrapError("Vault health or explicit TEST cluster identity is invalid")
    token_data = response_data(
        client.request("GET", "auth/token/lookup-self"), "root token lookup"
    )
    if not isinstance(token_data.get("policies"), list) or "root" not in token_data[
        "policies"
    ]:
        raise BootstrapError("bootstrap requires an owner root token")

    mounts = response_data(client.request("GET", "sys/mounts"), "mount listing")
    mount = mounts.get(f"{MOUNT}/")
    if mount is None:
        client.request(
            "POST",
            f"sys/mounts/{MOUNT}",
            {
                "type": "transit",
                "description": "Faz 24 TEST transcript-ready activation permits",
                "config": {"default_lease_ttl": "0s", "max_lease_ttl": "0s"},
            },
        )
    elif not isinstance(mount, dict) or mount.get("type") != "transit":
        raise BootstrapError("dedicated mount exists with a non-Transit type")

    current = client.request(
        "GET", f"{MOUNT}/keys/{KEY_NAME}", expected=frozenset({200, 404})
    )
    if current.status == 404:
        client.request(
            "POST",
            f"{MOUNT}/keys/{KEY_NAME}",
            {
                "type": "ed25519",
                "derived": False,
                "exportable": False,
                "allow_plaintext_backup": False,
            },
        )
    key_data = response_data(
        client.request("GET", f"{MOUNT}/keys/{KEY_NAME}"), "Transit key"
    )

    receipt = public_key_record(
        data=key_data,
        vault_origin=vault_origin,
        cluster_id=expected_cluster_id,
        verified_at=now,
    )

    try:
        policy_bytes = POLICY_PATH.read_bytes()
    except OSError as exc:
        raise BootstrapError("git-reviewed signer policy is unavailable") from exc
    if policy_bytes != EXPECTED_POLICY:
        raise BootstrapError("git-reviewed signer policy differs from the bootstrap contract")
    policy_text = policy_bytes.decode("utf-8")
    existing_policy = client.request(
        "GET", f"sys/policies/acl/{POLICY_NAME}", expected=frozenset({200, 404})
    )
    existing_rules = None
    if existing_policy.status == 200:
        policy_data = response_data(existing_policy, "signer policy")
        existing_rules = policy_data.get("policy") or policy_data.get("rules")
    if not isinstance(existing_rules, str) or existing_rules.strip() != policy_text.strip():
        client.request(
            "PUT", f"sys/policies/acl/{POLICY_NAME}", {"policy": policy_text}
        )
    verified_policy = response_data(
        client.request("GET", f"sys/policies/acl/{POLICY_NAME}"),
        "signer policy readback",
    )
    verified_rules = verified_policy.get("policy") or verified_policy.get("rules")
    if not isinstance(verified_rules, str) or verified_rules.strip() != policy_text.strip():
        raise BootstrapError("signer policy readback differs from git-reviewed bytes")

    token_response = client.request(
        "POST",
        "auth/token/create",
        {
            "policies": [POLICY_NAME],
            "ttl": f"{SIGNER_TTL_SECONDS}s",
            "explicit_max_ttl": f"{SIGNER_TTL_SECONDS}s",
            "renewable": False,
            "num_uses": SIGNER_TOKEN_USES,
            "no_default_policy": True,
        },
    ).payload
    auth = token_response.get("auth") if isinstance(token_response, dict) else None
    token = auth.get("client_token") if isinstance(auth, dict) else None
    accessor = auth.get("accessor") if isinstance(auth, dict) else None
    policies = auth.get("token_policies") if isinstance(auth, dict) else None
    lease_duration = auth.get("lease_duration") if isinstance(auth, dict) else None
    accessor_valid = (
        isinstance(accessor, str)
        and 20 <= len(accessor) <= 4096
        and accessor.isascii()
        and not any(character.isspace() for character in accessor)
    )
    if (
        not isinstance(token, str)
        or not 20 <= len(token) <= 4096
        or not token.isascii()
        or any(character.isspace() for character in token)
        or not accessor_valid
        or policies != [POLICY_NAME]
        or lease_duration != SIGNER_TTL_SECONDS
        or auth.get("renewable") is not False
    ):
        if accessor_valid:
            client.request(
                "POST", "auth/token/revoke-accessor", {"accessor": accessor}
            )
        raise BootstrapError("Vault returned an invalid narrow signer token")
    receipt_created = False
    signer_token_created = False
    try:
        lookup = response_data(
            client.request(
                "POST", "auth/token/lookup-accessor", {"accessor": accessor}
            ),
            "signer token lookup",
        )
        ttl = lookup.get("ttl")
        if (
            lookup.get("policies") != [POLICY_NAME]
            or lookup.get("renewable") is not False
            or lookup.get("num_uses") != SIGNER_TOKEN_USES
            or isinstance(ttl, bool)
            or not isinstance(ttl, int)
            or not 0 < ttl <= SIGNER_TTL_SECONDS
        ):
            raise BootstrapError("signer token readback differs from requested bounds")
        write_exclusive(receipt_out, canonical_json(receipt), 0o600)
        receipt_created = True
        write_exclusive(signer_token_out, token.encode("ascii"), 0o600)
        signer_token_created = True
    except (BootstrapError, OSError):
        if signer_token_created:
            unlink_if_created(signer_token_out)
        if receipt_created:
            unlink_if_created(receipt_out)
        client.request("POST", "auth/token/revoke-accessor", {"accessor": accessor})
        raise
    return receipt


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault-origin", required=True)
    parser.add_argument("--root-token-file", required=True, type=Path)
    parser.add_argument("--expected-cluster-id", required=True)
    parser.add_argument("--signer-token-out", required=True, type=Path)
    parser.add_argument("--receipt-out", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        origin = canonical_https_origin(args.vault_origin)
        root_token = secure_token(args.root_token_file, "root token file")
        receipt = bootstrap(
            client=VaultClient(origin=origin, token=root_token),
            vault_origin=origin,
            expected_cluster_id=args.expected_cluster_id,
            signer_token_out=args.signer_token_out,
            receipt_out=args.receipt_out,
            now=dt.datetime.now(dt.timezone.utc),
        )
    except BootstrapError as exc:
        print(f"bootstrap rejected: {exc}", file=sys.stderr)
        return 2
    receipt_bytes = canonical_json(receipt)
    print(f"key_id={receipt['keyId']}")
    print(f"receipt_sha256={hashlib.sha256(receipt_bytes).hexdigest()}")
    print(f"signer_token_ttl_seconds={SIGNER_TTL_SECONDS}")
    print(f"signer_token_num_uses={SIGNER_TOKEN_USES}")
    print("requires_out_of_band_owner_pin=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
