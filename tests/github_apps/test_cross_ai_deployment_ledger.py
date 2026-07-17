from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError
from scripts.github_apps.cross_ai_deployment_policy.ledger import ObserveLedger
from scripts.github_apps.cross_ai_deployment_policy.webhook import (
    DeploymentProtectionRequest,
)


def request(
    *,
    delivery_id: str = "11111111-2222-4333-8444-555555555555",
    payload_digest: str = "sha256:" + ("1" * 64),
) -> DeploymentProtectionRequest:
    return DeploymentProtectionRequest(
        delivery_id=delivery_id,
        repository_id=123456789,
        repository="Halildeu/platform-k8s-gitops",
        installation_id=2222,
        environment="faz22-view-only-pilot",
        head_sha="0123456789abcdef0123456789abcdef01234567",
        intent_ref=(
            "refs/tags/cross-ai-intent/"
            "30000000-0000-4000-8000-000000000001"
        ),
        request_id="30000000-0000-4000-8000-000000000001",
        run_id=987654321,
        callback_url=(
            "https://api.github.com/repos/Halildeu/platform-k8s-gitops/"
            "actions/runs/987654321/deployment_protection_rule"
        ),
        sender_id=424242,
        payload_sha256=payload_digest,
    )


class ObserveLedgerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "ledger.sqlite3"
        self.ledger = ObserveLedger(self.path)

    def tearDown(self) -> None:
        self.ledger.close()
        self.directory.cleanup()

    def test_records_delivery_idempotently_without_raw_payload(self) -> None:
        self.assertTrue(self.ledger.record_delivery(request()))
        self.assertFalse(self.ledger.record_delivery(request()))
        self.assertEqual(self.ledger.counts(), (1, 0))
        raw = self.path.read_bytes()
        self.assertNotIn(b"deployment_callback_url", raw)
        self.assertNotIn(b"platform-automation[bot]", raw)

    def test_rejects_delivery_id_collision(self) -> None:
        self.ledger.record_delivery(request())
        with self.assertRaisesRegex(PolicyError, "WEBHOOK_DELIVERY_COLLISION"):
            self.ledger.record_delivery(
                request(payload_digest="sha256:" + ("2" * 64))
            )

    def test_hash_chains_events(self) -> None:
        self.ledger.record_delivery(request())
        first = self.ledger.append_event(
            delivery_id=request().delivery_id,
            event_type="OBSERVED",
            reason_code="OBSERVE_MODE_NO_CALLBACK",
        )
        second = self.ledger.append_event(
            delivery_id=request().delivery_id,
            event_type="EVALUATED",
            reason_code="INTENT_NOT_REGISTERED",
        )
        self.assertEqual((first.sequence, second.sequence), (1, 2))
        self.assertNotEqual(first.event_hash, second.event_hash)
        connection = sqlite3.connect(self.path)
        try:
            previous = connection.execute(
                "SELECT previous_hash FROM ledger_events WHERE sequence = 2"
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(previous, first.event_hash)

    def test_sqlite_triggers_prevent_update_and_delete(self) -> None:
        self.ledger.record_delivery(request())
        self.ledger.append_event(
            delivery_id=request().delivery_id,
            event_type="OBSERVED",
            reason_code="OBSERVE_MODE_NO_CALLBACK",
        )
        connection = sqlite3.connect(self.path)
        try:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
                connection.execute("DELETE FROM ledger_events")
            with self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
                connection.execute(
                    "UPDATE deliveries SET environment = 'other'"
                )
        finally:
            connection.close()

    def test_event_requires_known_delivery(self) -> None:
        with self.assertRaisesRegex(PolicyError, "LEDGER_DELIVERY_MISSING"):
            self.ledger.append_event(
                delivery_id="missing",
                event_type="OBSERVED",
                reason_code="OBSERVE_MODE_NO_CALLBACK",
            )

    def test_decision_claim_is_idempotent_and_never_contradictory(self) -> None:
        deployment_request = request()
        self.ledger.record_delivery(deployment_request)
        first, inserted = self.ledger.claim_decision(
            request=deployment_request,
            state="approved",
            reason_code="SIGNED_EVIDENCE_VALID",
            evidence_digest="sha256:" + ("a" * 64),
            comment="APPROVED evidence=sha256:abc stage=apply",
        )
        second, duplicate_inserted = self.ledger.claim_decision(
            request=deployment_request,
            state="approved",
            reason_code="SIGNED_EVIDENCE_VALID",
            evidence_digest="sha256:" + ("a" * 64),
            comment="APPROVED evidence=sha256:abc stage=apply",
        )
        self.assertTrue(inserted)
        self.assertFalse(duplicate_inserted)
        self.assertEqual(first, second)
        with self.assertRaisesRegex(PolicyError, "DECISION_CONFLICT"):
            self.ledger.claim_decision(
                request=deployment_request,
                state="rejected",
                reason_code="LATE_DRIFT",
                evidence_digest=None,
                comment="REJECTED code=LATE_DRIFT",
            )
        succeeded = self.ledger.complete_decision(
            request=deployment_request,
            callback_status="Succeeded",
            callback_http_status=204,
        )
        self.assertEqual(succeeded.callback_status, "Succeeded")
        with self.assertRaisesRegex(PolicyError, "DECISION_CONFLICT"):
            self.ledger.complete_decision(
                request=deployment_request,
                callback_status="Unknown",
                callback_http_status=503,
            )

    def test_poller_high_water_advances_only_after_callback_success(self) -> None:
        deployment_request = request()
        delivered_at = datetime(2026, 7, 17, 17, 0, tzinfo=timezone.utc)
        self.ledger.record_delivery(deployment_request)
        with self.assertRaisesRegex(PolicyError, "POLLER_CALLBACK_NOT_SUCCEEDED"):
            self.ledger.advance_poller_after_callback(
                request=deployment_request,
                api_delivery_id=77,
                delivered_at=delivered_at,
            )
        self.ledger.claim_decision(
            request=deployment_request,
            state="approved",
            reason_code="SIGNED_EVIDENCE_VALID",
            evidence_digest="sha256:" + ("a" * 64),
            comment="APPROVED evidence=sha256:abc stage=apply",
        )
        self.ledger.complete_decision(
            request=deployment_request,
            callback_status="Succeeded",
            callback_http_status=204,
        )
        self.ledger.advance_poller_after_callback(
            request=deployment_request,
            api_delivery_id=77,
            delivered_at=delivered_at,
            recorded_at=delivered_at,
        )
        state = self.ledger.poller_state()
        self.assertEqual(state.high_water_delivery_id, 77)
        self.assertEqual(state.high_water_guid, deployment_request.delivery_id)
        self.assertEqual(state.last_success_at, "2026-07-17T17:00:00Z")


if __name__ == "__main__":
    unittest.main()
