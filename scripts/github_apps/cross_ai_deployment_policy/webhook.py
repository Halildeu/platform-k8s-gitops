"""GitHub deployment-protection webhook authentication and bounded parsing."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping
from urllib.parse import unquote, urlsplit

from .canonical import canonical_bytes
from .errors import reject


MAX_WEBHOOK_BYTES = 1024 * 1024
WEBHOOK_HEADER_NAMES = frozenset(
    {
        "content-type",
        "x-github-event",
        "x-github-delivery",
        "x-hub-signature-256",
    }
)
SIGNATURE = re.compile(r"^sha256=([a-f0-9]{64})$")
DELIVERY_ID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
HEAD_SHA = re.compile(r"^[a-f0-9]{40}$")
INTENT_REF = re.compile(
    r"^refs/tags/cross-ai-intent/([0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12})$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DeploymentProtectionRequest:
    delivery_id: str
    repository_id: int
    repository: str
    installation_id: int
    environment: str
    head_sha: str
    intent_ref: str
    request_id: str
    run_id: int
    callback_url: str
    sender_id: int
    payload_sha256: str
    provenance: str = "github_webhook_hmac_sha256_v1"


def load_secret_files(paths: Iterable[Path]) -> tuple[bytes, ...]:
    secrets: list[bytes] = []
    for path in paths:
        try:
            raw = path.read_bytes().strip()
        except OSError as exc:
            reject("WEBHOOK_SECRET_UNAVAILABLE", f"cannot read webhook secret file: {exc}")
        if len(raw) < 32 or len(raw) > 512 or b"\x00" in raw:
            reject(
                "WEBHOOK_SECRET_INVALID",
                "webhook secret must contain 32..512 non-NUL bytes",
            )
        if raw in secrets:
            reject("WEBHOOK_SECRET_DUPLICATE", "webhook secret rotation entries differ")
        secrets.append(raw)
    if not secrets:
        reject("WEBHOOK_SECRET_MISSING", "at least one webhook secret file is required")
    if len(secrets) > 2:
        reject("WEBHOOK_SECRET_COUNT", "at most two webhook secrets are accepted")
    return tuple(secrets)


def verify_webhook_signature(
    raw_body: bytes,
    signature_header: str | None,
    secrets: Iterable[bytes],
) -> None:
    if len(raw_body) > MAX_WEBHOOK_BYTES:
        reject("WEBHOOK_BODY_TOO_LARGE", "webhook body exceeds one MiB")
    match = SIGNATURE.fullmatch(signature_header or "")
    if match is None:
        reject("WEBHOOK_SIGNATURE_MISSING", "X-Hub-Signature-256 is missing or malformed")
    supplied = match.group(1)
    # Evaluate every active rotation secret; do not expose which one matched.
    matched = False
    secret_count = 0
    for secret in secrets:
        secret_count += 1
        expected = hmac.new(secret, raw_body, hashlib.sha256).hexdigest()
        matched = hmac.compare_digest(expected, supplied) or matched
    if secret_count == 0:
        reject("WEBHOOK_SECRET_MISSING", "no webhook secret is configured")
    if not matched:
        reject("WEBHOOK_SIGNATURE_INVALID", "webhook HMAC verification failed")


def _no_duplicate_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            reject("WEBHOOK_JSON_DUPLICATE_KEY", f"duplicate JSON key {key}")
        result[key] = value
    return result


def _object(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        reject("WEBHOOK_PAYLOAD_INVALID", f"{field} must be an object")
    return value


def _positive_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        reject("WEBHOOK_PAYLOAD_INVALID", f"{field} must be a positive integer")
    return value


def validate_callback_url(
    value: object,
    *,
    repository: str,
    allowed_api_origins: Iterable[str] = ("https://api.github.com",),
) -> tuple[int, str]:
    if not isinstance(value, str) or len(value) > 500:
        reject("CALLBACK_URL_INVALID", "deployment callback URL is invalid")
    parsed = urlsplit(value)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or origin not in set(allowed_api_origins)
    ):
        reject("CALLBACK_URL_INVALID", "deployment callback origin or shape is invalid")
    expected_prefix = f"/repos/{repository}/actions/runs/"
    decoded_path = unquote(parsed.path)
    if decoded_path != parsed.path or not decoded_path.startswith(expected_prefix):
        reject("CALLBACK_URL_INVALID", "deployment callback path is invalid")
    suffix = decoded_path[len(expected_prefix) :]
    parts = suffix.split("/")
    if len(parts) != 2 or parts[1] != "deployment_protection_rule":
        reject("CALLBACK_URL_INVALID", "deployment callback path is invalid")
    try:
        run_id = int(parts[0])
    except ValueError:
        reject("CALLBACK_URL_INVALID", "deployment callback run ID is invalid")
    if run_id < 1:
        reject("CALLBACK_URL_INVALID", "deployment callback run ID is invalid")
    reconstructed = f"{origin}{expected_prefix}{run_id}/deployment_protection_rule"
    if reconstructed != value:
        reject("CALLBACK_URL_INVALID", "deployment callback URL is not canonical")
    return run_id, reconstructed


def _parse_deployment_protection_payload(
    *,
    payload: dict[str, object],
    delivery_id: str,
    provenance: str,
    allowed_api_origins: Iterable[str],
) -> DeploymentProtectionRequest:
    if payload.get("action") != "requested":
        reject("WEBHOOK_ACTION_INVALID", "deployment protection action must be requested")

    repository_object = _object(payload.get("repository"), "repository")
    repository_id = _positive_int(repository_object.get("id"), "repository.id")
    repository = repository_object.get("full_name")
    if not isinstance(repository, str) or REPOSITORY.fullmatch(repository) is None:
        reject("WEBHOOK_PAYLOAD_INVALID", "repository.full_name is invalid")
    installation = _object(payload.get("installation"), "installation")
    installation_id = _positive_int(installation.get("id"), "installation.id")
    sender = _object(payload.get("sender"), "sender")
    sender_id = _positive_int(sender.get("id"), "sender.id")
    environment = payload.get("environment")
    if (
        not isinstance(environment, str)
        or not 1 <= len(environment) <= 120
        or any(
            character
            not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-"
            for character in environment
        )
    ):
        reject("WEBHOOK_PAYLOAD_INVALID", "environment is invalid")
    head_sha = payload.get("sha")
    if not isinstance(head_sha, str) or HEAD_SHA.fullmatch(head_sha) is None:
        reject("WEBHOOK_PAYLOAD_INVALID", "sha must be a full lowercase Git SHA")
    intent_ref = payload.get("ref")
    if not isinstance(intent_ref, str):
        reject("WEBHOOK_PAYLOAD_INVALID", "ref is missing")
    ref_match = INTENT_REF.fullmatch(intent_ref)
    if ref_match is None:
        reject("INTENT_REF_INVALID", "ref is not an immutable Cross-AI intent ref")
    run_id, callback_url = validate_callback_url(
        payload.get("deployment_callback_url"),
        repository=repository,
        allowed_api_origins=allowed_api_origins,
    )
    semantic_payload = canonical_bytes(payload)
    return DeploymentProtectionRequest(
        delivery_id=delivery_id.lower(),
        repository_id=repository_id,
        repository=repository,
        installation_id=installation_id,
        environment=environment,
        head_sha=head_sha,
        intent_ref=intent_ref,
        request_id=ref_match.group(1).lower(),
        run_id=run_id,
        callback_url=callback_url,
        sender_id=sender_id,
        payload_sha256=f"sha256:{hashlib.sha256(semantic_payload).hexdigest()}",
        provenance=provenance,
    )


def parse_deployment_protection_delivery(
    *,
    payload: object,
    delivery_id: str,
    allowed_api_origins: Iterable[str] = ("https://api.github.com",),
) -> DeploymentProtectionRequest:
    """Parse App-API delivery JSON without claiming raw-body HMAC provenance."""

    if DELIVERY_ID.fullmatch(delivery_id) is None:
        reject("WEBHOOK_DELIVERY_INVALID", "GitHub delivery GUID is invalid")
    if not isinstance(payload, dict) or any(not isinstance(key, str) for key in payload):
        reject("WEBHOOK_PAYLOAD_INVALID", "delivery payload must be an object")
    return _parse_deployment_protection_payload(
        payload=payload,
        delivery_id=delivery_id,
        provenance="github_app_delivery_api_v1",
        allowed_api_origins=allowed_api_origins,
    )


def parse_deployment_protection_webhook(
    *,
    raw_body: bytes,
    headers: Mapping[str, str],
    secrets: Iterable[bytes],
    allowed_api_origins: Iterable[str] = ("https://api.github.com",),
) -> DeploymentProtectionRequest:
    normalized_headers: dict[str, str] = {}
    for raw_name, value in headers.items():
        name = raw_name.casefold()
        if name not in WEBHOOK_HEADER_NAMES:
            continue
        if name in normalized_headers:
            reject(
                "WEBHOOK_HEADER_DUPLICATE",
                f"duplicate security-relevant webhook header {name}",
            )
        normalized_headers[name] = value

    content_type = (
        normalized_headers.get("content-type", "").split(";", 1)[0].strip().lower()
    )
    if content_type != "application/json":
        reject("WEBHOOK_CONTENT_TYPE_INVALID", "Content-Type must be application/json")
    if normalized_headers.get("x-github-event") != "deployment_protection_rule":
        reject("WEBHOOK_EVENT_INVALID", "unexpected GitHub webhook event")
    delivery_id = normalized_headers.get("x-github-delivery", "")
    if DELIVERY_ID.fullmatch(delivery_id) is None:
        reject("WEBHOOK_DELIVERY_INVALID", "X-GitHub-Delivery is invalid")
    verify_webhook_signature(
        raw_body,
        normalized_headers.get("x-hub-signature-256"),
        secrets,
    )
    try:
        payload = json.loads(raw_body, object_pairs_hook=_no_duplicate_object)
    except UnicodeDecodeError:
        reject("WEBHOOK_JSON_INVALID", "webhook body is not UTF-8")
    except json.JSONDecodeError:
        reject("WEBHOOK_JSON_INVALID", "webhook body is not valid JSON")
    if not isinstance(payload, dict):
        reject("WEBHOOK_PAYLOAD_INVALID", "webhook payload must be an object")
    return _parse_deployment_protection_payload(
        payload=payload,
        delivery_id=delivery_id,
        provenance="github_webhook_hmac_sha256_v1",
        allowed_api_origins=allowed_api_origins,
    )


__all__ = [
    "DeploymentProtectionRequest",
    "MAX_WEBHOOK_BYTES",
    "load_secret_files",
    "parse_deployment_protection_delivery",
    "parse_deployment_protection_webhook",
    "validate_callback_url",
    "verify_webhook_signature",
]
