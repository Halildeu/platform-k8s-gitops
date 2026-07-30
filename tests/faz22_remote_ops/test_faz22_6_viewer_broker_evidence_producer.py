import hashlib
import importlib.util
import io
import json
import sys
import unittest
import zipfile
from pathlib import Path

from tests.faz22_remote_ops import test_faz22_6_viewer_product_evidence_verifier as fixtures


MODULE_PATH = Path(__file__).parents[2] / "scripts/faz22-remote-ops/produce-view-only-viewer-broker-evidence.py"
SPEC = importlib.util.spec_from_file_location("viewer_broker_producer", MODULE_PATH)
PRODUCER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.path.insert(0, str(MODULE_PATH.parent))
sys.modules[SPEC.name] = PRODUCER
SPEC.loader.exec_module(PRODUCER)

RUNTIME_ARTIFACT_ID = 700002


def runtime_files(data_frames=105, rejected=1, binding=None, process_start_after="1.783987E9",
                  frame_overrides=None, audit_overrides=None):
    binding = binding or fixtures.binding()
    before = """process_start_time_seconds 1.783987E9
remote_access_bridge_viewer_ended_total 0.0
remote_access_bridge_viewer_frames_sent_total 0.0
remote_access_bridge_viewer_render_ack_accepted_total 0.0
remote_access_bridge_viewer_render_ack_rejected_total 0.0
remote_access_bridge_viewer_started_total 0.0
""".encode()
    after = f"""process_start_time_seconds {process_start_after}
remote_access_bridge_data_frames_total {data_frames}.0
remote_access_bridge_view_only_fanout_frames_total{{disposition=\"delivered\"}} 105.0
remote_access_bridge_viewer_ended_total 1.0
remote_access_bridge_viewer_frames_sent_total 100.0
remote_access_bridge_viewer_render_ack_accepted_total 100.0
remote_access_bridge_viewer_render_ack_rejected_total {rejected}.0
remote_access_bridge_viewer_started_total 1.0
""".encode()
    frame = {
        "schemaVersion": "faz22.6-viewer-frame-flow-raw-v1",
        "observedAt": "2026-07-14T00:05:00Z",
        "binding": binding,
        "firstSeq": 0,
        "lastSeq": 104,
        "firstObservedAtEpochMillis": 1783987500000,
        "firstDeliveredAtEpochMillis": 1783987500000,
        "lastObservedAtEpochMillis": 1783987500104,
        "producedSequenceCount": 105,
        "brokerReceivedDistinctCount": 105,
        "sequenceGapCount": 0,
        "dispositions": {"DELIVERED": 105, "DROPPED_NO_VIEWER": 0},
        "rawLogSha256": "sha256:" + "9" * 64,
    }
    frame.update(frame_overrides or {})
    audit = {
        "schemaVersion": "faz22.6-viewer-audit-raw-v1",
        "observedAt": "2026-07-14T00:05:00Z",
        "binding": binding,
        "chainCheckedCount": 20,
        "chainSha256": "sha256:" + "a" * 64,
        "viewStartOccurredAt": "2026-07-14T00:01:00Z",
        "firstFrameObservedAtEpochMillis": 1783987500000,
        "viewStopOccurredAt": "2026-07-14T00:06:00Z",
        "viewStartPresent": True,
        "viewStartCommittedBeforeFirstDelivered": True,
        "viewStopPresent": True,
        "hashChainVerified": True,
        "framesDelivered": 100,
        "framesRenderAcknowledged": 100,
        "recordingMode": "disabled",
        "contentPersisted": False,
        "contentStorageWrites": 0,
    }
    audit.update(audit_overrides or {})
    files = {
        "snapshots/d30-snapshot.json": b'{"schemaVersion":"faz22.6-viewer-d30-raw-v1"}\n',
        "snapshots/metrics-before.prom": before,
        "snapshots/metrics-after.prom": after,
        "snapshots/frame-flow-summary.json": (json.dumps(frame, sort_keys=True) + "\n").encode(),
        "snapshots/audit-summary.json": (json.dumps(audit, sort_keys=True) + "\n").encode(),
    }
    files["SHA256SUMS"] = "".join(
        f"{hashlib.sha256(raw).hexdigest()}  {name}\n" for name, raw in sorted(files.items())
    ).encode("ascii")
    return files


