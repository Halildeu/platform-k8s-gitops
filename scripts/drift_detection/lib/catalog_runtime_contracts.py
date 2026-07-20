"""Catalog-driven runtime image and JWT configuration contracts.

The service catalog is the authority for environment membership and JWT
classification.  Keeping these selectors here prevents every new isolated
product workload from having to be added to another hard-coded shell list.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .services_catalog import ServicesCatalog


EXPECTED_ISSUERS = {
    "prod": {"https://ai.acik.com/realms/serban"},
    "test": {
        "https://testai.acik.com/realms/platform-test",
        "http://keycloak:8080/realms/platform-test",
        "http://keycloak:8080/realms/serban",
    },
}

# Two canonical platform property contracts plus the existing audio-gateway
# compatibility pair.  New services must use KEYCLOAK_* or SECURITY_JWT_*.
JWT_KEY_PAIRS = (
    ("KEYCLOAK_ISSUER_URI", "KEYCLOAK_JWKS_URI"),
    ("SECURITY_JWT_ISSUER", "SECURITY_JWT_JWK_SET_URI"),
    ("AUDIO_GATEWAY_JWT_ISSUER_URI", "AUDIO_GATEWAY_JWT_JWKS_URI"),
)


@dataclass(frozen=True)
class ContractFinding:
    code: str
    message: str


def _flatten_documents(documents: Iterable[dict]) -> list[dict]:
    flattened: list[dict] = []
    for document in documents:
        if not isinstance(document, dict):
            continue
        if document.get("kind") == "List":
            flattened.extend(
                item for item in document.get("items", []) if isinstance(item, dict)
            )
        else:
            flattened.append(document)
    return flattened


def desired_image_digests(
    documents: Iterable[dict], catalog: ServicesCatalog, env: str
) -> dict[str, str]:
    """Return catalog-enabled workload name -> immutable primary image digest."""

    enabled = {
        service.name
        for service in catalog.enabled_in(env)
        if service.workload_kind in {"Deployment", "StatefulSet"}
    }
    digests: dict[str, str] = {}
    for document in _flatten_documents(documents):
        if document.get("kind") not in {"Deployment", "StatefulSet"}:
            continue
        metadata = document.get("metadata") or {}
        labels = metadata.get("labels") or {}
        name = labels.get("app.kubernetes.io/name") or metadata.get("name")
        if name not in enabled:
            continue
        containers = (
            (((document.get("spec") or {}).get("template") or {}).get("spec") or {}).get(
                "containers"
            )
            or []
        )
        if not containers:
            continue
        image = str(containers[0].get("image") or "")
        if "@sha256:" in image:
            digests[name] = image.rsplit("@", 1)[1]
    return digests


def compare_image_digests(
    desired: dict[str, str], live: dict[str, str]
) -> list[ContractFinding]:
    """Compare desired catalog workloads with pod imageIDs."""

    findings: list[ContractFinding] = []
    for name, desired_digest in sorted(desired.items()):
        live_digest = live.get(name)
        if not live_digest:
            findings.append(
                ContractFinding("service_missing", f"Service {name} in yaml but no live pods")
            )
        elif live_digest != desired_digest:
            findings.append(
                ContractFinding(
                    "digest_drift",
                    f"{name}: yaml={desired_digest} pod={live_digest}",
                )
            )
    for name in sorted(set(live) - set(desired)):
        findings.append(
            ContractFinding(
                "service_unmanaged",
                f"Live service {name} has no yaml entry (gitops untracked)",
            )
        )
    return findings


def jwt_config_findings(
    documents: Iterable[dict], catalog: ServicesCatalog, env: str
) -> list[ContractFinding]:
    """Validate issuer/JWKS pairs for every enabled JWT-validating service."""

    configmaps = {
        (document.get("metadata") or {}).get("name"): document.get("data") or {}
        for document in _flatten_documents(documents)
        if document.get("kind") == "ConfigMap"
    }
    expected = EXPECTED_ISSUERS.get(env, set())
    findings: list[ContractFinding] = []
    for service in sorted(catalog.enabled_in(env), key=lambda item: item.name):
        if not service.jwt_validates:
            continue
        data = configmaps.get(f"{service.name}-config")
        if data is None:
            findings.append(
                ContractFinding(
                    "configmap_jwt_missing",
                    f"{service.name}: catalog JWT service ConfigMap missing",
                )
            )
            continue

        selected = next(
            (
                (issuer_key, jwks_key, data.get(issuer_key, ""), data.get(jwks_key, ""))
                for issuer_key, jwks_key in JWT_KEY_PAIRS
                if data.get(issuer_key) or data.get(jwks_key)
            ),
            None,
        )
        if selected is None:
            findings.append(
                ContractFinding(
                    "configmap_jwt_missing",
                    f"{service.name}: no supported issuer/JWKS key pair set",
                )
            )
            continue

        issuer_key, jwks_key, issuer, jwks = selected
        if not issuer or not jwks:
            missing = issuer_key if not issuer else jwks_key
            findings.append(
                ContractFinding(
                    "configmap_jwt_missing", f"{service.name}: {missing} not set"
                )
            )
            continue
        if "OVERLAY_MUST_OVERRIDE" in issuer or "OVERLAY_MUST_OVERRIDE" in jwks:
            findings.append(
                ContractFinding(
                    "configmap_jwt_placeholder",
                    f"{service.name}: issuer/JWKS placeholder leaked into {env}",
                )
            )
            continue
        if expected and issuer not in expected:
            findings.append(
                ContractFinding(
                    "configmap_jwt_issuer",
                    f"{service.name}: {issuer_key}={issuer} not expected for {env}",
                )
            )
            continue
        if not jwks.endswith("/protocol/openid-connect/certs"):
            findings.append(
                ContractFinding(
                    "configmap_jwt_jwks",
                    f"{service.name}: {jwks_key} has invalid certs path",
                )
            )
    return findings
