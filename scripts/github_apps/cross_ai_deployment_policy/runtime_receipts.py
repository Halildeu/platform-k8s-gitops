"""Verify signed VIEW_ONLY preflight, lease and checkpoint runtime receipts."""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import stat
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from .canonical import canonical_bytes, sha256_digest
from .contract import VerifiedBundle
from .dsse import decode_public_key, verify_json_envelope
from .errors import reject
from .timeutil import parse_utc, utc_now


ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATHS = (
    ROOT / "schema/faz22-6-dsse-envelope-v1.schema.json",
    ROOT / "schema/faz22-6-view-only-transaction-binding-v1.schema.json",
    ROOT / "schema/faz22-6-view-only-transaction-binding-handoff-v1.schema.json",
    ROOT / "schema/faz22-6-view-only-live-preflight-request-v1.schema.json",
    ROOT / "schema/faz22-6-view-only-live-preflight-attestation-v1.schema.json",
    ROOT / "schema/faz22-6-view-only-checkpoint-lease-v1.schema.json",
    ROOT / "schema/faz22-6-view-only-external-checkpoint-create-v1.schema.json",
    ROOT / "schema/faz22-6-view-only-external-checkpoint-receipt-v1.schema.json",
    ROOT / "schema/faz22-6-view-only-runtime-trust-root-v1.schema.json",
)
PREFLIGHT_PAYLOAD_TYPE = (
    "application/vnd.acik.faz22-6-view-only-live-preflight-attestation.v1+json"
)
BINDING_HANDOFF_PAYLOAD_TYPE = (
    "application/vnd.acik.faz22-6-view-only-transaction-binding-handoff.v1+json"
)
LEASE_PAYLOAD_TYPE = (
    "application/vnd.acik.faz22-6-view-only-checkpoint-lease.v1+json"
)
CHECKPOINT_PAYLOAD_TYPE = (
    "application/vnd.acik.faz22-6-view-only-external-checkpoint-receipt.v1+json"
)
DSSE_ENVELOPE_DOMAIN = "faz22.6/view-only/dsse-envelope/v1"
BINDING_DOMAIN = "faz22.6/view-only/transaction-binding/v1"
TRANSACTION_ID_DOMAIN = "faz22.6/view-only/transaction-id/v1"
PREFLIGHT_REQUEST_DOMAIN = "faz22.6/view-only/live-preflight-request/v1"
CHECKPOINT_STORED_OBJECT_DOMAIN = (
    "faz22.6/view-only/checkpoint-stored-object/v1"
)
RUNTIME_TRUST_ROOT_DOMAIN = "faz22.6/view-only/runtime-trust-root/v1"
MAX_PREFLIGHT_ENVELOPE_BYTES = 512 * 1024
MAX_LEASE_ENVELOPE_BYTES = 1024 * 1024
MAX_CHECKPOINT_ENVELOPE_BYTES = 512 * 1024
MAX_BINDING_HANDOFF_ENVELOPE_BYTES = 64 * 1024
MAX_RUNTIME_EVIDENCE_ARCHIVE_BYTES = 48 * 1024 * 1024
MAX_RUNTIME_EVIDENCE_FILE_BYTES = 40 * 1024 * 1024
MAX_ZIP_COMPRESSION_RATIO = 100
RUNTIME_EVIDENCE_FILE = "runtime-evidence.json"


@dataclass(frozen=True)
class VerifiedRuntimeReceipt:
    payload_type: str
    payload: dict[str, Any]
    envelope: dict[str, Any]
    envelope_sha256: str
    signer_key_id: str


@dataclass(frozen=True)
class VerifiedRuntimeChain:
    binding_handoff: VerifiedRuntimeReceipt
    evaluation_preflight: VerifiedRuntimeReceipt
    redemption_preflight: VerifiedRuntimeReceipt
    lease: VerifiedRuntimeReceipt
    checkpoints: tuple[VerifiedRuntimeReceipt, ...]
    terminal: VerifiedRuntimeReceipt


@dataclass(frozen=True)
class RuntimeEvidencePackage:
    binding_handoff_envelope: dict[str, Any]
    evaluation_preflight_envelope: dict[str, Any]
    redemption_preflight_envelope: dict[str, Any]
    lease_envelope: dict[str, Any]
    checkpoint_envelopes: tuple[dict[str, Any], ...]
    archive_sha256: str


def runtime_envelope_sha256(envelope: dict[str, Any]) -> str:
    return sha256_digest(
        {"domain": DSSE_ENVELOPE_DOMAIN, "envelope": envelope}
    )


def runtime_trust_root_sha256(trust_root: dict[str, Any]) -> str:
    return sha256_digest(
        {"domain": RUNTIME_TRUST_ROOT_DOMAIN, "trustRoot": trust_root}
    )


