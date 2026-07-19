"""Fail-closed verification of the same-run VIEW_ONLY transaction preflight."""

from __future__ import annotations

import hashlib
import io
import json
import re
import stat
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .canonical import sha256_digest
from .errors import reject
from .timeutil import parse_utc


MAX_PREFLIGHT_ARCHIVE_BYTES = 4 * 1024 * 1024
MAX_PREFLIGHT_FILE_BYTES = 1024 * 1024
MAX_FINAL_ARCHIVE_BYTES = 8 * 1024 * 1024
MAX_FINAL_FILE_BYTES = 4 * 1024 * 1024
MAX_ZIP_COMPRESSION_RATIO = 100
SHA256 = re.compile(r"^sha256:[a-f0-9]{64}$")
CHECKSUM_LINE = re.compile(r"^(?P<hex>[a-f0-9]{64})  [.]?/preflight[.]json\n$")
REASON = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
HEAD_SHA = re.compile(r"^[a-f0-9]{40}$")
PILOT_SECONDS = {300, 600, 900, 1200, 1800}
TRANSACTION_TRANSITIONS = {
    "INIT": {"PREFLIGHT_VERIFIED"},
    "PREFLIGHT_VERIFIED": {"DECISION_AUTHORIZED"},
    "DECISION_AUTHORIZED": {
        "LIVE_REVALIDATED",
        "FAILURE_CAPTURED",
        "ARTIFACTS_STAGE_FAILED",
    },
    "LIVE_REVALIDATED": {
        "ACTIVATED",
        "FAILURE_CAPTURED",
        "ARTIFACTS_STAGE_FAILED",
    },
    "ACTIVATED": {
        "CONSENT_PENDING",
        "FAILURE_CAPTURED",
        "ARTIFACTS_STAGE_FAILED",
    },
    "CONSENT_PENDING": {
        "EVIDENCE_COLLECTED",
        "FAILURE_CAPTURED",
        "ARTIFACTS_STAGE_FAILED",
    },
    "EVIDENCE_COLLECTED": {
        "EVIDENCE_VERIFIED",
        "FAILURE_CAPTURED",
        "ARTIFACTS_STAGE_FAILED",
    },
    "EVIDENCE_VERIFIED": {
        "ARTIFACTS_STAGED",
        "FAILURE_CAPTURED",
        "ARTIFACTS_STAGE_FAILED",
    },
    "FAILURE_CAPTURED": {"ARTIFACTS_STAGED", "ARTIFACTS_STAGE_FAILED"},
    "ARTIFACTS_STAGE_FAILED": {"ROLLBACK_PENDING"},
    "ARTIFACTS_STAGED": {"ROLLBACK_PENDING"},
    "ROLLBACK_PENDING": {"ROLLED_BACK"},
    "ROLLED_BACK": {"COMPLETED", "FAILED_CLEAN"},
    "COMPLETED": set(),
    "FAILED_CLEAN": set(),
}


@dataclass(frozen=True)
class VerifiedTransactionPreflight:
    payload: dict[str, Any]
    preflight_sha256: str
    archive_sha256: str


@dataclass(frozen=True)
class VerifiedTransactionFinal:
    state: dict[str, Any]
    state_sha256: str
    archive_sha256: str
    conclusion: str
    target_state: str
    pre_rollback_artifact_id: int | None
    pre_rollback_artifact_digest: str | None


