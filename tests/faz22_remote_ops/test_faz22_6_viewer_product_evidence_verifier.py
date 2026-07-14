import copy
import hashlib
import importlib.util
import io
import json
import sys
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path


MODULE_PATH = Path(__file__).parents[2] / "scripts/faz22-remote-ops/verify-view-only-viewer-product-evidence.py"
SPEC = importlib.util.spec_from_file_location("viewer_product_verifier", MODULE_PATH)
VERIFIER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = VERIFIER
SPEC.loader.exec_module(VERIFIER)


RUN_ID = 123456
HEAD_SHA = "1" * 40
NOW = datetime(2026, 7, 14, 0, 10, 0, tzinfo=timezone.utc)
SOURCE_TYPES = tuple(sorted(VERIFIER.EXPECTED_CHILD_TYPES))
SOURCE_RUN_IDS = {name: 200000 + index for index, name in enumerate(SOURCE_TYPES, start=1)}
SOURCE_ARTIFACT_IDS = {name: 300000 + index for index, name in enumerate(SOURCE_TYPES, start=1)}
ACTIVATION_RUN_ID = 400001
AUTHORIZATION_ARTIFACT_ID = 500001


def sha(char):
    return "sha256:" + char * 64


def binding():
    return {
        "sessionSha256": sha("1"),
        "tenantSha256": sha("2"),
        "operatorSha256": sha("3"),
        "deviceSha256": sha("4"),
    }


def child(evidence_type, kind, payload, observed_at="2026-07-14T00:05:00Z"):
    return {
        "schemaVersion": "faz22.6.viewOnlyViewerProductChildEvidence.v2",
        "evidenceType": evidence_type,
        "sourceRevision": HEAD_SHA,
        "observedAt": observed_at,
        "binding": binding(),
        "producer": {
            "kind": kind,
            "tool": f"scripts/evidence/{evidence_type}",
            "toolVersion": "v2",
        },
        "payload": payload,
    }


