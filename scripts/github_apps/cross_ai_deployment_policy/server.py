"""GitHub App webhook service with explicit observe and enforcement modes."""

from __future__ import annotations

import json
import logging
import queue
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Protocol

from .errors import PolicyError, reject
from .evaluator import EvaluationResult
from .github import CallbackResult
from .intent_store import IntentRegistry, StageReservation
from .ledger import ObserveLedger
from .webhook import (
    MAX_WEBHOOK_BYTES,
    WEBHOOK_HEADER_NAMES,
    DeploymentProtectionRequest,
    parse_deployment_protection_webhook,
)


LOGGER = logging.getLogger("cross_ai_deployment_policy")


class RequestEvaluator(Protocol):
    def evaluate(self, request: DeploymentProtectionRequest) -> EvaluationResult: ...


class DecisionClient(Protocol):
    def post_decision(
        self,
        *,
        installation_id: int,
        repository: str,
        run_id: int,
        environment: str,
        state: str,
        comment: str,
    ) -> CallbackResult: ...


class BackgroundReconciler(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...

    def ready(self) -> bool: ...


class ObserveService:
    def __init__(
        self,
        *,
        secrets: tuple[bytes, ...],
        ledger: ObserveLedger,
        allowed_api_origins: tuple[str, ...] = ("https://api.github.com",),
        queue_capacity: int = 1000,
        evaluator: RequestEvaluator | None = None,
        mode: str = "observe",
        registry: IntentRegistry | None = None,
        decision_client: DecisionClient | None = None,
        outcome_sweeper: BackgroundReconciler | None = None,
    ) -> None:
        if not secrets:
            reject("WEBHOOK_SECRET_MISSING", "observe service requires webhook secrets")
        if mode not in {"observe", "enforce"}:
            reject("SERVICE_MODE_INVALID", "service mode must be observe or enforce")
        if mode == "enforce" and (
            evaluator is None
            or registry is None
            or decision_client is None
            or outcome_sweeper is None
        ):
            reject(
                "ENFORCEMENT_DEPENDENCY_MISSING",
                "enforcement requires evaluator, registry, decision client and outcome sweeper",
            )
        self.secrets = secrets
        self.ledger = ledger
        self.allowed_api_origins = allowed_api_origins
        self.evaluator = evaluator
        self._mode = mode
        self.registry = registry
        self.decision_client = decision_client
        self.outcome_sweeper = outcome_sweeper
        self.queue: queue.Queue[DeploymentProtectionRequest | None] = queue.Queue(
            maxsize=queue_capacity
        )
        self._accept_lock = threading.Lock()
        self._worker = threading.Thread(
            target=self._worker_loop,
            name="cross-ai-observe-worker",
            daemon=True,
        )
        if self.outcome_sweeper is not None:
            self.outcome_sweeper.start()
        self._worker.start()

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def evaluation_enabled(self) -> bool:
        return self.evaluator is not None

    @property
    def reconciliation_ready(self) -> bool:
        return self.outcome_sweeper is None or self.outcome_sweeper.ready()

    def accept(
        self,
        *,
        raw_body: bytes,
        headers: dict[str, str],
    ) -> tuple[DeploymentProtectionRequest, bool]:
        request = parse_deployment_protection_webhook(
            raw_body=raw_body,
            headers=headers,
            secrets=self.secrets,
            allowed_api_origins=self.allowed_api_origins,
        )
        with self._accept_lock:
            if self.queue.full():
                reject("OBSERVE_QUEUE_FULL", "observe queue has no capacity")
            inserted = self.ledger.record_delivery(request)
            if inserted:
                self.queue.put_nowait(request)
        return request, not inserted

    def _worker_loop(self) -> None:
        while True:
            request = self.queue.get()
            try:
                if request is None:
                    return
                result: EvaluationResult | None
                if self.mode == "observe":
                    result = self._observe(request)
                else:
                    result = self._enforce(request)
                LOGGER.info(
                    json.dumps(
                        {
                            "event": "deployment_protection_observed",
                            "deliveryId": request.delivery_id,
                            "repositoryId": request.repository_id,
                            "environment": request.environment,
                            "runId": request.run_id,
                            "payloadSha256": request.payload_sha256,
                            "mode": self.mode,
                            "evaluationEnabled": self.evaluation_enabled,
                            "evaluationResult": (
                                result.reason_code if result is not None else None
                            ),
                        },
                        separators=(",", ":"),
                        sort_keys=True,
                    )
                )
            except Exception:
                LOGGER.exception(
                    "observe processing failed delivery_id=%s",
                    request.delivery_id if request else "shutdown",
                )
                if request is not None:
                    try:
                        self.ledger.append_event(
                            delivery_id=request.delivery_id,
                            event_type="PROCESSING_FAILED",
                            reason_code="OBSERVE_PROCESSING_ERROR",
                        )
                    except Exception:
                        LOGGER.exception("failed to append bounded processing error")
            finally:
                self.queue.task_done()

    def _observe(
        self, request: DeploymentProtectionRequest
    ) -> EvaluationResult | None:
        self.ledger.append_event(
            delivery_id=request.delivery_id,
            event_type="OBSERVED",
            reason_code="OBSERVE_MODE_NO_CALLBACK",
        )
        if self.evaluator is None:
            return None
        try:
            result = self.evaluator.evaluate(request)
            self.ledger.append_event(
                delivery_id=request.delivery_id,
                event_type="EVALUATION_APPROVAL_CANDIDATE",
                reason_code=result.reason_code,
                evidence_digest=result.evidence_digest,
            )
            return result
        except PolicyError as exc:
            self.ledger.append_event(
                delivery_id=request.delivery_id,
                event_type="EVALUATION_REJECTED",
                reason_code=exc.code,
            )
            LOGGER.warning(
                "deployment evaluation rejected delivery_id=%s code=%s",
                request.delivery_id,
                exc.code,
            )
            return None

    @staticmethod
    def _approval_comment(result: EvaluationResult) -> str:
        evidence = result.evidence_digest.removeprefix("sha256:")[:16]
        return f"APPROVED evidence=sha256:{evidence} stage={result.stage} policy=v1"

    @staticmethod
    def _rejection_comment(code: str) -> str:
        bounded = code if len(code) <= 80 else "POLICY_REJECTED"
        return f"REJECTED code={bounded}"

    def _post_claimed_decision(
        self,
        *,
        request: DeploymentProtectionRequest,
        state: str,
        reason_code: str,
        evidence_digest: str | None,
        comment: str,
        reservation: StageReservation | None = None,
    ) -> None:
        if self.decision_client is None:
            reject("ENFORCEMENT_DEPENDENCY_MISSING", "decision client is missing")
        record, _inserted = self.ledger.claim_decision(
            request=request,
            state=state,
            reason_code=reason_code,
            evidence_digest=evidence_digest,
            comment=comment,
        )
        if record.callback_status in {"Succeeded", "DefinitiveFailure"}:
            self.ledger.append_event(
                delivery_id=request.delivery_id,
                event_type="DECISION_REPLAYED",
                reason_code=f"CALLBACK_{record.callback_status.upper()}",
                evidence_digest=evidence_digest,
            )
            return
        callback = self.decision_client.post_decision(
            installation_id=request.installation_id,
            repository=request.repository,
            run_id=request.run_id,
            environment=request.environment,
            state=state,
            comment=comment,
        )
        if callback.accepted:
            self.ledger.complete_decision(
                request=request,
                callback_status="Succeeded",
                callback_http_status=callback.status,
            )
            if reservation is not None:
                assert self.registry is not None
                self.registry.transition_stage(
                    request_id=reservation.request_id,
                    stage=reservation.stage,
                    to_state="ApprovedPendingOutcome",
                    reason_code="CALLBACK_ACCEPTED_204",
                )
            self.ledger.append_event(
                delivery_id=request.delivery_id,
                event_type="DECISION_APPROVED" if state == "approved" else "DECISION_REJECTED",
                reason_code=reason_code,
                evidence_digest=evidence_digest,
            )
            return
        callback_status = "Unknown" if callback.ambiguous else "DefinitiveFailure"
        self.ledger.complete_decision(
            request=request,
            callback_status=callback_status,
            callback_http_status=callback.status,
        )
        if reservation is not None:
            assert self.registry is not None
            if callback.ambiguous or reservation.state == "Reserved":
                self.registry.transition_stage(
                    request_id=reservation.request_id,
                    stage=reservation.stage,
                    to_state="OutcomeOverdue" if callback.ambiguous else "Rejected",
                    reason_code=callback.reason_code,
                )
        self.ledger.append_event(
            delivery_id=request.delivery_id,
            event_type="CALLBACK_UNKNOWN" if callback.ambiguous else "CALLBACK_DEFINITIVE_FAILURE",
            reason_code=callback.reason_code,
            evidence_digest=evidence_digest,
        )

    def _enforce(self, request: DeploymentProtectionRequest) -> EvaluationResult | None:
        assert self.evaluator is not None
        assert self.registry is not None
        self.ledger.append_event(
            delivery_id=request.delivery_id,
            event_type="ENFORCEMENT_REQUESTED",
            reason_code="AUTHENTICATED_WEBHOOK_ENQUEUED",
        )
        reservation: StageReservation | None = None
        try:
            result = self.evaluator.evaluate(request)
            reservation = self.registry.reserve_stage(
                request_id=result.request_id,
                stage=result.stage,
                run_id=result.run_id,
                run_attempt=result.run_attempt,
                app_rule_id=result.app_rule_id,
            )
            # Close the evaluation-to-callback window with a full second read.
            rechecked = self.evaluator.evaluate(request)
            if rechecked != result:
                reject("GITHUB_TRUTH_CHANGED", "evaluation changed before callback")
        except PolicyError as exc:
            if reservation is not None and reservation.state == "Reserved":
                self.registry.transition_stage(
                    request_id=reservation.request_id,
                    stage=reservation.stage,
                    to_state="Rejected",
                    reason_code=exc.code,
                )
            try:
                self._post_claimed_decision(
                    request=request,
                    state="rejected",
                    reason_code=exc.code,
                    evidence_digest=None,
                    comment=self._rejection_comment(exc.code),
                )
            except PolicyError as decision_exc:
                if decision_exc.code != "DECISION_CONFLICT":
                    raise
                self.ledger.append_event(
                    delivery_id=request.delivery_id,
                    event_type="DECISION_CONFLICT_BLOCKED",
                    reason_code=decision_exc.code,
                )
            return None
        self._post_claimed_decision(
            request=request,
            state="approved",
            reason_code=result.reason_code,
            evidence_digest=result.evidence_digest,
            comment=self._approval_comment(result),
            reservation=reservation,
        )
        return result

    def stop(self) -> None:
        self.queue.join()
        self.queue.put(None)
        self._worker.join(timeout=5)
        if self.outcome_sweeper is not None:
            self.outcome_sweeper.stop()


class PolicyHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[BaseHTTPRequestHandler],
        service: ObserveService,
    ) -> None:
        super().__init__(server_address, handler_class)
        self.service = service


class PolicyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "cross-ai-deployment-policy"
    sys_version = ""

    @property
    def service(self) -> ObserveService:
        return self.server.service  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: Any) -> None:
        LOGGER.info(
            "http client=%s method=%s path=%s status=%s",
            self.client_address[0],
            self.command,
            self.path.split("?", 1)[0],
            args[1] if len(args) > 1 else "unknown",
        )

    def _json(self, status: HTTPStatus, body: dict[str, Any]) -> None:
        encoded = json.dumps(body, separators=(",", ":"), sort_keys=True).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'none'")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:  # noqa: N802 (stdlib handler API)
        if self.path == "/healthz":
            self._json(HTTPStatus.OK, {"status": "up", "mode": self.service.mode})
            return
        if self.path == "/readyz":
            deliveries, events = self.service.ledger.counts()
            ready = self.service.reconciliation_ready
            self._json(
                HTTPStatus.OK if ready else HTTPStatus.SERVICE_UNAVAILABLE,
                {
                    "status": "ready" if ready else "not_ready",
                    "mode": self.service.mode,
                    "evaluationEnabled": self.service.evaluation_enabled,
                    "reconciliationReady": ready,
                    "deliveries": deliveries,
                    "events": events,
                },
            )
            return
        self._json(HTTPStatus.NOT_FOUND, {"status": "not_found"})

    def do_POST(self) -> None:  # noqa: N802 (stdlib handler API)
        if self.path != "/webhooks/github":
            self._json(HTTPStatus.NOT_FOUND, {"accepted": False, "code": "NOT_FOUND"})
            return
        if self.headers.get("Transfer-Encoding"):
            self._json(
                HTTPStatus.BAD_REQUEST,
                {"accepted": False, "code": "CHUNKED_BODY_FORBIDDEN"},
            )
            return
        content_length_value = self.headers.get("Content-Length")
        try:
            content_length = int(content_length_value or "")
        except ValueError:
            content_length = -1
        if content_length < 0:
            self._json(
                HTTPStatus.LENGTH_REQUIRED,
                {"accepted": False, "code": "CONTENT_LENGTH_REQUIRED"},
            )
            return
        if content_length > MAX_WEBHOOK_BYTES:
            self._json(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                {"accepted": False, "code": "WEBHOOK_BODY_TOO_LARGE"},
            )
            return
        raw_body = self.rfile.read(content_length)
        if len(raw_body) != content_length:
            self._json(
                HTTPStatus.BAD_REQUEST,
                {"accepted": False, "code": "WEBHOOK_BODY_TRUNCATED"},
            )
            return
        headers: dict[str, str] = {}
        for name in WEBHOOK_HEADER_NAMES:
            values = self.headers.get_all(name, [])
            if len(values) > 1:
                self._json(
                    HTTPStatus.BAD_REQUEST,
                    {"accepted": False, "code": "WEBHOOK_HEADER_DUPLICATE"},
                )
                return
            if values:
                headers[name] = values[0]
        try:
            request, duplicate = self.service.accept(
                raw_body=raw_body,
                headers=headers,
            )
        except PolicyError as exc:
            if exc.code in {
                "WEBHOOK_SIGNATURE_MISSING",
                "WEBHOOK_SIGNATURE_INVALID",
            }:
                status = HTTPStatus.UNAUTHORIZED
            elif exc.code == "OBSERVE_QUEUE_FULL":
                status = HTTPStatus.SERVICE_UNAVAILABLE
            else:
                status = HTTPStatus.BAD_REQUEST
            self._json(status, {"accepted": False, "code": exc.code})
            return
        self._json(
            HTTPStatus.ACCEPTED,
            {
                "accepted": True,
                "duplicate": duplicate,
                "deliveryId": request.delivery_id,
                "mode": self.service.mode,
            },
        )


def make_server(
    listen: str,
    port: int,
    service: ObserveService,
) -> PolicyHTTPServer:
    return PolicyHTTPServer((listen, port), PolicyHandler, service)


__all__ = ["ObserveService", "PolicyHTTPServer", "PolicyHandler", "make_server"]
