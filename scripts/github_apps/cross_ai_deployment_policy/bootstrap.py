"""Single-use, fail-closed runner bootstrap after Environment approval."""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable

from .canonical import sha256_digest
from .contract import EvidenceVerifier
from .errors import PolicyError, reject
from .evaluator import DeploymentEvaluator
from .oidc import GitHubOIDCVerifier
from .timeutil import parse_utc, utc_now, utc_seconds


REQUEST_ID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
FULL_SHA = re.compile(r"^[a-f0-9]{40}$")
STAGES = {"apply", "browser-evidence", "compensating-rollback"}
MAX_BOOTSTRAP_DELAY = timedelta(minutes=2)


@dataclass(frozen=True)
class RunnerBootstrapRequest:
    request_id: str
    stage: str
    run_id: int
    run_attempt: int
    intent_ref: str
    head_sha: str
    workflow_path: str
    runner_name: str

    @classmethod
    def parse(cls, value: object) -> "RunnerBootstrapRequest":
        if not isinstance(value, dict) or set(value) != {
            "requestId",
            "stage",
            "runId",
            "runAttempt",
            "intentRef",
            "headSha",
            "workflowPath",
            "runnerName",
        }:
            reject("BOOTSTRAP_REQUEST_INVALID", "bootstrap request fields are invalid")
        request_id = value["requestId"]
        stage = value["stage"]
        run_id = value["runId"]
        run_attempt = value["runAttempt"]
        intent_ref = value["intentRef"]
        head_sha = value["headSha"]
        workflow_path = value["workflowPath"]
        runner_name = value["runnerName"]
        if (
            not isinstance(request_id, str)
            or REQUEST_ID.fullmatch(request_id) is None
            or stage not in STAGES
            or not isinstance(run_id, int)
            or isinstance(run_id, bool)
            or run_id < 1
            or not isinstance(run_attempt, int)
            or isinstance(run_attempt, bool)
            or run_attempt < 1
            or intent_ref != f"refs/tags/cross-ai-intent/{request_id}"
            or not isinstance(head_sha, str)
            or FULL_SHA.fullmatch(head_sha) is None
            or not isinstance(workflow_path, str)
            or not workflow_path.startswith(".github/workflows/")
            or not workflow_path.endswith((".yml", ".yaml"))
            or not isinstance(runner_name, str)
            or not 1 <= len(runner_name) <= 200
            or any(character in runner_name for character in "\r\n\x00")
        ):
            reject("BOOTSTRAP_REQUEST_INVALID", "bootstrap request values are invalid")
        return cls(
            request_id=request_id,
            stage=stage,
            run_id=run_id,
            run_attempt=run_attempt,
            intent_ref=intent_ref,
            head_sha=head_sha,
            workflow_path=workflow_path,
            runner_name=runner_name,
        )


