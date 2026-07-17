from __future__ import annotations

import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.github_apps.cross_ai_deployment_policy.delivery_poller import DeliveryPoller
from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError
from scripts.github_apps.cross_ai_deployment_policy.github import HookDeliveryPage
from scripts.github_apps.cross_ai_deployment_policy.ledger import ObserveLedger
from tests.github_apps.test_cross_ai_deployment_webhook import payload


NOW = datetime(2026, 7, 17, 17, 30, tzinfo=timezone.utc)
GUID = "11111111-2222-4333-8444-555555555555"
WEBHOOK_URL = "https://testai.acik.com/github-apps/cross-ai-deployment-protection"


def item(*, status_code: int = 0) -> dict[str, object]:
    return {
        "id": 77,
        "guid": GUID,
        "delivered_at": "2026-07-17T17:29:00Z",
        "redelivery": False,
        "duration": 0.03,
        "status": "failed to connect" if status_code == 0 else "OK",
        "status_code": status_code,
        "event": "deployment_protection_rule",
        "action": "requested",
        "installation_id": 2222,
        "repository_id": 123456789,
    }


def detail(*, status_code: int = 0) -> dict[str, object]:
    value = item(status_code=status_code)
    value.update(
        {
            "url": WEBHOOK_URL,
            "request": {"headers": {"X-GitHub-Event": "redacted"}, "payload": payload()},
            "response": {"headers": None, "payload": None},
        }
    )
    return value


class FakeCycle:
    def __init__(self, items, details) -> None:
        self.items = tuple(items)
        self.details = details
        self.detail_calls: list[int] = []

    def list_deliveries(self, *, cursor=None):
        self.assert_cursor(cursor)
        return HookDeliveryPage(self.items, None)

    @staticmethod
    def assert_cursor(cursor):
        if cursor is not None:
            raise AssertionError("unexpected cursor")

    def delivery(self, delivery_id: int):
        self.detail_calls.append(delivery_id)
        return self.details[delivery_id]


class FakeReader:
    def __init__(self, cycle: FakeCycle) -> None:
        self.value = cycle
        self.cycles = 0
        self.polled = threading.Event()

    def cycle(self):
        self.cycles += 1
        self.polled.set()
        return self.value


class SuccessfulProcessor:
    def __init__(self, ledger: ObserveLedger) -> None:
        self.ledger = ledger
        self.requests = []

    def process_polled(self, request) -> bool:
        self.requests.append(request)
        self.ledger.record_delivery(request)
        if self.ledger.callback_succeeded(request):
            return True
        self.ledger.claim_decision(
            request=request,
            state="approved",
            reason_code="SIGNED_EVIDENCE_VALID",
            evidence_digest="sha256:" + ("a" * 64),
            comment="APPROVED evidence=sha256:abc stage=apply",
        )
        self.ledger.complete_decision(
            request=request,
            callback_status="Succeeded",
            callback_http_status=204,
        )
        return True


class RejectingProcessor:
    def process_polled(self, request) -> bool:
        return False


class DeliveryPollerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.ledger = ObserveLedger(Path(self.directory.name) / "ledger.sqlite3")

    def tearDown(self) -> None:
        self.ledger.close()
        self.directory.cleanup()

    def poller(self, cycle: FakeCycle, processor) -> DeliveryPoller:
        return DeliveryPoller(
            reader=FakeReader(cycle),  # type: ignore[arg-type]
            processor=processor,
            ledger=self.ledger,
            expected_webhook_url=WEBHOOK_URL,
            expected_installation_id=2222,
            expected_repository_id=123456789,
            now=lambda: NOW,
            jitter=lambda low, high: 0,
        )

    def test_failed_delivery_is_cross_checked_processed_and_advanced(self) -> None:
        processor = SuccessfulProcessor(self.ledger)
        poller = self.poller(FakeCycle([item()], {77: detail()}), processor)
        self.assertEqual(poller.poll_once(), 1)
        self.assertEqual(len(processor.requests), 1)
        self.assertEqual(
            processor.requests[0].provenance,
            "github_app_delivery_api_v1",
        )
        state = self.ledger.poller_state()
        self.assertEqual(state.high_water_delivery_id, 77)
        self.assertEqual(state.high_water_guid, GUID)

    def test_successful_webhook_delivery_is_not_reprocessed(self) -> None:
        processor = SuccessfulProcessor(self.ledger)
        cycle = FakeCycle([item(status_code=204)], {77: detail(status_code=204)})
        self.assertEqual(self.poller(cycle, processor).poll_once(), 0)
        self.assertEqual(cycle.detail_calls, [])
        self.assertEqual(processor.requests, [])

    def test_list_detail_mismatch_fails_closed(self) -> None:
        processor = SuccessfulProcessor(self.ledger)
        mismatched = detail()
        mismatched["repository_id"] = 999
        with self.assertRaisesRegex(
            PolicyError, "GITHUB_DELIVERY_LIST_DETAIL_MISMATCH"
        ):
            self.poller(FakeCycle([item()], {77: mismatched}), processor).poll_once()
        self.assertEqual(processor.requests, [])

    def test_high_water_does_not_advance_when_callback_is_not_accepted(self) -> None:
        with self.assertRaisesRegex(PolicyError, "POLLER_CALLBACK_NOT_SUCCEEDED"):
            self.poller(
                FakeCycle([item()], {77: detail()}),
                RejectingProcessor(),
            ).poll_once()
        self.assertIsNone(self.ledger.poller_state().high_water_delivery_id)

    def test_background_readiness_opens_only_after_successful_poll(self) -> None:
        reader = FakeReader(FakeCycle([], {}))
        poller = DeliveryPoller(
            reader=reader,  # type: ignore[arg-type]
            processor=SuccessfulProcessor(self.ledger),
            ledger=self.ledger,
            expected_webhook_url=WEBHOOK_URL,
            expected_installation_id=2222,
            expected_repository_id=123456789,
            now=lambda: NOW,
            jitter=lambda low, high: 0,
        )
        self.assertFalse(poller.ready())
        poller.start()
        try:
            self.assertTrue(reader.polled.wait(timeout=2))
            for _ in range(100):
                if poller.ready():
                    break
                threading.Event().wait(0.01)
            self.assertTrue(poller.ready())
        finally:
            poller.stop()
        self.assertFalse(poller.ready())

    def test_jitter_never_breaches_floor_and_backoff_is_capped(self) -> None:
        poller = DeliveryPoller(
            reader=FakeReader(FakeCycle([], {})),  # type: ignore[arg-type]
            processor=SuccessfulProcessor(self.ledger),
            ledger=self.ledger,
            expected_webhook_url=WEBHOOK_URL,
            expected_installation_id=2222,
            expected_repository_id=123456789,
            now=lambda: NOW,
            jitter=lambda low, high: low,
        )
        self.assertEqual(poller._success_delay(), 30.0)
        poller._jitter = lambda low, high: high
        self.assertEqual(poller._failure_delay(10), 300.0)


if __name__ == "__main__":
    unittest.main()
