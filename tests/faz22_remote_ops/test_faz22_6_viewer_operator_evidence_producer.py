import importlib.util
import sys
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
    def test_produces_verified_operator_child(self):
        child = PRODUCER.produce(
            fixtures.FakeClient(),
            fixtures.VERIFIER.EXPECTED_REPOSITORY,
            fixtures.SOURCE_RUN_IDS["browser"],
            fixtures.ACTIVATION_RUN_ID,
            fixtures.HEAD_SHA,
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
            )


if __name__ == "__main__":
    unittest.main()
