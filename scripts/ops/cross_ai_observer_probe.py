#!/usr/bin/env python3
"""Send one bounded, signed synthetic delivery to the receive-only observer.

The webhook secret is read only from a local owner-only file. The script never
prints the secret, signature, or raw payload; its stdout is a redacted JSON
result suitable for GitHub Actions evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


MAX_RESPONSE_BYTES = 8192


class ProbeError(RuntimeError):
    """A bounded probe contract failure safe to print without secret data."""


class _NoRedirect(HTTPRedirectHandler):
    """Keep the validated destination authoritative across the request."""

    def redirect_request(  # type: ignore[override]
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


@dataclass(frozen=True)
class ProbeConfig:
    url: str
    repository_id: int
    repository: str
    installation_id: int
    sender_id: int
    environment: str
    head_sha: str
    run_id: int


def _validate_target(url: str) -> None:
    parsed = urlsplit(url)
    loopback_http = parsed.scheme == "http" and parsed.hostname in {
        "127.0.0.1",
        "::1",
        "localhost",
    }
    if (
        (parsed.scheme != "https" and not loopback_http)
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ProbeError("probe URL must be HTTPS (or loopback HTTP for tests)")


def _read_secret(path: Path) -> bytes:
    try:
        secret = path.read_bytes().strip()
    except OSError as exc:
        raise ProbeError(f"cannot read webhook secret file: {exc}") from exc
    if len(secret) < 32 or len(secret) > 512 or b"\x00" in secret:
        raise ProbeError("webhook secret file has an invalid bounded value")
    return secret


def build_payload(
    config: ProbeConfig,
    *,
    request_id: str,
) -> bytes:
    try:
        canonical_request_id = str(uuid.UUID(request_id))
    except ValueError as exc:
        raise ProbeError("request ID is not a canonical UUID") from exc
    if len(config.head_sha) != 40 or any(
        character not in "0123456789abcdef" for character in config.head_sha
    ):
        raise ProbeError("head SHA must be 40 lowercase hexadecimal characters")
    payload: dict[str, Any] = {
        "action": "requested",
        "environment": config.environment,
        "event": "workflow_dispatch",
        "sha": config.head_sha,
        "ref": f"refs/tags/cross-ai-intent/{canonical_request_id}",
        "deployment_callback_url": (
            f"https://api.github.com/repos/{config.repository}/actions/runs/"
            f"{config.run_id}/deployment_protection_rule"
        ),
        "deployment": {"id": config.run_id},
        "pull_requests": [],
        "repository": {
            "id": config.repository_id,
            "full_name": config.repository,
        },
        "installation": {"id": config.installation_id},
        "sender": {
            "id": config.sender_id,
            "login": "cross-ai-observer-probe[bot]",
        },
    }
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()


def _post(
    *,
    url: str,
    body: bytes,
    delivery_id: str,
    secret: bytes,
) -> tuple[int, dict[str, Any]]:
    signature = hmac.new(secret, body, hashlib.sha256).hexdigest()
    request = Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "deployment_protection_rule",
            "X-GitHub-Delivery": delivery_id,
            "X-Hub-Signature-256": f"sha256={signature}",
        },
    )
    try:
        with build_opener(_NoRedirect).open(request, timeout=10) as response:
            status = response.status
            response_body = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        status = exc.code
        response_body = exc.read(MAX_RESPONSE_BYTES + 1)
    except URLError as exc:
        raise ProbeError(f"webhook request failed: {exc.reason}") from exc
    if len(response_body) > MAX_RESPONSE_BYTES:
        raise ProbeError("webhook response exceeded the bounded response size")
    try:
        parsed = json.loads(response_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProbeError("webhook response was not bounded JSON") from exc
    if not isinstance(parsed, dict):
        raise ProbeError("webhook response was not a JSON object")
    return status, parsed


def run_probe(
    *,
    config: ProbeConfig,
    secret_file: Path,
    request_id: str | None = None,
    delivery_id: str | None = None,
) -> dict[str, Any]:
    _validate_target(config.url)
    secret = _read_secret(secret_file)
    request_id = request_id or str(uuid.uuid4())
    delivery_id = (delivery_id or str(uuid.uuid4())).lower()
    try:
        canonical_delivery_id = str(uuid.UUID(delivery_id))
    except ValueError as exc:
        raise ProbeError("delivery ID is not a canonical UUID") from exc
    body = build_payload(config, request_id=request_id)

    first_status, first = _post(
        url=config.url,
        body=body,
        delivery_id=canonical_delivery_id,
        secret=secret,
    )
    second_status, second = _post(
        url=config.url,
        body=body,
        delivery_id=canonical_delivery_id,
        secret=secret,
    )
    if (
        first_status != 202
        or first.get("accepted") is not True
        or first.get("duplicate") is not False
        or first.get("mode") != "observe"
    ):
        raise ProbeError(
            f"first delivery rejected: status={first_status} code={first.get('code')}"
        )
    if (
        second_status != 202
        or second.get("accepted") is not True
        or second.get("duplicate") is not True
        or second.get("mode") != "observe"
    ):
        raise ProbeError(
            "duplicate delivery contract failed: "
            f"status={second_status} code={second.get('code')}"
        )
    if first.get("deliveryId") != canonical_delivery_id:
        raise ProbeError("observer returned a different delivery ID")

    return {
        "accepted": True,
        "deliveryId": canonical_delivery_id,
        "requestId": str(uuid.UUID(request_id)),
        "first": {"status": first_status, "duplicate": False},
        "second": {"status": second_status, "duplicate": True},
        "mode": "observe",
        "secretBytes": len(secret),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--secret-file", required=True, type=Path)
    parser.add_argument("--repository-id", required=True, type=int)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--installation-id", required=True, type=int)
    parser.add_argument("--sender-id", required=True, type=int)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--run-id", required=True, type=int)
    return parser


def main() -> int:
    args = _parser().parse_args()
    config = ProbeConfig(
        url=args.url,
        repository_id=args.repository_id,
        repository=args.repository,
        installation_id=args.installation_id,
        sender_id=args.sender_id,
        environment=args.environment,
        head_sha=args.head_sha,
        run_id=args.run_id,
    )
    try:
        result = run_probe(config=config, secret_file=args.secret_file)
    except ProbeError as exc:
        print(f"probe failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
