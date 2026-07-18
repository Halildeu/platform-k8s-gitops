"""Verify content-addressed workflow stage outcomes against a signed intent."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .canonical import sha256_digest
from .contract import VerifiedBundle
from .errors import reject
from .jsonutil import load_json_file
from .timeutil import parse_utc, utc_now


ROOT = Path(__file__).resolve().parents[3]
OUTCOME_SCHEMA = ROOT / "schema/cross-ai-deployment-stage-outcome-v1.schema.json"
MAX_CLOCK_SKEW = timedelta(seconds=60)


@dataclass(frozen=True)
class VerifiedStageOutcome:
    request_id: str
    stage: str
    run_id: int
    run_attempt: int
    outcome_digest: str
    target_state: str
    payload: dict[str, Any]


def _validate_schema(value: dict[str, Any]) -> None:
    schema = load_json_file(OUTCOME_SCHEMA)
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
        key=lambda item: list(item.path),
    )
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.absolute_path) or "$"
        reject(
            "STAGE_OUTCOME_SCHEMA_INVALID",
            f"stage outcome invalid at {location}: {first.message}",
        )


def verify_stage_outcome(
    payload: dict[str, Any],
    *,
    bundle: VerifiedBundle,
    expected_stage: str,
    expected_run_id: int,
    expected_run_attempt: int,
    expected_run_started_at: str,
    expected_critical_jobs_sha256: str,
    expected_source_artifact_name: str,
    expected_source_archive_sha256: str,
    now: datetime | None = None,
) -> VerifiedStageOutcome:
    """Bind a computed run/artifact outcome to the exact signed stage."""

    _validate_schema(payload)
    current = now or utc_now()
    subject = bundle.payload["subject"]
    grant = bundle.payload["grant"]
    stages = [
        item
        for item in bundle.payload["workflowStages"]
        if item["stage"] == expected_stage
    ]
    if len(stages) != 1:
        reject("STAGE_OUTCOME_BINDING_MISMATCH", "signed stage is missing or ambiguous")
    stage = stages[0]
    canonical_artifact_name = (
        f"cross-ai-stage-outcome-{bundle.request_id}-{expected_stage}-"
        f"{expected_run_id}-{expected_run_attempt}"
    )
    if expected_source_artifact_name != canonical_artifact_name:
        reject(
            "STAGE_OUTCOME_BINDING_MISMATCH",
            "source artifact name is not canonical for the signed run",
        )
    exact = {
        "requestId": bundle.request_id,
        "stage": expected_stage,
        "runId": expected_run_id,
        "runAttempt": expected_run_attempt,
        "runStartedAt": expected_run_started_at,
        "repositoryId": subject["repositoryId"],
        "repository": subject["repository"],
        "environment": subject["environment"],
        "headSha": subject["headSha"],
        "intentRef": subject["intentRef"],
        "sessionSha256": subject["sessionSha256"],
        "workflowBlobSha256": stage["workflowBlobSha256"],
        "criticalJobsSha256": expected_critical_jobs_sha256,
        "sourceArtifactName": expected_source_artifact_name,
        "sourceArchiveSha256": expected_source_archive_sha256,
        "artifactSetSha256": subject["artifactSetSha256"],
        "rollbackPlanSha256": subject["rollbackPlanSha256"],
        "postDeployVerifierSha256": subject["postDeployVerifierSha256"],
    }
    for field, expected in exact.items():
        if payload[field] != expected:
            reject(
                "STAGE_OUTCOME_BINDING_MISMATCH",
                f"stage outcome field {field} differs from signed/live authority",
            )

    created_at = parse_utc(payload["createdAt"], "stageOutcome.createdAt")
    run_started_at = parse_utc(payload["runStartedAt"], "stageOutcome.runStartedAt")
    grant_start = parse_utc(grant["notBefore"], "grant.notBefore")
    grant_end = parse_utc(grant["expiresAt"], "grant.expiresAt")
    if (
        created_at < grant_start - MAX_CLOCK_SKEW
        or created_at > grant_end + MAX_CLOCK_SKEW
    ):
        reject(
            "STAGE_OUTCOME_TIME_INVALID", "stage outcome is outside the signed grant"
        )
    if created_at > current + MAX_CLOCK_SKEW:
        reject(
            "STAGE_OUTCOME_TIME_INVALID", "stage outcome creation time is in the future"
        )
    if (
        run_started_at < grant_start - MAX_CLOCK_SKEW
        or run_started_at > created_at
        or run_started_at > current + MAX_CLOCK_SKEW
    ):
        reject(
            "STAGE_OUTCOME_TIME_INVALID", "run start time is outside the signed outcome"
        )

    conclusion = payload["conclusion"]
    watchdog_value = payload["watchdogExpiresAt"]
    if expected_stage == "apply":
        if conclusion not in {"success", "failure"}:
            reject(
                "STAGE_OUTCOME_STATE_INVALID",
                "apply outcome has an invalid conclusion",
            )
        if conclusion == "success" and watchdog_value is None:
            reject(
                "STAGE_OUTCOME_STATE_INVALID",
                "successful apply outcome requires a watchdog expiry",
            )
        if watchdog_value is not None:
            watchdog_end = parse_utc(watchdog_value, "stageOutcome.watchdogExpiresAt")
            if watchdog_end <= created_at or watchdog_end > grant_end:
                reject(
                    "STAGE_OUTCOME_WATCHDOG_INVALID",
                    "apply watchdog expiry is not bounded by the signed grant",
                )
    elif expected_stage == "browser-evidence":
        if conclusion not in {"success", "failure"} or watchdog_value is not None:
            reject(
                "STAGE_OUTCOME_STATE_INVALID",
                "browser outcome has an invalid conclusion or watchdog field",
            )
    else:
        if conclusion not in {"rolled-back", "failure"} or watchdog_value is not None:
            reject(
                "STAGE_OUTCOME_STATE_INVALID",
                "rollback outcome has an invalid conclusion or watchdog field",
            )

    target_state = {
        "success": "Succeeded",
        "failure": "Failed",
        "rolled-back": "RolledBack",
    }[conclusion]
    return VerifiedStageOutcome(
        request_id=bundle.request_id,
        stage=expected_stage,
        run_id=expected_run_id,
        run_attempt=expected_run_attempt,
        outcome_digest=sha256_digest(payload),
        target_state=target_state,
        payload=payload,
    )


__all__ = ["VerifiedStageOutcome", "verify_stage_outcome"]