def child_documents():
    states = {"captured": 105, "brokerReceived": 105, "viewerDelivered": 100, "viewerRendered": 100}
    return {
        "browser": child(
            "browser",
            "browser-harness",
            {
                "pilotStartedAt": "2026-07-14T00:01:00Z",
                "pilotEndedAt": "2026-07-14T00:06:00Z",
                "imageElementRendered": True,
                "pixelCheckPassed": True,
                "dlpMaskRectBps": "7500,7500,2500,2500",
                "dlpMaskPixelCheckPassed": True,
                "activeIndicatorPixelCheckPassed": True,
                "maskedFrameSha256": sha("8"),
                "renderAckAttemptedCount": 100,
                "renderAckAcceptedCount": 100,
                "consoleErrorCount": 0,
                "screenshotSha256": sha("5"),
                "firstFrameAgeMillis": 900,
                "steadyFrameAgeMillis": [200 + (index % 10) * 50 for index in range(100)],
                "meta": {
                    "recording": False,
                    "attended": True,
                    "capability": "VIEW_ONLY",
                    "viewerIdSha256": sha("6"),
                },
            },
        ),
        "broker": child(
            "broker",
            "prometheus-query",
            {
                "states": states,
                "framesSentMetricDelta": 100,
                "renderAckAcceptedMetricDelta": 100,
                "renderAckRejectedMetricDelta": 2,
                "reconnectCount": 0,
                "backpressureMode": "latest-wins-single-slot",
                "maxPendingFrames": 1,
                "metricsSnapshotSha256": sha("7"),
                "inputChannels": {
                    "keyboard": False,
                    "mouse": False,
                    "clipboard": False,
                    "fileTransfer": False,
                    "credentialEntry": False,
                    "shell": False,
                    "portForward": False,
                    "hiddenControl": False,
                },
                "dlp": {
                    "deliveredPathProven": True,
                    "rawContentIncluded": False,
                    "maskedFrameSha256": sha("8"),
                },
                "persistence": {
                    "recordingMode": "disabled",
                    "contentPersisted": False,
                    "contentStorageWrites": 0,
                },
            },
        ),
        "audit": child(
            "audit",
            "audit-verifier",
            {
                "viewStartPresent": True,
                "viewStartCommittedBeforeFirstDelivered": True,
                "viewStopPresent": True,
                "hashChainVerified": True,
                "framesDelivered": 100,
                "framesRenderAcknowledged": 100,
                "snapshotSha256": sha("9"),
            },
        ),
        "d30": child(
            "d30",
            "d30-verifier",
            {
                "images": [
                    {"component": "backend", "desiredDigest": sha("a"), "liveImageIdDigest": sha("a")},
                    {"component": "web", "desiredDigest": sha("b"), "liveImageIdDigest": sha("b")},
                ],
                "snapshotSha256": sha("c"),
            },
        ),
        "negative": child(
            "negative",
            "negative-harness",
            {
                "suiteSha256": sha("d"),
                "cases": {
                    "noAuth": True,
                    "wrongRole": True,
                    "wrongTenant": True,
                    "wrongDevice": True,
                    "expired": True,
                    "revoked": True,
                    "replayed": True,
                    "overConcurrency": True,
                    "disconnectedViewer": True,
                },
            },
        ),
        "termination": child(
            "termination",
            "termination-harness",
            {
                "suiteSha256": sha("e"),
                "cases": {
                    "localAbort": True,
                    "killOrRevoke": True,
                    "ttlExpiry": True,
                    "heartbeatLoss": True,
                    "consentWithdrawal": True,
                    "indicatorLoss": True,
                },
            },
        ),
        "operator": child(
            "operator",
            "protected-authorization",
            {
                "onePersonRoster": True,
                "pilotDeviceConsented": True,
                "exposureApproved": True,
                "protectedEnvironment": "faz22-view-only-pilot",
                "activationRunId": ACTIVATION_RUN_ID,
                "activationRunAttempt": 1,
                "activationHeadSha": HEAD_SHA,
                "authorizationArtifactId": AUTHORIZATION_ARTIFACT_ID,
                "authorizationArtifactDigest": VERIFIER.digest_bytes(activation_archive()),
                "authorizationSha256": VERIFIER.digest_bytes(authorization_bytes()),
                "kvkkMarkerSha256": VERIFIER.digest_bytes(KVKK_MARKER_BYTES),
            },
            observed_at="2026-07-14T00:00:30Z",
        ),
    }


