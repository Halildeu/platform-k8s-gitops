#!/usr/bin/env python3
"""Validate a tenant VIEW_ONLY policy against the platform safety baseline.

This tool validates source policy artifacts. It does not mint or verify the
runtime same-session Ed25519 envelope; that verifier belongs to the backend,
web, and agent implementation children of GitOps issue #2451.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
BASELINE_SCHEMA = ROOT / "schema/remote-view-platform-safety-baseline-v1.schema.json"
POLICY_SCHEMA = ROOT / "schema/remote-view-tenant-privacy-policy-v1.schema.json"


class PolicyError(Exception):
    pass


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicyError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PolicyError(f"{path} must contain a JSON object")
    return value


def canonical_bytes(value: Any) -> bytes:
    """JCS-compatible bytes for these integer-only, finite JSON contracts."""
    reject_floats(value)
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def reject_floats(value: Any, path: str = "$") -> None:
    if isinstance(value, float):
        raise PolicyError(f"{path}: floats are not permitted in v1 policy artifacts")
    if isinstance(value, dict):
        for key, child in value.items():
            reject_floats(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_floats(child, f"{path}[{index}]")


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def parse_utc(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise PolicyError(f"{field} must be an RFC3339 UTC timestamp") from exc
    if not value.endswith("Z") or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise PolicyError(f"{field} must use UTC Z notation")
    return parsed.astimezone(timezone.utc)


def validate_schema(instance: dict[str, Any], schema_path: Path, label: str) -> None:
    try:
        from jsonschema import Draft202012Validator, FormatChecker  # type: ignore
    except ImportError as exc:
        raise PolicyError("jsonschema is required: python3 -m pip install jsonschema") from exc

    schema = load_json(schema_path)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(instance), key=lambda item: list(item.path))
    if errors:
        rendered = []
        for error in errors[:20]:
            field = ".".join(str(part) for part in error.absolute_path) or "$"
            rendered.append(f"{field}: {error.message}")
        raise PolicyError(f"{label} schema invalid: " + "; ".join(rendered))


def validate_lifecycle(baseline: dict[str, Any], policy: dict[str, Any], at: datetime) -> None:
    baseline_from = parse_utc(baseline["lifecycle"]["validFrom"], "baseline.lifecycle.validFrom")
    baseline_review = parse_utc(baseline["lifecycle"]["reviewBy"], "baseline.lifecycle.reviewBy")
    if baseline_review <= baseline_from:
        raise PolicyError("baseline lifecycle must satisfy validFrom < reviewBy")
    if at < baseline_from or at > baseline_review:
        raise PolicyError("platform safety baseline is not current at the verification time")

    lifecycle = policy["lifecycle"]
    valid_from = parse_utc(lifecycle["validFrom"], "policy.lifecycle.validFrom")
    valid_until = parse_utc(lifecycle["validUntil"], "policy.lifecycle.validUntil")
    review_by = parse_utc(lifecycle["reviewBy"], "policy.lifecycle.reviewBy")
    if not valid_from < review_by <= valid_until:
        raise PolicyError("policy lifecycle must satisfy validFrom < reviewBy <= validUntil")
    if at < valid_from or at > valid_until:
        raise PolicyError("tenant policy is not effective at the verification time")
    if at > review_by:
        raise PolicyError("tenant policy reviewBy has expired")

    legal_review = parse_utc(policy["legalEvidence"]["reviewBy"], "legalEvidence.reviewBy")
    if at > legal_review:
        raise PolicyError("legal evidence reviewBy has expired")
    approved_at = policy["legalEvidence"]["approvedAt"]
    if approved_at is not None and parse_utc(approved_at, "legalEvidence.approvedAt") > at:
        raise PolicyError("legal evidence approvedAt cannot be in the future")


def validate_baseline_binding(baseline: dict[str, Any], policy: dict[str, Any]) -> str:
    actual_digest = digest(baseline)
    binding = policy["baseline"]
    if binding["baselineId"] != baseline["baselineId"]:
        raise PolicyError("tenant policy baselineId does not match the supplied baseline")
    if binding["baselineVersion"] != baseline["baselineVersion"]:
        raise PolicyError("tenant policy baselineVersion does not match the supplied baseline")
    if binding["baselineDigest"] != actual_digest:
        raise PolicyError("tenant policy baselineDigest does not match canonical baseline bytes")
    return actual_digest


def validate_limits(baseline: dict[str, Any], policy: dict[str, Any]) -> None:
    limits = baseline["limits"]
    if limits["maxEnvelopeLifetimeSeconds"] > limits["maxSessionTtlSeconds"]:
        raise PolicyError("baseline envelope lifetime cannot exceed session TTL")
    source = policy["policy"]
    session = source["session"]
    retention = source["retention"]
    checks = (
        (session["maxSessionTtlSeconds"], limits["maxSessionTtlSeconds"], "maxSessionTtlSeconds"),
        (session["maxViewers"], limits["maxViewers"], "maxViewers"),
        (
            retention["screenContent"]["ttlSeconds"],
            limits["maxScreenContentRetentionSeconds"],
            "screenContent.ttlSeconds",
        ),
        (
            retention["sessionMetadata"]["ttlSeconds"],
            limits["maxSessionMetadataRetentionSeconds"],
            "sessionMetadata.ttlSeconds",
        ),
        (
            retention["auditRecords"]["ttlSeconds"],
            limits["maxAuditRetentionSeconds"],
            "auditRecords.ttlSeconds",
        ),
    )
    for value, maximum, field in checks:
        if value > maximum:
            raise PolicyError(f"policy.{field} exceeds the platform safety maximum")


def validate_notice(policy: dict[str, Any]) -> None:
    notice = policy["policy"]["notice"]
    localizations = notice["localizations"]
    locales = [item["locale"] for item in localizations]
    if len(locales) != len(set(locales)):
        raise PolicyError("notice localizations must use unique locale values")
    if notice["defaultLocale"] not in set(locales):
        raise PolicyError("notice.defaultLocale must have a localization")
    for item in localizations:
        projection = dict(item)
        expected = projection.pop("contentDigest")
        if expected != digest(projection):
            raise PolicyError(f"notice localization digest mismatch for {item['locale']}")


def validate_policy_semantics(baseline: dict[str, Any], policy: dict[str, Any]) -> None:
    source = policy["policy"]
    governance = source["dataGovernance"]
    if governance["residencyMode"] == "single-region" and len(governance["storageRegions"]) != 1:
        raise PolicyError("single-region residency requires exactly one storage region")
    if governance["crossBorderTransfer"] == "deny":
        if governance["destinationRegions"] or governance["transferSafeguardRef"] is not None:
            raise PolicyError("cross-border deny requires no destinations or safeguard reference")
    else:
        if not governance["destinationRegions"] or governance["transferSafeguardRef"] is None:
            raise PolicyError("cross-border allow requires destinations and a safeguard reference")
        if set(governance["destinationRegions"]) & set(governance["storageRegions"]):
            raise PolicyError("cross-border destination regions must not repeat storage regions")

    controller_id = governance["controller"]["organizationId"]
    processor_ids = [item["organizationId"] for item in governance["processors"]]
    if len(processor_ids) != len(set(processor_ids)) or controller_id in set(processor_ids):
        raise PolicyError("controller and processor organization IDs must be unique")

    category_ids = [item["categoryId"] for item in source["specialCategory"]["rules"]]
    if len(category_ids) != len(set(category_ids)):
        raise PolicyError("specialCategory rules must use unique categoryId values")

    if source["specialCategory"]["detectionFailureAction"] != baseline["defaults"]["dlpFailureAction"]:
        raise PolicyError("tenant policy cannot weaken the platform DLP failure action")

    if source["recording"]["mode"] == "disabled":
        if source["retention"]["screenContent"] != {"persisted": False, "ttlSeconds": 0}:
            raise PolicyError("recording disabled requires zero screen-content persistence")

    legal = policy["legalEvidence"]
    deployment_class = policy["deploymentClass"]
    if deployment_class == "production" and legal["status"] != "approved":
        raise PolicyError("production policy requires approved legal evidence")
    if legal["status"] == "tracked-pending" and deployment_class != "bounded-test":
        raise PolicyError("tracked-pending legal evidence is limited to bounded-test")
    if deployment_class == "bounded-test":
        if source["session"]["maxViewers"] != 1:
            raise PolicyError("bounded-test requires exactly one viewer")
        if source["recording"]["mode"] != "disabled":
            raise PolicyError("bounded-test requires recording disabled")
        if governance["crossBorderTransfer"] != "deny":
            raise PolicyError("bounded-test requires cross-border transfer denied")
    if legal["status"] in {"withdrawn", "expired"}:
        raise PolicyError(f"legal evidence status {legal['status']} cannot authorize a session")
    if legal["status"] == "approved":
        if legal["decisionRecordDigest"] is None or legal["decisionRecordRef"] is None or legal["approvedAt"] is None:
            raise PolicyError("approved legal evidence requires decision digest, content-addressed ref and approvedAt")
        expected_ref = "urn:remote-view-legal-decision:" + legal["decisionRecordDigest"]
        if legal["decisionRecordRef"] != expected_ref:
            raise PolicyError("approved legal decision ref must be content-addressed by its digest")


def verify(baseline_path: Path, policy_path: Path, at: datetime) -> dict[str, Any]:
    baseline = load_json(baseline_path)
    policy = load_json(policy_path)
    validate_schema(baseline, BASELINE_SCHEMA, "platform baseline")
    validate_schema(policy, POLICY_SCHEMA, "tenant policy")
    baseline_digest = validate_baseline_binding(baseline, policy)
    validate_lifecycle(baseline, policy, at)
    validate_limits(baseline, policy)
    validate_notice(policy)
    validate_policy_semantics(baseline, policy)
    return {
        "schemaVersion": "remote-view-tenant-policy-verifier-result-v1",
        "status": "pass",
        "tenantId": policy["tenantId"],
        "policyId": policy["policyId"],
        "policyVersion": policy["policyVersion"],
        "policyDigest": digest(policy),
        "baselineId": baseline["baselineId"],
        "baselineVersion": baseline["baselineVersion"],
        "baselineDigest": baseline_digest,
        "legalEvidenceStatus": policy["legalEvidence"]["status"],
        "legalEvidenceDigest": digest(policy["legalEvidence"]),
        "verifiedAt": at.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--at", help="RFC3339 UTC verification time; defaults to now")
    args = parser.parse_args()
    try:
        at = parse_utc(args.at, "--at") if args.at else datetime.now(timezone.utc)
        result = verify(args.baseline, args.policy, at)
    except PolicyError as exc:
        print(f"remote-view-policy: blocked: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
