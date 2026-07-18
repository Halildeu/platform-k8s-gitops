"""Crash-safe, at-most-once dispatch of signed deployment intents."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable, Protocol

from .contract import VerifiedBundle
from .errors import PolicyError, reject
from .github import DispatchResult, GitHubIntentRef
from .intent_store import DispatchJob, IntentRegistry
from .timeutil import parse_utc, utc_now, utc_seconds


MAX_DISPATCH_DELAY = timedelta(minutes=10)


class IntentRefDispatcher(Protocol):
    def create_intent_ref(
        self,
        *,
        installation_id: int,
        repository: str,
        request_id: str,
        head_sha: str,
    ) -> GitHubIntentRef: ...

    def dispatch_workflow(
        self,
        *,
        installation_id: int,
        repository: str,
        workflow_path: str,
        request_id: str,
    ) -> DispatchResult: ...


class DispatchTruthReader(Protocol):
    def intent_ref(
        self,
        installation_id: int,
        repository: str,
        request_id: str,
    ) -> GitHubIntentRef: ...

    def workflow_runs_for_dispatch(
        self,
        installation_id: int,
        repository: str,
        workflow_path: str,
        intent_branch: str,
        created_from: str,
        created_to: str,
    ) -> tuple[dict[str, Any], ...]: ...


class IntentDispatchOrchestrator:
    """Bind verified evidence to an immutable ref before one external POST.

    GitHub does not expose an idempotency key for ``workflow_dispatch``.  A
    durable ``Sending`` claim is therefore never retried automatically.  Live
    workflow-run truth is the only way to reconcile an ambiguous POST.
    """

    def __init__(
        self,
        *,
        registry: IntentRegistry,
        dispatcher: IntentRefDispatcher,
        reader: DispatchTruthReader,
        installation_id: int,
        registration_principal: str,
        verify_envelope: Callable[[dict[str, Any]], VerifiedBundle],
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        if installation_id < 1:
            reject("DISPATCH_TARGET_INVALID", "dispatch App installation ID must be positive")
        if not registration_principal.startswith("spiffe://"):
            reject("REGISTRATION_PRINCIPAL_INVALID", "registration principal must be SPIFFE")
        self.registry = registry
        self.dispatcher = dispatcher
        self.reader = reader
        self.installation_id = installation_id
        self.registration_principal = registration_principal
        self.verify_envelope = verify_envelope
        self._now = now

    def _verified_record(
        self, request_id: str
    ) -> tuple[Any, dict[str, Any], VerifiedBundle]:
        record, envelope = self.registry.get_finalized(request_id)
        verified = self.verify_envelope(envelope)
        subject = verified.payload["subject"]
        grant = verified.payload["grant"]
        if (
            verified.request_id != record.request_id
            or verified.bundle_digest != record.bundle_digest
            or verified.subject_digest != record.subject_digest
            or verified.session_digest != record.session_digest
            or subject["repositoryId"] != record.repository_id
            or subject["repository"] != record.repository
            or subject["headSha"] != record.head_sha
            or subject["intentRef"] != record.intent_ref
            or grant["triggeringActorId"] != record.triggering_actor_id
        ):
            reject(
                "INTENT_BUNDLE_MISMATCH",
                "registry projection differs from currently verified evidence",
            )
        return record, envelope, verified

    def register_and_dispatch_apply(
        self,
        *,
        envelope: dict[str, Any],
    ) -> DispatchJob:
        current = self._now()
        verified = self.verify_envelope(envelope)
        self.registry.register(
            envelope=envelope,
            verified=verified,
            registration_principal=self.registration_principal,
            registered_at=current,
        )
        subject = verified.payload["subject"]
        live_ref = self.dispatcher.create_intent_ref(
            installation_id=self.installation_id,
            repository=subject["repository"],
            request_id=verified.request_id,
            head_sha=subject["headSha"],
        )
        self.registry.finalize_ref(
            request_id=verified.request_id,
            ref_object_id=live_ref.ref_object_id,
            resolved_head_sha=live_ref.head_sha,
            finalized_at=current,
        )
        return self.dispatch_stage(request_id=verified.request_id, stage="apply")

    def dispatch_stage(self, *, request_id: str, stage: str) -> DispatchJob:
        current = self._now()
        record, _, _ = self._verified_record(request_id)
        job = self.registry.queue_dispatch(
            request_id=request_id,
            stage=stage,
            installation_id=self.installation_id,
            repository=record.repository,
            queued_at=current,
        )
        if job.state != "Pending":
            # A previous process already crossed the durable dispatch claim.
            # Returning its state is safe; issuing another POST is not.
            return job
        claimed = self.registry.claim_dispatch(
            request_id=request_id,
            stage=stage,
            claimed_at=current,
        )
        snapshot_at = self._now()
        preexisting = self.reader.workflow_runs_for_dispatch(
            claimed.installation_id,
            claimed.repository,
            claimed.workflow_path,
            record.intent_ref.removeprefix("refs/tags/"),
            record.finalized_at or record.registered_at,
            utc_seconds(snapshot_at),
        )
        run_ids = [run.get("id") for run in preexisting]
        if any(
            not isinstance(run_id, int) or isinstance(run_id, bool) or run_id < 1
            for run_id in run_ids
        ):
            reject("DISPATCH_WATERMARK_INVALID", "pre-dispatch run snapshot is invalid")
        self.registry.record_dispatch_watermark(
            request_id=request_id,
            stage=stage,
            watermark=max(run_ids, default=0),
            snapshot_at=snapshot_at,
        )
        result = self.dispatcher.dispatch_workflow(
            installation_id=claimed.installation_id,
            repository=claimed.repository,
            workflow_path=claimed.workflow_path,
            request_id=claimed.request_id,
        )
        if result.accepted:
            if result.status is None:
                reject("DISPATCH_STATUS_INVALID", "accepted dispatch lacks HTTP status")
            return self.registry.mark_dispatch_posted(
                request_id=request_id,
                stage=stage,
                reason_code=result.reason_code,
                http_status=result.status,
                recorded_at=self._now(),
            )
        state = "Uncertain" if result.ambiguous else "Rejected"
        return self.registry.resolve_dispatch(
            request_id=request_id,
            stage=stage,
            state=state,
            reason_code=result.reason_code,
            http_status=result.status,
            resolved_at=self._now(),
        )

    @staticmethod
    def _matching_run(
        run: dict[str, Any],
        *,
        job: DispatchJob,
        record: Any,
        window_start: datetime,
        window_end: datetime,
        now: datetime,
        watermark: int,
    ) -> bool:
        repository = run.get("repository")
        head_repository = run.get("head_repository")
        actor = run.get("triggering_actor")
        run_id = run.get("id")
        run_attempt = run.get("run_attempt")
        if (
            not isinstance(repository, dict)
            or not isinstance(head_repository, dict)
            or not isinstance(actor, dict)
            or not isinstance(run_id, int)
            or isinstance(run_id, bool)
            or run_id < 1
            or run_id <= watermark
            or not isinstance(run_attempt, int)
            or isinstance(run_attempt, bool)
            or run_attempt < 1
            or run.get("event") != "workflow_dispatch"
            or run.get("head_branch") != record.intent_ref.removeprefix("refs/tags/")
            or run.get("head_sha") != record.head_sha
            or run.get("path") != job.workflow_path
            or actor.get("id") != job.expected_actor_id
            or repository.get("id") != record.repository_id
            or repository.get("full_name") != record.repository
            or head_repository.get("id") != record.repository_id
            or head_repository.get("full_name") != record.repository
        ):
            return False
        try:
            created_at = parse_utc(run.get("created_at"), "run.created_at")
        except PolicyError:
            return False
        return (
            window_start <= created_at <= window_end
            and created_at <= now + timedelta(seconds=60)
        )

    def reconcile_dispatch(self, *, request_id: str, stage: str) -> DispatchJob:
        current = self._now()
        job = self.registry.get_dispatch(request_id, stage)
        if job.state not in {"Sending", "Uncertain"} or job.claimed_at is None:
            reject("DISPATCH_STATE_INVALID", "dispatch is not eligible for reconciliation")
        if job.snapshot_at is None or job.pre_dispatch_run_id_watermark is None:
            reject(
                "DISPATCH_CORRELATION_INVALID",
                "dispatch has no durable pre-dispatch watermark",
            )
        record, _, _ = self._verified_record(request_id)
        window_start = parse_utc(job.claimed_at, "dispatch.claimedAt")
        window_end = min(
            window_start + MAX_DISPATCH_DELAY,
            parse_utc(record.expires_at, "intent.expiresAt"),
        )
        if window_end <= window_start:
            reject("DISPATCH_WINDOW_INVALID", "dispatch has no reconciliation window")
        runs = self.reader.workflow_runs_for_dispatch(
            job.installation_id,
            job.repository,
            job.workflow_path,
            record.intent_ref.removeprefix("refs/tags/"),
            utc_seconds(window_start),
            utc_seconds(window_end),
        )
        matches = [
            run
            for run in runs
            if self._matching_run(
                run,
                job=job,
                record=record,
                window_start=window_start,
                window_end=window_end,
                now=current,
                watermark=job.pre_dispatch_run_id_watermark,
            )
        ]
        if len(matches) > 1:
            if job.state == "Sending":
                self.registry.resolve_dispatch(
                    request_id=request_id,
                    stage=stage,
                    state="Uncertain",
                    reason_code="DISPATCH_RECONCILIATION_AMBIGUOUS",
                    http_status=job.http_status,
                    resolved_at=current,
                )
            reject(
                "DISPATCH_RECONCILIATION_AMBIGUOUS",
                "more than one live workflow run matches one dispatch",
            )
        if not matches:
            if job.state == "Sending" and current > window_end:
                return self.registry.resolve_dispatch(
                    request_id=request_id,
                    stage=stage,
                    state="Uncertain",
                    reason_code="DISPATCH_RECONCILIATION_EMPTY",
                    http_status=job.http_status,
                    resolved_at=current,
                )
            return job
        live_ref = self.reader.intent_ref(
            job.installation_id,
            job.repository,
            request_id,
        )
        if (
            live_ref.head_sha != record.head_sha
            or live_ref.ref_object_id != record.ref_object_id
        ):
            reject("INTENT_REF_MOVED", "live intent ref changed before reconciliation")
        return self.registry.reconcile_dispatch(
            request_id=request_id,
            stage=stage,
            run_id=matches[0]["id"],
            reconciled_at=current,
        )


__all__ = ["IntentDispatchOrchestrator", "MAX_DISPATCH_DELAY"]
