import importlib.util
import sys
import unittest
from pathlib import Path

from tests.faz22_remote_ops import test_faz22_6_viewer_broker_evidence_producer as broker_fixtures
from tests.faz22_remote_ops import test_faz22_6_viewer_product_evidence_verifier as fixtures


MODULE_PATH = Path(__file__).parents[2] / "scripts/faz22-remote-ops/produce-view-only-viewer-audit-evidence.py"
SPEC = importlib.util.spec_from_file_location("viewer_audit_producer", MODULE_PATH)
PRODUCER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.path.insert(0, str(MODULE_PATH.parent))
sys.modules[SPEC.name] = PRODUCER
SPEC.loader.exec_module(PRODUCER)


class ViewerAuditEvidenceProducerTest(unittest.TestCase):
    def test_produces_chain_verified_audit_child(self):
        child = PRODUCER.produce(
            broker_fixtures.RuntimeClient(), fixtures.VERIFIER.EXPECTED_REPOSITORY,
            fixtures.SOURCE_RUN_IDS["browser"], fixtures.HEAD_SHA,
        )
        self.assertEqual("audit", child["evidenceType"])
        self.assertTrue(child["payload"]["hashChainVerified"])
        self.assertEqual(100, child["payload"]["framesRenderAcknowledged"])

    def test_rejects_snapshot_from_another_session(self):
        other = dict(fixtures.binding())
        other["sessionSha256"] = "sha256:" + "f" * 64
        with self.assertRaisesRegex(PRODUCER.common.VERIFIER.EvidenceError, "same-session binding"):
            PRODUCER.produce(
                broker_fixtures.RuntimeClient(binding=other), fixtures.VERIFIER.EXPECTED_REPOSITORY,
                fixtures.SOURCE_RUN_IDS["browser"], fixtures.HEAD_SHA,
            )

    def test_commits_to_exact_redacted_audit_summary(self):
        client = broker_fixtures.RuntimeClient()
        child = PRODUCER.produce(
            client, fixtures.VERIFIER.EXPECTED_REPOSITORY,
            fixtures.SOURCE_RUN_IDS["browser"], fixtures.HEAD_SHA,
        )
        files = broker_fixtures.runtime_files()
        expected = fixtures.VERIFIER.digest_bytes(files["snapshots/audit-summary.json"])
        self.assertEqual(expected, child["payload"]["snapshotSha256"])


if __name__ == "__main__":
    unittest.main()
