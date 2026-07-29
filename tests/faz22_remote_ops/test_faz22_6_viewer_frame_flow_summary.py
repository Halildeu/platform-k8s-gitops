import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[2] / "scripts/faz22-remote-ops/build-view-only-viewer-frame-flow-summary.py"
SPEC = importlib.util.spec_from_file_location("viewer_frame_flow_summary", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def browser():
    return {
        "observedAt": "2026-07-14T00:05:00Z",
        "binding": {
            "sessionSha256": "sha256:" + "1" * 64,
            "tenantSha256": "sha256:" + "2" * 64,
            "operatorSha256": "sha256:" + "3" * 64,
            "deviceSha256": "sha256:" + "4" * 64,
        },
    }


def logs(count=100, conflicting=False):
    lines = []
    for seq in range(count):
        disposition = "DELIVERED" if seq % 2 else "DROPPED_NO_VIEWER"
        lines.append(
            f"view-only frame: session=s-safe stream=op-safe seq={seq} bytes=90000 "
            f"type=image/png disposition={disposition} ts={1783987500000 + seq}"
        )
    if conflicting:
        lines.append(
            "view-only frame: session=s-safe stream=op-safe seq=1 bytes=90000 "
            "type=image/png disposition=DROPPED_NO_VIEWER ts=1783987500001"
        )
    return ("\n".join(lines) + "\n").encode()


class ViewerFrameFlowSummaryTest(unittest.TestCase):
    def test_reduces_raw_identifiers_to_counts_and_hashes(self):
        result = MODULE.build(logs(), "s-safe", browser())
        self.assertEqual(100, result["producedSequenceCount"])
        self.assertEqual(100, result["brokerReceivedDistinctCount"])
        self.assertEqual(1783987500000, result["firstObservedAtEpochMillis"])
        self.assertEqual(1783987500099, result["lastObservedAtEpochMillis"])
        self.assertNotIn("s-safe", str(result))

    def test_rejects_conflicting_duplicate_sequence(self):
        with self.assertRaisesRegex(ValueError, "conflicting dispositions"):
            MODULE.build(logs(conflicting=True), "s-safe", browser())

    def test_rejects_unknown_nonempty_disposition(self):
        raw = logs() + (
            "view-only frame: session=s-safe stream=op-safe seq=100 bytes=4 "
            "type=image/png disposition=THROTTLED ts=1783987500100\n"
        ).encode()
        with self.assertRaisesRegex(ValueError, "unexpected non-empty"):
            MODULE.build(raw, "s-safe", browser())

    def test_rejects_nonmonotonic_broker_timestamps(self):
        raw = logs().replace(b"ts=1783987500050", b"ts=1783987500001")
        with self.assertRaisesRegex(ValueError, "not monotonic"):
            MODULE.build(raw, "s-safe", browser())

    def test_accepts_json_wrapped_broker_log_message(self):
        raw = b"\n".join(
            b'{"log":"' + line + b'"}'
            for line in logs().splitlines()
        ) + b"\n"
        result = MODULE.build(raw, "s-safe", browser())
        self.assertEqual(100, result["brokerReceivedDistinctCount"])
        self.assertEqual(1783987500099, result["lastObservedAtEpochMillis"])


if __name__ == "__main__":
    unittest.main()
