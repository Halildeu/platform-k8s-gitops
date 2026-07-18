import importlib.util
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/faz22-remote-ops/view_only_transaction_state.py"
SPEC = importlib.util.spec_from_file_location("view_only_transaction_state", MODULE_PATH)
assert SPEC and SPEC.loader
state_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(state_module)


SHA_A = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64
SHA_C = "sha256:" + "c" * 64
SHA_D = "sha256:" + "d" * 64
SHA_E = "sha256:" + "e" * 64


class ViewOnlyTransactionStateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "state.json"
        args = type("Args", (), {
            "output": str(self.path),
            "repository": "Halildeu/platform-k8s-gitops",
            "workflow_ref": "Halildeu/platform-k8s-gitops/.github/workflows/faz22-6-view-only-viewer-transaction.yml@refs/heads/main",
            "head_sha": "1" * 40,
            "run_id": 123456,
            "run_attempt": 1,
            "endpoint_id_sha256": SHA_A,
            "device_hostname_sha256": SHA_B,
            "policy_sha256": SHA_C,
            "mask_policy_sha256": SHA_D,
            "pilot_seconds": 300,
            "preflight_sha256": SHA_E,
        })
        state_module.initialize(args)

    def tearDown(self):
        self.temp.cleanup()

    def move(self, target, reason, payload=SHA_A, authorization=None, expiry=None, session=None):
        args = type("Args", (), {
            "state_file": str(self.path),
            "to": target,
            "reason_code": reason,
            "payload_sha256": payload,
            "authorization_sha256": authorization,
            "watchdog_expires_epoch": expiry,
            "session_sha256": session,
        })
        state_module.transition(args)

    def complete_success_path(self):
        self.move("PREFLIGHT_VERIFIED", "preflight-verified")
        self.move(
            "DECISION_AUTHORIZED",
            "decision-authorized",
            authorization=SHA_B,
            expiry=int(time.time()) + 1800,
        )
        self.move("LIVE_REVALIDATED", "live-revalidated")
        self.move("ACTIVATED", "viewer-activated")
        self.move("CONSENT_PENDING", "consent-pending")
        self.move("EVIDENCE_COLLECTED", "evidence-collected", session=SHA_C)
        self.move("EVIDENCE_VERIFIED", "evidence-verified")
        self.move("ARTIFACTS_STAGED", "artifacts-staged")
        self.move("ROLLBACK_PENDING", "rollback-pending")
        self.move("ROLLED_BACK", "rollback-verified")
        self.move("COMPLETED", "transaction-completed")

    def rewrite_and_resign(self, mutate):
        value = json.loads(self.path.read_text())
        mutate(value)
        previous = None
        for item in value["checkpoints"]:
            item["previousCheckpointSha256"] = previous
            unsigned = dict(item)
            unsigned.pop("checkpointSha256", None)
            item["checkpointSha256"] = state_module.digest(unsigned)
            previous = item["checkpointSha256"]
        self.path.write_text(json.dumps(value))
        os.chmod(self.path, 0o600)

    def test_success_path_is_content_addressed(self):
        self.complete_success_path()
        value = state_module.read_state(self.path)
        self.assertEqual(value["currentState"], "COMPLETED")
        self.assertEqual(value["binding"]["sessionSha256"], SHA_C)
        self.assertEqual(len(value["checkpoints"]), 12)
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)

    def test_failure_path_requires_artifact_stage_before_rollback(self):
        self.move("PREFLIGHT_VERIFIED", "preflight-verified")
        self.move(
            "DECISION_AUTHORIZED",
            "decision-authorized",
            authorization=SHA_B,
            expiry=int(time.time()) + 1800,
        )
        self.move("LIVE_REVALIDATED", "live-revalidated")
        self.move("ACTIVATED", "viewer-activated")
        self.move("FAILURE_CAPTURED", "collector-failed")
        with self.assertRaises(state_module.StateError):
            self.move("ROLLBACK_PENDING", "rollback-pending")
        self.move("ARTIFACTS_STAGED", "artifacts-staged")
        self.move("ROLLBACK_PENDING", "rollback-pending")
        self.move("ROLLED_BACK", "rollback-verified")
        self.move("FAILED_CLEAN", "transaction-failed-clean")

    def test_artifact_failure_still_allows_compensating_rollback(self):
        self.move("PREFLIGHT_VERIFIED", "preflight-verified")
        self.move(
            "DECISION_AUTHORIZED",
            "decision-authorized",
            authorization=SHA_B,
            expiry=int(time.time()) + 1800,
        )
        self.move("LIVE_REVALIDATED", "live-revalidated")
        self.move("ACTIVATED", "viewer-activated")
        self.move("ARTIFACTS_STAGE_FAILED", "artifact-stage-failed")
        self.move("ROLLBACK_PENDING", "rollback-pending")
        self.move("ROLLED_BACK", "rollback-verified")
        self.move("FAILED_CLEAN", "transaction-failed-clean")

    def test_activation_requires_live_revalidation_checkpoint(self):
        self.move("PREFLIGHT_VERIFIED", "preflight-verified")
        self.move(
            "DECISION_AUTHORIZED",
            "decision-authorized",
            authorization=SHA_B,
            expiry=int(time.time()) + 1800,
        )
        with self.assertRaises(state_module.StateError):
            self.move("ACTIVATED", "viewer-activated")
        self.move("LIVE_REVALIDATED", "live-revalidated", payload=SHA_C)
        self.move("ACTIVATED", "viewer-activated")
        value = state_module.read_state(self.path)
        self.assertEqual(value["checkpoints"][-2]["state"], "LIVE_REVALIDATED")
        self.assertEqual(value["checkpoints"][-2]["payloadSha256"], SHA_C)

    def test_tampered_checkpoint_is_rejected(self):
        value = json.loads(self.path.read_text())
        value["checkpoints"][0]["reasonCode"] = "tampered-reason"
        self.path.write_text(json.dumps(value))
        os.chmod(self.path, 0o600)
        with self.assertRaises(state_module.StateError):
            state_module.read_state(self.path)

    def test_tampered_binding_is_rejected(self):
        value = json.loads(self.path.read_text())
        value["binding"]["endpointIdSha256"] = SHA_B
        self.path.write_text(json.dumps(value))
        os.chmod(self.path, 0o600)
        with self.assertRaises(state_module.StateError):
            state_module.read_state(self.path)

    def test_expired_authorization_cannot_advance(self):
        self.move("PREFLIGHT_VERIFIED", "preflight-verified")
        with self.assertRaises(state_module.StateError):
            self.move(
                "DECISION_AUTHORIZED",
                "decision-authorized",
                authorization=SHA_B,
                expiry=int(time.time()) - 1,
            )

    def test_expired_authorization_cannot_claim_live_revalidation(self):
        now = int(time.time())
        self.move("PREFLIGHT_VERIFIED", "preflight-verified")
        self.move(
            "DECISION_AUTHORIZED",
            "decision-authorized",
            authorization=SHA_B,
            expiry=now + 60,
        )
        with mock.patch.object(state_module, "epoch_now", return_value=now + 120):
            with self.assertRaises(state_module.StateError):
                self.move("LIVE_REVALIDATED", "live-revalidated")

    def test_resigned_completed_ledger_without_authorization_or_session_is_rejected(self):
        self.complete_success_path()

        def mutate(value):
            value["binding"]["authorizationSha256"] = None
            value["binding"]["watchdogExpiresEpoch"] = None
            value["binding"]["sessionSha256"] = None
            binding_sha256 = state_module.digest(value["binding"])
            for item in value["checkpoints"]:
                item["bindingSha256"] = binding_sha256

        self.rewrite_and_resign(mutate)
        with self.assertRaises(state_module.StateError):
            state_module.read_state(self.path)

    def test_resigned_numeric_checkpoint_timestamp_is_rejected(self):
        self.complete_success_path()

        def mutate(value):
            value["checkpoints"][3]["observedAt"] = 123

        self.rewrite_and_resign(mutate)
        with self.assertRaises(state_module.StateError):
            state_module.read_state(self.path)

    def test_resigned_historical_binding_digest_is_rejected(self):
        self.complete_success_path()

        def mutate(value):
            value["checkpoints"][0]["bindingSha256"] = state_module.digest(value["binding"])

        self.rewrite_and_resign(mutate)
        with self.assertRaises(state_module.StateError):
            state_module.read_state(self.path)

    def test_expired_authorization_does_not_block_failure_cleanup(self):
        now = int(time.time())
        self.move("PREFLIGHT_VERIFIED", "preflight-verified")
        self.move(
            "DECISION_AUTHORIZED",
            "decision-authorized",
            authorization=SHA_B,
            expiry=now + 60,
        )
        with mock.patch.object(state_module, "epoch_now", return_value=now + 120):
            self.move("FAILURE_CAPTURED", "transaction-step-failed")
            self.move("ARTIFACTS_STAGED", "artifacts-staged")
            self.move("ROLLBACK_PENDING", "rollback-pending")
            self.move("ROLLED_BACK", "rollback-verified")
            self.move("FAILED_CLEAN", "transaction-failed-clean")


if __name__ == "__main__":
    unittest.main()