class RunnerBootstrapAuthorizer:
    def __init__(
        self,
        *,
        evaluator: DeploymentEvaluator,
        installation_id: int,
        oidc_verifier: GitHubOIDCVerifier,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        if installation_id not in evaluator.policy.allowed_installation_ids:
            reject(
                "BOOTSTRAP_INSTALLATION_INVALID",
                "bootstrap installation is not evaluator-authorized",
            )
        self.evaluator = evaluator
        self.installation_id = installation_id
        self.oidc_verifier = oidc_verifier
        self._now = now

    @staticmethod
    def _credential_digest(credential: bytes) -> str:
        if not 64 <= len(credential) <= 512 or b"\x00" in credential:
            reject("BOOTSTRAP_CREDENTIAL_INVALID", "bootstrap credential is invalid")
        return f"sha256:{hashlib.sha256(credential).hexdigest()}"

    @staticmethod
    def _runner_name_digest(name: str) -> str:
        return f"sha256:{hashlib.sha256(name.encode('utf-8')).hexdigest()}"

    def _verify_live_run_and_runner(
        self,
        *,
        request: RunnerBootstrapRequest,
        repository_id: int,
        repository: str,
        eligible_runners: list[dict[str, Any]],
    ) -> int:
        run = self.evaluator.github.workflow_run_attempt(
            self.installation_id,
            repository,
            request.run_id,
            request.run_attempt,
        )
        run_repository = run.get("repository")
        head_repository = run.get("head_repository")
        if (
            run.get("id") != request.run_id
            or run.get("run_attempt") != request.run_attempt
            or run.get("event") != "workflow_dispatch"
            or run.get("head_sha") != request.head_sha
            or run.get("head_branch") != request.intent_ref.removeprefix("refs/tags/")
            or run.get("path") != request.workflow_path
            or run.get("status") not in {"queued", "pending", "in_progress"}
            or not isinstance(run_repository, dict)
            or run_repository.get("id") != repository_id
            or run_repository.get("full_name") != repository
            or not isinstance(head_repository, dict)
            or head_repository.get("id") != repository_id
            or head_repository.get("full_name") != repository
        ):
            reject(
                "BOOTSTRAP_RUN_MISMATCH",
                "live workflow run differs from bootstrap request",
            )
        jobs = self.evaluator.github.workflow_jobs(
            self.installation_id,
            repository,
            request.run_id,
            request.run_attempt,
        )
        matches = [
            job
            for job in jobs
            if job.get("runner_name") == request.runner_name
            and job.get("status") == "in_progress"
            and isinstance(job.get("runner_id"), int)
            and not isinstance(job.get("runner_id"), bool)
            and job["runner_id"] > 0
        ]
        if len(matches) != 1:
            reject(
                "BOOTSTRAP_RUNNER_ASSIGNMENT_INVALID",
                "exactly one live in-progress job must bind the requesting runner",
            )
        runner_id = matches[0]["runner_id"]
        name_digest = self._runner_name_digest(request.runner_name)
        lease_matches = [
            entry
            for entry in eligible_runners
            if entry["runnerId"] == runner_id
            and entry["runnerNameSha256"] == name_digest
        ]
        if len(lease_matches) != 1:
            reject(
                "BOOTSTRAP_RUNNER_NOT_ADMITTED",
                "assigned runner is not in the signed admission lease",
            )
        return runner_id

    def authorize(
        self,
        *,
        request: RunnerBootstrapRequest,
        credential: bytes,
        oidc_token: str,
    ) -> dict[str, Any]:
        current = self._now()
        record, envelope = self.evaluator.registry.get_finalized(request.request_id)
        verified = EvidenceVerifier(
            trust_root=self.evaluator.trust_root,
            revocations_envelope=self.evaluator.revocations_loader(),
            now=current,
            expected_policy_sha256=self.evaluator.policy.digest,
            expected_trust_root_sha256=self.evaluator.expected_trust_root_sha256,
            expected_bundle_contract=self.evaluator.bundle_contract_version,
        ).verify_bundle(envelope)
        if verified.contract_version == "v3":
            reject(
                "BOOTSTRAP_NOT_APPLICABLE",
                "v3 transaction authority does not expose the retired stage bootstrap",
            )
        subject = verified.payload["subject"]
        grant = verified.payload["grant"]
        if (
            verified.bundle_digest != record.bundle_digest
            or verified.subject_digest != record.subject_digest
            or record.repository_id != subject["repositoryId"]
            or record.repository != subject["repository"]
            or record.environment != subject["environment"]
            or record.head_sha != request.head_sha
            or record.intent_ref != request.intent_ref
            or subject["headSha"] != request.head_sha
            or subject["intentRef"] != request.intent_ref
            or subject["repositoryId"] != self.evaluator.policy.repository_id
            or subject["repository"] != self.evaluator.policy.repository
            or subject["environment"] != self.evaluator.policy.environment
        ):
            reject("BOOTSTRAP_INTENT_MISMATCH", "bootstrap differs from signed intent")
        self.oidc_verifier.verify(
            oidc_token,
            repository_id=record.repository_id,
            repository=record.repository,
            environment=record.environment,
            intent_ref=request.intent_ref,
            head_sha=request.head_sha,
            workflow_path=request.workflow_path,
            run_id=request.run_id,
            run_attempt=request.run_attempt,
            actor_id=grant["triggeringActorId"],
        )
        if not hmac.compare_digest(
            self._credential_digest(credential),
            subject["bootstrapCredentialSha256"],
        ):
            reject(
                "BOOTSTRAP_CREDENTIAL_MISMATCH",
                "bootstrap credential is not subject-bound",
            )

        signed_stages = [
            stage
            for stage in verified.payload["workflowStages"]
            if stage["stage"] == request.stage
        ]
        if len(signed_stages) != 1:
            reject("BOOTSTRAP_STAGE_MISMATCH", "bootstrap stage is not signed")
        signed_stage = signed_stages[0]
        stage_policy = self.evaluator.policy.stages.get(request.stage)
        if (
            stage_policy is None
            or signed_stage["workflowPath"] != request.workflow_path
            or stage_policy.workflow_path != request.workflow_path
        ):
            reject("BOOTSTRAP_STAGE_MISMATCH", "bootstrap workflow differs from policy")
        reservation = self.evaluator.registry.get_stage(
            request.request_id, request.stage
        )
        if (
            reservation.state != "ApprovedPendingOutcome"
            or reservation.run_id != request.run_id
            or reservation.run_attempt != request.run_attempt
        ):
            reject("BOOTSTRAP_STAGE_NOT_APPROVED", "bootstrap run is not approved")
        approved_at = parse_utc(
            self.evaluator.registry.stage_approved_at(
                request.request_id, request.stage
            ),
            "bootstrap.approvedAt",
        )
        if current < approved_at or current > approved_at + MAX_BOOTSTRAP_DELAY:
            reject(
                "BOOTSTRAP_WINDOW_EXPIRED",
                "bootstrap did not start in the bounded window",
            )

        live_ref = self.evaluator.github.intent_ref(
            self.installation_id,
            record.repository,
            request.request_id,
        )
        if (
            live_ref.head_sha != request.head_sha
            or live_ref.ref_object_id != record.ref_object_id
        ):
            reject("INTENT_REF_MOVED", "live intent ref changed before bootstrap")
        self.evaluator._verify_live_runner_inventory(
            installation_id=self.installation_id,
            repository=record.repository,
            required_labels=stage_policy.required_runs_on_labels,
            lease_payload=verified.runner_admission_lease.payload,
        )
        runner_id = self._verify_live_run_and_runner(
            request=request,
            repository_id=record.repository_id,
            repository=record.repository,
            eligible_runners=verified.runner_admission_lease.payload["eligibleRunners"],
        )

        prior_stage: str | None = None
        if request.stage == "browser-evidence":
            prior_stage = "apply"
        elif request.stage == "compensating-rollback":
            prior_stage = "apply"
        prior_outcome_digest: str | None = None
        prior_outcome: dict[str, Any] | None = None
        prior_stage_state: str | None = None
        if prior_stage is not None:
            prior_reservation = self.evaluator.registry.get_stage(
                request.request_id, prior_stage
            )
            prior_stage_state = prior_reservation.state
            try:
                prior_outcome_digest, prior_outcome = (
                    self.evaluator.registry.get_stage_outcome(
                        request.request_id, prior_stage
                    )
                )
            except PolicyError as exc:
                if (
                    request.stage != "compensating-rollback"
                    or prior_stage_state != "CallbackUnknown"
                ):
                    raise
                if getattr(exc, "code", None) != "STAGE_OUTCOME_NOT_FOUND":
                    raise

        response = {
            "schemaVersion": "acik.cross-ai-runner-bootstrap-response.v1",
            "requestId": request.request_id,
            "stage": request.stage,
            "runId": request.run_id,
            "runAttempt": request.run_attempt,
            "runnerId": runner_id,
            "headSha": request.head_sha,
            "intentRef": request.intent_ref,
            "workflowPath": request.workflow_path,
            "bundleSha256": verified.bundle_digest,
            "bundleEnvelope": envelope,
            "priorStage": prior_stage,
            "priorStageState": prior_stage_state,
            "priorStageOutcomeSha256": prior_outcome_digest,
            "priorStageOutcome": prior_outcome,
            "issuedAt": utc_seconds(current),
            "expiresAt": reservation.reservation_expires_at,
        }
        response_digest = sha256_digest(response)
        response["responseSha256"] = response_digest
        self.evaluator.registry.consume_bootstrap(
            request_id=request.request_id,
            stage=request.stage,
            run_id=request.run_id,
            run_attempt=request.run_attempt,
            runner_id=runner_id,
            response_digest=response_digest,
            consumed_at=current,
        )
        return response


__all__ = ["RunnerBootstrapAuthorizer", "RunnerBootstrapRequest"]
