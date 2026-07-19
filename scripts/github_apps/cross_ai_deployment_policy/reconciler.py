"""Reconcile live GitHub run/job/artifact truth into durable stage outcomes."""

from __future__ import annotations

import hashlib
import io
import logging
import stat
import threading
import time
import zipfile
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Protocol

from jsonschema import Draft202012Validator, FormatChecker

from .canonical import canonical_bytes, sha256_digest
from .contract import EvidenceVerifier
from .dsse import decode_public_key, verify_json_envelope
from .errors import PolicyError, reject
from .github import GitHubArtifactDownloader, GitHubReader
from .intent_store import IntentRegistry
from .jsonutil import load_json_file, loads_json_bytes
from .outcome import (
    OUTCOME_PAYLOAD_TYPE,
    VerifiedStageOutcome,
    verify_stage_outcome,
)
from .provider import EnvelopeSigner
from .runtime_receipts import (
    RuntimeReceiptVerifier,
    runtime_evidence_from_archive,
)
from .timeutil import parse_utc, utc_now
from .transaction import verify_transaction_final, verify_transaction_preflight


ROOT = Path(__file__).resolve().parents[3]
STAGE_EVIDENCE_SCHEMA = (
    ROOT / "schema/cross-ai-deployment-stage-evidence-v1.schema.json"
)
STAGE_EVIDENCE_FILE = "cross-ai-stage-evidence.json"
MAX_STAGE_EVIDENCE_BYTES = 1024 * 1024
MAX_ZIP_COMPRESSION_RATIO = 100
TERMINAL_CONCLUSIONS = {
    "success",
    "failure",
    "cancelled",
    "timed_out",
    "action_required",
    "startup_failure",
    "stale",
}
LOGGER = logging.getLogger("cross_ai_deployment_policy.reconciler")


class OutcomeGitHubReader(Protocol):
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

    def workflow_bytes(
        self,
        installation_id: int,
        repository: str,
        workflow_path: str,
        head_sha: str,
    ) -> bytes: ...


class StageArtifactSource(Protocol):
    def fetch(
        self,
        *,
        installation_id: int,
        repository: str,
        run_id: int,
        artifact_name: str,
        expected_artifact_id: int | None = None,
    ) -> bytes: ...


class GitHubStageArtifactSource:
    def __init__(
        self,
        *,
        reader: GitHubReader,
        downloader: GitHubArtifactDownloader,
    ) -> None:
        self.reader = reader
        self.downloader = downloader

    def fetch(
        self,
        *,
        installation_id: int,
        repository: str,
        run_id: int,
        artifact_name: str,
        expected_artifact_id: int | None = None,
    ) -> bytes:
        artifact = self.reader.workflow_artifact(
            installation_id,
            repository,
            run_id,
            artifact_name,
        )
        if (
            expected_artifact_id is not None
            and artifact.artifact_id != expected_artifact_id
        ):
            reject(
                "STAGE_PRODUCT_ARTIFACT_MISMATCH",
                "live product artifact ID differs from stage evidence",
            )
        return self.downloader.download(
            installation_id=installation_id,
            repository=repository,
            artifact=artifact,
        )


def _stage_evidence_from_archive(archive: bytes) -> dict[str, Any]:
    if not archive:
        reject("STAGE_ARTIFACT_INVALID", "stage artifact archive is empty")
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            infos = bundle.infolist()
            if len(infos) != 1 or infos[0].filename != STAGE_EVIDENCE_FILE:
                reject(
                    "STAGE_ARTIFACT_INVALID",
                    "stage artifact must contain exactly one canonical evidence file",
                )
            info = infos[0]
            mode = info.external_attr >> 16
            if (
                info.is_dir()
                or info.flag_bits & 0x1
                or stat.S_ISLNK(mode)
                or not 1 <= info.file_size <= MAX_STAGE_EVIDENCE_BYTES
                or info.compress_size < 1
                or info.file_size > info.compress_size * MAX_ZIP_COMPRESSION_RATIO
            ):
                reject("STAGE_ARTIFACT_INVALID", "stage evidence ZIP entry is unsafe")
            raw = bundle.read(info)
    except (zipfile.BadZipFile, KeyError, RuntimeError):
        reject("STAGE_ARTIFACT_INVALID", "stage artifact is not a safe ZIP archive")
    if len(raw) != info.file_size:
        reject(
            "STAGE_ARTIFACT_INVALID", "stage evidence size differs from ZIP metadata"
        )
    value = loads_json_bytes(
        raw,
        max_bytes=MAX_STAGE_EVIDENCE_BYTES,
        label="stage evidence",
    )
    if canonical_bytes(value) != raw:
        reject("STAGE_ARTIFACT_NON_CANONICAL", "stage evidence JSON is not canonical")
    schema = load_json_file(STAGE_EVIDENCE_SCHEMA)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
        key=lambda item: list(item.path),
    )
    if errors:
        reject(
            "STAGE_EVIDENCE_SCHEMA_INVALID", "stage evidence schema validation failed"
        )
    return value