def runtime_evidence_from_archive(archive: bytes) -> RuntimeEvidencePackage:
    if not 1 <= len(archive) <= MAX_RUNTIME_EVIDENCE_ARCHIVE_BYTES:
        reject(
            "RUNTIME_EVIDENCE_ARCHIVE_INVALID",
            "runtime evidence archive is empty or exceeds the bounded size",
        )
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            infos = bundle.infolist()
            if len(infos) != 1 or infos[0].filename != RUNTIME_EVIDENCE_FILE:
                reject(
                    "RUNTIME_EVIDENCE_ARCHIVE_INVALID",
                    "runtime evidence archive must contain one canonical file",
                )
            info = infos[0]
            mode = info.external_attr >> 16
            if (
                info.is_dir()
                or info.flag_bits & 0x1
                or stat.S_ISLNK(mode)
                or not 1 <= info.file_size <= MAX_RUNTIME_EVIDENCE_FILE_BYTES
                or info.compress_size < 1
                or info.file_size > info.compress_size * MAX_ZIP_COMPRESSION_RATIO
            ):
                reject(
                    "RUNTIME_EVIDENCE_ARCHIVE_INVALID",
                    "runtime evidence ZIP entry is unsafe",
                )
            raw = bundle.read(info)
    except (zipfile.BadZipFile, KeyError, RuntimeError):
        reject(
            "RUNTIME_EVIDENCE_ARCHIVE_INVALID",
            "runtime evidence artifact is not a safe ZIP archive",
        )
    if len(raw) != info.file_size:
        reject(
            "RUNTIME_EVIDENCE_ARCHIVE_INVALID",
            "runtime evidence size differs from ZIP metadata",
        )
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        reject("RUNTIME_EVIDENCE_INVALID", "runtime evidence is not UTF-8 JSON")
    fields = {
        "schemaVersion",
        "bindingHandoffEnvelope",
        "evaluationPreflightEnvelope",
        "redemptionPreflightEnvelope",
        "leaseEnvelope",
        "checkpointEnvelopes",
    }
    if (
        not isinstance(value, dict)
        or raw != canonical_bytes(value)
        or set(value) != fields
        or value.get("schemaVersion") != "faz22.6.viewOnlyRuntimeEvidence.v1"
        or any(
            not isinstance(value[name], dict)
            for name in fields - {"schemaVersion", "checkpointEnvelopes"}
        )
        or not isinstance(value["checkpointEnvelopes"], list)
        or not 1 <= len(value["checkpointEnvelopes"]) <= 64
        or any(not isinstance(item, dict) for item in value["checkpointEnvelopes"])
    ):
        reject(
            "RUNTIME_EVIDENCE_INVALID",
            "runtime evidence package shape or canonical encoding is invalid",
        )
    return RuntimeEvidencePackage(
        binding_handoff_envelope=value["bindingHandoffEnvelope"],
        evaluation_preflight_envelope=value["evaluationPreflightEnvelope"],
        redemption_preflight_envelope=value["redemptionPreflightEnvelope"],
        lease_envelope=value["leaseEnvelope"],
        checkpoint_envelopes=tuple(value["checkpointEnvelopes"]),
        archive_sha256=f"sha256:{hashlib.sha256(archive).hexdigest()}",
    )


class _Schemas:
    def __init__(self) -> None:
        schemas: dict[str, dict[str, Any]] = {}
        for path in SCHEMA_PATHS:
            try:
                schema = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                reject("RUNTIME_SCHEMA_UNAVAILABLE", f"cannot load {path.name}")
            if not isinstance(schema, dict):
                reject("RUNTIME_SCHEMA_UNAVAILABLE", f"{path.name} is not an object")
            Draft202012Validator.check_schema(schema)
            schemas[path.name] = schema
        self.schemas = schemas
        self.registry = Registry().with_resources(
            (
                schema["$id"],
                Resource.from_contents(schema),
            )
            for schema in schemas.values()
        )

    def validate(self, value: object, name: str, code: str) -> None:
        errors = sorted(
            Draft202012Validator(
                self.schemas[name],
                registry=self.registry,
                format_checker=FormatChecker(),
            ).iter_errors(value),
            key=lambda item: list(item.path),
        )
        if errors:
            first = errors[0]
            location = ".".join(str(part) for part in first.absolute_path) or "$"
            reject(code, f"invalid runtime receipt at {location}: {first.message}")


