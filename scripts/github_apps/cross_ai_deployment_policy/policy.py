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
POLICY_SCHEMA_V2 = ROOT / "schema/cross-ai-deployment-policy-v2.schema.json"
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
    required_preflight_runs_on_labels: tuple[str, ...] = ()
    requires_same_run_preflight: bool = False
    requires_one_protected_environment_gate: bool = False
    required_authority_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class DeploymentPolicy:
    payload: dict[str, Any]
    digest: str
    phase: str
    schema_version: str
    authority_contract_version: str
    machine_only_enabled: bool
    repository_id: int
    repository: str
    environment: str
    allowed_api_origins: tuple[str, ...]
    runner_bootstrap_url: str | None
    allowed_installation_ids: frozenset[int]
    allowed_dispatcher_installation_ids: frozenset[int]
    allowed_dispatcher_actor_ids: frozenset[int]
    allowed_deployment_classes: frozenset[str]
    max_grant_ttl_minutes: int
    max_run_attempts: int
    preflight_artifact_prefix: str | None
    required_custom_rule_app_ids: frozenset[int]
    stages: dict[str, StagePolicy]


def load_policy(path: Path) -> DeploymentPolicy:
    try:
        payload = load_json_file(path)
    except Exception as exc:
        if hasattr(exc, "code"):
            raise
        reject("POLICY_UNAVAILABLE", "cannot read policy or schema")
    if not isinstance(payload, dict):
        reject("POLICY_SCHEMA_INVALID", "policy must be a JSON object")
    schema_version = payload.get("schemaVersion")
    if schema_version == "acik.cross-ai-deployment-policy.v1":
        schema_path = POLICY_SCHEMA
        authority_contract_version = "v2"
    elif schema_version == "acik.cross-ai-deployment-policy.v2":
        schema_path = POLICY_SCHEMA_V2
        authority_contract_version = "v3"
    else:
        reject("POLICY_SCHEMA_INVALID", "policy schema version is unsupported")
    try:
        schema = load_json_file(schema_path)
    except Exception as exc:
        if hasattr(exc, "code"):
            raise
        reject("POLICY_UNAVAILABLE", "cannot read policy schema")
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(
            payload
        ),
        key=lambda item: list(item.path),
    )
    if errors:
        first = errors[0]
        location = ".".join(str(part) for part in first.absolute_path) or "$"
        reject(
            "POLICY_SCHEMA_INVALID", f"policy invalid at {location}: {first.message}"
        )
    human_classes = set(payload["humanRequiredClasses"])
    if human_classes != REQUIRED_HUMAN_CLASSES:
        reject(
            "POLICY_HUMAN_BOUNDARY_INVALID",
            "v1 policy must preserve every mandatory human class",
        )
    if schema_version == "acik.cross-ai-deployment-policy.v1":
        stage_payloads = payload["workflowStages"]
        stage_names = [entry["stage"] for entry in stage_payloads]
        if stage_names != ["apply", "browser-evidence", "compensating-rollback"]:
            reject("POLICY_STAGE_ORDER_INVALID", "policy stages are not canonical")
    else:
        stage_payloads = [payload["workflowTransaction"]]
        if payload.get("authorityContractVersion") != "v3":
            reject(
                "POLICY_AUTHORITY_CONTRACT_INVALID",
                "single-transaction policy must require authority contract v3",
            )
    stages = {
        entry["stage"]: StagePolicy(
            stage=entry["stage"],
            workflow_path=entry["workflowPath"],
            required_preflight_runs_on_labels=tuple(
                entry.get("requiredPreflightRunsOnLabels", [])
            ),
            required_runs_on_labels=tuple(entry["requiredRunsOnLabels"]),
            require_runner_group=entry["requireRunnerGroup"],
            requires_same_run_preflight=entry.get(
                "requiresSameRunPreflight", False
            ),
            requires_one_protected_environment_gate=entry.get(
                "requiresOneProtectedEnvironmentGate", False
            ),
            required_authority_paths=tuple(entry.get("requiredAuthorityPaths", [])),
        )
        for entry in stage_payloads
    }
    return DeploymentPolicy(
        payload=payload,
        digest=sha256_digest(payload),
        phase=payload["phase"],
        schema_version=schema_version,
        authority_contract_version=authority_contract_version,
        machine_only_enabled=payload["machineOnlyEnabled"],
        repository_id=payload["repositoryId"],
        repository=payload["repository"],
        environment=payload["environment"],
        allowed_api_origins=tuple(payload["allowedApiOrigins"]),
        runner_bootstrap_url=payload.get("runnerBootstrapUrl"),
        allowed_installation_ids=frozenset(payload["allowedInstallationIds"]),
        allowed_dispatcher_installation_ids=frozenset(
            payload["allowedDispatcherInstallationIds"]
        ),
        allowed_dispatcher_actor_ids=frozenset(payload["allowedDispatcherActorIds"]),
        allowed_deployment_classes=frozenset(payload["allowedDeploymentClasses"]),
        max_grant_ttl_minutes=payload["maxGrantTtlMinutes"],
        max_run_attempts=payload.get("maxRunAttempts", 100),
        preflight_artifact_prefix=payload.get("preflightArtifactPrefix"),
        required_custom_rule_app_ids=frozenset(payload["requiredCustomRuleAppIds"]),
        stages=stages,
    )


def resolve_authority_contract(
    policy: DeploymentPolicy, trust_root: dict[str, Any]
) -> str:
    """Resolve legacy policy-v1 by trust-root generation; v2 is always v3."""

    trust_schema = trust_root.get("schemaVersion")
    if policy.schema_version == "acik.cross-ai-deployment-policy.v2":
        if trust_schema != "acik.cross-ai-deployment-trust-root.v2":
            reject(
                "POLICY_AUTHORITY_CONTRACT_INVALID",
                "single-transaction v3 requires a v2 trust root",
            )
        return "v3"
    if trust_schema == "acik.cross-ai-deployment-trust-root.v1":
        return "v1"
    if trust_schema == "acik.cross-ai-deployment-trust-root.v2":
        return "v2"
    reject(
        "TRUST_ROOT_SCHEMA_INVALID",
        "policy cannot resolve an unsupported trust-root generation",
    )


__all__ = [
    "DeploymentPolicy",
    "StagePolicy",
    "load_policy",
    "resolve_authority_contract",
]