def _safe_entries(archive: bytes) -> dict[str, bytes]:
    if not 1 <= len(archive) <= MAX_PREFLIGHT_ARCHIVE_BYTES:
        reject(
            "TRANSACTION_PREFLIGHT_ARCHIVE_INVALID",
            "preflight archive is empty or exceeds the bounded size",
        )
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            infos = bundle.infolist()
            if len(infos) != 2 or {item.filename for item in infos} != {
                "preflight.json",
                "SHA256SUMS",
            }:
                reject(
                    "TRANSACTION_PREFLIGHT_ARCHIVE_INVALID",
                    "preflight archive must contain exactly preflight.json and SHA256SUMS",
                )
            result: dict[str, bytes] = {}
            for info in infos:
                mode = info.external_attr >> 16
                if (
                    info.is_dir()
                    or info.flag_bits & 0x1
                    or stat.S_ISLNK(mode)
                    or not 1 <= info.file_size <= MAX_PREFLIGHT_FILE_BYTES
                    or info.compress_size < 1
                    or info.file_size > info.compress_size * MAX_ZIP_COMPRESSION_RATIO
                    or "/" in info.filename
                    or "\\" in info.filename
                ):
                    reject(
                        "TRANSACTION_PREFLIGHT_ARCHIVE_INVALID",
                        "preflight archive contains an unsafe entry",
                    )
                raw = bundle.read(info)
                if len(raw) != info.file_size:
                    reject(
                        "TRANSACTION_PREFLIGHT_ARCHIVE_INVALID",
                        "preflight entry size differs from ZIP metadata",
                    )
                result[info.filename] = raw
            return result
    except (zipfile.BadZipFile, KeyError, RuntimeError):
        reject(
            "TRANSACTION_PREFLIGHT_ARCHIVE_INVALID",
            "preflight artifact is not a safe ZIP archive",
        )


def _safe_final_entries(archive: bytes) -> dict[str, bytes]:
    if not 1 <= len(archive) <= MAX_FINAL_ARCHIVE_BYTES:
        reject(
            "TRANSACTION_FINAL_ARCHIVE_INVALID",
            "final archive is empty or exceeds the bounded size",
        )
    required = {"state.json", "rollback.stdout", "rollback.stderr"}
    allowed = required | {"pre-rollback-upload-receipt.json"}
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            infos = bundle.infolist()
            names = [item.filename for item in infos]
            if len(names) != len(set(names)) or not required.issubset(names):
                reject(
                    "TRANSACTION_FINAL_ARCHIVE_INVALID",
                    "final archive is missing a required unique receipt file",
                )
            if not set(names).issubset(allowed):
                reject(
                    "TRANSACTION_FINAL_ARCHIVE_INVALID",
                    "final archive contains a non-contract file",
                )
            result: dict[str, bytes] = {}
            for info in infos:
                mode = info.external_attr >> 16
                if (
                    info.is_dir()
                    or info.flag_bits & 0x1
                    or stat.S_ISLNK(mode)
                    or not 0 <= info.file_size <= MAX_FINAL_FILE_BYTES
                    or (info.file_size and info.compress_size < 1)
                    or (
                        info.compress_size
                        and info.file_size
                        > info.compress_size * MAX_ZIP_COMPRESSION_RATIO
                    )
                    or "/" in info.filename
                    or "\\" in info.filename
                ):
                    reject(
                        "TRANSACTION_FINAL_ARCHIVE_INVALID",
                        "final archive contains an unsafe entry",
                    )
                raw = bundle.read(info)
                if len(raw) != info.file_size:
                    reject(
                        "TRANSACTION_FINAL_ARCHIVE_INVALID",
                        "final entry size differs from ZIP metadata",
                    )
                result[info.filename] = raw
    except (zipfile.BadZipFile, KeyError, RuntimeError):
        reject(
            "TRANSACTION_FINAL_ARCHIVE_INVALID",
            "final artifact is not a safe ZIP archive",
        )
    if not result["state.json"] or not result["rollback.stdout"]:
        reject(
            "TRANSACTION_FINAL_ARCHIVE_INVALID",
            "final state and rollback receipt must be non-empty",
        )
    return result


