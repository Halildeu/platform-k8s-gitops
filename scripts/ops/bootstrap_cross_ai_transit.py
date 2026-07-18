#!/usr/bin/env python3
"""Owner-gated, TEST-only Vault Transit bootstrap for ADR-0045.

The root token is read from an owner-only regular file. It is never accepted in
argv or the environment and is never written to logs or the public receipt.
The operation is deliberately narrow: one named Transit mount, six fixed
non-exportable Ed25519 keys, and the git-reviewed config-reconciler policy.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MOUNT = "cross-ai"
KEY_NAMES = (
    "anthropic",
    "minimax",
    "openai",
    "coordinator",
    "revocation",
    "runner-management",
)
RECONCILER_POLICY_NAME = "vault-config-reconciler"


class BootstrapError(RuntimeError):
    pass


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _duplicate_reject(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise BootstrapError("Vault response contains a duplicate JSON key")
        result[key] = value
    return result


def _json_object(raw: bytes, label: str) -> dict[str, Any]:
    if not raw or len(raw) > MAX_RESPONSE_BYTES:
        raise BootstrapError(f"{label} response size is invalid")
    try:
        value = json.loads(raw, object_pairs_hook=_duplicate_reject)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BootstrapError(f"{label} response is not valid JSON") from exc
    if not isinstance(value, dict):
        raise BootstrapError(f"{label} response is not a JSON object")
    return value


def _secure_token_file(path: Path) -> str:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise BootstrapError("root token file is unavailable") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise BootstrapError("root token input must be a regular file")
        if metadata.st_uid != os.getuid():
            raise BootstrapError("root token file must be owned by the current user")
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            raise BootstrapError("root token file must not be group/world accessible")
        if not 20 <= metadata.st_size <= 4096:
            raise BootstrapError("root token file size is invalid")
        raw = os.read(descriptor, 4097)
    finally:
        os.close(descriptor)
    if len(raw) > 4096 or b"\x00" in raw:
        raise BootstrapError("root token file content is invalid")
    token_bytes = raw.rstrip(b"\r\n")
    if not token_bytes or any(byte in b" \t\r\n" for byte in token_bytes):
        raise BootstrapError("root token must be one ASCII token")
    try:
        return token_bytes.decode("ascii")
    except UnicodeDecodeError as exc:
        raise BootstrapError("root token must be ASCII") from exc


def _validated_origin(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    loopback_http = parsed.scheme == "http" and parsed.hostname in {
        "127.0.0.1",
        "localhost",
        "::1",
    }
    if (
        (parsed.scheme != "https" and not loopback_http)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.hostname is None
    ):
        raise BootstrapError("Vault address must be HTTPS or loopback HTTP")
    port = parsed.port
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    return f"{parsed.scheme}://{host}{f':{port}' if port else ''}"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
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
        self._opener = urllib.request.build_opener(_NoRedirect())

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        expected: frozenset[int] = frozenset({200, 204}),
    ) -> VaultResponse:
        body = _canonical_bytes(payload) if payload is not None else None
        request = urllib.request.Request(
            f"{self.origin}/v1/{path}",
            data=body,
            method=method,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-Vault-Token": self._token,
                "User-Agent": "acik-cross-ai-transit-bootstrap/1",
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
        parsed = _json_object(raw, path) if raw else None
        return VaultResponse(status=status, payload=parsed)


def _data(response: VaultResponse, label: str) -> dict[str, Any]:
    if response.payload is None or not isinstance(response.payload.get("data"), dict):
        raise BootstrapError(f"{label} response data is missing")
    return response.payload["data"]


def _public_key_record(key_name: str, data: dict[str, Any]) -> dict[str, Any]:
    required_false = (
        "derived",
        "exportable",
        "allow_plaintext_backup",
        "deletion_allowed",
    )
    if data.get("type") != "ed25519" or any(
        data.get(field) is not False for field in required_false
    ):
        raise BootstrapError(f"Transit key {key_name} has unsafe immutable settings")
    if data.get("supports_signing") is not True:
        raise BootstrapError(f"Transit key {key_name} does not support signing")
    version = data.get("latest_version")
    keys = data.get("keys")
    if not isinstance(version, int) or version < 1 or not isinstance(keys, dict):
        raise BootstrapError(f"Transit key {key_name} version data is invalid")
    version_data = keys.get(str(version))
    if not isinstance(version_data, dict):
        raise BootstrapError(f"Transit key {key_name} public version is missing")
    public_key = version_data.get("public_key")
    if not isinstance(public_key, str):
        raise BootstrapError(f"Transit key {key_name} public key is missing")
    try:
        decoded = base64.b64decode(public_key, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise BootstrapError(f"Transit key {key_name} public key is invalid") from exc
    if len(decoded) != 32:
        raise BootstrapError(f"Transit key {key_name} is not an Ed25519 public key")
    return {
        "keyId": f"vault-transit://{MOUNT}/{key_name}#v{version}",
        "keyName": key_name,
        "keyVersion": version,
        "publicKeyBase64": public_key,
    }


def _write_exclusive(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise BootstrapError("receipt output must be a new secure file") from exc
    try:
        os.write(descriptor, payload.encode("utf-8"))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def bootstrap(args: argparse.Namespace) -> dict[str, Any]:
    origin = _validated_origin(args.vault_addr)
    token = _secure_token_file(args.root_token_file)
    client = VaultClient(origin=origin, token=token)

    health = client.request(
        "GET", "sys/health", expected=frozenset({200, 429, 472, 473})
    ).payload
    if health is None:
        raise BootstrapError("Vault health response is missing")
    if health.get("initialized") is not True or health.get("sealed") is not False:
        raise BootstrapError("Vault must be initialized and unsealed")
    if health.get("standby") is not False:
        raise BootstrapError("bootstrap must target the active Vault node")
    if health.get("cluster_id") != args.expected_cluster_id:
        raise BootstrapError("Vault cluster ID does not match the explicit TEST target")

    token_data = _data(client.request("GET", "auth/token/lookup-self"), "token lookup")
    policies = token_data.get("policies")
    if not isinstance(policies, list) or "root" not in policies:
        raise BootstrapError("owner bootstrap requires a Vault root token")

    auth_mounts = _data(client.request("GET", "sys/auth"), "auth mounts")
    approle = auth_mounts.get("approle/")
    if not isinstance(approle, dict) or approle.get("type") != "approle":
        raise BootstrapError("existing AppRole auth mount is required")

    created: list[str] = []
    updated: list[str] = []
    mounts = _data(client.request("GET", "sys/mounts"), "secret mounts")
    mount = mounts.get(f"{MOUNT}/")
    if mount is None:
        client.request(
            "POST",
            f"sys/mounts/{MOUNT}",
            {
                "type": "transit",
                "description": "ADR-0045 TEST-only signed deployment evidence",
                "config": {"default_lease_ttl": "0s", "max_lease_ttl": "0s"},
            },
        )
        created.append(f"mount:{MOUNT}")
    elif not isinstance(mount, dict) or mount.get("type") != "transit":
        raise BootstrapError("cross-ai mount exists with a non-Transit type")

    key_records: list[dict[str, Any]] = []
    for key_name in KEY_NAMES:
        current = client.request(
            "GET", f"{MOUNT}/keys/{key_name}", expected=frozenset({200, 404})
        )
        if current.status == 404:
            client.request(
                "POST",
                f"{MOUNT}/keys/{key_name}",
                {
                    "type": "ed25519",
                    "derived": False,
                    "exportable": False,
                    "allow_plaintext_backup": False,
                },
            )
            created.append(f"key:{key_name}")
        key_data = _data(client.request("GET", f"{MOUNT}/keys/{key_name}"), key_name)
        key_records.append(_public_key_record(key_name, key_data))

    policy_path = args.reconciler_policy.resolve()
    try:
        policy_bytes = policy_path.read_bytes()
    except OSError as exc:
        raise BootstrapError("git-reviewed reconciler policy is unavailable") from exc
    if not policy_bytes or len(policy_bytes) > 512 * 1024 or b"\x00" in policy_bytes:
        raise BootstrapError("git-reviewed reconciler policy content is invalid")
    try:
        policy_text = policy_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BootstrapError("git-reviewed reconciler policy must be UTF-8") from exc
    existing_policy = client.request(
        "GET",
        f"sys/policies/acl/{RECONCILER_POLICY_NAME}",
        expected=frozenset({200, 404}),
    )
    existing_rules = None
    if existing_policy.status == 200:
        existing_data = _data(existing_policy, "reconciler policy")
        existing_rules = existing_data.get("policy") or existing_data.get("rules")
    if (
        not isinstance(existing_rules, str)
        or existing_rules.strip() != policy_text.strip()
    ):
        client.request(
            "PUT",
            f"sys/policies/acl/{RECONCILER_POLICY_NAME}",
            {"policy": policy_text},
        )
        updated.append(f"policy:{RECONCILER_POLICY_NAME}")
    verified_policy = _data(
        client.request("GET", f"sys/policies/acl/{RECONCILER_POLICY_NAME}"),
        "reconciler policy readback",
    )
    verified_rules = verified_policy.get("policy") or verified_policy.get("rules")
    if (
        not isinstance(verified_rules, str)
        or verified_rules.strip() != policy_text.strip()
    ):
        raise BootstrapError(
            "reconciler policy readback differs from git-reviewed content"
        )

    receipt = {
        "schemaVersion": "acik.cross-ai-transit-bootstrap-receipt.v1",
        "scope": "test-only",
        "vaultOrigin": origin,
        "vaultClusterId": args.expected_cluster_id,
        "vaultClusterName": health.get("cluster_name"),
        "mount": MOUNT,
        "keys": key_records,
        "reconcilerPolicyName": RECONCILER_POLICY_NAME,
        "reconcilerPolicySha256": f"sha256:{hashlib.sha256(policy_bytes).hexdigest()}",
        "createdResources": sorted(created),
        "updatedResources": sorted(updated),
        "verifiedAt": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "requiresOutOfBandOwnerPin": True,
    }
    return receipt


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Owner-gated TEST Vault Transit bootstrap for ADR-0045"
    )
    parser.add_argument("--vault-addr", required=True)
    parser.add_argument("--root-token-file", type=Path, required=True)
    parser.add_argument("--expected-cluster-id", required=True)
    parser.add_argument("--reconciler-policy", type=Path, required=True)
    parser.add_argument("--receipt-out", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        receipt = bootstrap(args)
        _write_exclusive(args.receipt_out, receipt)
    except BootstrapError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    digest = f"sha256:{hashlib.sha256(_canonical_bytes(receipt)).hexdigest()}"
    print(f"bootstrap_receipt_sha256={digest}")
    print(f"receipt={args.receipt_out}")
    print("live_enforcement_enabled=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
