#!/usr/bin/env python3
"""Verify a signed Faz 22.6 VIEW_ONLY KVKK decision and emit a bounded marker.

The decision record stays in access-controlled storage. The issue marker carries
only a content digest and content-addressed URN. Private keys are never read by
this tool: two authorized humans sign domain-separated approval requests using
their own key custody, then this verifier checks those detached Ed25519
signatures against the reviewed approver policy.
"""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DECISION_SCHEMA = ROOT / "schema/faz22-6-view-only-kvkk-decision-v1.schema.json"
POLICY_SCHEMA = ROOT / "schema/faz22-6-view-only-kvkk-approver-policy-v1.schema.json"
MARKER = "F22_6_VIEW_ONLY_KVKK: v1"
DOMAIN = "F22_6_VIEW_ONLY_KVKK_APPROVAL_V1"
SHA256 = re.compile(r"^sha256:[a-f0-9]{64}$")
POLICY_ID = re.compile(r"^[A-Za-z0-9._-]{3,120}$")
KEY_ID = re.compile(r"^kvkk-[a-z0-9][a-z0-9-]{2,62}$")
PRINCIPAL_ID = re.compile(r"^person:[a-z0-9][a-z0-9._-]{2,63}$")
PLACEHOLDER = re.compile(
    r"(?:__REQUIRED|<[^>]+>|\bTBD\b|\bTODO\b|DPO Example|John Doe|CHANGE[-_ ]?ME)",
    re.IGNORECASE,
)
SECRET_VALUE_PATTERNS = (
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"data:image/[A-Za-z0-9.+-]+;base64,", re.IGNORECASE),
)
SENSITIVE_KEYS = {
    "access_token", "refresh_token", "token", "authorization", "bearer", "jwt",
    "credential", "password", "secret", "cookie", "private_key", "frame_bytes",
    "image_bytes", "raw_screen", "payload_b64", "screen_content_bytes",
}
MARKER_REQUIRED_FIELDS = frozenset({
    "status", "kvkk_attended_pilot_signoff", "legal_dpo_consent",
    "retention_policy_approval", "owner_approved_by", "approved_at",
    "expires_at", "decision_payload_sha256", "decision_record_sha256",
    "decision_record_ref", "approver_policy_sha256", "approver_policy_ref",
    "privacy_owner_key_id", "privacy_owner_public_key_sha256",
    "privacy_owner_signed_at", "privacy_owner_signature",
    "legal_dpo_key_id", "legal_dpo_public_key_sha256",
    "legal_dpo_signed_at", "legal_dpo_signature",
})


class DecisionError(Exception):
    pass


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DecisionError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise DecisionError(f"{path} must contain a JSON object")
    return value