class RuntimeReceiptVerifier:
    """Fail-closed verifier for the external signed runtime authority chain."""

    def __init__(
        self,
        *,
        authority: dict[str, Any],
        runtime_trust_root: dict[str, Any],
        now: datetime | None = None,
        max_clock_skew_seconds: int = 30,
    ) -> None:
        if not 0 <= max_clock_skew_seconds <= 60:
            reject("RUNTIME_VERIFIER_CONFIG_INVALID", "clock skew is invalid")
        self.schemas = _Schemas()
        self.schemas.validate(
            runtime_trust_root,
            "faz22-6-view-only-runtime-trust-root-v1.schema.json",
            "RUNTIME_TRUST_ROOT_INVALID",
        )
        self.authority = authority
        self.runtime_trust_root = runtime_trust_root
        self.now = now or utc_now()
        self.clock_skew = timedelta(seconds=max_clock_skew_seconds)
        try:
            activation = authority["activation"]
            runtime_pin = authority["runtimeTrustRoot"]
            attestor = authority["attestor"]["receipt"]
            checkpoint = authority["checkpointCas"]
        except (KeyError, TypeError):
            reject("RUNTIME_AUTHORITY_INVALID", "runtime authority is incomplete")
        if (
            activation.get("state") != "active"
            or activation.get("blockers") != []
            or runtime_trust_root.get("activationState") != "active"
            or runtime_pin.get("digestDomain") != RUNTIME_TRUST_ROOT_DOMAIN
            or runtime_pin.get("expectedSha256")
            != runtime_trust_root_sha256(runtime_trust_root)
            or attestor.get("payloadType") != PREFLIGHT_PAYLOAD_TYPE
            or attestor.get("signerRole") != "runtime-attestor"
            or checkpoint["leaseRedeem"].get("receiptPayloadType")
            != LEASE_PAYLOAD_TYPE
            or checkpoint.get("receiptPayloadType") != CHECKPOINT_PAYLOAD_TYPE
            or checkpoint.get("receiptSignerRole") != "checkpoint-signer"
        ):
            reject(
                "RUNTIME_AUTHORITY_INACTIVE",
                "runtime authority or independently pinned trust root is inactive",
            )
        self.signer_ids = {
            "runtime-attestor": attestor["transitKeyId"],
            "checkpoint-signer": checkpoint["receiptTransitKeyId"],
        }
        self.keys: dict[str, dict[str, Any]] = {}
        for entry in runtime_trust_root["keys"]:
            key_id = entry["keyId"]
            if key_id in self.keys:
                reject("RUNTIME_TRUST_ROOT_INVALID", "runtime key ID is duplicated")
            self.keys[key_id] = entry
        if any(
            key_id not in self.keys or self.keys[key_id]["role"] != role
            for role, key_id in self.signer_ids.items()
        ):
            reject(
                "RUNTIME_AUTHORITY_INACTIVE",
                "runtime authority signer is absent from the pinned trust root",
            )
        self.transitions = checkpoint["stateMachine"]["transitions"]

    def _key_at(self, *, role: str, issued_at: datetime) -> tuple[str, bytes]:
        key_id = self.signer_ids[role]
        entry = self.keys[key_id]
        revoked_at = [
            parse_utc(item["revokedAt"], "runtimeTrustRoot.revokedAt")
            for item in self.runtime_trust_root["revocations"]
            if item["keyId"] == key_id
        ]
        if (
            entry.get("state") != "active"
            or entry.get("role") != role
            or not (
                parse_utc(entry["notBefore"], "runtimeTrustRoot.notBefore")
                <= issued_at
                < parse_utc(entry["notAfter"], "runtimeTrustRoot.notAfter")
            )
            or any(moment <= issued_at for moment in revoked_at)
        ):
            reject(
                "RUNTIME_SIGNER_INACTIVE",
                "runtime receipt signer was not active at issuance",
            )
        return key_id, decode_public_key(entry["publicKeyBase64"], key_id)

    def _decode_and_validate(
        self,
        *,
        envelope: dict[str, Any],
        payload_type: str,
        payload_schema: str,
        role: str,
        max_bytes: int,
        issued_field: str,
    ) -> VerifiedRuntimeReceipt:
        if not isinstance(envelope, dict) or not 1 <= len(canonical_bytes(envelope)) <= max_bytes:
            reject("RUNTIME_ENVELOPE_SIZE_INVALID", "runtime envelope size is invalid")
        self.schemas.validate(
            envelope,
            "faz22-6-dsse-envelope-v1.schema.json",
            "RUNTIME_ENVELOPE_INVALID",
        )
        if envelope.get("payloadType") != payload_type:
            reject("RUNTIME_PAYLOAD_TYPE_MISMATCH", "runtime payload type is invalid")
        encoded = envelope.get("payload")
        if not isinstance(encoded, str):
            reject("RUNTIME_ENVELOPE_INVALID", "runtime payload is not Base64 text")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            reject("RUNTIME_ENVELOPE_INVALID", "runtime payload Base64 is invalid")
        if base64.b64encode(raw).decode("ascii") != encoded:
            reject("RUNTIME_ENVELOPE_INVALID", "runtime payload Base64 is non-canonical")
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            reject("RUNTIME_PAYLOAD_INVALID", "runtime payload is not UTF-8 JSON")
        if not isinstance(payload, dict) or raw != canonical_bytes(payload):
            reject("RUNTIME_PAYLOAD_INVALID", "runtime payload is not canonical JCS")
        self.schemas.validate(payload, payload_schema, "RUNTIME_PAYLOAD_INVALID")
        issued_at = parse_utc(payload[issued_field], f"runtimeReceipt.{issued_field}")
        key_id, public_key = self._key_at(role=role, issued_at=issued_at)
        verified = verify_json_envelope(
            envelope,
            expected_payload_type=payload_type,
            allowed_keys={key_id: public_key},
            required_key_ids={key_id},
            exactly_one_signature=True,
        )
        if verified.payload != payload:
            reject("RUNTIME_SIGNATURE_INVALID", "runtime payload changed after signing")
        return VerifiedRuntimeReceipt(
            payload_type=payload_type,
            payload=payload,
            envelope=envelope,
            envelope_sha256=runtime_envelope_sha256(envelope),
            signer_key_id=key_id,
        )

    def _receipt_time(
        self,
        payload: dict[str, Any],
        *,
        as_of: datetime,
        max_age_seconds: int,
        allow_stale_seconds: int | None = None,
    ) -> tuple[datetime, datetime]:
        issued_at = parse_utc(payload["issuedAt"], "runtimeReceipt.issuedAt")
        expires_at = parse_utc(payload["expiresAt"], "runtimeReceipt.expiresAt")
        if (
            issued_at > as_of + self.clock_skew
            or expires_at <= issued_at
            or expires_at > issued_at + timedelta(seconds=max_age_seconds)
        ):
            reject("RUNTIME_RECEIPT_TIME_INVALID", "runtime receipt lifetime is invalid")
        if allow_stale_seconds is None:
            if as_of > expires_at + self.clock_skew:
                reject("RUNTIME_RECEIPT_EXPIRED", "runtime receipt has expired")
        elif as_of > issued_at + timedelta(seconds=allow_stale_seconds) + self.clock_skew:
            reject("RUNTIME_RECEIPT_STALE", "runtime receipt exceeds allowed staleness")
        return issued_at, expires_at

    @staticmethod
    def _binding(payload: dict[str, Any], binding: dict[str, Any]) -> None:
        expected_binding_sha = sha256_digest(
            {"domain": BINDING_DOMAIN, "binding": binding}
        )
        expected_transaction = sha256_digest(
            {"domain": TRANSACTION_ID_DOMAIN, "binding": binding}
        )
        if (
            payload.get("binding") != binding
            or payload.get("bindingSha256") != expected_binding_sha
            or payload.get("transactionIdSha256") != expected_transaction
        ):
            reject(
                "RUNTIME_BINDING_MISMATCH",
                "runtime receipt differs from the coordinator binding",
            )

    def verify_binding_handoff(
        self,
        *,
        envelope: dict[str, Any],
        coordinator_public_keys: dict[str, bytes],
        coordinator_key_id: str,
        authorization_bundle: VerifiedBundle,
        observed_at: datetime,
    ) -> VerifiedRuntimeReceipt:
        if (
            not isinstance(envelope, dict)
            or not 1
            <= len(canonical_bytes(envelope))
            <= MAX_BINDING_HANDOFF_ENVELOPE_BYTES
        ):
            reject(
                "RUNTIME_BINDING_HANDOFF_INVALID",
                "binding handoff envelope size is invalid",
            )
        self.schemas.validate(
            envelope,
            "faz22-6-dsse-envelope-v1.schema.json",
            "RUNTIME_BINDING_HANDOFF_INVALID",
        )
        if envelope.get("payloadType") != BINDING_HANDOFF_PAYLOAD_TYPE:
            reject(
                "RUNTIME_BINDING_HANDOFF_INVALID",
                "binding handoff payload type is invalid",
            )
        encoded = envelope.get("payload")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (binascii.Error, TypeError, ValueError):
            reject(
                "RUNTIME_BINDING_HANDOFF_INVALID",
                "binding handoff payload Base64 is invalid",
            )
        if base64.b64encode(raw).decode("ascii") != encoded:
            reject(
                "RUNTIME_BINDING_HANDOFF_INVALID",
                "binding handoff payload Base64 is non-canonical",
            )
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            reject(
                "RUNTIME_BINDING_HANDOFF_INVALID",
                "binding handoff payload is not UTF-8 JSON",
            )
        if not isinstance(payload, dict) or raw != canonical_bytes(payload):
            reject(
                "RUNTIME_BINDING_HANDOFF_INVALID",
                "binding handoff payload is not canonical JCS",
            )
        self.schemas.validate(
            payload,
            "faz22-6-view-only-transaction-binding-handoff-v1.schema.json",
            "RUNTIME_BINDING_HANDOFF_INVALID",
        )
        if coordinator_key_id not in coordinator_public_keys:
            reject(
                "RUNTIME_BINDING_HANDOFF_INVALID",
                "binding handoff coordinator is not pinned",
            )
        verified = verify_json_envelope(
            envelope,
            expected_payload_type=BINDING_HANDOFF_PAYLOAD_TYPE,
            allowed_keys={
                coordinator_key_id: coordinator_public_keys[coordinator_key_id]
            },
            required_key_ids={coordinator_key_id},
            exactly_one_signature=True,
        )
        if verified.payload != payload:
            reject(
                "RUNTIME_BINDING_HANDOFF_INVALID",
                "binding handoff changed after signature verification",
            )
        issued_at = parse_utc(payload["issuedAt"], "bindingHandoff.issuedAt")
        expires_at = parse_utc(payload["expiresAt"], "bindingHandoff.expiresAt")
        binding = payload["binding"]
        derivation = payload["derivation"]
        caller = payload["caller"]
        expected_binding_sha = sha256_digest(
            {"domain": BINDING_DOMAIN, "binding": binding}
        )
        expected_transaction = sha256_digest(
            {"domain": TRANSACTION_ID_DOMAIN, "binding": binding}
        )
        if (
            issued_at > observed_at + self.clock_skew
            or expires_at <= issued_at
            or expires_at > issued_at + timedelta(seconds=300)
            or payload["bindingSha256"] != expected_binding_sha
            or payload["transactionIdSha256"] != expected_transaction
            or binding["intentBundleSha256"]
            != authorization_bundle.bundle_digest
            or derivation["bundleEnvelopeSha256"]
            != authorization_bundle.bundle_digest
            or derivation["bundleRequestId"] != authorization_bundle.request_id
            or derivation["dispatchRunId"] != binding["runId"]
            or derivation["dispatchRunAttempt"] != binding["runAttempt"]
            or derivation["dispatchHeadSha"] != binding["headSha"]
            or derivation["dispatchWorkflowPath"] != binding["workflowPath"]
            or derivation["dispatchTriggeringActorId"]
            != binding["triggeringActorId"]
            or derivation["dispatchWorkflowRef"] != binding["workflowRef"]
            or caller["ref"] != binding["intentRef"]
            or caller["workflowRef"] != binding["workflowRef"]
            or caller["headSha"] != binding["headSha"]
            or caller["runId"] != binding["runId"]
            or caller["runAttempt"] != binding["runAttempt"]
            or caller["triggeringActorId"] != binding["triggeringActorId"]
        ):
            reject(
                "RUNTIME_BINDING_HANDOFF_MISMATCH",
                "binding handoff differs from signed bundle or live dispatch",
            )
        return VerifiedRuntimeReceipt(
            payload_type=BINDING_HANDOFF_PAYLOAD_TYPE,
            payload=payload,
            envelope=envelope,
            envelope_sha256=runtime_envelope_sha256(envelope),
            signer_key_id=coordinator_key_id,
        )

    def verify_preflight(
        self,
        *,
        envelope: dict[str, Any],
        binding: dict[str, Any],
        as_of: datetime | None = None,
        allow_stale_seconds: int | None = None,
        request: dict[str, Any] | None = None,
        binding_handoff_envelope: dict[str, Any] | None = None,
    ) -> VerifiedRuntimeReceipt:
        receipt = self._decode_and_validate(
            envelope=envelope,
            payload_type=PREFLIGHT_PAYLOAD_TYPE,
            payload_schema="faz22-6-view-only-live-preflight-attestation-v1.schema.json",
            role="runtime-attestor",
            max_bytes=MAX_PREFLIGHT_ENVELOPE_BYTES,
            issued_field="issuedAt",
        )
        payload = receipt.payload
        current = as_of or self.now
        issued_at, expires_at = self._receipt_time(
            payload,
            as_of=current,
            max_age_seconds=300,
            allow_stale_seconds=allow_stale_seconds,
        )
        self._binding(payload, binding)
        caller = payload["caller"]
        persona = payload["persona"]
        expected_subject = f"repo:{binding['repository']}:ref:{binding['intentRef']}"
        if (
            caller["subject"] != expected_subject
            or caller["repository"] != binding["repository"]
            or caller["repositoryId"] != str(binding["repositoryId"])
            or caller["workflowRef"] != binding["workflowRef"]
            or caller["ref"] != binding["intentRef"]
            or caller["headSha"] != binding["headSha"]
            or caller["runId"] != binding["runId"]
            or caller["runAttempt"] != binding["runAttempt"]
            or persona["identitySha256"]
            != binding["preflightPersonaIdentitySha256"]
            or persona["tenantIdSha256"] != binding["tenantIdSha256"]
            or parse_utc(persona["expiresAt"], "preflight.persona.expiresAt")
            < issued_at + timedelta(seconds=900)
        ):
            reject("RUNTIME_BINDING_MISMATCH", "preflight caller or persona is unbound")
        token_issued = parse_utc(caller["tokenIssuedAt"], "preflight.tokenIssuedAt")
        token_expires = parse_utc(caller["tokenExpiresAt"], "preflight.tokenExpiresAt")
        if (
            token_issued > issued_at + self.clock_skew
            or token_expires < issued_at
            or token_expires > token_issued + timedelta(seconds=300)
        ):
            reject("RUNTIME_RECEIPT_TIME_INVALID", "preflight OIDC lifetime is invalid")
        for check in payload["checks"].values():
            observed = parse_utc(check["observedAt"], "preflight.check.observedAt")
            check_expires = parse_utc(check["expiresAt"], "preflight.check.expiresAt")
            if (
                observed > issued_at + self.clock_skew
                or check_expires < issued_at
                or check_expires > expires_at
            ):
                reject("RUNTIME_RECEIPT_TIME_INVALID", "preflight check time is invalid")
        if request is not None:
            self.schemas.validate(
                request,
                "faz22-6-view-only-live-preflight-request-v1.schema.json",
                "RUNTIME_REQUEST_INVALID",
            )
            if (
                payload["requestId"] != request["requestId"]
                or payload["idempotencyKeySha256"]
                != request["idempotencyKeySha256"]
                or payload["requestSha256"]
                != sha256_digest(
                    {"domain": PREFLIGHT_REQUEST_DOMAIN, "request": request}
                )
            ):
                reject("RUNTIME_REQUEST_MISMATCH", "preflight request digest is invalid")
        if binding_handoff_envelope is not None and payload[
            "bindingHandoffEnvelopeSha256"
        ] != runtime_envelope_sha256(binding_handoff_envelope):
            reject(
                "RUNTIME_BINDING_MISMATCH",
                "preflight receipt differs from the signed binding handoff",
            )
        return receipt

    def verify_lease(
        self,
        *,
        envelope: dict[str, Any],
        binding: dict[str, Any],
        evaluation_preflight_envelope: dict[str, Any],
        redemption_preflight_envelope: dict[str, Any],
        authorization_envelope: dict[str, Any],
        authorization_bundle: VerifiedBundle,
        as_of: datetime | None = None,
        historical: bool = False,
        binding_handoff_envelope: dict[str, Any] | None = None,
    ) -> VerifiedRuntimeReceipt:
        receipt = self._decode_and_validate(
            envelope=envelope,
            payload_type=LEASE_PAYLOAD_TYPE,
            payload_schema="faz22-6-view-only-checkpoint-lease-v1.schema.json",
            role="checkpoint-signer",
            max_bytes=MAX_LEASE_ENVELOPE_BYTES,
            issued_field="issuedAt",
        )
        payload = receipt.payload
        signed_issued_at = parse_utc(payload["issuedAt"], "lease.issuedAt")
        issued_at, expires_at = self._receipt_time(
            payload,
            as_of=signed_issued_at if historical else (as_of or self.now),
            max_age_seconds=7200,
        )
        if historical and as_of is not None and issued_at > as_of + self.clock_skew:
            reject(
                "RUNTIME_RECEIPT_TIME_INVALID",
                "historical lease was issued after the observation boundary",
            )
        self._binding(payload, binding)
        evaluation = self.verify_preflight(
            envelope=evaluation_preflight_envelope,
            binding=binding,
            as_of=issued_at,
            allow_stale_seconds=7200,
            binding_handoff_envelope=binding_handoff_envelope,
        )
        redemption = self.verify_preflight(
            envelope=redemption_preflight_envelope,
            binding=binding,
            as_of=issued_at,
            binding_handoff_envelope=binding_handoff_envelope,
        )
        authorization_domain_digest = runtime_envelope_sha256(authorization_envelope)
        authorization_expires = authorization_bundle.expires_at
        caller = payload["authorizationCaller"]
        if (
            authorization_bundle.bundle_digest != binding["intentBundleSha256"]
            or sha256_digest(authorization_envelope)
            != authorization_bundle.bundle_digest
            or payload["evaluationPreflightReceiptEnvelopeSha256"]
            != evaluation.envelope_sha256
            or payload["redemptionPreflightReceiptEnvelopeSha256"]
            != redemption.envelope_sha256
            or payload["redemptionPreflightIssuedAt"]
            != redemption.payload["issuedAt"]
            or payload["authorizationEnvelopeSha256"]
            != authorization_domain_digest
            or issued_at < parse_utc(
                redemption.payload["issuedAt"], "redemptionPreflight.issuedAt"
            )
            or expires_at > authorization_expires
            or caller["subject"]
            != f"repo:{binding['repository']}:environment:{binding['environment']}"
            or caller["runId"] != binding["runId"]
            or caller["runAttempt"] != binding["runAttempt"]
            or caller["headSha"] != binding["headSha"]
            or payload["executorProfile"]["subject"]
            != f"repo:{binding['repository']}:ref:{binding['intentRef']}"
        ):
            reject("RUNTIME_LEASE_MISMATCH", "checkpoint lease authority is unbound")
        return receipt

    def verify_checkpoint(
        self,
        *,
        envelope: dict[str, Any],
        lease: VerifiedRuntimeReceipt,
        binding: dict[str, Any],
        as_of: datetime | None = None,
        request: dict[str, Any] | None = None,
        previous: VerifiedRuntimeReceipt | None = None,
        historical: bool = False,
    ) -> VerifiedRuntimeReceipt:
        if lease.payload_type != LEASE_PAYLOAD_TYPE:
            reject("RUNTIME_LEASE_MISMATCH", "checkpoint lease is not verified")
        receipt = self._decode_and_validate(
            envelope=envelope,
            payload_type=CHECKPOINT_PAYLOAD_TYPE,
            payload_schema="faz22-6-view-only-external-checkpoint-receipt-v1.schema.json",
            role="checkpoint-signer",
            max_bytes=MAX_CHECKPOINT_ENVELOPE_BYTES,
            issued_field="createdAt",
        )
        payload = receipt.payload
        created_at = parse_utc(payload["createdAt"], "checkpoint.createdAt")
        expires_at = parse_utc(payload["expiresAt"], "checkpoint.expiresAt")
        lease_issued = parse_utc(lease.payload["issuedAt"], "lease.issuedAt")
        lease_expires = parse_utc(lease.payload["expiresAt"], "lease.expiresAt")
        current = created_at if historical else (as_of or self.now)
        if historical and as_of is not None and created_at > as_of + self.clock_skew:
            reject(
                "RUNTIME_RECEIPT_TIME_INVALID",
                "historical checkpoint was created after the observation boundary",
            )
        self._binding(payload, binding)
        if (
            created_at > current + self.clock_skew
            or not lease_issued <= created_at < lease_expires
            or expires_at != lease_expires
            or current > expires_at + self.clock_skew
            or payload["leaseId"] != lease.payload["leaseId"]
            or payload["leaseEnvelopeSha256"]
            != runtime_envelope_sha256(lease.envelope)
            or payload["evaluationPreflightReceiptEnvelopeSha256"]
            != lease.payload["evaluationPreflightReceiptEnvelopeSha256"]
            or payload["redemptionPreflightReceiptEnvelopeSha256"]
            != lease.payload["redemptionPreflightReceiptEnvelopeSha256"]
            or payload["authorizationEnvelopeSha256"]
            != lease.payload["authorizationEnvelopeSha256"]
        ):
            reject("RUNTIME_CHECKPOINT_MISMATCH", "checkpoint differs from its lease")
        sequence = payload["sequence"]
        if previous is None:
            if (
                sequence != 0
                or payload["previousState"] is not None
                or payload["previousStoredObjectSha256"] is not None
                or payload["state"] != "DECISION_AUTHORIZED"
            ):
                reject(
                    "RUNTIME_CHECKPOINT_SEQUENCE_INVALID",
                    "initial checkpoint is not DECISION_AUTHORIZED sequence zero",
                )
        else:
            prior = previous.payload
            if (
                previous.payload_type != CHECKPOINT_PAYLOAD_TYPE
                or sequence != prior["sequence"] + 1
                or payload["previousState"] != prior["state"]
                or payload["previousStoredObjectSha256"]
                != prior["storedObjectSha256"]
                or payload["state"] not in self.transitions[prior["state"]]
            ):
                reject(
                    "RUNTIME_CHECKPOINT_SEQUENCE_INVALID",
                    "checkpoint sequence, previous digest or transition is invalid",
                )
        caller = payload["executorCaller"]
        if (
            caller["subject"]
            != f"repo:{binding['repository']}:ref:{binding['intentRef']}"
            or caller["runId"] != binding["runId"]
            or caller["runAttempt"] != binding["runAttempt"]
            or caller["headSha"] != binding["headSha"]
        ):
            reject("RUNTIME_CHECKPOINT_MISMATCH", "checkpoint executor is unbound")
        if request is not None:
            self.schemas.validate(
                request,
                "faz22-6-view-only-external-checkpoint-create-v1.schema.json",
                "RUNTIME_REQUEST_INVALID",
            )
            without_lease = dict(request)
            lease_envelope = without_lease.pop("leaseEnvelope")
            expected_stored = sha256_digest(
                {
                    "domain": CHECKPOINT_STORED_OBJECT_DOMAIN,
                    "request": without_lease,
                }
            )
            comparable = {
                "transactionIdSha256",
                "bindingSha256",
                "sequence",
                "previousState",
                "state",
                "reasonCode",
                "localCheckpointSha256",
                "localPayloadSha256",
                "previousStoredObjectSha256",
                "idempotencyKeySha256",
                "terminal",
            }
            if (
                runtime_envelope_sha256(lease_envelope)
                != runtime_envelope_sha256(lease.envelope)
                or any(payload[name] != request[name] for name in comparable)
                or payload["storedObjectSha256"] != expected_stored
            ):
                reject(
                    "RUNTIME_CHECKPOINT_MISMATCH",
                    "checkpoint receipt differs from its immutable create request",
                )
        return receipt

    def verify_chain(
        self,
        *,
        binding_handoff_envelope: dict[str, Any],
        coordinator_public_keys: dict[str, bytes],
        coordinator_key_id: str,
        evaluation_preflight_envelope: dict[str, Any],
        redemption_preflight_envelope: dict[str, Any],
        lease_envelope: dict[str, Any],
        authorization_envelope: dict[str, Any],
        authorization_bundle: VerifiedBundle,
        checkpoint_envelopes: tuple[dict[str, Any], ...],
        final_state: dict[str, Any],
        observed_at: datetime,
    ) -> VerifiedRuntimeChain:
        """Verify the complete signed external suffix against the local final ledger.

        Runtime receipts are authority artifacts, so reconciliation may occur after
        their action TTL. Historical verification still requires every signed
        issuance/create time to be inside the original authority window and no
        later than the trusted live-run observation boundary.
        """

        binding_handoff = self.verify_binding_handoff(
            envelope=binding_handoff_envelope,
            coordinator_public_keys=coordinator_public_keys,
            coordinator_key_id=coordinator_key_id,
            authorization_bundle=authorization_bundle,
            observed_at=observed_at,
        )
        binding = binding_handoff.payload["binding"]

        lease = self.verify_lease(
            envelope=lease_envelope,
            binding=binding,
            evaluation_preflight_envelope=evaluation_preflight_envelope,
            redemption_preflight_envelope=redemption_preflight_envelope,
            authorization_envelope=authorization_envelope,
            authorization_bundle=authorization_bundle,
            as_of=observed_at,
            historical=True,
            binding_handoff_envelope=binding_handoff_envelope,
        )
        evaluation = self.verify_preflight(
            envelope=evaluation_preflight_envelope,
            binding=binding,
            as_of=parse_utc(lease.payload["issuedAt"], "lease.issuedAt"),
            allow_stale_seconds=7200,
            binding_handoff_envelope=binding_handoff_envelope,
        )
        redemption = self.verify_preflight(
            envelope=redemption_preflight_envelope,
            binding=binding,
            as_of=parse_utc(lease.payload["issuedAt"], "lease.issuedAt"),
            binding_handoff_envelope=binding_handoff_envelope,
        )
        local = final_state.get("checkpoints")
        if (
            not isinstance(local, list)
            or not local
            or final_state.get("sequence") != len(local) - 1
            or final_state.get("currentState") not in {"COMPLETED", "FAILED_CLEAN"}
            or local[-1].get("state") != final_state.get("currentState")
        ):
            reject(
                "RUNTIME_CHAIN_LOCAL_STATE_INVALID",
                "runtime reconciliation requires a verified terminal local ledger",
            )
        decision_indexes = [
            index
            for index, checkpoint in enumerate(local)
            if isinstance(checkpoint, dict)
            and checkpoint.get("state") == "DECISION_AUTHORIZED"
        ]
        if len(decision_indexes) != 1:
            reject(
                "RUNTIME_CHAIN_LOCAL_STATE_INVALID",
                "local ledger has no unique DECISION_AUTHORIZED boundary",
            )
        local_suffix = local[decision_indexes[0] :]
        if (
            not checkpoint_envelopes
            or len(checkpoint_envelopes) != len(local_suffix)
            or len(checkpoint_envelopes) > lease.payload["maxWrites"]
        ):
            reject(
                "RUNTIME_CHAIN_INCOMPLETE",
                "external signed checkpoint chain does not cover the local authority suffix",
            )

        receipts: list[VerifiedRuntimeReceipt] = []
        previous: VerifiedRuntimeReceipt | None = None
        previous_created: datetime | None = None
        for sequence, (envelope, local_checkpoint) in enumerate(
            zip(checkpoint_envelopes, local_suffix, strict=True)
        ):
            receipt = self.verify_checkpoint(
                envelope=envelope,
                lease=lease,
                binding=binding,
                as_of=observed_at,
                previous=previous,
                historical=True,
            )
            payload = receipt.payload
            created_at = parse_utc(payload["createdAt"], "checkpoint.createdAt")
            if (
                payload["sequence"] != sequence
                or payload["state"] != local_checkpoint.get("state")
                or payload["reasonCode"] != local_checkpoint.get("reasonCode")
                or payload["localCheckpointSha256"]
                != local_checkpoint.get("checkpointSha256")
                or payload["localPayloadSha256"]
                != local_checkpoint.get("payloadSha256")
                or (previous_created is not None and created_at < previous_created)
                or (payload["terminal"] and sequence != len(local_suffix) - 1)
            ):
                reject(
                    "RUNTIME_CHAIN_LOCAL_MISMATCH",
                    "external signed checkpoint differs from the local final ledger",
                )
            receipts.append(receipt)
            previous = receipt
            previous_created = created_at

        terminal = receipts[-1]
        if (
            terminal.payload["terminal"] is not True
            or terminal.payload["state"] != final_state["currentState"]
            or terminal.payload["state"] not in {"COMPLETED", "FAILED_CLEAN"}
            or terminal.payload["sequence"]
            != lease.payload["sequenceMinimumInclusive"] + len(receipts) - 1
            or terminal.payload["sequence"]
            > lease.payload["sequenceMaximumInclusive"]
        ):
            reject(
                "RUNTIME_CHAIN_TERMINAL_INVALID",
                "external signed checkpoint chain has no exact terminal receipt",
            )
        return VerifiedRuntimeChain(
            binding_handoff=binding_handoff,
            evaluation_preflight=evaluation,
            redemption_preflight=redemption,
            lease=lease,
            checkpoints=tuple(receipts),
            terminal=terminal,
        )


__all__ = [
    "BINDING_HANDOFF_PAYLOAD_TYPE",
    "CHECKPOINT_PAYLOAD_TYPE",
    "LEASE_PAYLOAD_TYPE",
    "PREFLIGHT_PAYLOAD_TYPE",
    "RuntimeReceiptVerifier",
    "RuntimeEvidencePackage",
    "VerifiedRuntimeChain",
    "VerifiedRuntimeReceipt",
    "runtime_envelope_sha256",
    "runtime_evidence_from_archive",
    "runtime_trust_root_sha256",
]
