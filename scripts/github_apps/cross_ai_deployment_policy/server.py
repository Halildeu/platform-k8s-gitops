"""GitHub App webhook service with explicit observe and enforcement modes."""

from __future__ import annotations

import json
import logging
import queue
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Protocol

from .bootstrap import RunnerBootstrapAuthorizer, RunnerBootstrapRequest
from .binding import MAX_REQUEST_BYTES, ViewOnlyBindingAuthority
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
        bootstrap_authorizer: RunnerBootstrapAuthorizer | None = None,
        binding_authority: ViewOnlyBindingAuthority | None = None,
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
            or bootstrap_authorizer is None
        ):
            reject(
                "ENFORCEMENT_DEPENDENCY_MISSING",
                "enforcement requires evaluator, registry, decision client, "
                "outcome sweeper and runner bootstrap",
            )
        self.secrets = secrets
        self.ledger = ledger
        self.allowed_api_origins = allowed_api_origins
        self.evaluator = evaluator
        self._mode = mode
        self.registry = registry
        self.decision_client = decision_client
        self.outcome_sweeper = outcome_sweeper
        self.bootstrap_authorizer = bootstrap_authorizer
        self.binding_authority = binding_authority
        self._reconcilers: list[BackgroundReconciler] = []
        self.queue: queue.Queue[DeploymentProtectionRequest | None] = queue.Queue(
            maxsize=queue_capacity
        )
        self._accept_lock = threading.Lock()
        self._process_lock = threading.Lock()
        self._worker = threading.Thread(
            target=self._worker_loop,
            name="cross-ai-observe-worker",
            daemon=True,
        )
        if self.outcome_sweeper is not None:
            self.add_background_reconciler(self.outcome_sweeper)
        self._worker.start()

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def evaluation_enabled(self) -> bool:
        return self.evaluator is not None

    @property
    def reconciliation_ready(self) -> bool:
        return all(reconciler.ready() for reconciler in self._reconcilers)

    def add_background_reconciler(self, reconciler: BackgroundReconciler) -> None:
        with self._accept_lock:
            if reconciler in self._reconcilers:
                reject(
                    "RECONCILER_DUPLICATE", "background reconciler is already attached"
                )
            self._reconcilers.append(reconciler)
            reconciler.start()

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

    def process_polled(self, request: DeploymentProtectionRequest) -> bool:
        """Synchronously enforce one App-API-authenticated failed delivery.

        The return value is true only after GitHub accepted the decision callback.
        That lets the poller advance its durable high-water after, never before,
        callback success.
        """

        if self.mode != "enforce":
            reject("POLLER_MODE_INVALID", "delivery polling is enforce-mode only")
        if request.provenance != "github_app_delivery_api_v1":
            reject("POLLER_PROVENANCE_INVALID", "polled request provenance is invalid")
        with self._process_lock:
            self.ledger.record_delivery(request)
            if self.ledger.callback_succeeded(request):
                return True
            self._enforce(request)
            return self.ledger.callback_succeeded(request)

    def _worker_loop(self) -> None:
        while True:
            request = self.queue.get()
            try:
                if request is None:
                    return
                with self._process_lock:
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

    def _observe(self, request: DeploymentProtectionRequest) -> EvaluationResult | None:
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
        return (
            f"APPROVED evidence=sha256:{evidence} stage={result.stage} "
            f"policy_sha256={result.policy_digest}"
        )

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
                event_type="DECISION_APPROVED"
                if state == "approved"
                else "DECISION_REJECTED",
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
            event_type="CALLBACK_UNKNOWN"
            if callback.ambiguous
            else "CALLBACK_DEFINITIVE_FAILURE",
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
        for reconciler in reversed(self._reconcilers):
            reconciler.stop()


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
        encoded = json.dumps(
            body,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
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
        if (
            self.path
            == "/github-apps/cross-ai-deployment-protection/transaction-binding"
        ):
            self._transaction_binding()
            return
        if self.path == "/v1/runner-bootstrap":
            self._runner_bootstrap()
            return
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

    def _runner_bootstrap(self) -> None:
        if self.service.mode != "enforce" or self.service.bootstrap_authorizer is None:
            self._json(HTTPStatus.NOT_FOUND, {"accepted": False, "code": "NOT_FOUND"})
            return
        if self.headers.get("Transfer-Encoding"):
            self._json(
                HTTPStatus.BAD_REQUEST,
                {"accepted": False, "code": "CHUNKED_BODY_FORBIDDEN"},
            )
            return
        content_types = self.headers.get_all("Content-Type", [])
        if (
            len(content_types) != 1
            or self.headers.get_content_type() != "application/json"
        ):
            self._json(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                {"accepted": False, "code": "BOOTSTRAP_CONTENT_TYPE_INVALID"},
            )
            return
        authorization = self.headers.get_all("Authorization", [])
        bootstrap_credentials = self.headers.get_all(
            "X-Cross-AI-Bootstrap-Credential", []
        )
        if (
            len(authorization) != 1
            or not authorization[0].startswith("Bearer ")
            or len(bootstrap_credentials) != 1
        ):
            self._json(
                HTTPStatus.UNAUTHORIZED,
                {"accepted": False, "code": "BOOTSTRAP_CREDENTIAL_MISSING"},
            )
            return
        oidc_token = authorization[0][len("Bearer ") :]
        try:
            credential_bytes = bootstrap_credentials[0].encode("ascii")
        except UnicodeEncodeError:
            credential_bytes = b""
        content_length_value = self.headers.get("Content-Length")
        try:
            content_length = int(content_length_value or "")
        except ValueError:
            content_length = -1
        if not 1 <= content_length <= 16 * 1024:
            self._json(
                HTTPStatus.BAD_REQUEST,
                {"accepted": False, "code": "BOOTSTRAP_BODY_SIZE_INVALID"},
            )
            return
        raw_body = self.rfile.read(content_length)
        if len(raw_body) != content_length or b"\x00" in raw_body:
            self._json(
                HTTPStatus.BAD_REQUEST,
                {"accepted": False, "code": "BOOTSTRAP_BODY_INVALID"},
            )
            return

        def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in pairs:
                if key in result:
                    reject(
                        "BOOTSTRAP_REQUEST_INVALID",
                        "bootstrap request contains a duplicate key",
                    )
                result[key] = value
            return result

        try:
            value = json.loads(raw_body, object_pairs_hook=unique_object)
            request = RunnerBootstrapRequest.parse(value)
            response = self.service.bootstrap_authorizer.authorize(
                request=request,
                credential=credential_bytes,
                oidc_token=oidc_token,
            )
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._json(
                HTTPStatus.BAD_REQUEST,
                {"accepted": False, "code": "BOOTSTRAP_REQUEST_INVALID"},
            )
            return
        except PolicyError as exc:
            status = (
                HTTPStatus.CONFLICT
                if exc.code == "BOOTSTRAP_ALREADY_CONSUMED"
                else HTTPStatus.FORBIDDEN
            )
            self._json(status, {"accepted": False, "code": exc.code})
            return
        self._json(HTTPStatus.OK, response)

    def _transaction_binding(self) -> None:
        authority = self.service.binding_authority
        if self.service.mode != "enforce" or authority is None:
            self._json(HTTPStatus.NOT_FOUND, {"accepted": False, "code": "NOT_FOUND"})
            return
        if self.headers.get("Transfer-Encoding"):
            self._json(
                HTTPStatus.BAD_REQUEST,
                {"accepted": False, "code": "CHUNKED_BODY_FORBIDDEN"},
            )
            return
        content_types = self.headers.get_all("Content-Type", [])
        if (
            len(content_types) != 1
            or self.headers.get_content_type() != "application/json"
        ):
            self._json(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                {"accepted": False, "code": "BINDING_CONTENT_TYPE_INVALID"},
            )
            return
        authorization = self.headers.get_all("Authorization", [])
        if len(authorization) != 1 or not authorization[0].startswith("Bearer "):
            self._json(
                HTTPStatus.UNAUTHORIZED,
                {"accepted": False, "code": "BINDING_OIDC_MISSING"},
            )
            return
        oidc_token = authorization[0][len("Bearer ") :]
        content_length_value = self.headers.get("Content-Length")
        try:
            content_length = int(content_length_value or "")
        except ValueError:
            content_length = -1
        if not 1 <= content_length <= MAX_REQUEST_BYTES:
            self._json(
                HTTPStatus.BAD_REQUEST,
                {"accepted": False, "code": "BINDING_BODY_SIZE_INVALID"},
            )
            return
        raw_body = self.rfile.read(content_length)
        if len(raw_body) != content_length or b"\x00" in raw_body:
            self._json(
                HTTPStatus.BAD_REQUEST,
                {"accepted": False, "code": "BINDING_BODY_INVALID"},
            )
            return
        try:
            request = authority.parse_request(raw_body)
            response = authority.issue(request=request, oidc_token=oidc_token)
        except PolicyError as exc:
            if exc.code == "IDEMPOTENCY_CONFLICT":
                status = HTTPStatus.CONFLICT
            elif exc.code.startswith("BOOTSTRAP_OIDC_"):
                status = (
                    HTTPStatus.SERVICE_UNAVAILABLE
                    if exc.code.endswith("UNAVAILABLE")
                    else HTTPStatus.UNAUTHORIZED
                )
            elif exc.code in {
                "BINDING_AUTHORITY_INACTIVE",
                "BINDING_RUNTIME_TRUST_ROOT_INACTIVE",
                "BINDING_RUNTIME_TRUST_ROOT_INVALID",
                "BINDING_SCHEMA_UNAVAILABLE",
                "VAULT_SIGN_FAILED",
                "VAULT_SIGN_RESPONSE_INVALID",
            }:
                status = HTTPStatus.SERVICE_UNAVAILABLE
            elif exc.code in {
                "BINDING_IDEMPOTENCY_MISMATCH",
                "BINDING_REQUEST_INVALID",
                "JSON_DUPLICATE_KEY",
                "JSON_FLOAT_FORBIDDEN",
                "JSON_FILE_INVALID",
                "JSON_FILE_SIZE_INVALID",
            }:
                status = HTTPStatus.BAD_REQUEST
            else:
                status = HTTPStatus.FORBIDDEN
            self._json(status, {"accepted": False, "code": exc.code})
            return
        self._json(HTTPStatus.OK, response.envelope)


def make_server(
    listen: str,
    port: int,
    service: ObserveService,
) -> PolicyHTTPServer:
    return PolicyHTTPServer((listen, port), PolicyHandler, service)


__all__ = ["ObserveService", "PolicyHTTPServer", "PolicyHandler", "make_server"]