def archive(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, raw in files.items():
            bundle.writestr(name, raw)
    return output.getvalue()


class RuntimeClient(fixtures.FakeClient):
    def __init__(self, runtime_head_sha=fixtures.HEAD_SHA, **kwargs):
        super().__init__()
        self.runtime_archive = archive(runtime_files(**kwargs))
        self.runtime_head_sha = runtime_head_sha

    def get_json(self, path):
        browser_run = fixtures.SOURCE_RUN_IDS["browser"]
        if path == f"/repos/{fixtures.VERIFIER.EXPECTED_REPOSITORY}/actions/runs/{browser_run}/artifacts?per_page=100":
            value = super().get_json(path)
            value["artifacts"].append({
                "id": RUNTIME_ARTIFACT_ID,
                "name": f"faz22-6-view-only-viewer-runtime-snapshots-{browser_run}",
                "expired": False,
                "digest": fixtures.VERIFIER.digest_bytes(self.runtime_archive),
                "workflow_run": {"id": browser_run, "head_sha": self.runtime_head_sha},
            })
            return value
        return super().get_json(path)

    def get_bytes(self, path):
        if path == f"/repos/{fixtures.VERIFIER.EXPECTED_REPOSITORY}/actions/artifacts/{RUNTIME_ARTIFACT_ID}/zip":
            return self.runtime_archive
        return super().get_bytes(path)


class ViewerBrokerEvidenceProducerTest(unittest.TestCase):
    def test_produces_metric_correlated_broker_child(self):
        child = PRODUCER.produce(
            RuntimeClient(), fixtures.VERIFIER.EXPECTED_REPOSITORY,
            fixtures.SOURCE_RUN_IDS["browser"], fixtures.HEAD_SHA,
        )
        self.assertEqual("broker", child["evidenceType"])
        self.assertEqual(105, child["payload"]["states"]["brokerReceived"])
        self.assertEqual(100, child["payload"]["states"]["viewerRendered"])
        self.assertEqual(1, child["payload"]["renderAckRejectedMetricDelta"])

    def test_rejects_data_metric_count_mismatch(self):
        with self.assertRaisesRegex(PRODUCER.common.VERIFIER.EvidenceError, "DATA metric"):
            PRODUCER.produce(
                RuntimeClient(data_frames=104), fixtures.VERIFIER.EXPECTED_REPOSITORY,
                fixtures.SOURCE_RUN_IDS["browser"], fixtures.HEAD_SHA,
            )

    def test_rejects_absent_replay_rejection_signal(self):
        with self.assertRaisesRegex(PRODUCER.common.VERIFIER.EvidenceError, "rejection metric"):
            PRODUCER.produce(
                RuntimeClient(rejected=0), fixtures.VERIFIER.EXPECTED_REPOSITORY,
                fixtures.SOURCE_RUN_IDS["browser"], fixtures.HEAD_SHA,
            )

    def test_accepts_pre_subscription_frame_dropped_before_view_start(self):
        child = PRODUCER.produce(
            RuntimeClient(
                frame_overrides={
                    "firstObservedAtEpochMillis": 1783987259000,
                    "firstDeliveredAtEpochMillis": 1783987500000,
                    "dispositions": {"DELIVERED": 104, "DROPPED_NO_VIEWER": 1},
                },
            ),
            fixtures.VERIFIER.EXPECTED_REPOSITORY,
            fixtures.SOURCE_RUN_IDS["browser"],
            fixtures.HEAD_SHA,
        )
        self.assertEqual(105, child["payload"]["states"]["brokerReceived"])
        self.assertEqual(100, child["payload"]["states"]["viewerRendered"])

    def test_rejects_broker_restart_during_pilot(self):
        with self.assertRaisesRegex(PRODUCER.common.VERIFIER.EvidenceError, "process restarted"):
            PRODUCER.produce(
                RuntimeClient(process_start_after="1783987010.0"),
                fixtures.VERIFIER.EXPECTED_REPOSITORY,
                fixtures.SOURCE_RUN_IDS["browser"], fixtures.HEAD_SHA,
            )

    def test_rejects_unverified_audit_summary(self):
        with self.assertRaisesRegex(PRODUCER.common.VERIFIER.EvidenceError, "hashChainVerified"):
            PRODUCER.produce(
                RuntimeClient(audit_overrides={"hashChainVerified": False}),
                fixtures.VERIFIER.EXPECTED_REPOSITORY,
                fixtures.SOURCE_RUN_IDS["browser"], fixtures.HEAD_SHA,
            )

    def test_rejects_runtime_artifact_from_another_revision(self):
        with self.assertRaisesRegex(PRODUCER.common.VERIFIER.EvidenceError, "source revision binding"):
            PRODUCER.produce(
                RuntimeClient(runtime_head_sha="f" * 40),
                fixtures.VERIFIER.EXPECTED_REPOSITORY,
                fixtures.SOURCE_RUN_IDS["browser"], fixtures.HEAD_SHA,
            )

    def test_rejects_audit_start_after_first_broker_frame(self):
        with self.assertRaisesRegex(PRODUCER.common.VERIFIER.EvidenceError, "VIEW_START follows"):
            PRODUCER.produce(
                RuntimeClient(audit_overrides={"viewStartOccurredAt": "2026-07-14T00:06:00Z"}),
                fixtures.VERIFIER.EXPECTED_REPOSITORY,
                fixtures.SOURCE_RUN_IDS["browser"], fixtures.HEAD_SHA,
            )


if __name__ == "__main__":
    unittest.main()