def encode_json(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def encode_zip(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, raw in files.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 7, 14, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, raw)
    return output.getvalue()


KVKK_MARKER_BYTES = b"F22_6_VIEW_ONLY_KVKK: v1\nstatus: pass\n"


def authorization_bytes():
    return encode_json({
        "schemaVersion": "faz22.6-view-only-pilot-protected-authorization-v1",
        "environment": "faz22-view-only-pilot",
        "onePersonRoster": True,
        "operatorSha256": binding()["operatorSha256"],
        "consentingPilotDevice": True,
        "deviceSha256": binding()["deviceSha256"],
        "exposureApprovedByProtectedEnvironment": True,
        "kvkkMarkerSha256": VERIFIER.digest_bytes(KVKK_MARKER_BYTES),
        "expiresAt": "2026-07-14T00:20:00Z",
        "authorizationRunId": ACTIVATION_RUN_ID,
    })


def activation_archive():
    files = {
        "kvkk-marker.txt": KVKK_MARKER_BYTES,
        "kvkk-marker-verifier-result.json": encode_json({"status": "pass", "humanSignatureCount": 2}),
        "protected-authorization.json": authorization_bytes(),
    }
    sums = "".join(
        f"{hashlib.sha256(raw).hexdigest()}  {name}\n" for name, raw in files.items()
    ).encode("ascii")
    return encode_zip({**files, "SHA256SUMS": sums})


def source_archive(name, raw):
    return encode_zip({f"evidence/{name}.json": raw})


def source_entry(name, raw):
    run_id = SOURCE_RUN_IDS[name]
    archive = source_archive(name, raw)
    workflow_path, _ = VERIFIER.EXPECTED_SOURCE_WORKFLOWS[name]
    return {
        "repository": VERIFIER.EXPECTED_REPOSITORY,
        "workflowPath": workflow_path,
        "runId": run_id,
        "runAttempt": 1,
        "headSha": HEAD_SHA,
        "artifactId": SOURCE_ARTIFACT_IDS[name],
        "artifactName": f"faz22-6-view-only-viewer-{name}-evidence-{run_id}",
        "artifactDigest": VERIFIER.digest_bytes(archive),
        "artifactFile": f"evidence/{name}.json",
    }


def build_archive(children=None, mutate_root=None, extra_files=None, zip_entry=None):
    children = copy.deepcopy(children or child_documents())
    child_bytes = {f"evidence/{name}.json": encode_json(value) for name, value in children.items()}
    root = {
        "schemaVersion": VERIFIER.EVIDENCE_SCHEMA,
        "environment": "test",
        "producer": {
            "repository": VERIFIER.EXPECTED_REPOSITORY,
            "workflowPath": VERIFIER.EXPECTED_WORKFLOW_PATH,
            "runId": RUN_ID,
            "runAttempt": 1,
            "headSha": HEAD_SHA,
        },
        "generatedAt": "2026-07-14T00:06:01Z",
        "pilot": {"startedAt": "2026-07-14T00:01:00Z", "endedAt": "2026-07-14T00:06:00Z"},
        "binding": binding(),
        "scope": {
            "mode": "VIEW_ONLY",
            "recordingMode": "disabled",
            "attended": True,
            "maxViewers": 1,
            "productionReady": False,
            "broadRolloutReady": False,
            "multiViewerFanoutProven": False,
            "legalAcceptance": False,
        },
        "evidence": [
            {
                "type": name,
                "path": path,
                "sha256": VERIFIER.digest_bytes(raw),
                "source": source_entry(name, raw),
            }
            for path, raw in sorted(child_bytes.items())
            for name in [Path(path).stem]
        ],
    }
    if mutate_root:
        mutate_root(root)
    files = {"viewer-product-evidence.json": encode_json(root), **child_bytes, **(extra_files or {})}
    if zip_entry:
        files[zip_entry[0]] = zip_entry[1]
    return encode_zip(files)


class FakeClient:
    def __init__(self, archive=None):
        self.archive = archive or build_archive()
        with zipfile.ZipFile(io.BytesIO(self.archive)) as final_archive:
            self.source_children = {
                name: final_archive.read(f"evidence/{name}.json")
                for name in SOURCE_TYPES
                if f"evidence/{name}.json" in final_archive.namelist()
            }
        self.source_archives = {
            name: source_archive(name, raw) for name, raw in self.source_children.items()
        }
        self.activation_archive = activation_archive()
        self.run_missing = False
        self.artifact_missing = False
        self.artifact_digest = VERIFIER.digest_bytes(self.archive)
        self.run_conclusion = "success"
        self.run_updated_at = "2026-07-14T00:07:00Z"
        self.run_started_at = "2026-07-14T00:06:01Z"
        self.source_run_started_at = {name: "2026-07-14T00:00:00Z" for name in SOURCE_TYPES}
        self.source_run_updated_at = {name: "2026-07-14T00:06:00Z" for name in SOURCE_TYPES}
        self.artifact_expired = False
        self.source_run_missing = None

    def get_json(self, path):
        if path == f"/repos/{VERIFIER.EXPECTED_REPOSITORY}/actions/runs/{ACTIVATION_RUN_ID}":
            return {
                "id": ACTIVATION_RUN_ID,
                "status": "completed",
                "conclusion": "success",
                "event": "workflow_dispatch",
                "head_branch": "main",
                "head_sha": HEAD_SHA,
                "run_attempt": 1,
                "name": VERIFIER.EXPECTED_ACTIVATION_WORKFLOW_NAME,
                "path": VERIFIER.EXPECTED_ACTIVATION_WORKFLOW_PATH,
                "run_started_at": "2026-07-14T00:00:00Z",
                "updated_at": "2026-07-14T00:00:30Z",
            }
        if path == f"/repos/{VERIFIER.EXPECTED_REPOSITORY}/actions/runs/{ACTIVATION_RUN_ID}/artifacts?per_page=100":
            return {
                "total_count": 1,
                "artifacts": [{
                    "id": AUTHORIZATION_ARTIFACT_ID,
                    "name": f"faz22-view-only-pilot-protected-authorization-{ACTIVATION_RUN_ID}",
                    "expired": False,
                    "digest": VERIFIER.digest_bytes(self.activation_archive),
                    "created_at": "2026-07-14T00:00:20Z",
                    "updated_at": "2026-07-14T00:00:20Z",
                    "workflow_run": {"id": ACTIVATION_RUN_ID, "head_sha": HEAD_SHA},
                }],
            }
        if path == f"/repos/{VERIFIER.EXPECTED_REPOSITORY}/actions/runs/{RUN_ID}":
            if self.run_missing:
                raise VERIFIER.EvidenceError("GitHub API run returned HTTP 404")
            return {
                "id": RUN_ID,
                "status": "completed",
                "conclusion": self.run_conclusion,
                "event": "workflow_dispatch",
                "head_branch": "main",
                "head_sha": HEAD_SHA,
                "run_attempt": 1,
                "name": VERIFIER.EXPECTED_WORKFLOW_NAME,
                "path": VERIFIER.EXPECTED_WORKFLOW_PATH,
                "run_started_at": self.run_started_at,
                "updated_at": self.run_updated_at,
            }
        for name in SOURCE_TYPES:
            run_id = SOURCE_RUN_IDS[name]
            artifact_id = SOURCE_ARTIFACT_IDS[name]
            workflow_path, workflow_name = VERIFIER.EXPECTED_SOURCE_WORKFLOWS[name]
            if path == f"/repos/{VERIFIER.EXPECTED_REPOSITORY}/actions/runs/{run_id}":
                if self.source_run_missing == name:
                    raise VERIFIER.EvidenceError(f"{name} source run returned HTTP 404")
                return {
                    "id": run_id,
                    "status": "completed",
                    "conclusion": "success",
                    "event": "workflow_dispatch",
                    "head_branch": "main",
                    "head_sha": HEAD_SHA,
                    "run_attempt": 1,
                    "name": workflow_name,
                    "path": workflow_path,
                    "run_started_at": self.source_run_started_at[name],
                    "updated_at": self.source_run_updated_at[name],
                }
            if path == f"/repos/{VERIFIER.EXPECTED_REPOSITORY}/actions/runs/{run_id}/artifacts?per_page=100":
                archive = self.source_archives[name]
                return {
                    "total_count": 1,
                    "artifacts": [{
                        "id": artifact_id,
                        "name": f"faz22-6-view-only-viewer-{name}-evidence-{run_id}",
                        "expired": False,
                        "digest": VERIFIER.digest_bytes(archive),
                        "created_at": "2026-07-14T00:06:30Z",
                        "updated_at": "2026-07-14T00:06:30Z",
                        "workflow_run": {"id": run_id, "head_sha": HEAD_SHA},
                    }],
                }
        if path == f"/repos/{VERIFIER.EXPECTED_REPOSITORY}/actions/runs/{RUN_ID}/artifacts?per_page=100":
            artifacts = [] if self.artifact_missing else [{
                "id": 789,
                "name": f"faz22-6-view-only-viewer-product-evidence-{RUN_ID}",
                "expired": self.artifact_expired,
                "digest": self.artifact_digest,
                "created_at": "2026-07-14T00:06:30Z",
                "updated_at": "2026-07-14T00:06:30Z",
                "workflow_run": {"id": RUN_ID, "head_sha": HEAD_SHA},
            }]
            return {"total_count": len(artifacts), "artifacts": artifacts}
        raise AssertionError(f"unexpected JSON API path: {path}")

    def get_bytes(self, path):
        if path == f"/repos/{VERIFIER.EXPECTED_REPOSITORY}/actions/artifacts/{AUTHORIZATION_ARTIFACT_ID}/zip":
            return self.activation_archive
        if path == f"/repos/{VERIFIER.EXPECTED_REPOSITORY}/actions/artifacts/789/zip":
            return self.archive
        for name, artifact_id in SOURCE_ARTIFACT_IDS.items():
            if path == f"/repos/{VERIFIER.EXPECTED_REPOSITORY}/actions/artifacts/{artifact_id}/zip":
                return self.source_archives[name]
        raise AssertionError(f"unexpected artifact API path: {path}")


class ViewerProductEvidenceVerifierTest(unittest.TestCase):
    def verify(self, client=None, now=NOW):
        return VERIFIER.verify_product_evidence(
            client or FakeClient(), VERIFIER.EXPECTED_REPOSITORY, RUN_ID, now=now
        )

    def test_valid_provenance_bound_artifact_passes_with_digest_marker(self):
        result = self.verify()
        self.assertEqual("pass", result["status"])
        self.assertEqual(100, result["computed"]["renderedFrames"])
        self.assertEqual(0.0, result["computed"]["renderLossRate"])
        self.assertIn(VERIFIER.MARKER, result["marker"])
        self.assertIn(f"run_id: {RUN_ID}", result["marker"])
        self.assertIn(f"artifact_digest: {result['artifactDigest']}", result["marker"])
        self.assertIn(f"evidence_root_sha256: {result['evidenceRootSha256']}", result["marker"])
        self.assertNotIn("sessionId", result["marker"])
        self.assertNotIn("deviceId", result["marker"])

    def test_post_pilot_source_attestation_is_allowed_before_producer(self):
        archive = build_archive(
            mutate_root=lambda root: root.update({"generatedAt": "2026-07-14T00:08:02Z"})
        )
        client = FakeClient(archive)
        client.source_run_started_at["broker"] = "2026-07-14T00:07:00Z"
        client.source_run_updated_at["broker"] = "2026-07-14T00:08:00Z"
        client.run_started_at = "2026-07-14T00:08:01Z"
        client.run_updated_at = "2026-07-14T00:09:00Z"
        self.assertEqual("pass", self.verify(client)["status"])

    def test_source_attestation_24h_and_producer_order_boundaries(self):
        observed = datetime(2026, 7, 14, 0, 0, tzinfo=timezone.utc)
        VERIFIER.validate_source_attestation_timing(
            observed,
            datetime(2026, 7, 15, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 7, 15, 0, 0, 1, tzinfo=timezone.utc),
            "broker",
        )
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "attestation is stale"):
            VERIFIER.validate_source_attestation_timing(
                observed,
                datetime(2026, 7, 15, 0, 0, 1, tzinfo=timezone.utc),
                datetime(2026, 7, 15, 0, 0, 2, tzinfo=timezone.utc),
                "broker",
            )
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "before the producer"):
            VERIFIER.validate_source_attestation_timing(
                observed,
                datetime(2026, 7, 14, 1, 0, 1, tzinfo=timezone.utc),
                datetime(2026, 7, 14, 1, 0, tzinfo=timezone.utc),
                "broker",
            )

    def test_nonexistent_run_and_artifact_fail_closed(self):
        client = FakeClient()
        client.run_missing = True
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "404"):
            self.verify(client)
        client = FakeClient()
        client.artifact_missing = True
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "exactly one"):
            self.verify(client)

    def test_failed_run_and_expired_artifact_fail_closed(self):
        client = FakeClient()
        client.run_conclusion = "failure"
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "conclusion"):
            self.verify(client)
        client = FakeClient()
        client.artifact_expired = True
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "expired"):
            self.verify(client)

    def test_archive_digest_mismatch_fails_closed(self):
        client = FakeClient()
        client.artifact_digest = sha("a")
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "digest"):
            self.verify(client)

    def test_missing_or_tampered_source_artifact_fails_closed(self):
        client = FakeClient()
        client.source_run_missing = "browser"
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "browser source run returned HTTP 404"):
            self.verify(client)

        client = FakeClient()
        client.source_archives["browser"] = source_archive("browser", b'{}\n')
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "source artifact digest"):
            self.verify(client)

    def test_duplicate_source_run_is_rejected(self):
        def duplicate(root):
            by_type = {entry["type"]: entry for entry in root["evidence"]}
            by_type["broker"]["source"]["runId"] = by_type["browser"]["source"]["runId"]

        with self.assertRaisesRegex(VERIFIER.EvidenceError, "distinct source run"):
            self.verify(FakeClient(build_archive(mutate_root=duplicate)))

    def test_zip_slip_and_unexpected_file_fail_closed(self):
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "unsafe entry"):
            self.verify(FakeClient(build_archive(zip_entry=("../escape.json", b"{}"))))
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "file set mismatch"):
            self.verify(FakeClient(build_archive(extra_files={"claim.txt": b"pass"})))

    def test_unknown_root_field_is_rejected_by_strict_schema(self):
        archive = build_archive(mutate_root=lambda root: root.update({"callerClaim": "pass"}))
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "Additional properties"):
            self.verify(FakeClient(archive))

    def test_child_digest_tamper_fails_closed(self):
        archive = build_archive()
        with zipfile.ZipFile(io.BytesIO(archive)) as original:
            files = {info.filename: original.read(info) for info in original.infolist()}
        files["evidence/browser.json"] += b" "
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as changed:
            for name, raw in files.items():
                changed.writestr(name, raw)
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "child digest mismatch"):
            self.verify(FakeClient(output.getvalue()))

    def test_cross_session_child_binding_fails_closed(self):
        children = child_documents()
        children["audit"]["binding"]["sessionSha256"] = sha("a")
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "same-session binding"):
            self.verify(FakeClient(build_archive(children=children)))

    def test_activation_receipt_is_content_and_identity_bound(self):
        client = FakeClient()
        client.activation_archive += b"tamper"
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "authorization artifact digest"):
            self.verify(client)

        operator = child_documents()["operator"]["payload"]
        unauthorized_binding = binding()
        unauthorized_binding["operatorSha256"] = sha("a")
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "authorized operator binding"):
            VERIFIER.verify_activation_authorization(
                FakeClient(), operator, HEAD_SHA, unauthorized_binding,
                datetime(2026, 7, 14, 0, 1, tzinfo=timezone.utc),
                datetime(2026, 7, 14, 0, 6, tzinfo=timezone.utc),
            )

    def test_95_delivered_one_rendered_class_and_low_render_ratio_fail(self):
        children = child_documents()
        broker = children["broker"]["payload"]
        broker["states"] = {"captured": 200, "brokerReceived": 200, "viewerDelivered": 200, "viewerRendered": 100}
        broker["framesSentMetricDelta"] = 200
        children["audit"]["payload"]["framesDelivered"] = 200
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "loss-rate"):
            self.verify(FakeClient(build_archive(children=children)))

    def test_short_or_stale_pilot_fails_closed(self):
        short = build_archive(
            mutate_root=lambda root: root["pilot"].update({"startedAt": "2026-07-14T00:05:00Z"})
        )
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "pilot duration"):
            self.verify(FakeClient(short))
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "stale"):
            self.verify(FakeClient(), now=datetime(2026, 7, 16, tzinfo=timezone.utc))

    def test_root_pilot_must_match_browser_measured_window(self):
        archive = build_archive(
            mutate_root=lambda root: root["pilot"].update({"startedAt": "2026-07-14T00:00:59Z"})
        )
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "browser pilot start"):
            self.verify(FakeClient(archive))

    def test_d30_drift_and_duplicate_component_fail_closed(self):
        children = child_documents()
        children["d30"]["payload"]["images"][1]["component"] = "backend"
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "exactly one"):
            self.verify(FakeClient(build_archive(children=children)))
        children = child_documents()
        children["d30"]["payload"]["images"][0]["liveImageIdDigest"] = sha("f")
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "desired digest"):
            self.verify(FakeClient(build_archive(children=children)))

    def test_secret_or_raw_identifier_shape_fails_hygiene(self):
        children = child_documents()
        children["operator"]["payload"]["authorization"] = "Bearer abcdefghijklmnop"
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "schema invalid"):
            self.verify(FakeClient(build_archive(children=children)))


if __name__ == "__main__":
    unittest.main()
