import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

from tests.faz22_remote_ops import test_faz22_6_viewer_product_evidence_verifier as fixtures


MODULE_PATH = Path(__file__).parents[2] / "scripts/faz22-remote-ops/produce-view-only-viewer-operator-evidence.py"
SPEC = importlib.util.spec_from_file_location("viewer_operator_producer", MODULE_PATH)
PRODUCER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.path.insert(0, str(MODULE_PATH.parent))
sys.modules[SPEC.name] = PRODUCER
SPEC.loader.exec_module(PRODUCER)


class ViewerOperatorEvidenceProducerTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_owner_policy_v2 = PRODUCER.VERIFIER.OWNER_POLICY_V2
        self.original_revocation_ledger = PRODUCER.VERIFIER.REVOCATION_LEDGER
        PRODUCER.VERIFIER.OWNER_POLICY_V2 = Path(self.temp_dir.name) / "owner-policy.json"
        PRODUCER.VERIFIER.REVOCATION_LEDGER = Path(self.temp_dir.name) / "revocations.json"
        PRODUCER.VERIFIER.OWNER_POLICY_V2.write_bytes(
            fixtures.encode_json(fixtures.owner_policy_fixture())
        )
        PRODUCER.VERIFIER.REVOCATION_LEDGER.write_bytes(
            fixtures.encode_json(fixtures.revocation_fixture())
        )

    def tearDown(self):
        PRODUCER.VERIFIER.OWNER_POLICY_V2 = self.original_owner_policy_v2
        PRODUCER.VERIFIER.REVOCATION_LEDGER = self.original_revocation_ledger
        self.temp_dir.cleanup()

    def test_produces_verified_operator_child(self):
        child = PRODUCER.produce(
            fixtures.FakeClient(),
            fixtures.VERIFIER.EXPECTED_REPOSITORY,
            fixtures.SOURCE_RUN_IDS["browser"],
            fixtures.ACTIVATION_RUN_ID,
            fixtures.HEAD_SHA,
            advisory_scope_bytes=fixtures.ADVISORY_FIXTURE.scope_bytes,
            cross_ai_trust_root=fixtures.ADVISORY_FIXTURE.authority.trust_root,
            cross_ai_revocations=(
                fixtures.ADVISORY_FIXTURE.authority.revocations_envelope
            ),
            expected_cross_ai_trust_root_sha256=(
                fixtures.ADVISORY_FIXTURE.authority.expected_trust_root_sha256
            ),
            codex_executable_policy=(
                fixtures.ADVISORY_FIXTURE.authority.codex_executable_policy
            ),
        )
        self.assertEqual("operator", child["evidenceType"])
        self.assertEqual(fixtures.binding(), child["binding"])
        self.assertEqual(fixtures.ACTIVATION_RUN_ID, child["payload"]["activationRunId"])
        self.assertNotIn("sessionId", str(child))

    def test_rejects_activation_from_different_revision(self):
        client = fixtures.FakeClient()
        original = client.get_json

        def changed(path):
            value = original(path)
            if path.endswith(f"/actions/runs/{fixtures.ACTIVATION_RUN_ID}"):
                value["head_sha"] = "2" * 40
            return value

        client.get_json = changed
        with self.assertRaisesRegex(PRODUCER.VERIFIER.EvidenceError, "activation head SHA"):
            PRODUCER.produce(
                client,
                fixtures.VERIFIER.EXPECTED_REPOSITORY,
                fixtures.SOURCE_RUN_IDS["browser"],
                fixtures.ACTIVATION_RUN_ID,
                fixtures.HEAD_SHA,
                advisory_scope_bytes=fixtures.ADVISORY_FIXTURE.scope_bytes,
                cross_ai_trust_root=fixtures.ADVISORY_FIXTURE.authority.trust_root,
                cross_ai_revocations=(
                    fixtures.ADVISORY_FIXTURE.authority.revocations_envelope
                ),
                expected_cross_ai_trust_root_sha256=(
                    fixtures.ADVISORY_FIXTURE.authority.expected_trust_root_sha256
                ),
                codex_executable_policy=(
                    fixtures.ADVISORY_FIXTURE.authority.codex_executable_policy
                ),
            )


if __name__ == "__main__":
    unittest.main()
