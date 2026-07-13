import copy
import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[2] / "scripts/faz22-remote-ops/verify-view-only-viewer-product-evidence.py"
SPEC = importlib.util.spec_from_file_location("viewer_product_verifier", MODULE_PATH)
VERIFIER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = VERIFIER
SPEC.loader.exec_module(VERIFIER)


def evidence():
    digest_a = "sha256:" + "a" * 64
    digest_b = "sha256:" + "b" * 64
    return {
        "schemaVersion": VERIFIER.EVIDENCE_SCHEMA,
        "environment": "test",
        "evidenceRefs": [
            "github-actions://Halildeu/platform-k8s-gitops/runs/123",
            "artifact://viewer/browser-smoke.json",
            "protected://audit/view-start-stop",
            "operator://attended-pilot/approval",
        ],
        "states": {"captured": 100, "brokerReceived": 100, "viewerDelivered": 95, "viewerRendered": 92},
        "quality": {
            "firstFrameAgeMillis": 1400,
            "steadyFrameAgeMillis": [250, 300, 400, 500, 700, 800, 1000],
            "reconnectCount": 0,
            "backpressureMode": "latest-wins-single-slot",
            "maxPendingFrames": 1,
            "soakSeconds": 600,
        },
        "negativeMatrix": {key: "pass" for key in VERIFIER.PASS_KEYS},
        "termination": {key: "pass" for key in VERIFIER.TERMINATION_KEYS},
        "inputChannels": {key: False for key in VERIFIER.NO_INPUT_KEYS},
        "dlp": {"deliveredPathProven": True, "rawContentIncluded": False, "maskedFrameSha256": "c" * 64},
        "persistence": {"recordingMode": "disabled", "contentPersisted": False, "contentStorageWrites": 0},
        "browser": {
            "imageElementRendered": True,
            "pixelCheckPassed": True,
            "renderAckAcceptedCount": 92,
            "consoleErrorCount": 0,
            "screenshotSha256": "d" * 64,
        },
        "broker": {
            "framesSentMetricDelta": 95,
            "renderAckAcceptedMetricDelta": 92,
            "renderAckRejectedMetricDelta": 2,
            "metricsSnapshotSha256": "e" * 64,
        },
        "d30Images": [
            {"component": "backend", "desiredDigest": digest_a, "liveImageIdDigest": digest_a},
            {"component": "web", "desiredDigest": digest_b, "liveImageIdDigest": digest_b},
        ],
        "audit": {
            "viewStartPresent": True,
            "viewStartCommittedBeforeFirstDelivered": True,
            "viewStopPresent": True,
            "hashChainVerified": True,
            "framesDelivered": 95,
            "framesRenderAcknowledged": 92,
            "snapshotSha256": "f" * 64,
        },
        "boundaries": {key: False for key in VERIFIER.BOUNDARY_FALSE_KEYS},
    }


class ViewerProductEvidenceVerifierTest(unittest.TestCase):
    def test_valid_bounded_pilot_passes(self):
        checks, computed = VERIFIER.validate(evidence())
        self.assertTrue(all(check.passed for check in checks))
        self.assertEqual(500.0, computed["steadyFrameAgeP50Millis"])
        self.assertEqual(1000.0, computed["steadyFrameAgeP95Millis"])
        self.assertEqual(0.05, computed["dropRate"])
        self.assertEqual(VERIFIER.MARKER, VERIFIER.result_document(checks, computed)["marker"])

    def test_render_claim_without_rendered_frames_fails(self):
        candidate = evidence()
        candidate["states"]["viewerRendered"] = 0
        checks, computed = VERIFIER.validate(candidate)
        self.assertFalse(all(check.passed for check in checks))
        self.assertNotIn("marker", VERIFIER.result_document(checks, computed))

    def test_production_or_legal_overclaim_fails(self):
        candidate = evidence()
        candidate["boundaries"]["productionReady"] = True
        candidate["boundaries"]["legalAcceptance"] = True
        checks, _ = VERIFIER.validate(candidate)
        self.assertFalse(all(check.passed for check in checks))

    def test_raw_frame_or_token_shape_fails_redaction(self):
        for key, value in (("dataB64", "AAAA"), ("authorization", "Bearer abcdefghijklmnop")):
            candidate = copy.deepcopy(evidence())
            candidate[key] = value
            checks, _ = VERIFIER.validate(candidate)
            self.assertFalse(next(check.passed for check in checks if check.name == "redaction"))

    def test_slo_and_d30_drift_fail(self):
        candidate = evidence()
        candidate["quality"]["steadyFrameAgeMillis"][-1] = 2501
        candidate["d30Images"][0]["liveImageIdDigest"] = "sha256:" + "f" * 64
        checks, _ = VERIFIER.validate(candidate)
        failed = {check.name for check in checks if not check.passed}
        self.assertIn("steady_p95_slo", failed)
        self.assertIn("d30_image_parity", failed)

    def test_duplicate_d30_component_and_query_bearing_reference_fail(self):
        candidate = evidence()
        candidate["d30Images"][1]["component"] = "backend"
        candidate["evidenceRefs"][0] += "?token=not-allowed"
        checks, _ = VERIFIER.validate(candidate)
        failed = {check.name for check in checks if not check.passed}
        self.assertIn("d30_image_parity", failed)
        self.assertIn("evidence_refs", failed)

    def test_zero_hash_zero_age_and_unordered_audit_fail(self):
        candidate = evidence()
        candidate["quality"]["firstFrameAgeMillis"] = 0
        candidate["browser"]["screenshotSha256"] = "0" * 64
        candidate["audit"]["viewStartCommittedBeforeFirstDelivered"] = False
        checks, _ = VERIFIER.validate(candidate)
        failed = {check.name for check in checks if not check.passed}
        self.assertIn("first_frame_slo", failed)
        self.assertIn("browser_render", failed)
        self.assertIn("audit_correlation", failed)

    def test_browser_broker_and_audit_ack_counts_must_cross_check(self):
        candidate = evidence()
        candidate["broker"]["renderAckAcceptedMetricDelta"] = 91
        candidate["audit"]["framesRenderAcknowledged"] = 90
        checks, _ = VERIFIER.validate(candidate)
        failed = {check.name for check in checks if not check.passed}
        self.assertIn("broker_metric_correlation", failed)
        self.assertIn("audit_correlation", failed)


if __name__ == "__main__":
    unittest.main()