def canonical_bytes(value: Any) -> bytes:
    # RFC 8785/JCS-compatible for this schema's domain: object keys are fixed
    # ASCII schema keys and numeric values are integers (no floats/NaN).
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def sha256_hex(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def decision_payload(record: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(record)
    payload.pop("approvals", None)
    return payload


def decision_record_projection(record: dict[str, Any]) -> dict[str, Any]:
    """Canonical record projection that avoids a signature/hash cycle."""
    projection = copy.deepcopy(record)
    for approval in projection.get("approvals", {}).values():
        approval.pop("signatureBase64", None)
    return projection


def parse_utc(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise DecisionError(f"{field} must be an RFC3339 UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0) or not value.endswith("Z"):
        raise DecisionError(f"{field} must use UTC Z notation")
    return parsed.astimezone(timezone.utc)


def utc_seconds(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalized_key(value: str) -> str:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    return value.replace("-", "_").replace(".", "_").lower()


def scan_hygiene(value: Any, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if normalized_key(str(key)) in SENSITIVE_KEYS:
                findings.append(f"{child_path}: forbidden sensitive key")
            findings.extend(scan_hygiene(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(scan_hygiene(child, f"{path}[{index}]"))
    elif isinstance(value, str):
        if PLACEHOLDER.search(value):
            findings.append(f"{path}: unresolved placeholder")
        if any(pattern.search(value) for pattern in SECRET_VALUE_PATTERNS):
            findings.append(f"{path}: secret or screen-content shaped value")
    return findings


def validate_schema(instance: dict[str, Any], schema_path: Path, label: str) -> None:
    try:
        from jsonschema import Draft202012Validator  # type: ignore
    except ImportError as exc:
        raise DecisionError("jsonschema is required: python3 -m pip install jsonschema") from exc
    schema = load_json(schema_path)
    Draft202012Validator.check_schema(schema)
    errors = sorted(Draft202012Validator(schema).iter_errors(instance), key=lambda item: list(item.path))
    if errors:
        rendered = []
        for error in errors[:20]:
            field = ".".join(str(part) for part in error.absolute_path) or "$"
            rendered.append(f"{field}: {error.message}")
        raise DecisionError(f"{label} schema invalid: " + "; ".join(rendered))


def approval_message_from_digest(
    payload_digest: str,
    record_digest: str,
    policy_digest: str,
    principal_id: str,
    role: str,
    signed_at: str,
    status: str,
    approved_at: str,
    review_expires_at: str,
) -> bytes:
    lines = (
        DOMAIN,
        f"decision_payload_sha256={payload_digest}",
        f"decision_record_sha256={record_digest}",
        f"approver_policy_sha256={policy_digest}",
        f"principal_id={principal_id}",
        f"role={role}",
        f"signed_at={signed_at}",
        f"status={status}",
        f"approved_at={approved_at}",
        f"review_expires_at={review_expires_at}",
    )
    return ("\n".join(lines) + "\n").encode("utf-8")


def approval_message(record: dict[str, Any], approval: dict[str, Any], policy: dict[str, Any]) -> bytes:
    return approval_message_from_digest(
        f"sha256:{sha256_hex(decision_payload(record))}",
        f"sha256:{sha256_hex(decision_record_projection(record))}",
        f"sha256:{sha256_hex(policy)}",
        approval["principalId"],
        approval["role"],
        approval["signedAt"],
        record["status"],
        record["lifecycle"]["approvedAt"],
        record["lifecycle"]["reviewExpiresAt"],
    )


def policy_entry(policy: dict[str, Any], principal: str, role: str) -> dict[str, Any]:
    matches = [
        entry for entry in policy["authorizedApprovers"]
        if entry["principalId"] == principal and entry["role"] == role
    ]
    if len(matches) != 1:
        raise DecisionError(f"{role} principal is not uniquely authorized by approver policy")
    return matches[0]


def policy_entry_by_key(policy: dict[str, Any], key_id: str, role: str) -> dict[str, Any]:
    matches = [
        entry for entry in policy["authorizedApprovers"]
        if entry["keyId"] == key_id and entry["role"] == role
    ]
    if len(matches) != 1:
        raise DecisionError(f"{role} key is not uniquely authorized by canonical approver policy")
    return matches[0]


def ed25519_public_key_bytes(public_key_b64: str, label: str) -> bytes:
    try:
        public_key = base64.b64decode(public_key_b64, validate=True)
    except (TypeError, ValueError) as exc:
        raise DecisionError(f"{label} public key is invalid Base64") from exc
    if len(public_key) != 32:
        raise DecisionError(f"{label} public key must be a raw 32-byte Ed25519 key")
    return public_key


def ed25519_public_key_sha256(public_key_b64: str, label: str) -> str:
    public_key = ed25519_public_key_bytes(public_key_b64, label)
    return f"sha256:{hashlib.sha256(public_key).hexdigest()}"


def validate_policy_core(policy: dict[str, Any]) -> None:
    expected_top = {
        "schemaVersion", "policyId", "identityDirectoryRef",
        "engineeringPrincipalIds", "authorizedApprovers",
    }
    if set(policy) != expected_top:
        raise DecisionError("approver policy has missing or unknown top-level keys")
    if policy.get("schemaVersion") != "faz22.6-view-only-kvkk-approver-policy-v1":
        raise DecisionError("approver policy schemaVersion is invalid")
    if not isinstance(policy.get("policyId"), str) or not POLICY_ID.fullmatch(policy["policyId"]):
        raise DecisionError("approver policy policyId is invalid")
    if not isinstance(policy.get("identityDirectoryRef"), str) or not policy["identityDirectoryRef"].startswith("policy://"):
        raise DecisionError("approver policy identityDirectoryRef is invalid")
    engineering = policy.get("engineeringPrincipalIds")
    entries = policy.get("authorizedApprovers")
    if not isinstance(engineering, list) or not engineering or len(set(engineering)) != len(engineering):
        raise DecisionError("approver policy engineeringPrincipalIds must be a non-empty unique list")
    if not all(isinstance(item, str) and PRINCIPAL_ID.fullmatch(item) for item in engineering):
        raise DecisionError("approver policy contains an invalid engineering principal")
    if not isinstance(entries, list) or len(entries) < 2:
        raise DecisionError("approver policy must contain at least two authorized approvers")
    expected_entry = {"keyId", "principalId", "role", "ed25519PublicKeyBase64", "validFrom", "validUntil"}
    key_ids: set[str] = set()
    principal_ids: set[str] = set()
    public_keys: set[bytes] = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != expected_entry:
            raise DecisionError("approver policy entry has missing or unknown keys")
        if not isinstance(entry["keyId"], str) or not KEY_ID.fullmatch(entry["keyId"]):
            raise DecisionError("approver policy keyId is invalid")
        if not isinstance(entry["principalId"], str) or not PRINCIPAL_ID.fullmatch(entry["principalId"]):
            raise DecisionError("approver policy principalId is invalid")
        if entry["role"] not in {"privacy-owner", "legal-or-dpo"}:
            raise DecisionError("approver policy role is invalid")
        public_key = ed25519_public_key_bytes(
            entry["ed25519PublicKeyBase64"], "approver policy"
        )
        valid_from = parse_utc(entry["validFrom"], "approver policy validFrom")
        valid_until = parse_utc(entry["validUntil"], "approver policy validUntil")
        if valid_until <= valid_from:
            raise DecisionError("approver policy key validity window is invalid")
        if entry["principalId"] in set(engineering):
            raise DecisionError("approver policy authorizes an engineering principal for legal approval")
        key_ids.add(entry["keyId"])
        principal_ids.add(entry["principalId"])
        public_keys.add(public_key)
    if len(key_ids) != len(entries):
        raise DecisionError("approver policy key IDs must be globally unique")
    if len(principal_ids) != len(entries):
        raise DecisionError("approver policy principal IDs must be globally unique")
    if len(public_keys) != len(entries):
        raise DecisionError("approver policy Ed25519 public keys must be globally unique")


def verify_signature_with_openssl(message: bytes, signature: bytes, public_key: bytes, label: str) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "public.der").write_bytes(bytes.fromhex("302a300506032b6570032100") + public_key)
        (root / "signature.bin").write_bytes(signature)
        (root / "message.bin").write_bytes(message)
        try:
            completed = subprocess.run(
                [
                    "openssl", "pkeyutl", "-verify", "-pubin",
                    "-inkey", str(root / "public.der"), "-keyform", "DER",
                    "-rawin", "-in", str(root / "message.bin"),
                    "-sigfile", str(root / "signature.bin"),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except OSError as exc:
            raise DecisionError("cryptography or OpenSSL 3 is required for Ed25519 verification") from exc
        if completed.returncode != 0:
            raise DecisionError(f"{label} Ed25519 signature verification failed")


def verify_signature(message: bytes, signature_b64: str, public_key_b64: str, label: str) -> None:
    try:
        signature = base64.b64decode(signature_b64, validate=True)
        public_key = base64.b64decode(public_key_b64, validate=True)
    except (TypeError, ValueError) as exc:
        raise DecisionError(f"{label} Ed25519 material is not valid Base64") from exc
    if len(signature) != 64 or len(public_key) != 32:
        raise DecisionError(f"{label} Ed25519 material has invalid length")
    try:
        from cryptography.exceptions import InvalidSignature  # type: ignore
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey  # type: ignore
    except ImportError:
        # Live audit runners need no Python package install: OpenSSL 3 verifies
        # the same raw Ed25519 key after wrapping it in the fixed SPKI prefix.
        verify_signature_with_openssl(message, signature, public_key, label)
    else:
        try:
            Ed25519PublicKey.from_public_bytes(public_key).verify(signature, message)
        except (ValueError, InvalidSignature) as exc:
            raise DecisionError(f"{label} Ed25519 signature verification failed") from exc


def validate_semantics(
    record: dict[str, Any], policy: dict[str, Any], now: datetime, verify_signatures: bool
) -> dict[str, Any]:
    hygiene = scan_hygiene(record) + scan_hygiene(policy)
    if hygiene:
        raise DecisionError("evidence hygiene failed: " + "; ".join(hygiene[:20]))
    validate_policy_core(policy)

    lifecycle = record["lifecycle"]
    approved_at = parse_utc(lifecycle["approvedAt"], "lifecycle.approvedAt")
    expires_at = parse_utc(lifecycle["reviewExpiresAt"], "lifecycle.reviewExpiresAt")
    if approved_at > now:
        raise DecisionError("lifecycle.approvedAt is in the future")
    if expires_at <= now:
        raise DecisionError("lifecycle.reviewExpiresAt is expired")
    if expires_at <= approved_at:
        raise DecisionError("lifecycle.reviewExpiresAt must be after approvedAt")
    if expires_at - approved_at > timedelta(days=366):
        raise DecisionError("review window must not exceed 366 days")

    verified_at = parse_utc(record["uxVerification"]["verifiedAt"], "uxVerification.verifiedAt")
    if verified_at > approved_at or verified_at > now:
        raise DecisionError("attended UX verification must exist before approval")
    for key in ("sessionMetadata", "auditRecords"):
        effective = parse_utc(record["retention"][key]["effectiveFrom"], f"retention.{key}.effectiveFrom")
        if effective > approved_at:
            raise DecisionError(f"retention.{key}.effectiveFrom must not be after approval")
    storage_retention = record["governance"]["decisionRecordStorage"]["recordRetention"]
    storage_effective = parse_utc(storage_retention["effectiveFrom"], "governance.decisionRecordStorage.recordRetention.effectiveFrom")
    if storage_effective > approved_at:
        raise DecisionError("decision-record storage retention must be effective before approval")

    owner = record["approvals"]["privacyOwner"]
    legal = record["approvals"]["legalOrDpo"]
    if owner["role"] != "privacy-owner" or legal["role"] != "legal-or-dpo":
        raise DecisionError("approval roles must match their slots")
    if owner["principalId"] == legal["principalId"]:
        raise DecisionError("privacy owner and legal/DPO must be different people")
    engineering = set(policy["engineeringPrincipalIds"])
    if owner["principalId"] in engineering or legal["principalId"] in engineering:
        raise DecisionError("an engineering principal cannot approve the legal decision")

    signed_times: list[datetime] = []
    attestation_result: dict[str, dict[str, str]] = {}
    for label, approval in (("privacyOwner", owner), ("legalOrDpo", legal)):
        signed_at = parse_utc(approval["signedAt"], f"approvals.{label}.signedAt")
        if signed_at > now:
            raise DecisionError(f"approvals.{label}.signedAt is in the future")
        signed_times.append(signed_at)
        entry = policy_entry(policy, approval["principalId"], approval["role"])
        valid_from = parse_utc(entry["validFrom"], f"policy.{label}.validFrom")
        valid_until = parse_utc(entry["validUntil"], f"policy.{label}.validUntil")
        if not valid_from <= signed_at <= valid_until:
            raise DecisionError(f"approvals.{label} was signed outside key validity")
        if verify_signatures:
            verify_signature(
                approval_message(record, approval, policy),
                approval["signatureBase64"],
                entry["ed25519PublicKeyBase64"],
                label,
            )
        attestation_result[label] = {
            "keyId": entry["keyId"],
            "publicKeySha256": ed25519_public_key_sha256(
                entry["ed25519PublicKeyBase64"], f"policy.{label}"
            ),
            "signedAt": approval["signedAt"],
            "signatureBase64": approval["signatureBase64"],
        }

    if approved_at != max(signed_times):
        raise DecisionError("lifecycle.approvedAt must equal the later human signature timestamp")
    if record["retention"]["screenContent"]["ownerPrincipalId"] != owner["principalId"]:
        raise DecisionError("screen-content retention owner must be the authorized privacy owner")
    for key in ("sessionMetadata", "auditRecords"):
        if record["retention"][key]["ownerPrincipalId"] != owner["principalId"]:
            raise DecisionError(f"retention.{key} owner must be the authorized privacy owner")
    if storage_retention["ownerPrincipalId"] != owner["principalId"]:
        raise DecisionError("decision-record storage retention owner must be the authorized privacy owner")

    full_digest = sha256_hex(decision_record_projection(record))
    policy_digest = sha256_hex(policy)
    return {
        "status": "pass",
        "schemaVersion": "faz22.6-view-only-kvkk-decision-verifier-v1",
        "decisionStatus": record["status"],
        "decisionPayloadSha256": f"sha256:{sha256_hex(decision_payload(record))}",
        "decisionRecordSha256": f"sha256:{full_digest}",
        "decisionRecordRef": f"urn:decision-record:sha256:{full_digest}",
        "approverPolicySha256": f"sha256:{policy_digest}",
        "approverPolicyRef": f"urn:approver-policy:sha256:{policy_digest}",
        "approverPolicyId": policy["policyId"],
        "approvedAt": utc_seconds(approved_at),
        "reviewExpiresAt": utc_seconds(expires_at),
        "approvalAttestations": attestation_result,
        "humanSignatureCount": 2,
        "recordContainsRawScreenOrSecret": False,
    }


def marker_text(result: dict[str, Any]) -> str:
    cleared = result["decisionStatus"] == "approved"
    decision_value = "pass" if cleared else "withdrawn"
    status = "cleared" if cleared else "withdrawn"
    owner_ref = f"dual-human-signature:{result['approverPolicyId']}"
    owner_attestation = result["approvalAttestations"]["privacyOwner"]
    legal_attestation = result["approvalAttestations"]["legalOrDpo"]
    return "\n".join((
        MARKER,
        f"status: {status}",
        f"kvkk_attended_pilot_signoff: {decision_value}",
        f"legal_dpo_consent: {decision_value}",
        f"retention_policy_approval: {decision_value}",
        f"owner_approved_by: {owner_ref}",
        f"approved_at: {result['approvedAt']}",
        f"expires_at: {result['reviewExpiresAt']}",
        f"decision_payload_sha256: {result['decisionPayloadSha256']}",
        f"decision_record_sha256: {result['decisionRecordSha256']}",
        f"decision_record_ref: {result['decisionRecordRef']}",
        f"approver_policy_sha256: {result['approverPolicySha256']}",
        f"approver_policy_ref: {result['approverPolicyRef']}",
        f"privacy_owner_key_id: {owner_attestation['keyId']}",
        f"privacy_owner_public_key_sha256: {owner_attestation['publicKeySha256']}",
        f"privacy_owner_signed_at: {owner_attestation['signedAt']}",
        f"privacy_owner_signature: {owner_attestation['signatureBase64']}",
        f"legal_dpo_key_id: {legal_attestation['keyId']}",
        f"legal_dpo_public_key_sha256: {legal_attestation['publicKeySha256']}",
        f"legal_dpo_signed_at: {legal_attestation['signedAt']}",
        f"legal_dpo_signature: {legal_attestation['signatureBase64']}",
        "",
    ))


def parse_marker(raw: str) -> dict[str, str]:
    if "\r" in raw or "\t" in raw or not raw.endswith("\n"):
        raise DecisionError("marker must use canonical LF-terminated lines")
    lines = raw.splitlines()
    if not lines or lines[0] != MARKER:
        raise DecisionError(f"marker must start with exact line: {MARKER}")
    fields: dict[str, str] = {}
    for line in lines[1:]:
        if not line:
            continue
        match = re.fullmatch(r"([A-Za-z0-9_]+): ([^\r\n\t]{1,512})", line)
        if not match:
            raise DecisionError("marker contains a non-canonical field line")
        key, value = match.groups()
        if key in fields:
            raise DecisionError("marker contains an invalid or duplicate field key")
        if value != value.strip():
            raise DecisionError("marker contains a non-canonical field value")
        fields[key] = value
    return fields


def verify_marker(raw: str, policy: dict[str, Any], now: datetime) -> dict[str, Any]:
    validate_policy_core(policy)
    fields = parse_marker(raw)
    if set(fields) != MARKER_REQUIRED_FIELDS:
        raise DecisionError("cleared marker has missing or unknown fields")
    if fields["status"] != "cleared" or any(
        fields[key] != "pass"
        for key in ("kvkk_attended_pilot_signoff", "legal_dpo_consent", "retention_policy_approval")
    ):
        raise DecisionError("marker does not carry a cleared legal decision")
    if fields["owner_approved_by"] != f"dual-human-signature:{policy['policyId']}":
        raise DecisionError("marker owner policy reference does not match canonical policy")
    for key in ("decision_payload_sha256", "decision_record_sha256", "approver_policy_sha256"):
        if not SHA256.fullmatch(fields[key]):
            raise DecisionError(f"marker {key} is invalid")
    if fields["decision_record_ref"] != f"urn:decision-record:{fields['decision_record_sha256']}":
        raise DecisionError("marker decision record digest/ref mismatch")
    policy_digest = f"sha256:{sha256_hex(policy)}"
    if fields["approver_policy_sha256"] != policy_digest:
        raise DecisionError("marker approver policy digest does not match canonical policy")
    if fields["approver_policy_ref"] != f"urn:approver-policy:{policy_digest}":
        raise DecisionError("marker approver policy digest/ref mismatch")

    approved_at = parse_utc(fields["approved_at"], "marker approved_at")
    expires_at = parse_utc(fields["expires_at"], "marker expires_at")
    if expires_at <= approved_at or expires_at - approved_at > timedelta(days=366):
        raise DecisionError("marker lifecycle window is invalid")

    engineering = set(policy["engineeringPrincipalIds"])
    signed_times: list[datetime] = []
    principals: list[str] = []
    public_key_fingerprints: list[str] = []
    for prefix, role in (("privacy_owner", "privacy-owner"), ("legal_dpo", "legal-or-dpo")):
        key_id = fields[f"{prefix}_key_id"]
        entry = policy_entry_by_key(policy, key_id, role)
        if entry["principalId"] in engineering:
            raise DecisionError("marker approval resolves to an engineering principal")
        signed_at = parse_utc(fields[f"{prefix}_signed_at"], f"marker {prefix}_signed_at")
        if signed_at > now:
            raise DecisionError(f"marker {prefix}_signed_at is in the future")
        valid_from = parse_utc(entry["validFrom"], f"policy {prefix} validFrom")
        valid_until = parse_utc(entry["validUntil"], f"policy {prefix} validUntil")
        if not valid_from <= signed_at <= valid_until:
            raise DecisionError(f"marker {prefix} signature is outside key validity")
        fingerprint = fields[f"{prefix}_public_key_sha256"]
        if not SHA256.fullmatch(fingerprint):
            raise DecisionError(f"marker {prefix} public key fingerprint is invalid")
        expected_fingerprint = ed25519_public_key_sha256(
            entry["ed25519PublicKeyBase64"], f"policy {prefix}"
        )
        if fingerprint != expected_fingerprint:
            raise DecisionError(
                f"marker {prefix} public key fingerprint does not match canonical policy"
            )
        verify_signature(
            approval_message_from_digest(
                fields["decision_payload_sha256"],
                fields["decision_record_sha256"],
                fields["approver_policy_sha256"],
                entry["principalId"],
                role,
                fields[f"{prefix}_signed_at"],
                "approved",
                fields["approved_at"],
                fields["expires_at"],
            ),
            fields[f"{prefix}_signature"],
            entry["ed25519PublicKeyBase64"],
            f"marker {prefix}",
        )
        signed_times.append(signed_at)
        principals.append(entry["principalId"])
        public_key_fingerprints.append(fingerprint)
    if len(set(principals)) != 2:
        raise DecisionError("marker signatures must resolve to two different people")
    if len(set(public_key_fingerprints)) != 2:
        raise DecisionError("marker signatures must resolve to two different Ed25519 keys")
    if approved_at != max(signed_times):
        raise DecisionError("marker approved_at must equal the later human signature timestamp")

    state = "expired" if expires_at <= now else "pass"
    return {
        "status": state,
        "schemaVersion": "faz22.6-view-only-kvkk-marker-verifier-v1",
        "decisionPayloadSha256": fields["decision_payload_sha256"],
        "decisionRecordSha256": fields["decision_record_sha256"],
        "approverPolicySha256": policy_digest,
        "approvedAt": fields["approved_at"],
        "reviewExpiresAt": fields["expires_at"],
        "humanSignatureCount": 2,
    }


def signing_requests(record: dict[str, Any], policy: dict[str, Any], now: datetime) -> dict[str, Any]:
    candidate = copy.deepcopy(record)
    dummy_signature = base64.b64encode(b"\0" * 64).decode("ascii")
    for approval in candidate.get("approvals", {}).values():
        approval["signatureBase64"] = dummy_signature
    validate_schema(candidate, DECISION_SCHEMA, "decision")
    validate_schema(policy, POLICY_SCHEMA, "approver policy")
    validate_semantics(candidate, policy, now, verify_signatures=False)
    return {
        "schemaVersion": "faz22.6-view-only-kvkk-signing-requests-v1",
        "decisionPayloadSha256": f"sha256:{sha256_hex(decision_payload(candidate))}",
        "requests": {
            label: base64.b64encode(approval_message(candidate, approval, policy)).decode("ascii")
            for label, approval in candidate["approvals"].items()
        },
        "instructions": "Base64-decode each request and sign its exact bytes with the corresponding human-held Ed25519 key.",
    }


def write_json(path: Path | None, value: dict[str, Any]) -> None:
    rendered = json.dumps(value, indent=2, sort_keys=True) + "\n"
    if path is None:
        sys.stdout.write(rendered)
    else:
        path.write_text(rendered, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="signed decision record JSON")
    parser.add_argument("--approver-policy", required=True, type=Path, help="reviewed public-key policy JSON")
    parser.add_argument(
        "--verify-marker-input",
        help="verify a marker against the canonical policy; use '-' for stdin",
    )
    parser.add_argument("--result-out", type=Path, help="redacted verifier result JSON")
    parser.add_argument("--marker-out", type=Path, help="write marker only after both signatures verify")
    parser.add_argument("--signing-requests-out", type=Path, help="prepare unsigned human signing requests; no marker")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        policy = load_json(args.approver_policy)
        now = datetime.now(timezone.utc)
        if args.verify_marker_input is not None:
            if args.input or args.marker_out or args.signing_requests_out:
                raise DecisionError("marker verification cannot be combined with decision generation options")
            try:
                raw_marker = (
                    sys.stdin.read()
                    if args.verify_marker_input == "-"
                    else Path(args.verify_marker_input).read_text(encoding="utf-8")
                )
            except OSError as exc:
                raise DecisionError(f"cannot read marker: {exc}") from exc
            write_json(args.result_out, verify_marker(raw_marker, policy, now))
            return 0
        if not args.input:
            raise DecisionError("--input is required unless --verify-marker-input is used")
        if args.signing_requests_out:
            if args.marker_out:
                raise DecisionError("--signing-requests-out and --marker-out are mutually exclusive")
            record = load_json(args.input)
            write_json(args.signing_requests_out, signing_requests(record, policy, now))
            return 0

        record = load_json(args.input)
        validate_schema(record, DECISION_SCHEMA, "decision")
        validate_schema(policy, POLICY_SCHEMA, "approver policy")
        result = validate_semantics(record, policy, now, verify_signatures=True)
        write_json(args.result_out, result)
        if args.marker_out:
            args.marker_out.write_text(marker_text(result), encoding="utf-8")
        return 0
    except DecisionError as exc:
        error = {
            "status": "fail",
            "schemaVersion": "faz22.6-view-only-kvkk-decision-verifier-v1",
            "error": str(exc),
        }
        write_json(args.result_out, error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
