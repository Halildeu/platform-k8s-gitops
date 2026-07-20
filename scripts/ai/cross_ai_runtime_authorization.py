"""Strict owner-only authorization for the fixed Cross-AI runtime service."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from scripts.github_apps.cross_ai_deployment_policy.canonical import canonical_bytes
from scripts.github_apps.cross_ai_deployment_policy.errors import reject
from scripts.github_apps.cross_ai_deployment_policy.jsonutil import loads_json_bytes
from scripts.github_apps.cross_ai_deployment_policy.timeutil import parse_utc, utc_now


AUTHORIZATION_SCHEMA = "acik.cross-ai-provider-review-runtime-authorization.v1"
AUTH_AUDIENCE = "acik-cross-ai-provider-review-runtime"
MAX_AUTH_BYTES = 4096
MAX_AUTH_LIFETIME = timedelta(hours=1)


@dataclass(frozen=True)
class RuntimeAuthorization:
    token: str
    expires_at: datetime

    def assert_active(self) -> None:
        if utc_now() >= self.expires_at:
            reject(
                "PROVIDER_RUNTIME_AUTH_EXPIRED",
                "runtime authorization is expired",
            )


def load_runtime_authorization(path: Path) -> RuntimeAuthorization:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        reject("PROVIDER_RUNTIME_AUTH_UNAVAILABLE", "authorization cannot be opened")
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1
            or metadata.st_mode & 0o077
            or not 1 <= metadata.st_size <= MAX_AUTH_BYTES
        ):
            reject(
                "PROVIDER_RUNTIME_AUTH_INVALID",
                "authorization must be a bounded owner-only regular file",
            )
        raw = os.read(descriptor, metadata.st_size + 1)
    except OSError:
        reject("PROVIDER_RUNTIME_AUTH_UNAVAILABLE", "authorization cannot be read")
    finally:
        os.close(descriptor)
    if len(raw) != metadata.st_size:
        reject("PROVIDER_RUNTIME_AUTH_INVALID", "authorization changed while reading")
    document = loads_json_bytes(
        raw,
        max_bytes=MAX_AUTH_BYTES,
        label="runtime authorization",
    )
    required = {"schemaVersion", "audience", "token", "issuedAt", "expiresAt"}
    token = document.get("token") if isinstance(document, dict) else None
    if (
        not isinstance(document, dict)
        or set(document) != required
        or document.get("schemaVersion") != AUTHORIZATION_SCHEMA
        or document.get("audience") != AUTH_AUDIENCE
        or not isinstance(token, str)
        or not 32 <= len(token) <= 512
        or not token.isascii()
        or any(character.isspace() for character in token)
        or canonical_bytes(document) != raw
    ):
        reject(
            "PROVIDER_RUNTIME_AUTH_INVALID",
            "runtime authorization fields are invalid",
        )
    issued_at = parse_utc(document.get("issuedAt"), "authorization.issuedAt")
    expires_at = parse_utc(document.get("expiresAt"), "authorization.expiresAt")
    now = utc_now()
    if (
        issued_at > now
        or expires_at <= now
        or expires_at <= issued_at
        or expires_at - issued_at > MAX_AUTH_LIFETIME
    ):
        reject(
            "PROVIDER_RUNTIME_AUTH_EXPIRED",
            "runtime authorization lifetime is invalid or expired",
        )
    return RuntimeAuthorization(token=token, expires_at=expires_at)


__all__ = [
    "AUTHORIZATION_SCHEMA",
    "AUTH_AUDIENCE",
    "RuntimeAuthorization",
    "load_runtime_authorization",
]
