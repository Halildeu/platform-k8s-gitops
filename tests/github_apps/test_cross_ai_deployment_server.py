from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from scripts.github_apps.cross_ai_deployment_policy.ledger import ObserveLedger
from scripts.github_apps.cross_ai_deployment_policy.evaluator import EvaluationResult
from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError
from scripts.github_apps.cross_ai_deployment_policy.github import CallbackResult
from scripts.github_apps.cross_ai_deployment_policy.intent_store import StageReservation
from scripts.github_apps.cross_ai_deployment_policy.server import (
    ObserveService,
    make_server,
)
from scripts.github_apps.cross_ai_deployment_policy.webhook import (
    parse_deployment_protection_delivery,
)
from tests.github_apps.test_cross_ai_deployment_webhook import (
    TEST_HMAC_KEY,
    payload,
    signed_request,
)


class ObserveServerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.ledger = ObserveLedger(Path(self.directory.name) / "ledger.sqlite3")
        self.service = ObserveService(secrets=(TEST_HMAC_KEY,), ledger=self.ledger)
        self.server = make_server("127.0.0.1", 0, self.service)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host, self.port = self.server.server_address

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.service.stop()
        self.ledger.close()
        self.directory.cleanup()

    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, object]]:
        connection = http.client.HTTPConnection(self.host, self.port, timeout=5)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            parsed = json.loads(response.read())
            return response.status, parsed
        finally:
            connection.close()

    def test_health_and_readiness_are_observe_only(self) -> None:
        status, health = self.request("GET", "/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(health, {"mode": "observe", "status": "up"})
        status, ready = self.request("GET", "/readyz")
        self.assertEqual(status, 200)
        self.assertEqual(ready["mode"], "observe")

    def test_accepts_and_deduplicates_authenticated_delivery(self) -> None:
        raw = json.dumps(payload(), separators=(",", ":")).encode()
        headers, body = signed_request(raw)
        status, first = self.request(
            "POST",
            "/webhooks/github",
            body=body,
            headers=headers,
        )
        self.assertEqual(status, 202)
        self.assertFalse(first["duplicate"])
        status, second = self.request(
            "POST",
            "/webhooks/github",
            body=body,
            headers=headers,
        )
        self.assertEqual(status, 202)
        self.assertTrue(second["duplicate"])
        self.service.queue.join()
        self.assertEqual(self.ledger.counts(), (1, 1))

    def test_accepts_lowercase_upstream_header_names(self) -> None:
        raw = json.dumps(payload(), separators=(",", ":")).encode()
        headers, body = signed_request(raw)
        status, response = self.request(
            "POST",
            "/webhooks/github",
            body=body,
            headers={name.lower(): value for name, value in headers.items()},
        )
        self.assertEqual(status, 202)
        self.assertTrue(response["accepted"])

    def test_rejects_bad_signature_without_recording(self) -> None:
        raw = json.dumps(payload(), separators=(",", ":")).encode()
        headers, body = signed_request(raw)
        headers["X-Hub-Signature-256"] = "sha256=" + ("0" * 64)
        status, response = self.request(
            "POST",
            "/webhooks/github",
            body=body,
            headers=headers,
        )
        self.assertEqual(status, 401)
        self.assertEqual(response["code"], "WEBHOOK_SIGNATURE_INVALID")
        self.assertEqual(self.ledger.counts(), (0, 0))

    def test_rejects_unknown_route_and_chunked_shape(self) -> None:
        status, _ = self.request("POST", "/other", body=b"{}", headers={})
        self.assertEqual(status, 404)


class FakeEvaluator:
    def __init__(self, reject_code: str | None = None) -> None:
        self.reject_code = reject_code

    def evaluate(self, request):
        if self.reject_code:
            raise PolicyError(self.reject_code, "bounded rejection")
        return EvaluationResult(
            approval_candidate=True,
            reason_code="SIGNED_EVIDENCE_AND_GITHUB_TRUTH_VALID",
            request_id=request.request_id,
            stage="apply",
            run_id=request.run_id,
            run_attempt=1,
            app_rule_id=555,
            evidence_digest="sha256:" + ("a" * 64),
            policy_digest="sha256:" + ("b" * 64),
            provider_families=("anthropic", "xai"),
        )


class FakeRegistry:
    def __init__(self) -> None:
        self.transitions: list[str] = []

    def reserve_stage(self, **kwargs):
        return StageReservation(
            request_id=kwargs["request_id"],
            stage=kwargs["stage"],
            run_id=kwargs["run_id"],
            run_attempt=kwargs["run_attempt"],
            app_rule_id=kwargs["app_rule_id"],
            reservation_id="99999999-0000-4000-8000-000000000001",
            reservation_expires_at="2026-07-16T21:00:00Z",
            state="Reserved",
            idempotent=False,
        )

    def transition_stage(self, **kwargs):
        self.transitions.append(kwargs["to_state"])


class FakeDecisionClient:
    def __init__(self, result: CallbackResult) -> None:
        self.result = result
        self.states: list[str] = []

    def post_decision(self, **kwargs):
        self.states.append(kwargs["state"])
        return self.result


class FakeSweeper:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def ready(self) -> bool:
        return self.started and not self.stopped


class NotReadySweeper(FakeSweeper):
    def ready(self) -> bool:
        return False


class EvaluatingObserveServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.ledger = ObserveLedger(Path(self.directory.name) / "ledger.sqlite3")

    def tearDown(self) -> None:
        self.ledger.close()
        self.directory.cleanup()

    def accept(self, evaluator: FakeEvaluator) -> tuple[str, ...]:
        service = ObserveService(
            secrets=(TEST_HMAC_KEY,), ledger=self.ledger, evaluator=evaluator
        )
        try:
            raw = json.dumps(payload(), separators=(",", ":")).encode()
            headers, body = signed_request(raw)
            request, duplicate = service.accept(raw_body=body, headers=headers)
            self.assertFalse(duplicate)
            service.queue.join()
            return tuple(
                event.event_type + ":" + event.reason_code
                for event in self.ledger.events_for_delivery(request.delivery_id)
            )
        finally:
            service.stop()

    def test_observe_records_candidate_without_callback(self) -> None:
        self.assertEqual(
            self.accept(FakeEvaluator()),
            (
                "OBSERVED:OBSERVE_MODE_NO_CALLBACK",
                "EVALUATION_APPROVAL_CANDIDATE:SIGNED_EVIDENCE_AND_GITHUB_TRUTH_VALID",
            ),
        )

    def test_observe_records_fail_closed_reason(self) -> None:
        self.assertEqual(
            self.accept(FakeEvaluator("HEAD_OR_WORKFLOW_MISMATCH")),
            (
                "OBSERVED:OBSERVE_MODE_NO_CALLBACK",
                "EVALUATION_REJECTED:HEAD_OR_WORKFLOW_MISMATCH",
            ),
        )


class EnforcementServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.directory.cleanup()

    def run_service(
        self,
        *,
        evaluator: FakeEvaluator,
        callback: CallbackResult,
    ) -> tuple[tuple[str, ...], FakeRegistry, FakeDecisionClient]:
        ledger = ObserveLedger(Path(self.directory.name) / "enforce.sqlite3")
        registry = FakeRegistry()
        client = FakeDecisionClient(callback)
        sweeper = FakeSweeper()
        service = ObserveService(
            secrets=(TEST_HMAC_KEY,),
            ledger=ledger,
            evaluator=evaluator,
            mode="enforce",
            registry=registry,  # type: ignore[arg-type]
            decision_client=client,
            outcome_sweeper=sweeper,
        )
        try:
            raw = json.dumps(payload(), separators=(",", ":")).encode()
            headers, body = signed_request(raw)
            request, _ = service.accept(raw_body=body, headers=headers)
            service.queue.join()
            events = tuple(
                event.event_type
                for event in ledger.events_for_delivery(request.delivery_id)
            )
            return events, registry, client
        finally:
            service.stop()
            self.assertTrue(sweeper.started)
            self.assertTrue(sweeper.stopped)
            ledger.close()

    def test_enforcement_reserves_rechecks_and_approves_only_after_204(self) -> None:
        events, registry, client = self.run_service(
            evaluator=FakeEvaluator(),
            callback=CallbackResult(True, False, 204, "CALLBACK_ACCEPTED_204"),
        )
        self.assertEqual(client.states, ["approved"])
        self.assertEqual(registry.transitions, ["ApprovedPendingOutcome"])
        self.assertEqual(events, ("ENFORCEMENT_REQUESTED", "DECISION_APPROVED"))

    def test_enforcement_posts_fail_closed_rejection(self) -> None:
        events, registry, client = self.run_service(
            evaluator=FakeEvaluator("HEAD_OR_WORKFLOW_MISMATCH"),
            callback=CallbackResult(True, False, 204, "CALLBACK_ACCEPTED_204"),
        )
        self.assertEqual(client.states, ["rejected"])
        self.assertEqual(registry.transitions, [])
        self.assertEqual(events, ("ENFORCEMENT_REQUESTED", "DECISION_REJECTED"))

    def test_ambiguous_approval_quarantines_stage(self) -> None:
        events, registry, client = self.run_service(
            evaluator=FakeEvaluator(),
            callback=CallbackResult(False, True, 503, "CALLBACK_HTTP_AMBIGUOUS"),
        )
        self.assertEqual(client.states, ["approved"])
        self.assertEqual(registry.transitions, ["OutcomeOverdue"])
        self.assertEqual(events, ("ENFORCEMENT_REQUESTED", "CALLBACK_UNKNOWN"))

    def test_enforcement_readiness_requires_live_reconciler(self) -> None:
        ledger = ObserveLedger(Path(self.directory.name) / "not-ready.sqlite3")
        sweeper = NotReadySweeper()
        service = ObserveService(
            secrets=(TEST_HMAC_KEY,),
            ledger=ledger,
            evaluator=FakeEvaluator(),
            mode="enforce",
            registry=FakeRegistry(),  # type: ignore[arg-type]
            decision_client=FakeDecisionClient(
                CallbackResult(True, False, 204, "CALLBACK_ACCEPTED_204")
            ),
            outcome_sweeper=sweeper,
        )
        try:
            self.assertFalse(service.reconciliation_ready)
        finally:
            service.stop()
            ledger.close()

    def test_polled_delivery_processes_synchronously_and_replays_idempotently(self) -> None:
        ledger = ObserveLedger(Path(self.directory.name) / "polled.sqlite3")
        registry = FakeRegistry()
        client = FakeDecisionClient(
            CallbackResult(True, False, 204, "CALLBACK_ACCEPTED_204")
        )
        service = ObserveService(
            secrets=(TEST_HMAC_KEY,),
            ledger=ledger,
            evaluator=FakeEvaluator(),
            mode="enforce",
            registry=registry,  # type: ignore[arg-type]
            decision_client=client,
            outcome_sweeper=FakeSweeper(),
        )
        try:
            request = parse_deployment_protection_delivery(
                payload=payload(),
                delivery_id="11111111-2222-4333-8444-555555555555",
            )
            self.assertTrue(service.process_polled(request))
            self.assertTrue(service.process_polled(request))
            self.assertEqual(client.states, ["approved"])
        finally:
            service.stop()
            ledger.close()

if __name__ == "__main__":
    unittest.main()