def _critical_jobs_digest(
    jobs: tuple[dict[str, Any], ...], *, run_attempt: int, require_success: bool
) -> str:
    projection: list[dict[str, Any]] = []
    names: set[str] = set()
    for job in jobs:
        name = job.get("name")
        conclusion = job.get("conclusion")
        if (
            not isinstance(name, str)
            or not name
            or name in names
            or job.get("run_attempt") != run_attempt
            or job.get("status") != "completed"
            or conclusion not in TERMINAL_CONCLUSIONS
        ):
            reject(
                "GITHUB_JOBS_INVALID", "critical job identity or conclusion is invalid"
            )
        names.add(name)
        if require_success and conclusion != "success":
            reject("GITHUB_CRITICAL_JOB_FAILED", "a critical job did not succeed")
        steps_value = job.get("steps")
        if not isinstance(steps_value, list) or not steps_value:
            reject("GITHUB_JOBS_INVALID", "critical job steps are missing")
        steps: list[dict[str, Any]] = []
        numbers: set[int] = set()
        for step in steps_value:
            if not isinstance(step, dict):
                reject("GITHUB_JOBS_INVALID", "critical step is invalid")
            number = step.get("number")
            step_name = step.get("name")
            step_conclusion = step.get("conclusion")
            if (
                not isinstance(number, int)
                or isinstance(number, bool)
                or number < 1
                or number in numbers
                or not isinstance(step_name, str)
                or not step_name
                or step.get("status") != "completed"
                or step_conclusion not in TERMINAL_CONCLUSIONS | {"skipped"}
            ):
                reject("GITHUB_JOBS_INVALID", "critical step state is invalid")
            numbers.add(number)
            if require_success and step_conclusion != "success":
                reject("GITHUB_CRITICAL_JOB_FAILED", "a critical step did not succeed")
            steps.append(
                {"number": number, "name": step_name, "conclusion": step_conclusion}
            )
        projection.append(
            {
                "name": name,
                "conclusion": conclusion,
                "steps": sorted(steps, key=lambda item: item["number"]),
            }
        )
    return sha256_digest(
        {
            "domain": "acik.cross-ai-critical-jobs.v1",
            "jobs": sorted(projection, key=lambda item: item["name"]),
        }
    )


