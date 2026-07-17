"""Strict deployment policy loading and content-addressed identity."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .canonical import sha256_digest
from .errors import reject
from .jsonutil import load_json_file


ROOT = Path(__file__).resolve().parents[3]
POLICY_SCHEMA = ROOT / "schema/cross-ai-deployment-policy-v1.schema.json"
REQUIRED_HUMAN_CLASSES = {
    "attended-consent",
    "legal-dpo",
    "named-authority",
    "production-secret-owner",
    "irreversible-production",
    "production",
    "break-glass",
}


@dataclass(frozen=True)
class StagePolicy:
    stage: str
    workflow_path: str
    required_runs_on_labels: tuple[str, ...]
    require_runner_group: bool


@dataclass(frozen=True)
class DeploymentPolicy:
    payload: dict[str, Any]
    digest: str
    phase: str
    repository_id: int
    repository: str
    environment: str
    allowed_api_origins: tuple[str, ...]
    allowed_installation_ids: frozenset[int]
    allowed_dispatcher_actor_ids: frozenset[int]
    allowed_deployment_classes: frozenset[str]
    max_grant_ttl_minutes: int
    required_custom_rule_app_ids: frozenset[int]
    stages: dict[str, StagePolicy]


def load_policy(path: Path) -> DeploymentPolicy:
    try:
        payload = load_json_file(path)
        schema = load_json_file(POLICY_SCHEMA)
    except Exception as exc:
        if hasattr(exc, "code"):
            raise
        reject("POLICY_UNAVAILABLE", "cannot read policy or schema")
    if not isinstance(payload, dict):
        reject("POLICY_SCHEMA_INVALID", "policy must be a JSON object")
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(payload),
        key=lambda item: list(item.path),
    )
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.absolute_path) or "$"
        reject("POLICY_SCHEMA_INVALID", f"policy invalid at {location}: {first.message}")
    human_classes = set(payload["humanRequiredClasses"])
    if human_classes != REQUIRED_HUMAN_CLASSES:
        reject(
            "POLICY_HUMAN_BOUNDARY_INVALID",
            "v1 policy must preserve every mandatory human class",
        )
    stage_payloads = payload["workflowStages"]
    stage_names = [entry["stage"] for entry in stage_payloads]
    if stage_names != ["apply", "browser-evidence", "compensating-rollback"]:
        reject("POLICY_STAGE_ORDER_INVALID", "policy stages are not canonical")
    stages = {
        entry["stage"]: StagePolicy(
            stage=entry["stage"],
            workflow_path=entry["workflowPath"],
            required_runs_on_labels=tuple(entry["requiredRunsOnLabels"]),
            require_runner_group=entry["requireRunnerGroup"],
        )
        for entry in stage_payloads
    }
    return DeploymentPolicy(
        payload=payload,
        digest=sha256_digest(payload),
        phase=payload["phase"],
        repository_id=payload["repositoryId"],
        repository=payload["repository"],
        environment=payload["environment"],
        allowed_api_origins=tuple(payload["allowedApiOrigins"]),
        allowed_installation_ids=frozenset(payload["allowedInstallationIds"]),
        allowed_dispatcher_actor_ids=frozenset(payload["allowedDispatcherActorIds"]),
        allowed_deployment_classes=frozenset(payload["allowedDeploymentClasses"]),
        max_grant_ttl_minutes=payload["maxGrantTtlMinutes"],
        required_custom_rule_app_ids=frozenset(payload["requiredCustomRuleAppIds"]),
        stages=stages,
    )


__all__ = ["DeploymentPolicy", "StagePolicy", "load_policy"]
