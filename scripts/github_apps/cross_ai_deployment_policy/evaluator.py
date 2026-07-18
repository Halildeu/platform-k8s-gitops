"""Deterministic observe/enforcement evaluation against live GitHub truth."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Protocol

from .canonical import sha256_digest
from .contract import EvidenceVerifier
from .errors import reject
from .github import GitHubIntentRef
from .intent_store import IntentRegistry
from .policy import DeploymentPolicy
from .timeutil import parse_utc, utc_now
from .webhook import DeploymentProtectionRequest
from .workflow import inspect_workflow


MAX_DISPATCH_DELAY = timedelta(minutes=10)


class GitHubTruthReader(Protocol):
    def repository(self, installation_id: int, repository: str) -> dict[str, Any]: ...

    def workflow_run(
        self, installation_id: int, repository: str, run_id: int
    ) -> dict[str, Any]: ...

    def intent_ref(
        self, installation_id: int, repository: str, request_id: str
    ) -> GitHubIntentRef: ...

    def workflow_bytes(
        self,
        installation_id: int,
        repository: str,
        workflow_path: str,
        head_sha: str,
    ) -> bytes: ...

    def environment(
        self, installation_id: int, repository: str, environment: str
    ) -> dict[str, Any]: ...

    def repository_runners(
        self, installation_id: int, repository: str
    ) -> tuple[dict[str, Any], ...]: ...

    def workflow_run_attempt(
        self,
        installation_id: int,
        repository: str,
        run_id: int,
        run_attempt: int,
    ) -> dict[str, Any]: ...

    def workflow_jobs(
        self,
        installation_id: int,
        repository: str,
        run_id: int,
        run_attempt: int,
    ) -> tuple[dict[str, Any], ...]: ...


@dataclass(frozen=True)
class EvaluationResult:
    approval_candidate: bool
    reason_code: str
    request_id: str
    stage: str
    run_id: int
    run_attempt: int
    app_rule_id: int
    evidence_digest: str
    policy_digest: str
    provider_families: tuple[str, ...]


class DeploymentEvaluator:
    def __init__(
        self,
        *,
        policy: DeploymentPolicy,
        registry: IntentRegistry,
        github: GitHubTruthReader,
        trust_root: dict[str, Any],
        expected_trust_root_sha256: str,
        revocations_loader: Callable[[], dict[str, Any]],
        mode: str = "observe",
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        if mode not in {"observe", "enforce"}:
            reject(
                "EVALUATOR_MODE_INVALID", "evaluator mode must be observe or enforce"
            )
        if mode == "enforce" and policy.phase == "observe":
            reject(
                "ENFORCE_PHASE_INVALID",
                "observe policy cannot authorize an enforcement callback",
            )
        self.policy = policy
        self.registry = registry
        self.github = github
        self.trust_root = trust_root
        self.expected_trust_root_sha256 = expected_trust_root_sha256
        self.revocations_loader = revocations_loader
        self.mode = mode
        self._now = now

    @staticmethod
    def _object(value: object, field: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            reject("GITHUB_TRUTH_INVALID", f"{field} is not an object")
        return value

    @staticmethod
    def _positive_int(value: object, field: str) -> int:
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            reject("GITHUB_TRUTH_INVALID", f"{field} is not a positive integer")
        return value

    def _policy_binding(self, request: DeploymentProtectionRequest) -> None:
        if (
            request.repository_id != self.policy.repository_id
            or request.repository != self.policy.repository
        ):
            reject(
                "POLICY_REPOSITORY_MISMATCH", "webhook repository is not allowlisted"
            )
        if request.environment != self.policy.environment:
            reject(
                "POLICY_ENVIRONMENT_MISMATCH", "webhook Environment is not allowlisted"
            )
        if request.installation_id not in self.policy.allowed_installation_ids:
            reject(
                "POLICY_INSTALLATION_MISMATCH",
                "GitHub App installation is not allowlisted",
            )

    def _environment_binding(self, value: dict[str, Any]) -> int:
        if value.get("name") != self.policy.environment:
            reject("ENVIRONMENT_SNAPSHOT_MISMATCH", "Environment name differs")
        rules = value.get("protection_rules")
        if not isinstance(rules, list):
            reject(
                "ENVIRONMENT_SNAPSHOT_INVALID",
                "Environment protection rules are missing",
            )
        custom_apps: set[int] = set()
        required_reviewer = False
        for rule_value in rules:
            rule = self._object(rule_value, "environment.protection_rules[]")
            rule_type = rule.get("type")
            if rule_type == "required_reviewers":
                required_reviewer = True
            elif rule_type == "custom":
                app = self._object(
                    rule.get("app"), "environment.protection_rules[].app"
                )
                custom_apps.add(self._positive_int(app.get("id"), "custom App ID"))
        if custom_apps != set(self.policy.required_custom_rule_app_ids):
            reject(
                "ENVIRONMENT_CUSTOM_RULE_DRIFT",
                "enabled custom deployment rule App IDs differ from policy",
            )
        if len(custom_apps) != 1:
            reject(
                "ENVIRONMENT_CUSTOM_RULE_DRIFT",
                "v1 requires exactly one custom rule App",
            )
        if self.mode == "enforce" and value.get("can_admins_bypass") is not False:
            reject(
                "ENVIRONMENT_ADMIN_BYPASS_UNVERIFIED",
                "enforcement requires live proof that administrators cannot bypass rules",
            )
        if self.policy.phase == "dual-gate" and not required_reviewer:
            reject(
                "ENVIRONMENT_REVIEWER_DRIFT",
                "dual-gate phase requires a human reviewer",
            )
        if self.policy.phase == "machine-only-nonprod" and required_reviewer:
            reject(
                "ENVIRONMENT_REVIEWER_DRIFT",
                "machine-only phase must not retain the repeated reviewer rule",
            )
        branch = self._object(
            value.get("deployment_branch_policy"), "deployment_branch_policy"
        )
        if (
            branch.get("protected_branches") is not False
            or branch.get("custom_branch_policies") is not True
        ):
            reject(
                "ENVIRONMENT_BRANCH_POLICY_DRIFT",
                "Environment must use custom deployment branch policy for intent refs",
            )
        return next(iter(custom_apps))

    def _run_binding(
        self,
        *,
        request: DeploymentProtectionRequest,
        run: dict[str, Any],
        record_registered_at: str,
        record_finalized_at: str | None,
    ) -> tuple[str, int]:
        if self._positive_int(run.get("id"), "run.id") != request.run_id:
            reject("RUN_ID_MISMATCH", "workflow run ID differs from callback route")
        if run.get("event") != "workflow_dispatch":
            reject("RUN_EVENT_MISMATCH", "workflow run is not workflow_dispatch")
        if run.get("head_sha") != request.head_sha:
            reject("HEAD_OR_WORKFLOW_MISMATCH", "workflow run head differs")
        expected_branch = request.intent_ref.removeprefix("refs/tags/")
        if run.get("head_branch") != expected_branch:
            reject(
                "INTENT_REF_MISMATCH",
                "workflow run did not use the immutable intent ref",
            )
        repository = self._object(run.get("repository"), "run.repository")
        head_repository = self._object(
            run.get("head_repository"), "run.head_repository"
        )
        if (
            repository.get("id") != self.policy.repository_id
            or repository.get("full_name") != self.policy.repository
            or head_repository.get("id") != self.policy.repository_id
            or head_repository.get("full_name") != self.policy.repository
        ):
            reject(
                "RUN_REPOSITORY_MISMATCH", "run repository or head repository differs"
            )
        actor = self._object(run.get("triggering_actor"), "run.triggering_actor")
        actor_id = self._positive_int(actor.get("id"), "run.triggering_actor.id")
        if actor_id not in self.policy.allowed_dispatcher_actor_ids:
            reject(
                "RUN_ACTOR_MISMATCH", "triggering actor is not the trusted dispatcher"
            )
        run_attempt = self._positive_int(run.get("run_attempt"), "run.run_attempt")
        status = run.get("status")
        if status not in {"queued", "waiting", "pending", "in_progress"}:
            reject(
                "RUN_STATE_INVALID",
                "workflow run is not awaiting or entering execution",
            )
        workflow_path = run.get("path")
        if not isinstance(workflow_path, str):
            reject("GITHUB_TRUTH_INVALID", "run.path is missing")
        created_at = parse_utc(run.get("created_at"), "run.created_at")
        finalized_at = parse_utc(
            record_finalized_at or record_registered_at,
            "intent.finalizedAt",
        )
        if created_at < finalized_at or created_at > finalized_at + MAX_DISPATCH_DELAY:
            reject(
                "RUN_DISPATCH_WINDOW_INVALID", "workflow run is outside dispatch window"
            )
        if created_at > self._now() + timedelta(seconds=60):
            reject(
                "RUN_DISPATCH_WINDOW_INVALID",
                "workflow run creation time is in the future",
            )
        return workflow_path, run_attempt

    @staticmethod
    def _runner_name_digest(name: str) -> str:
        return f"sha256:{hashlib.sha256(name.encode('utf-8')).hexdigest()}"

    def _verify_live_runner_inventory(
        self,
        *,
        installation_id: int,
        repository: str,
        required_labels: tuple[str, ...],
        lease_payload: dict[str, Any],
    ) -> None:
        if "self-hosted" not in required_labels:
            return
        live = self.github.repository_runners(installation_id, repository)
        eligible: list[dict[str, Any]] = []
        for runner in live:
            runner_id = runner.get("id")
            name = runner.get("name")
            labels_value = runner.get("labels")
            if (
                not isinstance(runner_id, int)
                or isinstance(runner_id, bool)
                or runner_id < 1
                or not isinstance(name, str)
                or not name
                or runner.get("status") != "online"
                or not isinstance(runner.get("busy"), bool)
                or not isinstance(labels_value, list)
            ):
                reject(
                    "GITHUB_RUNNER_INVENTORY_INVALID",
                    "repository runner inventory contains an invalid runner",
                )
            labels: list[str] = []
            for label in labels_value:
                if not isinstance(label, dict) or not isinstance(
                    label.get("name"), str
                ):
                    reject(
                        "GITHUB_RUNNER_INVENTORY_INVALID",
                        "repository runner inventory contains an invalid label",
                    )
                labels.append(label["name"])
            if len(set(labels)) != len(labels):
                reject(
                    "GITHUB_RUNNER_INVENTORY_INVALID",
                    "repository runner inventory contains duplicate labels",
                )
            if set(required_labels).issubset(labels):
                eligible.append(
                    {
                        "runnerId": runner_id,
                        "runnerNameSha256": self._runner_name_digest(name),
                        "labels": sorted(labels),
                    }
                )
        signed = lease_payload["eligibleRunners"]
        signed_projection = sorted(
            (
                {
                    "runnerId": entry["runnerId"],
                    "runnerNameSha256": entry["runnerNameSha256"],
                    "labels": sorted(entry["labels"]),
                }
                for entry in signed
            ),
            key=lambda entry: entry["runnerId"],
        )
        live_projection = sorted(eligible, key=lambda entry: entry["runnerId"])
        generation = sha256_digest(
            {
                "domain": "acik.cross-ai-runner-inventory-generation.v1",
                "runners": live_projection,
            }
        )
        if (
            not live_projection
            or live_projection != signed_projection
            or generation != lease_payload["inventoryGenerationSha256"]
        ):
            reject(
                "RUNNER_ADMISSION_LEASE_DRIFT",
                "live eligible runner inventory differs from the signed lease",
            )

    def evaluate(self, request: DeploymentProtectionRequest) -> EvaluationResult:
        now = self._now()
        self._policy_binding(request)
        record, envelope = self.registry.get_finalized(request.request_id)
        if (
            record.repository_id != request.repository_id
            or record.repository != request.repository
            or record.environment != request.environment
            or record.head_sha != request.head_sha
            or record.intent_ref != request.intent_ref
        ):
            reject(
                "INTENT_WEBHOOK_BINDING_MISMATCH",
                "registered intent differs from webhook",
            )

        verified = EvidenceVerifier(
            trust_root=self.trust_root,
            revocations_envelope=self.revocations_loader(),
            now=now,
            expected_policy_sha256=self.policy.digest,
            expected_trust_root_sha256=self.expected_trust_root_sha256,
        ).verify_bundle(envelope)
        if (
            verified.bundle_digest != record.bundle_digest
            or verified.subject_digest != record.subject_digest
            or verified.session_digest != record.session_digest
        ):
            reject("INTENT_BUNDLE_MISMATCH", "registry and signed evidence differ")
        subject = verified.payload["subject"]
        grant = verified.payload["grant"]
        if subject["deploymentClass"] not in self.policy.allowed_deployment_classes:
            reject(
                "HUMAN_REQUIRED_CLASS",
                "deployment class is outside reversible non-prod",
            )
        if grant["triggeringActorId"] not in self.policy.allowed_dispatcher_actor_ids:
            reject("RUN_ACTOR_MISMATCH", "signed triggering actor is not allowlisted")
        grant_start = parse_utc(grant["notBefore"], "grant.notBefore")
        grant_end = parse_utc(grant["expiresAt"], "grant.expiresAt")
        if grant_end - grant_start > timedelta(
            minutes=self.policy.max_grant_ttl_minutes
        ):
            reject("GRANT_TTL_EXCEEDED", "grant exceeds deployment policy TTL")

        repository = self.github.repository(request.installation_id, request.repository)
        if (
            repository.get("id") != self.policy.repository_id
            or repository.get("full_name") != self.policy.repository
        ):
            reject("GITHUB_REPOSITORY_MISMATCH", "live repository identity differs")
        if repository.get("fork") is not False:
            reject("GITHUB_REPOSITORY_MISMATCH", "fork repositories are not authorized")
        environment = self.github.environment(
            request.installation_id, request.repository, request.environment
        )
        app_rule_id = self._environment_binding(environment)
        run = self.github.workflow_run(
            request.installation_id, request.repository, request.run_id
        )
        workflow_path, run_attempt = self._run_binding(
            request=request,
            run=run,
            record_registered_at=record.registered_at,
            record_finalized_at=record.finalized_at,
        )
        live_ref = self.github.intent_ref(
            request.installation_id, request.repository, request.request_id
        )
        if (
            live_ref.head_sha != request.head_sha
            or live_ref.ref_object_id != record.ref_object_id
        ):
            reject(
                "INTENT_REF_MOVED",
                "live intent ref no longer resolves to reviewed head",
            )

        matching_stages = [
            stage
            for stage in verified.payload["workflowStages"]
            if stage["workflowPath"] == workflow_path
        ]
        if len(matching_stages) != 1:
            reject("HEAD_OR_WORKFLOW_MISMATCH", "workflow path is not one signed stage")
        signed_stage = matching_stages[0]
        stage_name = signed_stage["stage"]
        stage_policy = self.policy.stages.get(stage_name)
        if stage_policy is None or stage_policy.workflow_path != workflow_path:
            reject("HEAD_OR_WORKFLOW_MISMATCH", "workflow path differs from policy")
        if tuple(signed_stage["runsOnLabels"]) != stage_policy.required_runs_on_labels:
            reject(
                "RUNNER_POLICY_OR_INPUT_AUTHORITY_MISMATCH",
                "signed runner labels differ",
            )
        if stage_policy.require_runner_group != ("runnerGroupId" in signed_stage):
            reject(
                "RUNNER_POLICY_OR_INPUT_AUTHORITY_MISMATCH",
                "signed runner group differs",
            )
        self._verify_live_runner_inventory(
            installation_id=request.installation_id,
            repository=request.repository,
            required_labels=stage_policy.required_runs_on_labels,
            lease_payload=verified.runner_admission_lease.payload,
        )

        workflow_raw = self.github.workflow_bytes(
            request.installation_id,
            request.repository,
            workflow_path,
            request.head_sha,
        )
        inspection = inspect_workflow(
            workflow_raw,
            stage_policy=stage_policy,
            environment=request.environment,
            expected_bootstrap_url=self.policy.runner_bootstrap_url,
        )
        if (
            inspection.workflow_sha256 != signed_stage["workflowBlobSha256"]
            or inspection.dependency_lock_sha256 != signed_stage["dependencyLockSha256"]
            or inspection.concurrency_group_sha256
            != signed_stage["concurrencyGroupSha256"]
        ):
            reject(
                "INTENT_REF_OR_DEPENDENCY_LOCK_MISMATCH",
                "workflow or dependency projection differs from signed evidence",
            )
        if (
            grant["triggeringActorId"]
            != self._object(run["triggering_actor"], "actor")["id"]
        ):
            reject("RUN_ACTOR_MISMATCH", "run actor differs from signed grant")

        return EvaluationResult(
            approval_candidate=True,
            reason_code="SIGNED_EVIDENCE_AND_GITHUB_TRUTH_VALID",
            request_id=request.request_id,
            stage=stage_name,
            run_id=request.run_id,
            run_attempt=run_attempt,
            app_rule_id=app_rule_id,
            evidence_digest=verified.bundle_digest,
            policy_digest=self.policy.digest,
            provider_families=verified.provider_families,
        )


__all__ = ["DeploymentEvaluator", "EvaluationResult", "GitHubTruthReader"]