class GitHubOutcomeReconciler:
    def __init__(
        self,
        *,
        installation_id: int,
        registry: IntentRegistry,
        github: OutcomeGitHubReader,
        artifact_source: StageArtifactSource,
        trust_root: dict[str, Any],
        expected_trust_root_sha256: str,
        revocations_loader: Callable[[], dict[str, Any]],
        bundle_contract_version: str = "v1",
        outcome_signer: EnvelopeSigner | None = None,
        runtime_verifier_loader: Callable[
            [Any, dict[str, Any], datetime], RuntimeReceiptVerifier
        ]
        | None = None,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        if installation_id < 1:
            reject("GITHUB_INSTALLATION_ID_INVALID", "installation ID must be positive")
        self.installation_id = installation_id
        self.registry = registry
        self.github = github
        self.artifact_source = artifact_source
        self.trust_root = trust_root
        self.expected_trust_root_sha256 = expected_trust_root_sha256
        self.revocations_loader = revocations_loader
        if bundle_contract_version not in {"v1", "v2", "v3"}:
            reject(
                "BUNDLE_CONTRACT_INVALID",
                "outcome reconciler contract version is unsupported",
            )
        self.bundle_contract_version = bundle_contract_version
        if bundle_contract_version == "v3" and outcome_signer is None:
            reject(
                "STAGE_OUTCOME_SIGNER_REQUIRED",
                "v3 reconciler requires a Vault-backed coordinator signer",
            )
        self.outcome_signer = outcome_signer
        self.runtime_verifier_loader = runtime_verifier_loader
        self.coordinator_public_keys = {
            entry["keyId"]: decode_public_key(
                entry["publicKeyBase64"], entry["keyId"]
            )
            for entry in trust_root.get("keys", [])
            if isinstance(entry, dict)
            and entry.get("role") == "coordinator"
            and isinstance(entry.get("keyId"), str)
        }
        if bundle_contract_version == "v3" and (
            outcome_signer is None
            or outcome_signer.key_id not in self.coordinator_public_keys
        ):
            reject(
                "STAGE_OUTCOME_SIGNER_INVALID",
                "v3 outcome signer is not a trust-root coordinator key",
            )
        self._now = now

    def _runtime_verifier(
        self,
        *,
        record: Any,
        signed_stage: dict[str, Any],
        current: datetime,
    ) -> RuntimeReceiptVerifier:
        if self.runtime_verifier_loader is not None:
            return self.runtime_verifier_loader(record, signed_stage, current)
        signed_files = {
            entry["path"]: entry["sha256"]
            for entry in signed_stage.get("authorityFiles", [])
            if isinstance(entry, dict)
            and isinstance(entry.get("path"), str)
            and isinstance(entry.get("sha256"), str)
        }
        authority_path = "config/faz22-6-view-only-live-preflight-authority.v1.json"
        trust_root_path = "config/faz22-6-view-only-runtime-trust-root.v1.json"
        if authority_path not in signed_files or trust_root_path not in signed_files:
            reject(
                "RUNTIME_AUTHORITY_FILE_MISSING",
                "signed transaction scope omits runtime authority files",
            )
        values: dict[str, dict[str, Any]] = {}
        for path in (authority_path, trust_root_path):
            raw = self.github.workflow_bytes(
                self.installation_id,
                record.repository,
                path,
                record.head_sha,
            )
            if f"sha256:{hashlib.sha256(raw).hexdigest()}" != signed_files[path]:
                reject(
                    "RUNTIME_AUTHORITY_FILE_MISMATCH",
                    "exact-head runtime authority differs from signed transaction scope",
                )
            values[path] = loads_json_bytes(
                raw,
                max_bytes=256 * 1024,
                label=f"runtime authority {path}",
            )
        return RuntimeReceiptVerifier(
            authority=values[authority_path],
            runtime_trust_root=values[trust_root_path],
            now=current,
            max_clock_skew_seconds=self.trust_root["maxClockSkewSeconds"],
        )

    def _reconcile_transaction(
        self,
        *,
        current: datetime,
        record: Any,
        verified: Any,
        authorization_envelope: dict[str, Any],
        reservation: Any,
        signed_stage: dict[str, Any],
        run: dict[str, Any],
        run_started_at: str,
        critical_jobs_sha256: str,
    ) -> VerifiedStageOutcome:
        preflight_name = (
            "faz22-view-only-transaction-preflight-"
            f"{reservation.run_id}-{reservation.run_attempt}"
        )
        preflight_archive = self.artifact_source.fetch(
            installation_id=self.installation_id,
            repository=record.repository,
            run_id=reservation.run_id,
            artifact_name=preflight_name,
        )
        preflight = verify_transaction_preflight(
            preflight_archive,
            repository=record.repository,
            workflow_path=signed_stage["workflowPath"],
            intent_ref=record.intent_ref,
            head_sha=record.head_sha,
            run_id=reservation.run_id,
            run_attempt=reservation.run_attempt,
            subject=verified.payload["subject"],
            grant=verified.payload["grant"],
            observed_at=current,
            max_clock_skew_seconds=self.trust_root["maxClockSkewSeconds"],
        )
        final_name = (
            "faz22-view-only-transaction-final-"
            f"{reservation.run_id}-{reservation.run_attempt}"
        )
        final_archive = self.artifact_source.fetch(
            installation_id=self.installation_id,
            repository=record.repository,
            run_id=reservation.run_id,
            artifact_name=final_name,
        )
        final = verify_transaction_final(
            final_archive,
            repository=record.repository,
            workflow_path=signed_stage["workflowPath"],
            intent_ref=record.intent_ref,
            head_sha=record.head_sha,
            run_id=reservation.run_id,
            run_attempt=reservation.run_attempt,
            subject=verified.payload["subject"],
            grant=verified.payload["grant"],
            preflight_sha256=preflight.preflight_sha256,
            observed_at=current,
            max_clock_skew_seconds=self.trust_root["maxClockSkewSeconds"],
        )
        runtime_name = (
            "faz22-view-only-transaction-runtime-"
            f"{reservation.run_id}-{reservation.run_attempt}"
        )
        runtime_archive = self.artifact_source.fetch(
            installation_id=self.installation_id,
            repository=record.repository,
            run_id=reservation.run_id,
            artifact_name=runtime_name,
        )
        runtime_package = runtime_evidence_from_archive(runtime_archive)
        runtime_chain = self._runtime_verifier(
            record=record,
            signed_stage=signed_stage,
            current=current,
        ).verify_chain(
            binding_handoff_envelope=runtime_package.binding_handoff_envelope,
            coordinator_public_keys=self.coordinator_public_keys,
            coordinator_key_id=verified.coordinator_key_id,
            evaluation_preflight_envelope=(
                runtime_package.evaluation_preflight_envelope
            ),
            redemption_preflight_envelope=(
                runtime_package.redemption_preflight_envelope
            ),
            lease_envelope=runtime_package.lease_envelope,
            authorization_envelope=authorization_envelope,
            authorization_bundle=verified,
            checkpoint_envelopes=runtime_package.checkpoint_envelopes,
            final_state=final.state,
            observed_at=current,
        )
        expected_run_conclusion = (
            "success" if final.conclusion == "success" else "failure"
        )
        if run.get("conclusion") != expected_run_conclusion:
            reject(
                "TRANSACTION_FINAL_RUN_MISMATCH",
                "terminal transaction state differs from the live run conclusion",
            )
        if final.pre_rollback_artifact_id is not None:
            pre_rollback_name = (
                "faz22-view-only-transaction-pre-rollback-"
                f"{reservation.run_id}-{reservation.run_attempt}"
            )
            pre_rollback_archive = self.artifact_source.fetch(
                installation_id=self.installation_id,
                repository=record.repository,
                run_id=reservation.run_id,
                artifact_name=pre_rollback_name,
                expected_artifact_id=final.pre_rollback_artifact_id,
            )
            live_digest = (
                f"sha256:{hashlib.sha256(pre_rollback_archive).hexdigest()}"
            )
            if live_digest != final.pre_rollback_artifact_digest:
                reject(
                    "TRANSACTION_PRE_ROLLBACK_ARTIFACT_MISMATCH",
                    "pre-rollback artifact differs from the terminal upload receipt",
                )
        subject = verified.payload["subject"]
        outcome = {
            "schemaVersion": "acik.cross-ai-deployment-stage-outcome.v1",
            "requestId": verified.request_id,
            "stage": "transaction",
            "runId": reservation.run_id,
            "runAttempt": reservation.run_attempt,
            "runStartedAt": run_started_at,
            "repositoryId": subject["repositoryId"],
            "repository": subject["repository"],
            "environment": subject["environment"],
            "headSha": subject["headSha"],
            "intentRef": subject["intentRef"],
            "sessionSha256": subject["sessionSha256"],
            "workflowBlobSha256": signed_stage["workflowBlobSha256"],
            "criticalJobsSha256": critical_jobs_sha256,
            "sourceArtifactName": final_name,
            "sourceArchiveSha256": final.archive_sha256,
            "runtimeEvidenceArtifactName": runtime_name,
            "runtimeEvidenceArchiveSha256": runtime_package.archive_sha256,
            "runtimeLeaseEnvelopeSha256": runtime_chain.lease.envelope_sha256,
            "runtimeTerminalReceiptSha256": (
                runtime_chain.terminal.envelope_sha256
            ),
            "artifactSetSha256": subject["artifactSetSha256"],
            "rollbackPlanSha256": subject["rollbackPlanSha256"],
            "postDeployVerifierSha256": subject["postDeployVerifierSha256"],
            "productArtifactId": None,
            "productArtifactName": None,
            "productArtifactDigest": None,
            "watchdogExpiresAt": None,
            "conclusion": final.conclusion,
            "createdAt": final.state["checkpoints"][-1]["observedAt"],
        }
        verified_outcome = verify_stage_outcome(
            outcome,
            bundle=verified,
            expected_stage="transaction",
            expected_run_id=reservation.run_id,
            expected_run_attempt=reservation.run_attempt,
            expected_run_started_at=run_started_at,
            expected_critical_jobs_sha256=critical_jobs_sha256,
            expected_source_artifact_name=final_name,
            expected_source_archive_sha256=final.archive_sha256,
            expected_runtime_evidence_artifact_name=runtime_name,
            expected_runtime_evidence_archive_sha256=(
                runtime_package.archive_sha256
            ),
            expected_runtime_lease_envelope_sha256=(
                runtime_chain.lease.envelope_sha256
            ),
            expected_runtime_terminal_receipt_sha256=(
                runtime_chain.terminal.envelope_sha256
            ),
            now=current,
        )
        assert self.outcome_signer is not None
        if self.outcome_signer.key_id != verified.coordinator_key_id:
            reject(
                "STAGE_OUTCOME_SIGNER_MISMATCH",
                "outcome signer differs from the signed intent coordinator",
            )
        envelope = self.outcome_signer.sign_json_envelope(
            payload_type=OUTCOME_PAYLOAD_TYPE,
            payload=verified_outcome.payload,
        )
        receipt = verify_json_envelope(
            envelope,
            expected_payload_type=OUTCOME_PAYLOAD_TYPE,
            allowed_keys={
                self.outcome_signer.key_id: self.coordinator_public_keys[
                    self.outcome_signer.key_id
                ]
            },
            required_key_ids={self.outcome_signer.key_id},
            exactly_one_signature=True,
        )
        if receipt.payload != verified_outcome.payload:
            reject(
                "STAGE_OUTCOME_SIGNATURE_INVALID",
                "signed outcome receipt payload changed after verification",
            )
        verified_outcome = replace(
            verified_outcome,
            receipt_digest=receipt.envelope_digest,
            receipt_signer_key_id=self.outcome_signer.key_id,
        )
        self.registry.record_stage_outcome(
            request_id=verified_outcome.request_id,
            stage=verified_outcome.stage,
            run_id=verified_outcome.run_id,
            run_attempt=verified_outcome.run_attempt,
            outcome=verified_outcome.payload,
            outcome_digest=verified_outcome.outcome_digest,
            target_state=verified_outcome.target_state,
            outcome_envelope=envelope,
            outcome_envelope_digest=receipt.envelope_digest,
            outcome_signer_key_id=self.outcome_signer.key_id,
            recorded_at=current,
        )
        return verified_outcome

    def reconcile(self, *, request_id: str, stage: str) -> VerifiedStageOutcome:
        current = self._now()
        record, envelope = self.registry.get_finalized(request_id)
        verified = EvidenceVerifier(
            trust_root=self.trust_root,
            revocations_envelope=self.revocations_loader(),
            now=current,
            expected_trust_root_sha256=self.expected_trust_root_sha256,
            expected_bundle_contract=self.bundle_contract_version,
        ).verify_bundle(envelope)
        reservation = self.registry.get_stage(request_id, stage)
        signed_stages = [
            item
            for item in verified.payload["workflowStages"]
            if item["stage"] == stage
        ]
        if len(signed_stages) != 1:
            reject("STAGE_OUTCOME_BINDING_MISMATCH", "signed stage is ambiguous")
        signed_stage = signed_stages[0]
        run = self.github.workflow_run_attempt(
            self.installation_id,
            record.repository,
            reservation.run_id,
            reservation.run_attempt,
        )
        run_repository = run.get("repository")
        head_repository = run.get("head_repository")
        expected_branch = record.intent_ref.removeprefix("refs/tags/")
        if (
            run.get("id") != reservation.run_id
            or run.get("run_attempt") != reservation.run_attempt
            or run.get("event") != "workflow_dispatch"
            or run.get("head_sha") != record.head_sha
            or run.get("head_branch") != expected_branch
            or run.get("path") != signed_stage["workflowPath"]
            or not isinstance(run_repository, dict)
            or run_repository.get("id") != record.repository_id
            or run_repository.get("full_name") != record.repository
            or not isinstance(head_repository, dict)
            or head_repository.get("id") != record.repository_id
            or head_repository.get("full_name") != record.repository
        ):
            reject(
                "STAGE_OUTCOME_RUN_MISMATCH",
                "workflow run differs from signed reservation",
            )
        if (
            run.get("status") != "completed"
            or run.get("conclusion") not in TERMINAL_CONCLUSIONS
        ):
            reject(
                "STAGE_OUTCOME_RUN_NOT_TERMINAL", "workflow run attempt is not terminal"
            )
        if reservation.state == "OutcomeOverdue":
            self.registry.transition_stage(
                request_id=request_id,
                stage=stage,
                to_state="CallbackUnknown",
                reason_code="TERMINAL_RUN_WITH_UNSEALED_OUTCOME",
                recorded_at=current,
            )
        run_started_at = run.get("run_started_at")
        if not isinstance(run_started_at, str):
            reject("STAGE_OUTCOME_RUN_MISMATCH", "run start time is missing")
        parse_utc(run_started_at, "workflowRun.run_started_at")
        jobs = self.github.workflow_jobs(
            self.installation_id,
            record.repository,
            reservation.run_id,
            reservation.run_attempt,
        )
        critical_jobs_sha256 = _critical_jobs_digest(
            jobs,
            run_attempt=reservation.run_attempt,
            require_success=run["conclusion"] == "success",
        )
        if stage == "transaction":
            return self._reconcile_transaction(
                current=current,
                record=record,
                verified=verified,
                authorization_envelope=envelope,
                reservation=reservation,
                signed_stage=signed_stage,
                run=run,
                run_started_at=run_started_at,
                critical_jobs_sha256=critical_jobs_sha256,
            )
        artifact_name = (
            f"cross-ai-stage-outcome-{request_id}-{stage}-"
            f"{reservation.run_id}-{reservation.run_attempt}"
        )
        archive = self.artifact_source.fetch(
            installation_id=self.installation_id,
            repository=record.repository,
            run_id=reservation.run_id,
            artifact_name=artifact_name,
        )
        archive_sha256 = f"sha256:{hashlib.sha256(archive).hexdigest()}"
        evidence = _stage_evidence_from_archive(archive)
        if stage == "browser-evidence" and evidence["conclusion"] == "success":
            product_artifact_id = evidence["productArtifactId"]
            product_artifact_name = evidence["productArtifactName"]
            product_artifact_digest = evidence["productArtifactDigest"]
            if (
                not isinstance(product_artifact_id, int)
                or isinstance(product_artifact_id, bool)
                or product_artifact_id < 1
                or not isinstance(product_artifact_name, str)
                or not product_artifact_name
                or not isinstance(product_artifact_digest, str)
            ):
                reject(
                    "STAGE_PRODUCT_ARTIFACT_MISMATCH",
                    "successful browser evidence lacks product artifact binding",
                )
            product_archive = self.artifact_source.fetch(
                installation_id=self.installation_id,
                repository=record.repository,
                run_id=reservation.run_id,
                artifact_name=product_artifact_name,
                expected_artifact_id=product_artifact_id,
            )
            live_product_digest = (
                f"sha256:{hashlib.sha256(product_archive).hexdigest()}"
            )
            if live_product_digest != product_artifact_digest:
                reject(
                    "STAGE_PRODUCT_ARTIFACT_MISMATCH",
                    "downloaded product artifact digest differs from stage evidence",
                )
        outcome = dict(evidence)
        outcome["schemaVersion"] = "acik.cross-ai-deployment-stage-outcome.v1"
        outcome["runStartedAt"] = run_started_at
        outcome["criticalJobsSha256"] = critical_jobs_sha256
        outcome["sourceArtifactName"] = artifact_name
        outcome["sourceArchiveSha256"] = archive_sha256
        expected_conclusion = (
            "rolled-back"
            if stage == "compensating-rollback" and run["conclusion"] == "success"
            else run["conclusion"]
        )
        if expected_conclusion not in {"success", "failure", "rolled-back"}:
            expected_conclusion = "failure"
        if outcome.get("conclusion") != expected_conclusion:
            reject(
                "STAGE_OUTCOME_RUN_MISMATCH",
                "artifact conclusion differs from live run",
            )
        verified_outcome = verify_stage_outcome(
            outcome,
            bundle=verified,
            expected_stage=stage,
            expected_run_id=reservation.run_id,
            expected_run_attempt=reservation.run_attempt,
            expected_run_started_at=run_started_at,
            expected_critical_jobs_sha256=critical_jobs_sha256,
            expected_source_artifact_name=artifact_name,
            expected_source_archive_sha256=archive_sha256,
            now=current,
        )
        self.registry.record_stage_outcome(
            request_id=verified_outcome.request_id,
            stage=verified_outcome.stage,
            run_id=verified_outcome.run_id,
            run_attempt=verified_outcome.run_attempt,
            outcome=verified_outcome.payload,
            outcome_digest=verified_outcome.outcome_digest,
            target_state=verified_outcome.target_state,
            recorded_at=current,
        )
        return verified_outcome


class OutcomeSweeper:
    """Continuously reconcile missed completion webhooks and restart windows."""

    def __init__(
        self,
        *,
        registry: IntentRegistry,
        reconciler: GitHubOutcomeReconciler,
        interval_seconds: float = 30.0,
        autostart: bool = False,
    ) -> None:
        if not 1.0 <= interval_seconds <= 120.0:
            reject("OUTCOME_SWEEPER_INTERVAL_INVALID", "sweeper interval is invalid")
        self.registry = registry
        self.reconciler = reconciler
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._lifecycle_lock = threading.Lock()
        self._started = False
        self._last_heartbeat = 0.0
        self._thread = threading.Thread(
            target=self._loop,
            name="cross-ai-outcome-sweeper",
            daemon=True,
        )
        if autostart:
            self.start()

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._started:
                return
            if self._stop.is_set():
                reject("OUTCOME_SWEEPER_STOPPED", "stopped sweeper cannot be restarted")
            self._thread.start()
            self._started = True

    def run_once(self) -> tuple[int, int]:
        self.registry.expire_pending_stages()
        attempted = 0
        completed = 0
        for reservation in self.registry.pending_stages():
            attempted += 1
            try:
                self.reconciler.reconcile(
                    request_id=reservation.request_id,
                    stage=reservation.stage,
                )
                completed += 1
            except PolicyError as exc:
                LOGGER.info(
                    "outcome reconciliation pending request_id=%s stage=%s code=%s",
                    reservation.request_id,
                    reservation.stage,
                    exc.code,
                )
            except Exception:
                LOGGER.exception(
                    "unexpected outcome reconciliation error request_id=%s stage=%s",
                    reservation.request_id,
                    reservation.stage,
                )
        return attempted, completed

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._last_heartbeat = time.monotonic()
            try:
                self.run_once()
            except Exception:
                LOGGER.exception("unexpected outcome sweeper loop error")
            self._last_heartbeat = time.monotonic()
            self._stop.wait(self.interval_seconds)

    def ready(self) -> bool:
        if not self._started or not self._thread.is_alive() or self._stop.is_set():
            return False
        return (
            time.monotonic() - self._last_heartbeat <= self.interval_seconds * 2 + 5.0
        )

    def stop(self) -> None:
        self._stop.set()
        if self._started and self._thread.is_alive():
            self._thread.join(timeout=60.0)
        if self._thread.is_alive():
            reject(
                "OUTCOME_SWEEPER_STOP_TIMEOUT", "sweeper did not stop before shutdown"
            )


__all__ = [
    "GitHubOutcomeReconciler",
    "GitHubStageArtifactSource",
    "OutcomeSweeper",
    "OutcomeGitHubReader",
    "StageArtifactSource",
]
