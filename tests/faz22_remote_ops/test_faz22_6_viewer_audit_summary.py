import importlib.util
import json
import sys
import unittest
from datetime import datetime
from pathlib import Path


MODULE_PATH = Path(__file__).parents[2] / "scripts/faz22-remote-ops/build-view-only-viewer-audit-summary.py"
SPEC = importlib.util.spec_from_file_location("viewer_audit_summary", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

SESSION = "session-safe-1"
STREAM = "screen-view-safe-1"
TENANT = "11111111-1111-1111-1111-111111111111"
OPERATOR = "operator-subject-safe"
DEVICE = "22222222-2222-2222-2222-222222222222"


def millis(value):
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)


def browser():
    return {
        "observedAt": "2026-07-14T00:05:00Z",
        "binding": {
            "sessionSha256": MODULE.sha256_text(SESSION),
            "tenantSha256": MODULE.sha256_text(TENANT),
            "operatorSha256": MODULE.sha256_text(OPERATOR),
            "deviceSha256": MODULE.sha256_text(DEVICE),
        },
    }


def frame_flow():
    return {
        "binding": browser()["binding"],
        "firstObservedAtEpochMillis": millis("2026-07-14T00:00:59Z"),
        "firstDeliveredAtEpochMillis": millis("2026-07-14T00:01:01Z"),
        "lastDeliveredAtEpochMillis": millis("2026-07-14T00:05:59Z"),
        "lastObservedAtEpochMillis": millis("2026-07-14T00:05:59Z"),
    }


def row(event_id, action, occurred_at, metadata, previous=None):
    value = {
        "id": event_id,
        "tenant_id": TENANT,
        "device_id": None,
        "command_id": None,
        "event_type": MODULE.EVENT_TYPE,
        "action": action,
        "performed_by_subject": OPERATOR,
        "correlation_id": SESSION,
        "metadata": metadata,
        "before_state": None,
        "after_state": None,
        "occurred_at": occurred_at,
        "prev_event_hash": previous,
        "event_hash": "0" * 64,
        "event_hash_alg": MODULE.HASH_ALGORITHM,
        "event_hash_version": MODULE.HASH_VERSION,
    }
    value["event_hash"] = MODULE.computed_event_hash(value)
    return value


def chain():
    base = {
        "sessionId": SESSION,
        "deviceId": DEVICE,
        "streamId": STREAM,
        "recording": False,
        "attended": True,
        "capability": "VIEW_ONLY",
    }
    start = row(
        "00000000-0000-0000-0000-000000000001", "VIEW_START",
        "2026-07-14T00:01:00.000000Z", base,
    )
    stop_meta = dict(base, framesDelivered=101, framesRenderAcknowledged=100)
    stop = row(
        "00000000-0000-0000-0000-000000000002", "VIEW_STOP",
        "2026-07-14T00:06:00.123000Z", stop_meta, start["event_hash"],
    )
    return [start, stop]


def raw_chain(rows=None):
    return ("\n".join(json.dumps(value, sort_keys=True) for value in (rows or chain())) + "\n").encode()


class ViewerAuditSummaryTest(unittest.TestCase):
    def test_verifies_full_chain_and_redacts_raw_identity(self):
        result = MODULE.build(
            raw_chain(), f"{SESSION}\t1\tPOLICY_EVENT\t{{}}\n".encode(),
            SESSION, STREAM, browser(), frame_flow(),
        )
        self.assertTrue(result["hashChainVerified"])
        self.assertEqual(2, result["chainCheckedCount"])
        self.assertEqual(101, result["framesDelivered"])
        self.assertEqual(0, result["contentStorageWrites"])
        self.assertNotIn(SESSION, json.dumps(result))
        self.assertNotIn(OPERATOR, json.dumps(result))

    def test_rejects_a_tampered_historical_row(self):
        rows = chain()
        rows[0]["metadata"]["attended"] = False
        with self.assertRaisesRegex(ValueError, "event hash mismatch"):
            MODULE.build(
                raw_chain(rows), f"{SESSION}\t1\tPOLICY_EVENT\t{{}}\n".encode(),
                SESSION, STREAM, browser(), frame_flow(),
            )

    def test_rejects_recording_content_write(self):
        recording = f"{SESSION}\t1\tPOLICY_EVENT\t{{}}\n{SESSION}\t2\tAGENT_OUTPUT\t{{}}\n".encode()
        with self.assertRaisesRegex(ValueError, "content storage writes"):
            MODULE.build(raw_chain(), recording, SESSION, STREAM, browser(), frame_flow())

    def test_rejects_empty_recording_audit_ledger(self):
        with self.assertRaisesRegex(ValueError, "empty or lacks a policy event"):
            MODULE.build(raw_chain(), b"", SESSION, STREAM, browser(), frame_flow())

    def test_rejects_noncanonical_binding_field_set(self):
        invalid_browser = browser()
        invalid_browser["binding"]["extra"] = "sha256:" + "f" * 64
        with self.assertRaisesRegex(ValueError, "browser binding is invalid"):
            MODULE.build(
                raw_chain(), f"{SESSION}\t1\tPOLICY_EVENT\t{{}}\n".encode(),
                SESSION, STREAM, invalid_browser, frame_flow(),
            )

    def test_rejects_view_start_after_first_viewer_delivery(self):
        invalid_flow = frame_flow()
        invalid_flow["firstDeliveredAtEpochMillis"] = millis("2026-07-14T00:00:59Z")
        with self.assertRaisesRegex(ValueError, "before first broker delivery"):
            MODULE.build(
                raw_chain(), f"{SESSION}\t1\tPOLICY_EVENT\t{{}}\n".encode(),
                SESSION, STREAM, browser(), invalid_flow,
            )

    def test_rejects_view_stop_before_last_broker_delivery(self):
        invalid_flow = frame_flow()
        invalid_flow["lastDeliveredAtEpochMillis"] = millis("2026-07-14T00:06:01Z")
        invalid_flow["lastObservedAtEpochMillis"] = millis("2026-07-14T00:06:01Z")
        with self.assertRaisesRegex(ValueError, "precedes the last broker-delivered frame"):
            MODULE.build(
                raw_chain(), f"{SESSION}\t1\tPOLICY_EVENT\t{{}}\n".encode(),
                SESSION, STREAM, browser(), invalid_flow,
            )

    def test_accepts_dropped_no_viewer_frame_observed_after_view_stop(self):
        valid_flow = frame_flow()
        valid_flow["lastObservedAtEpochMillis"] = millis("2026-07-14T00:06:01Z")
        result = MODULE.build(
            raw_chain(), f"{SESSION}\t1\tPOLICY_EVENT\t{{}}\n".encode(),
            SESSION, STREAM, browser(), valid_flow,
        )
        self.assertTrue(result["viewStopPresent"])


if __name__ == "__main__":
    unittest.main()
