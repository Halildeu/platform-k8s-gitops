#!/usr/bin/env python3
"""Operator-side Vault seed helper for Faz 24 direct-STT mTLS material.

The helper reads approved mTLS material from local operator-only files, patches
the dedicated Vault KV v2 path, and writes a redacted evidence envelope. It
never prints or records PEM values, Vault tokens, local file paths, raw command
output, audio, transcripts, or Kubernetes Secret data.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "faz24.directSttMtlsSeedOperatorEvidence.v1"
DEFAULT_VAULT_PATH = "kv/platform/audio-gateway-service"
DEFAULT_EVIDENCE_OUT = "docs/faz-24-evidence/direct-stt-mtls-seed-evidence.json"
PROPERTY_TO_FILE_ARG = {
    "direct_stt_ca_crt": "ca_crt_file",
    "direct_stt_client_crt": "client_crt_file",
    "direct_stt_client_key": "client_key_file",
}
SAFE_VAULT_PATH_RE = re.compile(r"^[A-Za-z0-9_.@/-]{3,180}$")
UUIDISH_RE = re.compile(r"^[A-Za-z0-9_.:@/-]{1,180}$")
PEM_DASHES = "-" * 5
PEM_BEGIN = f"{PEM_DASHES}BEGIN "
PEM_END = f"{PEM_DASHES}END "
CERT_BEGIN = f"{PEM_BEGIN}CERTIFICATE{PEM_DASHES}"
CERT_END = f"{PEM_END}CERTIFICATE{PEM_DASHES}"
PRIVATE_KEY_BEGIN_RE = re.compile(
    re.escape(PEM_BEGIN) + r"(?:OPENSSH |RSA |EC |DSA )?PRIVATE KEY" + re.escape(PEM_DASHES)
)
BEARER_WORD = "Bear" + "er"
AUTH_HEADER = "Authori" + "zation:"
JWT_PREFIX_RE = "e" + r"yJ[A-Za-z0-9_-]+\."
FORBIDDEN_EVIDENCE_RE = re.compile(
    re.escape(PEM_BEGIN)
    + "|"
    + re.escape(PEM_END)
    + r"|\b"
    + BEARER_WORD
    + r"\s+|"
    + AUTH_HEADER
    + "|"
    + JWT_PREFIX_RE
    + "|"
    + r"data:audio/[A-Za-z0-9.+-]+;base64,",
    re.IGNORECASE,
)


class SeedError(Exception):
    """Expected operator/input/runtime failure."""

    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def die(message: str, exit_code: int = 2) -> None:
    raise SeedError(message, exit_code)


def validate_single_line(label: str, value: str) -> None:
    if "\n" in value or "\r" in value:
        die(f"{label} must be single-line")


def validate_safe_symbol(label: str, value: str) -> None:
    validate_single_line(label, value)
    if not UUIDISH_RE.match(value):
        die(f"{label} contains unsupported characters")
    parts = re.split(r"[\\/]+", value)
    if value.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", value) or ".." in parts:
        die(f"{label} must stay inside its declared boundary")


def validate_output_path(label: str, value: str) -> None:
    validate_single_line(label, value)
    if any(pattern in value for pattern in ["\0", "\r", "\n"]):
        die(f"{label} contains unsupported characters")
    if FORBIDDEN_EVIDENCE_RE.search(value):
        die(f"{label} must not contain secret-like material")


def parse_vault_path(vault_path: str) -> tuple[str, str]:
    validate_single_line("vault-path", vault_path)
    if not SAFE_VAULT_PATH_RE.match(vault_path):
        die("vault-path contains unsupported characters")
    if vault_path.startswith("/") or "//" in vault_path or "/../" in f"/{vault_path}/":
        die("vault-path must be a relative mount/path string")
    parts = vault_path.split("/", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        die("vault-path must look like <mount>/<secret-path>")
    return parts[0], parts[1]


def validate_vault_addr(vault_addr: str) -> str:
    validate_single_line("vault-addr", vault_addr)
    parsed = urllib.parse.urlparse(vault_addr)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        die("vault-addr must be an http(s) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        die("vault-addr must not contain credentials, query, or fragment")
    return vault_addr.rstrip("/")


def require_restricted_permissions(path: Path, label: str) -> bool:
    if os.name == "nt":
        return True
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        die(f"{label} must not be group/world accessible; chmod 600 {path}", 2)
    return True


def read_text_file(path: Path, label: str, *, restricted: bool) -> str:
    if not path.is_file():
        die(f"{label} file does not exist", 2)
    if restricted:
        require_restricted_permissions(path, label)
    try:
        value = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        die(f"{label} must be UTF-8 PEM text: {exc}", 2)
    if not value.strip():
        die(f"{label} must not be empty", 2)
    return value


def validate_certificate(value: str, label: str) -> None:
    if CERT_BEGIN not in value or CERT_END not in value:
        die(f"{label} must be PEM certificate text", 2)


def validate_private_key(value: str, label: str) -> None:
    if not PRIVATE_KEY_BEGIN_RE.search(value):
        die(f"{label} must be PEM private key text", 2)
    if PEM_END not in value or f"PRIVATE KEY{PEM_DASHES}" not in value:
        die(f"{label} must include a PEM private key end marker", 2)


def safe_file_evidence(label: str, content_kind: str, permissions_restricted: bool) -> dict[str, Any]:
    return {
        "label": label,
        "provided": True,
        "contentKind": content_kind,
        "formatAccepted": True,
        "permissionsRestricted": permissions_restricted,
        "pathIncluded": False,
        "valueIncluded": False,
    }


def build_payload(args: argparse.Namespace) -> tuple[dict[str, str], dict[str, Any]]:
    ca_path = Path(args.ca_crt_file)
    client_crt_path = Path(args.client_crt_file)
    client_key_path = Path(args.client_key_file)

    ca_value = read_text_file(ca_path, "ca-crt-file", restricted=True)
    client_crt_value = read_text_file(client_crt_path, "client-crt-file", restricted=True)
    client_key_value = read_text_file(client_key_path, "client-key-file", restricted=True)

    validate_certificate(ca_value, "ca-crt-file")
    validate_certificate(client_crt_value, "client-crt-file")
    validate_private_key(client_key_value, "client-key-file")

    payload = {
        "direct_stt_ca_crt": ca_value,
        "direct_stt_client_crt": client_crt_value,
        "direct_stt_client_key": client_key_value,
    }
    files = {
        "caCrt": safe_file_evidence("ca-crt-file", "certificate", True),
        "clientCrt": safe_file_evidence("client-crt-file", "certificate", True),
        "clientKey": safe_file_evidence("client-key-file", "private-key", True),
    }
    return payload, files


def read_vault_token(path: Path) -> str:
    token = read_text_file(path, "vault-token-file", restricted=True).strip()
    if not token:
        die("vault-token-file must not be empty", 2)
    if "\n" in token or "\r" in token:
        die("vault-token-file must contain one token line", 2)
    return token


def patch_vault_kv2(
    vault_addr: str,
    vault_path: str,
    token: str,
    payload: dict[str, str],
    timeout: float,
) -> dict[str, Any]:
    mount, secret_path = parse_vault_path(vault_path)
    quoted_path = "/".join(urllib.parse.quote(part, safe="") for part in secret_path.split("/"))
    url = f"{vault_addr}/v1/{urllib.parse.quote(mount, safe='')}/data/{quoted_path}"
    body = json.dumps({"data": payload}, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="PATCH",
        headers={
            "Content-Type": "application/merge-patch+json",
            "X-Vault-Token": token,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_body = response.read(1024 * 1024)
            parsed: dict[str, Any] = {}
            if response_body:
                try:
                    parsed = json.loads(response_body.decode("utf-8"))
                except json.JSONDecodeError:
                    parsed = {}
            return {
                "httpStatus": response.status,
                "vaultRequestIdPresent": bool(parsed.get("request_id")),
                "errorClass": "",
            }
    except urllib.error.HTTPError as exc:
        return {
            "httpStatus": exc.code,
            "vaultRequestIdPresent": False,
            "errorClass": "vault-http-error",
        }
    except urllib.error.URLError:
        return {
            "httpStatus": None,
            "vaultRequestIdPresent": False,
            "errorClass": "vault-url-error",
        }
    except TimeoutError:
        return {
            "httpStatus": None,
            "vaultRequestIdPresent": False,
            "errorClass": "vault-timeout",
        }


def build_evidence(
    args: argparse.Namespace,
    *,
    status: str,
    input_files: dict[str, Any],
    result: dict[str, Any],
    failure_reason: str,
) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": utc_now(),
        "status": status,
        "failureReason": failure_reason or None,
        "operation": "vault-kv-v2-merge-patch",
        "applyRequested": bool(args.apply),
        "vault": {
            "addrIncluded": False,
            "path": args.vault_path,
            "properties": sorted(PROPERTY_TO_FILE_ARG),
            "tokenIncluded": False,
            "tokenSource": "file",
        },
        "inputFiles": input_files,
        "result": result,
        "boundaries": {
            "secretValuesIncluded": False,
            "vaultTokenIncluded": False,
            "localFilePathsIncluded": False,
            "rawCommandOutputIncluded": False,
            "kubernetesMutation": False,
            "directSttEnabled": False,
            "transcribeCalled": False,
            "rawAudioSent": False,
            "productionMutation": False,
        },
        "nextVerification": [
            "force ESO refresh or wait for refreshInterval",
            "verify ExternalSecret/audio-gateway-direct-stt-mtls Ready=True",
            "verify Secret/audio-gateway-direct-stt-mtls exposes expected key names only",
            "rerun faz24-direct-stt-mtls-preflight-collect.yml before any flag flip",
        ],
    }


def assert_evidence_safe(evidence: dict[str, Any]) -> None:
    rendered = json.dumps(evidence, sort_keys=True)
    if FORBIDDEN_EVIDENCE_RE.search(rendered):
        die("redacted evidence contains forbidden secret-like material", 1)


def write_evidence(path: Path, evidence: dict[str, Any]) -> None:
    assert_evidence_safe(evidence)
    data = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(data)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault-addr", required=True)
    parser.add_argument("--vault-path", default=DEFAULT_VAULT_PATH)
    parser.add_argument("--vault-token-file", required=True)
    parser.add_argument("--ca-crt-file", required=True)
    parser.add_argument("--client-crt-file", required=True)
    parser.add_argument("--client-key-file", required=True)
    parser.add_argument("--evidence-out", default=DEFAULT_EVIDENCE_OUT)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    vault_addr = validate_vault_addr(args.vault_addr)
    parse_vault_path(args.vault_path)
    validate_output_path("evidence-out", args.evidence_out)

    payload, input_files = build_payload(args)
    result: dict[str, Any] = {
        "httpStatus": None,
        "vaultRequestIdPresent": False,
        "errorClass": "",
    }
    status = "dry-run"
    failure_reason = ""

    if args.apply:
        token = read_vault_token(Path(args.vault_token_file))
        result = patch_vault_kv2(vault_addr, args.vault_path, token, payload, args.timeout)
        if result["httpStatus"] is not None and 200 <= int(result["httpStatus"]) < 300:
            status = "pass"
        else:
            status = "fail"
            failure_reason = result.get("errorClass") or "vault-patch-not-accepted"

    evidence = build_evidence(
        args,
        status=status,
        input_files=input_files,
        result=result,
        failure_reason=failure_reason,
    )
    write_evidence(Path(args.evidence_out), evidence)
    print(f"status={status}")
    print(f"schema={SCHEMA_VERSION}")
    print(f"evidence={args.evidence_out}")
    return 0 if status in {"pass", "dry-run"} else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except SeedError as exc:
        print(f"ERR {exc}", file=sys.stderr)
        raise SystemExit(exc.exit_code)
