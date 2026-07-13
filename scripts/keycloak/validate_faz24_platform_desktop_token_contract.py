#!/usr/bin/env python3
"""Validate the Faz 24 platform-desktop JWT claim/audience contract.

This is a preflight helper for the recorder external meeting-admin path. It
does not verify the JWT signature and never prints the token. It only decodes
the payload and reports whether the token carries the bounded claims needed by
the current testai recorder flow.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any


DEFAULT_REQUIRED_AUDIENCES = ("audio-gateway-service", "meeting-service")
# Mirrors the current test api-gateway/auth-service accepted audience contract
# recorded in GitOps config; override this when runtime config changes.
DEFAULT_GATEWAY_AUDIENCES = ("frontend", "account", "auth-service")
DEFAULT_REQUIRED_CLAIMS = (
    "sub",
    "org_id",
    "tenant_id",
    "tenantId",
    "companyId",
    "userId",
)
DEFAULT_RESOURCE_CLIENT_ID = "audio-gateway-service"
DEFAULT_REQUIRED_CLIENT_ROLES = ("audio_record",)


def _csv(value: str | None, default: tuple[str, ...]) -> list[str]:
    if value is None:
        return list(default)
    return [part.strip() for part in value.split(",") if part.strip()]


def _b64url_decode(segment: str) -> bytes:
    padding = "=" * ((4 - len(segment) % 4) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def _read_token(path: str | None) -> str:
    if path:
        token = Path(path).read_text(encoding="utf-8").strip()
    else:
        token = sys.stdin.read().strip()
    if not token:
        raise ValueError("empty token input; pass --token-file or pipe token on stdin")
    return token


def _decode_payload(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) < 2:
        raise ValueError("token is not JWT-shaped; expected at least two dot-separated segments")
    try:
        payload = json.loads(_b64url_decode(parts[1]))
    except Exception as exc:  # pragma: no cover - exact decoder error is not user-facing
        raise ValueError(f"could not decode JWT payload: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("JWT payload is not a JSON object")
    return payload


def _normalize_audience(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    return [str(value)]


def _roles(payload: dict[str, Any]) -> list[str]:
    realm_access = payload.get("realm_access")
    if not isinstance(realm_access, dict):
        return []
    roles = realm_access.get("roles")
    if not isinstance(roles, list):
        return []
    return [str(role) for role in roles if role is not None]


def _client_roles(payload: dict[str, Any], resource_client_id: str) -> list[str]:
    resource_access = payload.get("resource_access")
    if not isinstance(resource_access, dict):
        return []
    client_access = resource_access.get(resource_client_id)
    if not isinstance(client_access, dict):
        return []
    roles = client_access.get("roles")
    if not isinstance(roles, list):
        return []
    return [str(role) for role in roles if role is not None]


def _uuid_value(value: Any) -> uuid.UUID | None:
    if value in (None, ""):
        return None
    try:
        return uuid.UUID(str(value).strip())
    except (ValueError, AttributeError):
        return None


def _company_tenant_uuid(company_id: Any) -> uuid.UUID | None:
    if company_id in (None, ""):
        return None
    digest = bytearray(hashlib.md5(f"company:{str(company_id).strip()}".encode()).digest())
    digest[6] = (digest[6] & 0x0F) | 0x30
    digest[8] = (digest[8] & 0x3F) | 0x80
    return uuid.UUID(bytes=bytes(digest))


def _compat_tenant_uuid(value: Any) -> uuid.UUID | None:
    parsed = _uuid_value(value)
    if parsed is not None:
        return parsed
    text = "" if value is None else str(value).strip()
    if text and text.isascii() and text.isdigit():
        return _company_tenant_uuid(text)
    return None


def validate(
    payload: dict[str, Any],
    *,
    required_audiences: list[str],
    gateway_audiences: list[str],
    required_claims: list[str],
    resource_client_id: str,
    required_client_roles: list[str],
    required_azp: str,
    required_role: str,
    expected_issuer: str | None,
) -> dict[str, Any]:
    aud = _normalize_audience(payload.get("aud"))
    roles = _roles(payload)
    client_roles = _client_roles(payload, resource_client_id)
    failures: list[str] = []

    missing_required_audiences = [item for item in required_audiences if item not in aud]
    gateway_matches = [item for item in gateway_audiences if item in aud]
    missing_claims = [
        item
        for item in required_claims
        if item not in payload or payload.get(item) in (None, "")
    ]
    missing_client_roles = [
        item for item in required_client_roles if item not in client_roles
    ]

    tenant_aliases: dict[str, uuid.UUID] = {}
    invalid_tenant_aliases: list[str] = []
    for claim in ("org_id", "tenant_id"):
        if claim in payload and payload.get(claim) not in (None, ""):
            parsed = _uuid_value(payload.get(claim))
            if parsed is None:
                invalid_tenant_aliases.append(claim)
            else:
                tenant_aliases[claim] = parsed
    if "tenantId" in payload and payload.get("tenantId") not in (None, ""):
        parsed = _compat_tenant_uuid(payload.get("tenantId"))
        if parsed is None:
            invalid_tenant_aliases.append("tenantId")
        else:
            tenant_aliases["tenantId"] = parsed
    if "companyId" in payload and payload.get("companyId") not in (None, ""):
        parsed = _company_tenant_uuid(payload.get("companyId"))
        if parsed is None:
            invalid_tenant_aliases.append("companyId")
        else:
            tenant_aliases["companyId"] = parsed

    checked_tenant_aliases = ("org_id", "tenant_id", "tenantId", "companyId")
    missing_tenant_aliases = [
        claim
        for claim in checked_tenant_aliases
        if claim not in payload or payload.get(claim) in (None, "")
    ]
    distinct_tenants = {str(value) for value in tenant_aliases.values()}
    tenant_aliases_consistent = (
        not missing_tenant_aliases
        and not invalid_tenant_aliases
        and len(distinct_tenants) == 1
    )

    if missing_required_audiences:
        failures.append(
            "missing required service audience(s): " + ",".join(missing_required_audiences)
        )
    if not gateway_matches:
        failures.append(
            "missing api-gateway-compatible audience; expected one of "
            + ",".join(gateway_audiences)
        )
    if missing_claims:
        failures.append("missing required claim(s): " + ",".join(missing_claims))
    if invalid_tenant_aliases:
        failures.append(
            "invalid tenant claim alias(es): " + ",".join(invalid_tenant_aliases)
        )
    if len(distinct_tenants) > 1:
        failures.append("conflicting tenant claim aliases")
    if payload.get("azp") != required_azp:
        failures.append(f"azp mismatch: expected {required_azp}")
    if required_role not in roles:
        failures.append(f"missing realm role: {required_role}")
    if missing_client_roles:
        failures.append(
            "missing client role(s) for "
            + resource_client_id
            + ": "
            + ",".join(missing_client_roles)
        )
    if expected_issuer is not None and payload.get("iss") != expected_issuer:
        failures.append(f"issuer mismatch: expected {expected_issuer}")

    return {
        "schemaVersion": "faz24.platformDesktopTokenContract.v1",
        "status": "pass" if not failures else "fail",
        "tokenIncluded": False,
        "azp": payload.get("azp"),
        "issuer": payload.get("iss"),
        "audience": {
            "values": aud,
            "required": required_audiences,
            "missingRequired": missing_required_audiences,
            "gatewayAccepted": gateway_audiences,
            "gatewayMatches": gateway_matches,
            "gatewayCompatible": bool(gateway_matches),
        },
        "claims": {
            claim: claim in payload and payload.get(claim) not in (None, "")
            for claim in required_claims
        },
        "tenantAliases": {
            "checked": list(checked_tenant_aliases),
            "present": [claim for claim in tenant_aliases],
            "missing": missing_tenant_aliases,
            "invalid": invalid_tenant_aliases,
            "consistent": tenant_aliases_consistent,
            "valuesIncluded": False,
        },
        "realmRole": {
            "required": required_role,
            "present": required_role in roles,
        },
        "clientRole": {
            "resourceClientId": resource_client_id,
            "required": required_client_roles,
            "missing": missing_client_roles,
            "present": not missing_client_roles,
        },
        "failures": failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate a redacted Faz 24 platform-desktop access-token contract "
            "without printing token material."
        )
    )
    parser.add_argument(
        "--token-file",
        default=os.environ.get("TOKEN_FILE"),
        help="Path to a file containing the access token. If omitted, stdin is used.",
    )
    parser.add_argument(
        "--required-audiences",
        default=os.environ.get("REQUIRED_AUDIENCES"),
        help=(
            "Comma-separated service audiences. Default: "
            + ",".join(DEFAULT_REQUIRED_AUDIENCES)
        ),
    )
    parser.add_argument(
        "--gateway-accepted-audiences",
        default=os.environ.get("GATEWAY_ACCEPTED_AUDIENCES"),
        help=(
            "Comma-separated audiences accepted by api-gateway. Default: "
            + ",".join(DEFAULT_GATEWAY_AUDIENCES)
        ),
    )
    parser.add_argument(
        "--required-claims",
        default=os.environ.get("REQUIRED_CLAIMS"),
        help="Comma-separated required claims. Default: " + ",".join(DEFAULT_REQUIRED_CLAIMS),
    )
    parser.add_argument(
        "--resource-client-id",
        default=os.environ.get("RESOURCE_CLIENT_ID", DEFAULT_RESOURCE_CLIENT_ID),
        help="Resource client id for capability roles. Default: " + DEFAULT_RESOURCE_CLIENT_ID,
    )
    parser.add_argument(
        "--required-client-roles",
        default=os.environ.get("REQUIRED_CLIENT_ROLES"),
        help=(
            "Comma-separated client roles on --resource-client-id. Default: "
            + ",".join(DEFAULT_REQUIRED_CLIENT_ROLES)
        ),
    )
    parser.add_argument(
        "--required-azp",
        default=os.environ.get("REQUIRED_AZP", "platform-desktop"),
        help="Expected azp client id. Default: platform-desktop.",
    )
    parser.add_argument(
        "--required-role",
        default=os.environ.get("REQUIRED_ROLE", "MEETING_ADMIN"),
        help="Expected realm role. Default: MEETING_ADMIN.",
    )
    parser.add_argument(
        "--expected-issuer",
        default=os.environ.get("EXPECTED_ISSUER"),
        help="Optional exact issuer assertion.",
    )
    args = parser.parse_args(argv)

    try:
        token = _read_token(args.token_file)
        payload = _decode_payload(token)
        report = validate(
            payload,
            required_audiences=_csv(args.required_audiences, DEFAULT_REQUIRED_AUDIENCES),
            gateway_audiences=_csv(args.gateway_accepted_audiences, DEFAULT_GATEWAY_AUDIENCES),
            required_claims=_csv(args.required_claims, DEFAULT_REQUIRED_CLAIMS),
            resource_client_id=args.resource_client_id,
            required_client_roles=_csv(
                args.required_client_roles,
                DEFAULT_REQUIRED_CLIENT_ROLES,
            ),
            required_azp=args.required_azp,
            required_role=args.required_role,
            expected_issuer=args.expected_issuer,
        )
    except ValueError as exc:
        report = {
            "schemaVersion": "faz24.platformDesktopTokenContract.v1",
            "status": "error",
            "tokenIncluded": False,
            "error": str(exc),
        }
        print(json.dumps(report, indent=2, sort_keys=True))
        return 2

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