def _json_object(raw: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        reject("TRANSACTION_FINAL_INVALID", f"{label} is not valid UTF-8 JSON")
    if not isinstance(value, dict):
        reject("TRANSACTION_FINAL_INVALID", f"{label} is not a JSON object")
    return value


def _require_digest(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        reject("TRANSACTION_FINAL_INVALID", f"{label} is not canonical SHA-256")
    return value


def _verify_transaction_state(
    state: dict[str, Any],
    *,
    repository: str,
    workflow_ref: str,
    head_sha: str,
    run_id: int,
    run_attempt: int,
    subject: dict[str, Any],
    grant: dict[str, Any],
    preflight_sha256: str,
    rollback_sha256: str,
    observed_at: datetime,
    max_clock_skew_seconds: int,
) -> tuple[str, str]:
    top_fields = {
        "schemaVersion",
        "binding",
        "currentState",
        "sequence",
        "reasonCode",
        "checkpoints",
    }
    if set(state) != top_fields or state.get("schemaVersion") != (
        "faz22.6.viewOnlyTransactionState.v1"
    ):
        reject(
            "TRANSACTION_FINAL_STATE_INVALID",
            "transaction state top-level contract is invalid",
        )
    binding = state.get("binding")
    binding_fields = {
        "repository",
        "workflowRef",
        "headSha",
        "runId",
        "runAttempt",
        "endpointIdSha256",
        "deviceHostnameSha256",
        "policySha256",
        "maskPolicySha256",
        "pilotSeconds",
        "preflightSha256",
        "authorizationSha256",
        "watchdogExpiresEpoch",
        "sessionSha256",
    }
    if not isinstance(binding, dict) or set(binding) != binding_fields:
        reject(
            "TRANSACTION_FINAL_STATE_INVALID",
            "transaction state binding contract is invalid",
        )
    expected = {
        "repository": repository,
        "workflowRef": workflow_ref,
        "headSha": head_sha,
        "runId": run_id,
        "runAttempt": run_attempt,
        "endpointIdSha256": subject["endpointIdSha256"],
        "deviceHostnameSha256": subject["deviceHostnameSha256"],
        "policySha256": subject["pilotOwnerPolicySha256"],
        "maskPolicySha256": subject["maskPolicySha256"],
        "pilotSeconds": subject["pilotSeconds"],
        "preflightSha256": preflight_sha256,
    }
    if any(binding.get(name) != value for name, value in expected.items()):
        reject(
            "TRANSACTION_FINAL_BINDING_MISMATCH",
            "final transaction state differs from the signed same-run subject",
        )
    if (
        REPOSITORY.fullmatch(binding["repository"]) is None
        or HEAD_SHA.fullmatch(binding["headSha"]) is None
        or binding["pilotSeconds"] not in PILOT_SECONDS
        or not isinstance(binding["runId"], int)
        or isinstance(binding["runId"], bool)
        or binding["runId"] < 1
        or not isinstance(binding["runAttempt"], int)
        or isinstance(binding["runAttempt"], bool)
        or binding["runAttempt"] < 1
    ):
        reject(
            "TRANSACTION_FINAL_STATE_INVALID",
            "transaction state binding values are invalid",
        )
    for name in (
        "endpointIdSha256",
        "deviceHostnameSha256",
        "policySha256",
        "maskPolicySha256",
        "preflightSha256",
        "authorizationSha256",
    ):
        _require_digest(binding.get(name), label=name)
    session_sha256 = binding.get("sessionSha256")
    if session_sha256 is not None:
        _require_digest(session_sha256, label="sessionSha256")
    watchdog_epoch = binding.get("watchdogExpiresEpoch")
    if (
        not isinstance(watchdog_epoch, int)
        or isinstance(watchdog_epoch, bool)
        or watchdog_epoch < 1
    ):
        reject(
            "TRANSACTION_FINAL_STATE_INVALID",
            "watchdog expiry is not a positive epoch",
        )

    current_state = state.get("currentState")
    reason_code = state.get("reasonCode")
    checkpoints = state.get("checkpoints")
    if (
        current_state not in {"COMPLETED", "FAILED_CLEAN"}
        or not isinstance(reason_code, str)
        or REASON.fullmatch(reason_code) is None
        or not isinstance(checkpoints, list)
        or not checkpoints
        or state.get("sequence") != len(checkpoints) - 1
    ):
        reject(
            "TRANSACTION_FINAL_STATE_INVALID",
            "transaction state is not a canonical terminal ledger",
        )

    grant_start = parse_utc(grant["notBefore"], "grant.notBefore")
    grant_end = parse_utc(grant["expiresAt"], "grant.expiresAt")
    skew = timedelta(seconds=max_clock_skew_seconds)
    if watchdog_epoch > int((grant_end + skew).timestamp()):
        reject(
            "TRANSACTION_FINAL_TTL_INVALID",
            "transaction watchdog extends beyond the signed grant",
        )

    previous: str | None = None
    previous_time: datetime | None = None
    authorization_seen = False
    evidence_seen = False
    failure_seen = False
    observed_states: set[str] = set()
    decision_time: datetime | None = None
    rollback_payload: str | None = None
    for index, checkpoint in enumerate(checkpoints):
        checkpoint_fields = {
            "sequence",
            "state",
            "observedAt",
            "reasonCode",
            "payloadSha256",
            "bindingSha256",
            "previousCheckpointSha256",
            "checkpointSha256",
        }
        if (
            not isinstance(checkpoint, dict)
            or set(checkpoint) != checkpoint_fields
            or checkpoint.get("sequence") != index
            or checkpoint.get("state") not in TRANSACTION_TRANSITIONS
            or not isinstance(checkpoint.get("reasonCode"), str)
            or REASON.fullmatch(checkpoint["reasonCode"]) is None
        ):
            reject(
                "TRANSACTION_FINAL_STATE_INVALID",
                "transaction checkpoint shape or sequence is invalid",
            )
        payload_sha256 = _require_digest(
            checkpoint.get("payloadSha256"), label="checkpoint payload"
        )
        _require_digest(checkpoint.get("bindingSha256"), label="checkpoint binding")
        checkpoint_sha256 = _require_digest(
            checkpoint.get("checkpointSha256"), label="checkpoint"
        )
        if checkpoint.get("previousCheckpointSha256") != previous:
            reject(
                "TRANSACTION_FINAL_STATE_INVALID",
                "transaction checkpoint previous digest is invalid",
            )
        unsigned = dict(checkpoint)
        unsigned.pop("checkpointSha256")
        if sha256_digest(unsigned) != checkpoint_sha256:
            reject(
                "TRANSACTION_FINAL_STATE_INVALID",
                "transaction checkpoint digest verification failed",
            )
        checkpoint_time = parse_utc(
            checkpoint.get("observedAt"), "transaction.checkpoint.observedAt"
        )
        if (
            checkpoint_time < grant_start - skew
            or checkpoint_time > grant_end + skew
            or checkpoint_time > observed_at + skew
            or (previous_time is not None and checkpoint_time < previous_time)
        ):
            reject(
                "TRANSACTION_FINAL_TIME_INVALID",
                "transaction checkpoint time is outside the signed monotonic window",
            )
        checkpoint_state = checkpoint["state"]
        observed_states.add(checkpoint_state)
        if checkpoint_state == "DECISION_AUTHORIZED":
            authorization_seen = True
            decision_time = checkpoint_time
        if checkpoint_state == "EVIDENCE_COLLECTED":
            evidence_seen = True
        if checkpoint_state in {"FAILURE_CAPTURED", "ARTIFACTS_STAGE_FAILED"}:
            failure_seen = True
        historical_binding = dict(binding)
        if not authorization_seen:
            historical_binding["authorizationSha256"] = None
            historical_binding["watchdogExpiresEpoch"] = None
        if not evidence_seen:
            historical_binding["sessionSha256"] = None
        if checkpoint["bindingSha256"] != sha256_digest(historical_binding):
            reject(
                "TRANSACTION_FINAL_STATE_INVALID",
                "transaction checkpoint historical binding is invalid",
            )
        if index == 0:
            if checkpoint_state != "INIT" or previous is not None:
                reject(
                    "TRANSACTION_FINAL_STATE_INVALID",
                    "transaction checkpoint chain does not start at INIT",
                )
        elif checkpoint_state not in TRANSACTION_TRANSITIONS[checkpoints[index - 1]["state"]]:
            reject(
                "TRANSACTION_FINAL_STATE_INVALID",
                "transaction checkpoint transition is invalid",
            )
        if checkpoint_state == "ROLLED_BACK":
            rollback_payload = payload_sha256
        previous = checkpoint_sha256
        previous_time = checkpoint_time

    tail = checkpoints[-1]
    if (
        tail["state"] != current_state
        or tail["reasonCode"] != reason_code
        or tail["bindingSha256"] != sha256_digest(binding)
        or checkpoints[0]["payloadSha256"] != preflight_sha256
        or checkpoints[1]["state"] != "PREFLIGHT_VERIFIED"
        or checkpoints[1]["payloadSha256"] != preflight_sha256
        or not authorization_seen
        or evidence_seen != (session_sha256 is not None)
        or decision_time is None
        or int(decision_time.timestamp()) >= watchdog_epoch
        or previous_time is None
        or int(previous_time.timestamp()) > watchdog_epoch
        or rollback_payload != rollback_sha256
        or tail["payloadSha256"] != rollback_sha256
    ):
        reject(
            "TRANSACTION_FINAL_STATE_INVALID",
            "transaction terminal ledger bindings are inconsistent",
        )
    required_common = {
        "DECISION_AUTHORIZED",
        "LIVE_REVALIDATED",
        "ACTIVATED",
        "ROLLBACK_PENDING",
        "ROLLED_BACK",
    }
    if not required_common.issubset(observed_states):
        reject(
            "TRANSACTION_FINAL_STATE_INVALID",
            "transaction terminal ledger omits a required lifecycle checkpoint",
        )
    if current_state == "COMPLETED":
        required_success = {
            "CONSENT_PENDING",
            "EVIDENCE_COLLECTED",
            "EVIDENCE_VERIFIED",
            "ARTIFACTS_STAGED",
        }
        if failure_seen or not required_success.issubset(observed_states):
            reject(
                "TRANSACTION_FINAL_STATE_INVALID",
                "COMPLETED is not a verified success and rollback path",
            )
        return "success", "Succeeded"
    if not failure_seen or not {
        "ARTIFACTS_STAGED",
        "ARTIFACTS_STAGE_FAILED",
    }.intersection(observed_states):
        reject(
            "TRANSACTION_FINAL_STATE_INVALID",
            "FAILED_CLEAN lacks a captured failure and artifact disposition",
        )
    return "rolled-back", "RolledBack"


def _verify_upload_receipt(
    raw: bytes,
    *,
    head_sha: str,
    run_id: int,
    run_attempt: int,
    grant: dict[str, Any],
    observed_at: datetime,
    max_clock_skew_seconds: int,
) -> tuple[dict[str, Any], str]:
    receipt = _json_object(raw, label="pre-rollback upload receipt")
    expected_fields = {
        "schemaVersion",
        "artifactId",
        "artifactDigest",
        "artifactUrl",
        "packageSha256",
        "headSha",
        "runId",
        "runAttempt",
        "observedAt",
    }
    if set(receipt) != expected_fields or receipt.get("schemaVersion") != (
        "faz22.6.viewOnlyTransactionArtifactUploadReceipt.v1"
    ):
        reject(
            "TRANSACTION_FINAL_RECEIPT_INVALID",
            "pre-rollback upload receipt contract is invalid",
        )
    if (
        receipt.get("headSha") != head_sha
        or receipt.get("runId") != run_id
        or receipt.get("runAttempt") != run_attempt
        or not isinstance(receipt.get("artifactId"), int)
        or isinstance(receipt.get("artifactId"), bool)
        or receipt["artifactId"] < 1
        or not isinstance(receipt.get("artifactUrl"), str)
        or not receipt["artifactUrl"].startswith("https://github.com/")
        or "?" in receipt["artifactUrl"]
    ):
        reject(
            "TRANSACTION_FINAL_RECEIPT_INVALID",
            "pre-rollback upload receipt differs from the live run",
        )
    _require_digest(receipt.get("artifactDigest"), label="artifactDigest")
    _require_digest(receipt.get("packageSha256"), label="packageSha256")
    receipt_time = parse_utc(
        receipt.get("observedAt"), "transaction.uploadReceipt.observedAt"
    )
    grant_start = parse_utc(grant["notBefore"], "grant.notBefore")
    grant_end = parse_utc(grant["expiresAt"], "grant.expiresAt")
    skew = timedelta(seconds=max_clock_skew_seconds)
    if (
        receipt_time < grant_start - skew
        or receipt_time > grant_end + skew
        or receipt_time > observed_at + skew
    ):
        reject(
            "TRANSACTION_FINAL_TIME_INVALID",
            "pre-rollback upload receipt is outside the signed grant",
        )
    return receipt, f"sha256:{hashlib.sha256(raw).hexdigest()}"


def verify_transaction_preflight(
    archive: bytes,
    *,
    repository: str,
    workflow_path: str,
    intent_ref: str,
    head_sha: str,
    run_id: int,
    run_attempt: int,
    subject: dict[str, Any],
    grant: dict[str, Any],
    observed_at: datetime,
    max_clock_skew_seconds: int,
) -> VerifiedTransactionPreflight:
    """Bind a completed read-only preflight to the protected callback run."""

    entries = _safe_entries(archive)
    manifest = entries["preflight.json"]
    checksum_raw = entries["SHA256SUMS"]
    try:
        checksum = checksum_raw.decode("ascii")
    except UnicodeDecodeError:
        reject(
            "TRANSACTION_PREFLIGHT_CHECKSUM_INVALID",
            "preflight checksum manifest is not ASCII",
        )
    match = CHECKSUM_LINE.fullmatch(checksum)
    manifest_hex = hashlib.sha256(manifest).hexdigest()
    if match is None or match.group("hex") != manifest_hex:
        reject(
            "TRANSACTION_PREFLIGHT_CHECKSUM_INVALID",
            "preflight checksum does not bind the manifest",
        )
    try:
        payload = json.loads(manifest)
    except (UnicodeDecodeError, json.JSONDecodeError):
        reject(
            "TRANSACTION_PREFLIGHT_MANIFEST_INVALID",
            "preflight manifest is not valid UTF-8 JSON",
        )
    if not isinstance(payload, dict):
        reject(
            "TRANSACTION_PREFLIGHT_MANIFEST_INVALID",
            "preflight manifest is not an object",
        )
    expected_keys = {
        "schemaVersion",
        "repository",
        "workflowRef",
        "headSha",
        "runId",
        "runAttempt",
        "endpointIdSha256",
        "deviceHostnameSha256",
        "policySha256",
        "maskPolicySha256",
        "expectedImageDigest",
        "pilotSeconds",
        "observedAt",
        "mutationCount",
        "attendedConsentAttempted",
        "staleWatchdogReclaimRequired",
        "staleWatchdogAuthorizationSha256",
        "verdict",
    }
    if set(payload) != expected_keys:
        reject(
            "TRANSACTION_PREFLIGHT_MANIFEST_INVALID",
            "preflight manifest fields are not the exact v1 contract",
        )
    expected_ref = f"{repository}/{workflow_path}@{intent_ref}"
    expected_values = {
        "schemaVersion": "faz22.6.viewOnlyTransactionPreflight.v1",
        "repository": repository,
        "workflowRef": expected_ref,
        "headSha": head_sha,
        "runId": run_id,
        "runAttempt": run_attempt,
        "endpointIdSha256": subject["endpointIdSha256"],
        "deviceHostnameSha256": subject["deviceHostnameSha256"],
        "policySha256": subject["pilotOwnerPolicySha256"],
        "maskPolicySha256": subject["maskPolicySha256"],
        "expectedImageDigest": subject["runtimeImageDigest"],
        "pilotSeconds": subject["pilotSeconds"],
        "mutationCount": 0,
        "attendedConsentAttempted": False,
        "verdict": "PASS",
    }
    if any(payload.get(key) != value for key, value in expected_values.items()):
        reject(
            "TRANSACTION_PREFLIGHT_BINDING_MISMATCH",
            "preflight manifest differs from the signed same-run subject",
        )
    stale_required = payload.get("staleWatchdogReclaimRequired")
    stale_owner = payload.get("staleWatchdogAuthorizationSha256")
    if not isinstance(stale_required, bool) or (
        (stale_required and (not isinstance(stale_owner, str) or SHA256.fullmatch(stale_owner) is None))
        or (not stale_required and stale_owner is not None)
    ):
        reject(
            "TRANSACTION_PREFLIGHT_STALE_WATCHDOG_INVALID",
            "stale watchdog observation is not fail-closed",
        )
    manifest_time = parse_utc(payload.get("observedAt"), "preflight.observedAt")
    not_before = parse_utc(grant["notBefore"], "grant.notBefore")
    expires_at = parse_utc(grant["expiresAt"], "grant.expiresAt")
    skew = timedelta(seconds=max_clock_skew_seconds)
    if (
        manifest_time < not_before - skew
        or manifest_time > expires_at + skew
        or manifest_time > observed_at + skew
    ):
        reject(
            "TRANSACTION_PREFLIGHT_TIME_INVALID",
            "preflight observation is outside the signed grant window",
        )
    return VerifiedTransactionPreflight(
        payload=payload,
        preflight_sha256=f"sha256:{manifest_hex}",
        archive_sha256=f"sha256:{hashlib.sha256(archive).hexdigest()}",
    )


def transaction_evidence_digest(
    *, bundle_sha256: str, preflight: VerifiedTransactionPreflight
) -> str:
    return sha256_digest(
        {
            "domain": "acik.cross-ai-single-transaction-approval-evidence.v1",
            "bundleSha256": bundle_sha256,
            "preflightSha256": preflight.preflight_sha256,
            "preflightArchiveSha256": preflight.archive_sha256,
        }
    )


def verify_transaction_final(
    archive: bytes,
    *,
    repository: str,
    workflow_path: str,
    intent_ref: str,
    head_sha: str,
    run_id: int,
    run_attempt: int,
    subject: dict[str, Any],
    grant: dict[str, Any],
    preflight_sha256: str,
    observed_at: datetime,
    max_clock_skew_seconds: int,
) -> VerifiedTransactionFinal:
    """Verify terminal transaction state, cleanup and pre-rollback upload receipt."""

    entries = _safe_final_entries(archive)
    rollback_sha256 = (
        f"sha256:{hashlib.sha256(entries['rollback.stdout']).hexdigest()}"
    )
    state = _json_object(entries["state.json"], label="transaction state")
    workflow_ref = f"{repository}/{workflow_path}@{intent_ref}"
    conclusion, target_state = _verify_transaction_state(
        state,
        repository=repository,
        workflow_ref=workflow_ref,
        head_sha=head_sha,
        run_id=run_id,
        run_attempt=run_attempt,
        subject=subject,
        grant=grant,
        preflight_sha256=preflight_sha256,
        rollback_sha256=rollback_sha256,
        observed_at=observed_at,
        max_clock_skew_seconds=max_clock_skew_seconds,
    )
    receipt_raw = entries.get("pre-rollback-upload-receipt.json")
    receipt: dict[str, Any] | None = None
    receipt_sha256: str | None = None
    if receipt_raw is not None:
        receipt, receipt_sha256 = _verify_upload_receipt(
            receipt_raw,
            head_sha=head_sha,
            run_id=run_id,
            run_attempt=run_attempt,
            grant=grant,
            observed_at=observed_at,
            max_clock_skew_seconds=max_clock_skew_seconds,
        )
    checkpoints = state["checkpoints"]
    artifact_checkpoint = next(
        (item for item in checkpoints if item["state"] == "ARTIFACTS_STAGED"),
        None,
    )
    if artifact_checkpoint is not None and (
        receipt is None or artifact_checkpoint["payloadSha256"] != receipt_sha256
    ):
        reject(
            "TRANSACTION_FINAL_RECEIPT_INVALID",
            "ARTIFACTS_STAGED is not bound to the immutable upload receipt",
        )
    if artifact_checkpoint is None and receipt is not None:
        reject(
            "TRANSACTION_FINAL_RECEIPT_INVALID",
            "upload receipt exists without an ARTIFACTS_STAGED checkpoint",
        )
    return VerifiedTransactionFinal(
        state=state,
        state_sha256=sha256_digest(state),
        archive_sha256=f"sha256:{hashlib.sha256(archive).hexdigest()}",
        conclusion=conclusion,
        target_state=target_state,
        pre_rollback_artifact_id=(receipt["artifactId"] if receipt else None),
        pre_rollback_artifact_digest=(
            receipt["artifactDigest"] if receipt else None
        ),
    )


__all__ = [
    "VerifiedTransactionFinal",
    "VerifiedTransactionPreflight",
    "transaction_evidence_digest",
    "verify_transaction_final",
    "verify_transaction_preflight",
]
