#!/usr/bin/env python3
"""Fail-closed verifier for transcript-ready legacy pre-enable evidence."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

from collect_transcript_ready_pre_enable_evidence import (
    DEFAULT_POLICY,
    HOST_POWERSHELL,
    REDIS_LUA,
    ROOT,
    contract_sha256,
)
from transcript_ready_pre_enable_contract import (
    EVIDENCE_SCHEMA,
    ISSUE,
    VERDICT_SCHEMA,
    ContractError,
    SHA1_RE,
    file_sha256,
    load_json,
    load_policy,
    parse_utc,
    require_git_sha,
    require_sha256,
    sensitive_findings,
    sha256_bytes,
)


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    message: str
    remediation: str | None = None


REMEDIATION_EVIDENCE_SCHEMA = "faz24.transcriptReadyRemediationEvidence.v1"
ISSUE_CLAIM_EVIDENCE_SCHEMA = "faz24.transcriptReadyEvidenceIssueClaim.v1"
REMEDIATION_ISSUE_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#[1-9][0-9]*$")
GATE_EVIDENCE_ISSUE = "Halildeu/platform-k8s-gitops#2610"
EMPTY_SET_SHA256 = sha256_bytes(b"[]")
OUTBOX_STATUS_KEYS = {
    "pending",
    "claimedActive",
    "claimedStale",
    "dead",
    "published",
    "total",
}


def add(
    checks: list[Check],
    name: str,
    passed: bool,
    message: str,
    remediation: str | None = None,
) -> None:
    checks.append(Check(name, passed, message, None if passed else remediation))


def object_field(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{name} must be an object")
    return value


def integer(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def zero(value: Any) -> bool:
    return integer(value) == 0


def exact_keys(value: Any, expected: set[str]) -> bool:
    return isinstance(value, dict) and set(value) == expected


def nonnegative(value: Any) -> bool:
    number = integer(value)
    return number is not None and number >= 0


def sha256_value(value: Any) -> bool:
    try:
        require_sha256(value, "digest")
    except ContractError:
        return False
    return True


def empty_result_digest(value: Any) -> bool:
    return value == EMPTY_SET_SHA256


def inventory_digest(count: int, value: Any) -> bool:
    return sha256_value(value) and (
        (count == 0 and empty_result_digest(value))
        or (count > 0 and not empty_result_digest(value))
    )


def outbox_status_counts(value: Any, *, require_zero: bool = False) -> bool:
    if not exact_keys(value, OUTBOX_STATUS_KEYS):
        return False
    counts = [value[key] for key in OUTBOX_STATUS_KEYS]
    if not all(nonnegative(item) for item in counts):
        return False
    subtotal = sum(value[key] for key in OUTBOX_STATUS_KEYS - {"total"})
    return value["total"] == subtotal and (not require_zero or value["total"] == 0)


def event_contract_evidence_valid(value: Any) -> bool:
    return exact_keys(
        value,
        {
            "meetingEventSchema",
            "readyEventType",
            "analysisRunIdEmission",
            "finalizationAnalysisRunId",
        },
    ) and value == {
        "meetingEventSchema": "meeting.event.v1",
        "readyEventType": "meeting.transcript.ready",
        "analysisRunIdEmission": "non-null-v1",
        "finalizationAnalysisRunId": "uuid-not-null-event-bound",
    }


def backfill_evidence_valid(value: Any) -> bool:
    expected = {
        "action",
        "beforeNullFinalizationCount",
        "inventorySetSha256",
        "processedCount",
        "failedCount",
        "afterNullFinalizationCount",
        "resultSetSha256",
        "analysisRunIdUuid",
        "analysisRunIdNotNull",
        "occurrenceBound",
    }
    if not exact_keys(value, expected):
        return False
    before = integer(value["beforeNullFinalizationCount"])
    processed = integer(value["processedCount"])
    if before is None or before < 0 or processed is None:
        return False
    expected_action = "NOOP_ZERO_INVENTORY" if before == 0 else "BACKFILL"
    return (
        value["action"] == expected_action
        and inventory_digest(before, value["inventorySetSha256"])
        and processed == before
        and zero(value["failedCount"])
        and zero(value["afterNullFinalizationCount"])
        and empty_result_digest(value["resultSetSha256"])
        and value["analysisRunIdUuid"] is True
        and value["analysisRunIdNotNull"] is True
        and value["occurrenceBound"] is True
    )


def outbox_evidence_valid(value: Any) -> bool:
    expected = {
        "action",
        "beforeLegacyByStatus",
        "beforeMalformedReadyCount",
        "inventorySetSha256",
        "processedCount",
        "purgedCount",
        "republishedCount",
        "failedCount",
        "afterLegacyByStatus",
        "afterMalformedReadyCount",
        "resultSetSha256",
    }
    if not exact_keys(value, expected):
        return False
    before_status = value["beforeLegacyByStatus"]
    malformed = integer(value["beforeMalformedReadyCount"])
    if not outbox_status_counts(before_status) or malformed is None or malformed < 0:
        return False
    total = before_status["total"] + malformed
    processed = integer(value["processedCount"])
    purged = integer(value["purgedCount"])
    republished = integer(value["republishedCount"])
    if processed is None or purged is None or republished is None:
        return False
    if total == 0:
        action_valid = (
            value["action"] == "NOOP_ZERO_INVENTORY"
            and purged == 0
            and republished == 0
        )
    else:
        action_valid = (
            value["action"] == "PURGE" and purged == total and republished == 0
        ) or (value["action"] == "REPUBLISH" and republished == total and purged == 0)
    return (
        action_valid
        and inventory_digest(total, value["inventorySetSha256"])
        and processed == total
        and zero(value["failedCount"])
        and outbox_status_counts(value["afterLegacyByStatus"], require_zero=True)
        and zero(value["afterMalformedReadyCount"])
        and empty_result_digest(value["resultSetSha256"])
    )


def redis_evidence_valid(value: Any) -> bool:
    expected = {
        "action",
        "beforeLegacyReadyV1Count",
        "beforeMalformedReadyCount",
        "inventorySetSha256",
        "dlqReceiptSetSha256",
        "dlqAcceptedCount",
        "xackCount",
        "xdelCount",
        "failedCount",
        "afterLegacyReadyV1Count",
        "afterMalformedReadyCount",
        "afterStreamLength",
        "afterScannedCount",
        "afterCompleteScan",
        "afterClassificationDigestSha1",
        "resultSetSha256",
    }
    if not exact_keys(value, expected):
        return False
    before_legacy = integer(value["beforeLegacyReadyV1Count"])
    before_malformed = integer(value["beforeMalformedReadyCount"])
    counts = [
        before_legacy,
        before_malformed,
        integer(value["dlqAcceptedCount"]),
        integer(value["xackCount"]),
        integer(value["xdelCount"]),
        integer(value["afterStreamLength"]),
        integer(value["afterScannedCount"]),
    ]
    if any(item is None or item < 0 for item in counts):
        return False
    total = before_legacy + before_malformed
    if total == 0:
        action_valid = value["action"] == "NOOP_ZERO_INVENTORY" and all(
            value[field] == 0
            for field in ("dlqAcceptedCount", "xackCount", "xdelCount")
        )
    else:
        action_valid = (
            value["action"] == "DLQ_ACK_XDEL"
            and value["dlqAcceptedCount"] == total
            and 0 <= value["xackCount"] <= total
            and value["xdelCount"] == total
        )
    return (
        action_valid
        and inventory_digest(total, value["inventorySetSha256"])
        and inventory_digest(total, value["dlqReceiptSetSha256"])
        and zero(value["failedCount"])
        and zero(value["afterLegacyReadyV1Count"])
        and zero(value["afterMalformedReadyCount"])
        and value["afterCompleteScan"] is True
        and value["afterScannedCount"] == value["afterStreamLength"]
        and isinstance(value["afterClassificationDigestSha1"], str)
        and SHA1_RE.fullmatch(value["afterClassificationDigestSha1"]) is not None
        and empty_result_digest(value["resultSetSha256"])
    )


def typed_artifact_evidence_valid(evidence_type: str, value: Any) -> bool:
    validators = {
        "EVENT_CONTRACT": event_contract_evidence_valid,
        "BACKFILL": backfill_evidence_valid,
        "OUTBOX_REMEDIATION": outbox_evidence_valid,
        "REDIS_REMEDIATION": redis_evidence_valid,
    }
    validator = validators.get(evidence_type)
    return validator is not None and validator(value)


def producer_capability(
    policy: dict[str, Any], image_digest: Any, gate_contract_sha256: str
) -> dict[str, Any] | None:
    matches = [
        item
        for item in policy["producerCapabilities"]
        if isinstance(item, dict)
        and item.get("transcriptImageDigest") == image_digest
        and item.get("analysisRunIdEmission") == "non-null-v1"
        and item.get("finalizationAnalysisRunId") == "uuid-not-null-event-bound"
        and item.get("gateContractSha256") == gate_contract_sha256
    ]
    return matches[0] if len(matches) == 1 else None


def host_guard(policy: dict[str, Any], host: dict[str, Any]) -> dict[str, Any] | None:
    matches = [
        item
        for item in policy["hostStartupGuards"]
        if isinstance(item, dict)
        and item.get("platformAiCommit") == host.get("platformAiCommit")
        and item.get("startupScriptSha256") == host.get("startupScriptSha256")
        and item.get("permitRequired") is True
    ]
    return matches[0] if len(matches) == 1 else None


def count_view(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    counts = snapshot.get("counts")
    if not isinstance(counts, dict):
        return None
    value = dict(counts)
    value.pop("capturedAt", None)
    return value


def repository_json_artifact(
    relative_value: Any,
    digest_value: Any,
    artifact_root: Path,
) -> dict[str, Any] | None:
    if not isinstance(relative_value, str):
        return None
    relative = Path(relative_value)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    try:
        root = artifact_root.resolve(strict=True)
        artifact = (root / relative).resolve(strict=True)
        artifact.relative_to(root)
        if not artifact.is_file() or artifact.stat().st_size > 1_000_000:
            return None
        if file_sha256(artifact) != digest_value:
            return None
        return load_json(artifact)
    except (ContractError, OSError, ValueError):
        return None


def capability_artifact_valid(
    capability: dict[str, Any],
    *,
    path_field: str,
    digest_field: str,
    evidence_type: str,
    artifact_root: Path,
    policy: dict[str, Any],
    collection_started: dt.datetime | None,
) -> bool:
    document = repository_json_artifact(
        capability.get(path_field), capability.get(digest_field), artifact_root
    )
    if document is None:
        return False
    top_level_valid = exact_keys(
        document,
        {
            "schemaVersion",
            "issue",
            "evidenceType",
            "status",
            "environment",
            "backendCommit",
            "transcriptImageDigest",
            "gateContractSha256",
            "evidenceIssue",
            "evidenceIssueClaimPath",
            "evidenceIssueClaimSha256",
            "completedAt",
            "evidence",
        },
    )
    claim = repository_json_artifact(
        document.get("evidenceIssueClaimPath"),
        document.get("evidenceIssueClaimSha256"),
        artifact_root,
    )
    claim_valid = exact_keys(
        claim,
        {
            "schemaVersion",
            "gateIssue",
            "issue",
            "source",
            "environment",
            "boardStatusAtClaim",
            "claimedAt",
            "claimSessionSha256",
        },
    )
    claimed_at = None
    completed_at = None
    try:
        if isinstance(claim, dict):
            claimed_at = parse_utc(claim.get("claimedAt"))
        completed_at = parse_utc(document.get("completedAt"))
    except ContractError:
        pass
    temporal_order_valid = (
        claimed_at is not None
        and completed_at is not None
        and collection_started is not None
        and claimed_at <= completed_at < collection_started
    )
    return (
        top_level_valid
        and document.get("schemaVersion") == REMEDIATION_EVIDENCE_SCHEMA
        and document.get("issue") == ISSUE
        and document.get("evidenceType") == evidence_type
        and document.get("status") == "accepted"
        and document.get("environment") == policy["environment"]
        and document.get("backendCommit") == capability.get("backendCommit")
        and document.get("transcriptImageDigest")
        == capability.get("transcriptImageDigest")
        and document.get("gateContractSha256") == capability.get("gateContractSha256")
        and isinstance(document.get("evidenceIssue"), str)
        and REMEDIATION_ISSUE_RE.fullmatch(document["evidenceIssue"]) is not None
        and document["evidenceIssue"].lower() != GATE_EVIDENCE_ISSUE.lower()
        and claim_valid
        and claim.get("schemaVersion") == ISSUE_CLAIM_EVIDENCE_SCHEMA
        and claim.get("gateIssue") == ISSUE
        and claim.get("issue") == document["evidenceIssue"]
        and claim.get("source") == "github-project-v2"
        and claim.get("environment") == policy["environment"]
        and claim.get("boardStatusAtClaim") == "In Progress"
        and sha256_value(claim.get("claimSessionSha256"))
        and claim.get("claimSessionSha256") != EMPTY_SET_SHA256
        and temporal_order_valid
        and typed_artifact_evidence_valid(evidence_type, document.get("evidence"))
        and not sensitive_findings(document)
    )


def validate(
    evidence: dict[str, Any],
    policy: dict[str, Any],
    *,
    expected_gitops_commit: str,
    policy_path: Path,
    now: dt.datetime,
    artifact_root: Path = ROOT,
) -> tuple[list[Check], dict[str, Any]]:
    checks: list[Check] = []
    add(
        checks,
        "metadata_only",
        not sensitive_findings(evidence),
        "evidence must contain counts, booleans and digests only",
        "RECOLLECT_METADATA_ONLY",
    )
    add(
        checks,
        "schema",
        evidence.get("schemaVersion") == EVIDENCE_SCHEMA,
        f"schemaVersion must be {EVIDENCE_SCHEMA}",
        "FRESH_ZERO_SCAN",
    )
    add(checks, "issue", evidence.get("issue") == ISSUE, f"issue must be {ISSUE}")
    add(
        checks,
        "candidate_status",
        evidence.get("status") == "candidate",
        "collector status must be candidate without collection failures",
        "FRESH_ZERO_SCAN",
    )
    generated = None
    try:
        generated = parse_utc(evidence.get("generatedAt"))
    except ContractError:
        pass
    age = None if generated is None else (now - generated).total_seconds()
    add(
        checks,
        "freshness",
        age is not None and 0 <= age <= int(policy["freshnessSeconds"]),
        f"evidence age must be 0..{policy['freshnessSeconds']} seconds",
        "FRESH_ZERO_SCAN",
    )
    failures = evidence.get("collectionFailures")
    add(
        checks,
        "collection_complete",
        failures == [],
        "all live collectors must complete",
        "FRESH_ZERO_SCAN",
    )

    source = object_field(evidence.get("source"), "source")
    collection_started = None
    collection_finished = None
    try:
        collection_started = parse_utc(source.get("collectionStartedAt"))
        collection_finished = parse_utc(source.get("collectionFinishedAt"))
    except ContractError:
        pass
    collection_duration = (
        None
        if collection_started is None or collection_finished is None
        else (collection_finished - collection_started).total_seconds()
    )
    add(
        checks,
        "collection_window",
        collection_duration is not None
        and 0 <= collection_duration <= int(policy["maxCollectionSeconds"])
        and collection_finished == generated,
        "all observations must be bounded by the fresh collection envelope",
        "FRESH_ZERO_SCAN",
    )
    add(
        checks,
        "gitops_commit",
        source.get("gitopsCommit") == expected_gitops_commit,
        "evidence must bind the exact GitOps commit",
        "FRESH_ZERO_SCAN",
    )
    add(
        checks,
        "policy_digest",
        source.get("policySha256") == file_sha256(policy_path),
        "evidence policy digest must match the verified policy bytes",
        "FRESH_ZERO_SCAN",
    )
    expected_contract = contract_sha256(
        policy["environment"]["postgresSchema"],
        policy["requiredStartupGateMarker"],
    )
    add(
        checks,
        "query_contract_digest",
        source.get("queryContractSha256") == expected_contract,
        "collector query contract digest must match this verifier",
        "FRESH_ZERO_SCAN",
    )
    add(
        checks,
        "environment",
        evidence.get("environment") == policy["environment"],
        "evidence environment must exactly match policy",
        "FRESH_ZERO_SCAN",
    )

    live = object_field(evidence.get("live"), "live")
    component_times: list[dt.datetime] = []
    for component_name in (
        "transcriptPod",
        "postgresBefore",
        "redis",
        "postgresAfter",
        "gpuHost",
    ):
        component = live.get(component_name)
        try:
            if not isinstance(component, dict):
                raise ContractError("component must be an object")
            component_times.append(parse_utc(component.get("observedAt")))
        except ContractError:
            component_times = []
            break
    add(
        checks,
        "component_observation_window",
        len(component_times) == 5
        and collection_started is not None
        and collection_finished is not None
        and all(
            collection_started <= observed_at <= collection_finished
            for observed_at in component_times
        ),
        "every live component observation must fall inside the collection envelope",
        "FRESH_ZERO_SCAN",
    )
    pod = object_field(live.get("transcriptPod"), "live.transcriptPod")
    image_digest = pod.get("imageDigest")
    immutable_image = False
    try:
        require_sha256(image_digest, "imageDigest", prefix=True)
        immutable_image = True
    except ContractError:
        pass
    capability = producer_capability(policy, image_digest, expected_contract)
    add(
        checks,
        "transcript_pod_identity",
        pod.get("collected") is True
        and pod.get("ready") is True
        and integer(pod.get("restartCount")) is not None
        and immutable_image,
        "one ready transcript pod with immutable imageID is required",
        "KEEP_CONSUMER_DISABLED",
    )
    add(
        checks,
        "approved_producer_capability",
        capability is not None,
        "live transcript image must be allowlisted for non-null v1 analysisRunId emission",
        "KEEP_CONSUMER_DISABLED",
    )
    if capability is not None:
        for field in (
            "transcriptImageDigest",
            "backendCommit",
            "eventContractSha256",
            "gateContractSha256",
            "backfillEvidenceSha256",
            "outboxRemediationEvidenceSha256",
            "redisRemediationEvidenceSha256",
        ):
            value = capability.get(field)
            valid = False
            try:
                if field == "backendCommit":
                    require_git_sha(value, field)
                elif field == "transcriptImageDigest":
                    require_sha256(value, field, prefix=True)
                else:
                    require_sha256(value, field)
                valid = True
            except ContractError:
                pass
            add(
                checks,
                f"producer_capability_{field}",
                valid,
                f"{field} must be immutable",
            )
        for path_field, digest_field, evidence_type in (
            (
                "eventContractEvidencePath",
                "eventContractSha256",
                "EVENT_CONTRACT",
            ),
            (
                "backfillEvidencePath",
                "backfillEvidenceSha256",
                "BACKFILL",
            ),
            (
                "outboxRemediationEvidencePath",
                "outboxRemediationEvidenceSha256",
                "OUTBOX_REMEDIATION",
            ),
            (
                "redisRemediationEvidencePath",
                "redisRemediationEvidenceSha256",
                "REDIS_REMEDIATION",
            ),
        ):
            add(
                checks,
                f"producer_capability_{evidence_type.lower()}_artifact",
                capability_artifact_valid(
                    capability,
                    path_field=path_field,
                    digest_field=digest_field,
                    evidence_type=evidence_type,
                    artifact_root=artifact_root,
                    policy=policy,
                    collection_started=collection_started,
                ),
                f"{evidence_type} evidence must be a matching repository artifact",
                "KEEP_CONSUMER_DISABLED",
            )

    before = object_field(live.get("postgresBefore"), "live.postgresBefore")
    after = object_field(live.get("postgresAfter"), "live.postgresAfter")
    schema_before = (
        before.get("schema") if isinstance(before.get("schema"), dict) else {}
    )
    schema_after = after.get("schema") if isinstance(after.get("schema"), dict) else {}
    expected_database_identity = {
        "databaseName": policy["environment"]["postgresDatabase"],
        "serverAddress": policy["environment"]["postgresHost"],
        "serverPort": policy["environment"]["postgresPort"],
    }
    database_identity = {
        key: schema_before.get(key) for key in expected_database_identity
    }
    add(
        checks,
        "postgres_target_identity",
        database_identity == expected_database_identity
        and all(
            schema_after.get(key) == value
            for key, value in expected_database_identity.items()
        ),
        "both PostgreSQL snapshots must come from the exact policy database endpoint",
        "FRESH_ZERO_SCAN",
    )
    schema_ready = all(
        schema_before.get(key) is True and schema_after.get(key) is True
        for key in (
            "finalizationTablePresent",
            "outboxTablePresent",
            "analysisRunIdColumnPresent",
            "analysisRunIdNotNull",
            "analysisRunIdUuid",
            "finalizationOccurrenceColumnsPresent",
            "outboxRequiredColumnsPresent",
        )
    )
    add(
        checks,
        "postgres_schema_capability",
        before.get("collected") is True
        and after.get("collected") is True
        and schema_before == schema_after
        and schema_ready,
        "analysis_run_id must be UUID and NOT NULL in both PostgreSQL snapshots",
        "BACKFILL",
    )
    before_counts = count_view(before)
    after_counts = count_view(after)
    postgres_capture_times: list[dt.datetime] = []
    for snapshot in (before, after):
        counts_value = snapshot.get("counts")
        try:
            if not isinstance(counts_value, dict):
                raise ContractError("counts must be an object")
            postgres_capture_times.append(parse_utc(counts_value.get("capturedAt")))
        except ContractError:
            postgres_capture_times = []
            break
    add(
        checks,
        "postgres_capture_window",
        len(postgres_capture_times) == 2
        and collection_started is not None
        and collection_finished is not None
        and all(
            collection_started <= captured_at <= collection_finished
            for captured_at in postgres_capture_times
        ),
        "both database snapshots must be captured inside the collection envelope",
        "FRESH_ZERO_SCAN",
    )
    counts_stable = before_counts is not None and before_counts == after_counts
    add(
        checks,
        "postgres_double_snapshot_stable",
        counts_stable,
        "PostgreSQL counters must be unchanged around the atomic Redis scan",
        "FRESH_ZERO_SCAN",
    )
    counts = before_counts or {}
    add(
        checks,
        "finalization_null_rows",
        zero(counts.get("finalizationNullAnalysisRunId")),
        "transcript finalizations with NULL analysis_run_id must be zero",
        "BACKFILL",
    )
    legacy = (
        counts.get("legacyOutbox")
        if isinstance(counts.get("legacyOutbox"), dict)
        else {}
    )
    for status in (
        "pending",
        "claimedActive",
        "claimedStale",
        "dead",
        "published",
        "total",
    ):
        add(
            checks,
            f"legacy_outbox_{status}",
            zero(legacy.get(status)),
            f"legacy transcript-ready outbox {status} count must be zero",
            "PURGE_OR_REPUBLISH",
        )
    add(
        checks,
        "malformed_ready_outbox",
        zero(counts.get("malformedReadyOutbox")),
        "malformed transcript-ready outbox count must be zero",
        "PURGE_OR_REPUBLISH",
    )
    legacy_total = integer(legacy.get("total"))
    malformed_total = integer(counts.get("malformedReadyOutbox"))
    compatible_total = integer(counts.get("compatibleReadyOutbox"))
    ready_total = integer(counts.get("readyOutboxTotal"))
    add(
        checks,
        "postgres_ready_classification_complete",
        legacy_total is not None
        and malformed_total is not None
        and compatible_total is not None
        and ready_total is not None
        and min(legacy_total, malformed_total, compatible_total, ready_total) >= 0
        and legacy_total + malformed_total + compatible_total == ready_total,
        "every transcript-ready outbox row must have exactly one classification",
        "PURGE_OR_REPUBLISH",
    )

    redis = object_field(live.get("redis"), "live.redis")
    add(
        checks,
        "redis_target_identity",
        redis.get("host") == policy["environment"]["redisHost"]
        and redis.get("port") == policy["environment"]["redisPort"]
        and redis.get("tls") is policy["environment"]["redisTls"],
        "Redis evidence must come from the exact policy endpoint and TLS mode",
        "FRESH_ZERO_SCAN",
    )
    expected_lua = sha256_bytes(REDIS_LUA.encode("utf-8"))
    add(
        checks,
        "redis_script_digest",
        redis.get("scriptSha256") == expected_lua,
        "Redis EVAL_RO script digest must match this verifier",
        "FRESH_ZERO_SCAN",
    )
    length = integer(redis.get("length"))
    scanned = integer(redis.get("scanned"))
    add(
        checks,
        "redis_complete_atomic_scan",
        redis.get("collected") is True
        and redis.get("complete") is True
        and redis.get("truncated") is False
        and redis.get("atomicMetadataStable") is True
        and length is not None
        and scanned == length
        and length <= int(policy["redisScanMaxEntries"]),
        "Redis scan must atomically classify the complete retained stream",
        "FRESH_ZERO_SCAN",
    )
    add(
        checks,
        "redis_legacy_ready",
        zero(redis.get("legacyReadyV1")),
        "retained meeting.event.v1 ready rows with null analysisRunId must be zero",
        "DLQ_ACK_XDEL",
    )
    add(
        checks,
        "redis_malformed_ready",
        zero(redis.get("malformedReady")),
        "retained malformed transcript-ready rows must be zero",
        "DLQ_ACK_XDEL",
    )
    compatible_binding_digest = counts.get("compatibleBindingSetSha256")
    redis_binding_digest = redis.get("compatibleBindingSetSha256")
    compatible_binding_count = integer(counts.get("compatibleReadyOutbox"))
    redis_compatible_count = integer(redis.get("compatibleReady"))
    binding_digests_valid = True
    try:
        require_sha256(compatible_binding_digest, "PostgreSQL compatible binding set")
        require_sha256(redis_binding_digest, "Redis compatible binding set")
    except ContractError:
        binding_digests_valid = False
    add(
        checks,
        "cross_store_compatible_bindings",
        binding_digests_valid
        and compatible_binding_count is not None
        and compatible_binding_count == redis_compatible_count
        and compatible_binding_digest == redis_binding_digest,
        "Redis and PostgreSQL must contain the same compatible occurrence bindings",
        "PURGE_OR_REPUBLISH",
    )
    digest = redis.get("classificationDigestSha1")
    add(
        checks,
        "redis_classification_digest",
        isinstance(digest, str) and SHA1_RE.fullmatch(digest) is not None,
        "Redis classification must bind every retained entry ID and class",
        "FRESH_ZERO_SCAN",
    )
    group = redis.get("group") if isinstance(redis.get("group"), dict) else {}
    add(
        checks,
        "redis_group_pending",
        zero(group.get("pending")),
        "target ready consumer group PEL must be empty",
        "DLQ_ACK_XDEL",
    )
    add(
        checks,
        "redis_group_absent_before_enable",
        group.get("exists") is False
        and zero(group.get("pending"))
        and zero(group.get("consumers")),
        "target ready group must not exist before the first governed enable",
        "DLQ_ACK_XDEL",
    )

    host = object_field(live.get("gpuHost"), "live.gpuHost")
    guard = host_guard(policy, host)
    expected_probe_sha = sha256_bytes(
        HOST_POWERSHELL.replace(
            "__STARTUP_GATE_MARKER__", policy["requiredStartupGateMarker"]
        ).encode("utf-8")
    )
    host_metadata_valid = True
    try:
        require_git_sha(host.get("platformAiCommit"), "platformAiCommit")
        require_git_sha(host.get("repoHeadCommit"), "repoHeadCommit")
        require_sha256(host.get("startupScriptSha256"), "startupScriptSha256")
        require_sha256(host.get("probeSha256"), "probeSha256")
    except ContractError:
        host_metadata_valid = False
    add(
        checks,
        "gpu_host_identity",
        host.get("collected") is True
        and host_metadata_valid
        and host.get("computerName") == policy["environment"]["gpuHostComputerName"]
        and host.get("deploymentStateMatch") is True
        and host.get("platformAiCommit") == host.get("repoHeadCommit")
        and host.get("probeSha256") == expected_probe_sha,
        "GPU host deployment ledger and repo HEAD must match",
        "KEEP_CONSUMER_DISABLED",
    )
    add(
        checks,
        "host_consumer_default_off",
        (
            (
                host.get("runtimeConfigState") == "absent"
                and zero(host.get("runtimeConfigMatchCount"))
            )
            or (
                host.get("runtimeConfigState") == "false"
                and integer(host.get("runtimeConfigMatchCount")) == 1
            )
        )
        and host.get("machineEnvironmentState") in {"unset", "false"}
        and host.get("healthReachable") is True
        and host.get("healthConsumerPresent") is True
        and host.get("healthEnabled") is False
        and host.get("healthStatus") == "disabled"
        and host.get("healthWorkerRunning") is False
        and host.get("healthRedisGroupReady") is False,
        "effective host config and live health must prove the ready consumer disabled",
        "KEEP_CONSUMER_DISABLED",
    )
    add(
        checks,
        "approved_host_startup_guard",
        guard is not None and host.get("startupGateMarkerPresent") is True,
        "platform-ai startup must be allowlisted and require a fresh permit",
        "KEEP_CONSUMER_DISABLED",
    )
    if guard is not None:
        for field, validator in (
            ("platformAiCommit", require_git_sha),
            ("startupScriptSha256", require_sha256),
        ):
            valid = True
            try:
                validator(guard.get(field), field)
            except ContractError:
                valid = False
            add(
                checks,
                f"host_guard_{field}",
                valid,
                f"{field} must be immutable",
                "KEEP_CONSUMER_DISABLED",
            )
    add(
        checks,
        "policy_enable_boundary",
        policy.get("currentBoundary", {}).get("enableAuthorized") is True,
        "repo policy must deliberately authorize this exact enable candidate",
        "KEEP_CONSUMER_DISABLED",
    )

    boundary = object_field(evidence.get("boundary"), "boundary")
    add(
        checks,
        "read_only_boundary",
        boundary
        == {
            "readOnly": True,
            "consumerEnableAttempted": False,
            "workloadMutationAttempted": False,
            "secretValuesIncluded": False,
            "customerContentIncluded": False,
            "enableAuthorized": False,
        },
        "collector must remain read-only, metadata-only and non-enabling",
        "RECOLLECT_METADATA_ONLY",
    )
    context = {
        "producerCapability": (
            None
            if capability is None
            else {
                "transcriptImageDigest": capability.get("transcriptImageDigest"),
                "backendCommit": capability.get("backendCommit"),
            }
        ),
        "liveTranscriptPod": {
            "podUid": pod.get("uid"),
            "imageDigest": pod.get("imageDigest"),
            "observedAt": pod.get("observedAt"),
        },
        "hostStartupGuard": (
            None
            if guard is None
            else {
                "platformAiCommit": guard.get("platformAiCommit"),
                "startupScriptSha256": guard.get("startupScriptSha256"),
                "permitRequired": guard.get("permitRequired"),
            }
        ),
    }
    return checks, context


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--expected-gitops-commit", required=True)
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def build_verdict(
    *,
    checks: list[Check],
    context: dict[str, Any],
    policy: dict[str, Any] | None,
    expected_gitops_commit: str,
    policy_digest: str | None,
    evidence_digest: str | None,
    generated_at: dt.datetime,
) -> dict[str, Any]:
    if generated_at.tzinfo is None or generated_at.utcoffset() != dt.timedelta(0):
        raise ContractError("verdict generation time must be UTC")
    generated_at = generated_at.replace(microsecond=0)
    accepted = all(check.passed for check in checks)
    remediations = sorted(
        {
            check.remediation
            for check in checks
            if not check.passed and check.remediation
        }
    )
    if not accepted:
        remediations.append("FRESH_ZERO_SCAN")
        remediations = sorted(set(remediations))
    live_pod = context.get("liveTranscriptPod")
    evidence_age_seconds = None
    if isinstance(live_pod, dict):
        try:
            evidence_age_seconds = int(
                (generated_at - parse_utc(live_pod.get("observedAt"))).total_seconds()
            )
        except ContractError:
            evidence_age_seconds = None
    bound_live_pod = (
        None
        if not isinstance(live_pod, dict)
        else {
            **live_pod,
            "evidenceSha256": evidence_digest,
        }
    )
    return {
        "schemaVersion": VERDICT_SCHEMA,
        "generatedAt": generated_at.isoformat().replace("+00:00", "Z"),
        "issue": ISSUE,
        "status": "accepted-candidate" if accepted else "rejected",
        "enableAuthorized": accepted,
        "checks": [
            {**asdict(check), "remediation": check.remediation or ""}
            for check in checks
        ],
        "requiredRemediationEvidence": remediations,
        "binding": {
            "targetAppEnv": (
                policy.get("environment", {}).get("appEnv")
                if isinstance(policy, dict)
                else None
            ),
            "expectedGitopsCommit": expected_gitops_commit,
            "policySha256": policy_digest,
            "producerCapability": context.get("producerCapability"),
            "liveTranscriptPod": bound_live_pod,
            "hostStartupGuard": context.get("hostStartupGuard"),
            "evidenceAgeSeconds": evidence_age_seconds,
        },
        "boundary": (
            "A passing candidate is usable only by the allowlisted host startup guard; "
            "it is not an operator assertion or a production approval."
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    policy = None
    policy_digest = None
    evidence_digest = None
    verdict_generated_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    try:
        expected_commit = require_git_sha(
            args.expected_gitops_commit, "expected GitOps commit"
        )
        policy = load_policy(args.policy)
        policy_digest = file_sha256(args.policy)
        evidence = load_json(args.evidence)
        evidence_digest = file_sha256(args.evidence)
        checks, context = validate(
            evidence,
            policy,
            expected_gitops_commit=expected_commit,
            policy_path=args.policy,
            now=verdict_generated_at,
        )
    except ContractError as exc:
        checks = [Check("verifier_input", False, str(exc), "FRESH_ZERO_SCAN")]
        context = {}
    accepted = all(check.passed for check in checks)
    verdict = build_verdict(
        checks=checks,
        context=context,
        policy=policy,
        expected_gitops_commit=args.expected_gitops_commit,
        policy_digest=policy_digest,
        evidence_digest=evidence_digest,
        generated_at=verdict_generated_at,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(verdict, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        args.output.chmod(0o600)
    print(
        ("PASS" if accepted else "REJECTED")
        + ": Faz 24 transcript-ready legacy pre-enable gate"
    )
    if not accepted:
        for check in checks:
            if not check.passed:
                print(f"- {check.name}: {check.message}", file=sys.stderr)
        print(
            "required=" + ",".join(verdict["requiredRemediationEvidence"]),
            file=sys.stderr,
        )
    return 0 if accepted else 1


if __name__ == "__main__":
    sys.exit(main())
