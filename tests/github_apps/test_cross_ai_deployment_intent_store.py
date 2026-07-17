from __future__ import annotations

import tempfile
import threading
import unittest
from datetime import timedelta
from pathlib import Path

from scripts.github_apps.cross_ai_deployment_policy.contract import EvidenceVerifier
from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError
from scripts.github_apps.cross_ai_deployment_policy.intent_store import (
    ContentAddressedStore,
    IntentRegistry,
)
from tests.github_apps.cross_ai_policy_fixtures import FixtureFactory


class IntentStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.factory = FixtureFactory()
        self.fixture = self.factory.build()
        self.verified = EvidenceVerifier(
            trust_root=self.fixture.trust_root,
            revocations_envelope=self.fixture.revocations_envelope,
            now=self.fixture.now,
        ).verify_bundle(self.fixture.bundle_envelope)
        self.cas = ContentAddressedStore(Path(self.directory.name) / "cas")
        self.registry = IntentRegistry(
            Path(self.directory.name) / "registry.sqlite3", self.cas
        )

    def tearDown(self) -> None:
        self.registry.close()
        self.directory.cleanup()

    def register(self) -> bool:
        return self.registry.register(
            envelope=self.fixture.bundle_envelope,
            verified=self.verified,
            registration_principal="spiffe://acik/platform/trusted-dispatcher",
            registered_at=self.fixture.now,
        )

    def finalize(self) -> bool:
        self.register()
        return self.registry.finalize_ref(
            request_id=self.verified.request_id,
            ref_object_id="a" * 40,
            resolved_head_sha=self.verified.payload["subject"]["headSha"],
            finalized_at=self.fixture.now,
        )

    def test_registers_verified_bundle_in_cas_idempotently(self) -> None:
        self.assertTrue(self.register())
        self.assertFalse(self.register())
        self.assertTrue(self.finalize())
        self.assertFalse(self.finalize())
        record, envelope = self.registry.get_finalized(self.verified.request_id)
        self.assertEqual(record.bundle_digest, self.verified.bundle_digest)
        self.assertEqual(envelope, self.fixture.bundle_envelope)
        self.assertEqual(self.registry.event_count(), 2)

    def test_rejects_wrong_principal_ref_and_tampered_cas(self) -> None:
        with self.assertRaisesRegex(PolicyError, "REGISTRATION_PRINCIPAL_MISMATCH"):
            self.registry.register(
                envelope=self.fixture.bundle_envelope,
                verified=self.verified,
                registration_principal="spiffe://acik/platform/other",
                registered_at=self.fixture.now,
            )
        self.register()
        with self.assertRaisesRegex(PolicyError, "INTENT_REF_MOVED"):
            self.registry.finalize_ref(
                request_id=self.verified.request_id,
                ref_object_id="a" * 40,
                resolved_head_sha="b" * 40,
                finalized_at=self.fixture.now,
            )
        self.finalize()
        path = self.cas._path(self.verified.bundle_digest)
        path.write_bytes(b"{}")
        with self.assertRaisesRegex(PolicyError, "CAS_OBJECT_TAMPERED"):
            self.registry.get_finalized(self.verified.request_id)

    def test_reservation_is_one_time_and_same_request_is_idempotent(self) -> None:
        self.finalize()
        first = self.registry.reserve_stage(
            request_id=self.verified.request_id,
            stage="apply",
            run_id=101,
            run_attempt=1,
            app_rule_id=999,
            now=self.fixture.now,
        )
        second = self.registry.reserve_stage(
            request_id=self.verified.request_id,
            stage="apply",
            run_id=101,
            run_attempt=1,
            app_rule_id=999,
            now=self.fixture.now,
        )
        self.assertFalse(first.idempotent)
        self.assertTrue(second.idempotent)
        self.assertEqual(first.reservation_id, second.reservation_id)
        with self.assertRaisesRegex(PolicyError, "GRANT_REPLAY_OR_CONSUMED"):
            self.registry.reserve_stage(
                request_id=self.verified.request_id,
                stage="apply",
                run_id=102,
                run_attempt=1,
                app_rule_id=999,
                now=self.fixture.now,
            )

    def test_stage_order_cannot_be_bypassed_without_outcome_record(self) -> None:
        self.finalize()
        with self.assertRaisesRegex(PolicyError, "PRIOR_STAGE_NOT_VERIFIED"):
            self.registry.reserve_stage(
                request_id=self.verified.request_id,
                stage="browser-evidence",
                run_id=201,
                run_attempt=1,
                app_rule_id=999,
                now=self.fixture.now,
            )
        self.registry.reserve_stage(
            request_id=self.verified.request_id,
            stage="apply",
            run_id=101,
            run_attempt=1,
            app_rule_id=999,
            now=self.fixture.now,
        )
        self.registry.transition_stage(
            request_id=self.verified.request_id,
            stage="apply",
            to_state="ApprovedPendingOutcome",
            reason_code="CALLBACK_204",
            recorded_at=self.fixture.now,
        )
        with self.assertRaisesRegex(PolicyError, "STAGE_OUTCOME_REQUIRED"):
            self.registry.transition_stage(
                request_id=self.verified.request_id,
                stage="apply",
                to_state="Succeeded",
                reason_code="OUTCOME_VERIFIED",
                recorded_at=self.fixture.now,
            )
        with self.assertRaisesRegex(PolicyError, "PRIOR_STAGE_NOT_VERIFIED"):
            self.registry.reserve_stage(
                request_id=self.verified.request_id,
                stage="browser-evidence",
                run_id=201,
                run_attempt=1,
                app_rule_id=999,
                now=self.fixture.now,
            )

    def test_concurrent_reservation_has_one_winner(self) -> None:
        self.finalize()
        results: list[str] = []

        def reserve(run_id: int) -> None:
            try:
                result = self.registry.reserve_stage(
                    request_id=self.verified.request_id,
                    stage="apply",
                    run_id=run_id,
                    run_attempt=1,
                    app_rule_id=999,
                    now=self.fixture.now,
                )
                results.append(f"won:{result.run_id}")
            except PolicyError as exc:
                results.append(exc.code)

        threads = [threading.Thread(target=reserve, args=(run_id,)) for run_id in (301, 302)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sum(result.startswith("won:") for result in results), 1)
        self.assertIn("GRANT_REPLAY_OR_CONSUMED", results)

    def test_only_terminal_proof_can_move_uncertain_apply_to_callback_unknown(self) -> None:
        self.finalize()
        self.registry.reserve_stage(
            request_id=self.verified.request_id,
            stage="apply",
            run_id=401,
            run_attempt=1,
            app_rule_id=999,
            now=self.fixture.now,
        )
        self.registry.transition_stage(
            request_id=self.verified.request_id,
            stage="apply",
            to_state="OutcomeOverdue",
            reason_code="CALLBACK_TRANSPORT_AMBIGUOUS",
            recorded_at=self.fixture.now,
        )
        with self.assertRaisesRegex(PolicyError, "PRIOR_STAGE_NOT_VERIFIED"):
            self.registry.reserve_stage(
                request_id=self.verified.request_id,
                stage="compensating-rollback",
                run_id=402,
                run_attempt=1,
                app_rule_id=999,
                now=self.fixture.now,
            )
        self.registry.transition_stage(
            request_id=self.verified.request_id,
            stage="apply",
            to_state="CallbackUnknown",
            reason_code="TERMINAL_RUN_WITH_UNSEALED_OUTCOME",
            recorded_at=self.fixture.now,
        )
        rollback = self.registry.reserve_stage(
            request_id=self.verified.request_id,
            stage="compensating-rollback",
            run_id=402,
            run_attempt=1,
            app_rule_id=999,
            now=self.fixture.now,
        )
        self.assertEqual(rollback.state, "Reserved")

    def test_outcome_deadline_quarantines_apply_without_unlocking_rollback(self) -> None:
        self.finalize()
        reservation = self.registry.reserve_stage(
            request_id=self.verified.request_id,
            stage="apply",
            run_id=501,
            run_attempt=1,
            app_rule_id=999,
            now=self.fixture.now,
        )
        self.assertEqual(reservation.reservation_expires_at, "2026-07-16T21:00:00Z")
        self.registry.transition_stage(
            request_id=self.verified.request_id,
            stage="apply",
            to_state="ApprovedPendingOutcome",
            reason_code="CALLBACK_204",
            recorded_at=self.fixture.now,
        )
        self.assertEqual(
            self.registry.expire_pending_stages(
                now=self.fixture.now + timedelta(minutes=31)
            ),
            1,
        )
        self.assertEqual(
            self.registry.get_stage(self.verified.request_id, "apply").state,
            "OutcomeOverdue",
        )
        with self.assertRaisesRegex(PolicyError, "PRIOR_STAGE_NOT_VERIFIED"):
            self.registry.reserve_stage(
                request_id=self.verified.request_id,
                stage="compensating-rollback",
                run_id=502,
                run_attempt=1,
                app_rule_id=999,
                now=self.fixture.now + timedelta(minutes=31),
            )


if __name__ == "__main__":
    unittest.main()
