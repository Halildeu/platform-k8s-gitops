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


def case_binding(session_char):
    value = binding()
    value["sessionSha256"] = sha(session_char)
    return value


def negative_payload():
    cases = {
        name: {
            "observedAt": "2026-07-14T00:05:00Z",
            "binding": case_binding("1"),
            "result": "fail-closed",
            "outcome": VERIFIER.NEGATIVE_CASE_CONTRACT[name].outcome,
            "requestAccepted": False,
            "deliveryContinued": False,
            "httpStatus": VERIFIER.NEGATIVE_CASE_CONTRACT[name].http_status,
            "evidenceSha256": sha(format(index, "x")),
        }
        for index, name in enumerate(VERIFIER.NEGATIVE_CASES)
    }
    payload = {
        "authorizationSha256": VERIFIER.digest_bytes(authorization_bytes()),
        "cases": cases,
    }
    payload["suiteSha256"] = VERIFIER.digest_json(payload)
    return payload


def termination_payload():
    specs = {
        "localAbort": ("local-abort", 700),
        "killOrRevoke": ("kill-or-revoke", 500),
        "ttlExpiry": ("ttl-expiry", 900),
        "heartbeatLoss": ("heartbeat-loss", 30_000),
        "indicatorLoss": ("indicator-loss", 800),
    }
    session_chars = ("5", "6", "7", "8", "9")
    evidence_chars = ("a", "b", "c", "d", "e")
    audit_chars = ("0", "5", "6", "7", "8")
    cases = {}
    for index, (name, (trigger, latency)) in enumerate(specs.items()):
        cases[name] = {
            "observedAt": "2026-07-14T00:05:00Z",
            "binding": case_binding(session_chars[index]),
            "result": "terminated",
            "trigger": trigger,
            "deliveryTerminated": True,
            "terminationLatencyMillis": latency,
            "evidenceSha256": sha(evidence_chars[index]),
            "viewStopAuditSha256": sha(audit_chars[index]),
        }
    payload = {
        "authorizationSha256": VERIFIER.digest_bytes(authorization_bytes()),
        "cases": cases,
    }
    payload["suiteSha256"] = VERIFIER.digest_json(payload)
    return payload


def matrix_attestation_files(evidence_type, document):
    files = {}
    payload = document["payload"]
    termination_ordinals = {name: index for index, name in enumerate(VERIFIER.TERMINATION_CASES)}
    for case_name, case in payload["cases"].items():
        common = {
            "schemaVersion": f"faz22.6.viewOnlyViewer{evidence_type.title()}CaseAttestation.v1",
            "caseName": case_name,
            "sourceRevision": document["sourceRevision"],
            "observedAt": case["observedAt"],
            "binding": case["binding"],
            "authorizationSha256": payload["authorizationSha256"],
            "runtimeSnapshotSha256": VERIFIER.digest_bytes(
                f"{evidence_type}:{case_name}:runtime".encode()
            ),
        }
        if evidence_type == "negative":
            contract = VERIFIER.NEGATIVE_CASE_CONTRACT[case_name]
            attestation = {
                **common,
                "request": {
                    "method": contract.method,
                    "targetClass": contract.target_class,
                    "credentialClass": contract.credential_class,
                },
                "result": {
                    "outcome": case["outcome"],
                    "requestAccepted": False,
                    "deliveryContinued": False,
                    "httpStatus": case["httpStatus"],
                },
                "auditEventSha256": VERIFIER.digest_bytes(
                    f"negative:{case_name}:audit".encode()
                ),
            }
        else:
            started = 1_752_451_500_000 + termination_ordinals[case_name] * 10_000
            attestation = {
                **common,
                "trigger": case["trigger"],
                "triggeredAtEpochMillis": started,
                "deliveryEndedAtEpochMillis": started + case["terminationLatencyMillis"],
                "result": {"deliveryTerminated": True},
                "viewStopAuditSha256": case["viewStopAuditSha256"],
                "productSignals": {
                    "viewerClosed": True,
                    "brokerSessionTerminal": True,
                    "agentEventObserved": True,
                    "viewStopAuditVerified": True,
                    **({
                        "endpointUserInitiated": True,
                        "consentLeaseRevoked": True,
                    } if case_name == "localAbort" else {}),
                },
            }
        raw = encode_json(attestation)
        case["evidenceSha256"] = VERIFIER.digest_bytes(raw)
        files[f"attestations/{evidence_type}/{case_name}.json"] = raw
    payload["suiteSha256"] = VERIFIER.digest_json({
        "authorizationSha256": payload["authorizationSha256"],
        "cases": payload["cases"],
    })
    return files


def child_documents():
    states = {"captured": 105, "brokerReceived": 105, "viewerDelivered": 100, "viewerRendered": 100}
    documents = {
        "browser": child(
            "browser",
            "browser-harness",
            {
                "pilotStartedAt": "2026-07-14T00:01:00Z",
                "pilotEndedAt": "2026-07-14T00:06:00Z",
                "imageElementRendered": True,
                "pixelCheckPassed": True,
                "inputChannelControlCount": 0,
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
            negative_payload(),
        ),
        "termination": child(
            "termination",
            "termination-harness",
            termination_payload(),
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
    matrix_attestation_files("negative", documents["negative"])
    matrix_attestation_files("termination", documents["termination"])
    return documents


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
    files = {f"evidence/{name}.json": raw}
    if name in {"negative", "termination"}:
        document = json.loads(raw)
        files.update(matrix_attestation_files(name, document))
        regenerated = encode_json(document)
        if regenerated != raw:
            raise AssertionError(f"{name} fixture attestation digest drift")
    return encode_zip(files)


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

    def validate_matrices(self, children):
        VERIFIER.validate_negative_and_termination(
            children["negative"]["payload"],
            children["termination"]["payload"],
            children["operator"]["payload"],
            binding(),
            datetime(2026, 7, 14, 0, 1, tzinfo=timezone.utc),
            datetime(2026, 7, 14, 0, 20, tzinfo=timezone.utc),
            {
                "negative": datetime(2026, 7, 14, 0, 5, tzinfo=timezone.utc),
                "termination": datetime(2026, 7, 14, 0, 5, tzinfo=timezone.utc),
            },
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

    def test_boolean_only_negative_claim_is_rejected(self):
        children = child_documents()
        children["negative"]["payload"]["cases"]["noAuth"] = True
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "schema invalid"):
            VERIFIER.validate_schema(children["negative"], VERIFIER.CHILD_SCHEMA, "negative child")

    def test_matrix_suite_digest_and_authorization_are_content_bound(self):
        children = child_documents()
        children["negative"]["payload"]["cases"]["noAuth"]["httpStatus"] = 403
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "negative suite digest"):
            self.validate_matrices(children)

        children = child_documents()
        children["termination"]["payload"]["authorizationSha256"] = sha("f")
        payload = children["termination"]["payload"]
        payload["suiteSha256"] = VERIFIER.digest_json({
            "authorizationSha256": payload["authorizationSha256"],
            "cases": payload["cases"],
        })
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "protected authorization digest"):
            self.validate_matrices(children)

    def test_termination_cases_require_isolated_sessions_and_latency_slo(self):
        children = child_documents()
        cases = children["termination"]["payload"]["cases"]
        cases["indicatorLoss"]["binding"]["sessionSha256"] = cases["localAbort"]["binding"]["sessionSha256"]
        payload = children["termination"]["payload"]
        payload["suiteSha256"] = VERIFIER.digest_json({
            "authorizationSha256": payload["authorizationSha256"], "cases": cases,
        })
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "distinct isolated sessions"):
            self.validate_matrices(children)

        children = child_documents()
        children["termination"]["payload"]["cases"]["killOrRevoke"]["terminationLatencyMillis"] = 1001
        payload = children["termination"]["payload"]
        payload["suiteSha256"] = VERIFIER.digest_json({
            "authorizationSha256": payload["authorizationSha256"], "cases": payload["cases"],
        })
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "exceeded the 1000ms"):
            self.validate_matrices(children)

    def test_matrix_case_attestation_bytes_are_independently_digest_bound(self):
        document = child_documents()["negative"]
        raw_child = encode_json(document)
        files = VERIFIER.safe_archive_files(source_archive("negative", raw_child))
        path = "attestations/negative/noAuth.json"
        files[path] += b" "
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "attestation digest"):
            VERIFIER.validate_matrix_source_attestations("negative", files, raw_child)

    def test_local_abort_must_also_prove_attended_consent_withdrawal(self):
        document = child_documents()["termination"]
        raw_child = encode_json(document)
        files = VERIFIER.safe_archive_files(source_archive("termination", raw_child))
        path = "attestations/termination/localAbort.json"
        attestation = json.loads(files[path])
        del attestation["productSignals"]["consentLeaseRevoked"]
        files[path] = encode_json(attestation)
        document["payload"]["cases"]["localAbort"]["evidenceSha256"] = \
            VERIFIER.digest_bytes(files[path])
        document["payload"]["suiteSha256"] = VERIFIER.digest_json({
            "authorizationSha256": document["payload"]["authorizationSha256"],
            "cases": document["payload"]["cases"],
        })
        raw_child = encode_json(document)
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "localAbort product signals"):
            VERIFIER.validate_matrix_source_attestations("termination", files, raw_child)

    def test_matrix_cases_must_fit_protected_authorization_expiry(self):
        children = child_documents()
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "authorized matrix window"):
            VERIFIER.validate_negative_and_termination(
                children["negative"]["payload"], children["termination"]["payload"],
                children["operator"]["payload"], binding(),
                datetime(2026, 7, 14, 0, 1, tzinfo=timezone.utc),
                datetime(2026, 7, 14, 0, 4, 59, tzinfo=timezone.utc),
                {
                    "negative": datetime(2026, 7, 14, 0, 5, tzinfo=timezone.utc),
                    "termination": datetime(2026, 7, 14, 0, 5, tzinfo=timezone.utc),
                },
            )

    def test_negative_case_name_cannot_be_relabelled_with_another_outcome(self):
        self.assertEqual("unauthorized", VERIFIER.NEGATIVE_CASE_CONTRACT["wrongRole"].outcome)
        children = child_documents()
        payload = children["negative"]["payload"]
        payload["cases"]["wrongRole"]["outcome"] = "not-found"
        payload["suiteSha256"] = VERIFIER.digest_json({
            "authorizationSha256": payload["authorizationSha256"], "cases": payload["cases"],
        })
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "wrongRole outcome"):
            self.validate_matrices(children)

    def test_negative_case_must_use_the_real_product_channel_contract(self):
        # Wrong-role authentication must be 401, while signed-permit expiry is
        # exercised through the acceptance-only POST agent-permit channel.
        self.assertEqual(401, VERIFIER.NEGATIVE_CASE_CONTRACT["wrongRole"].http_status)
        self.assertEqual("POST", VERIFIER.NEGATIVE_CASE_CONTRACT["expired"].method)
        document = child_documents()["negative"]
        raw_child = encode_json(document)
        files = VERIFIER.safe_archive_files(source_archive("negative", raw_child))

        wrong_role_path = "attestations/negative/wrongRole.json"
        wrong_role = json.loads(files[wrong_role_path])
        wrong_role["result"]["httpStatus"] = 404
        files[wrong_role_path] = encode_json(wrong_role)
        document["payload"]["cases"]["wrongRole"]["httpStatus"] = 404
        document["payload"]["cases"]["wrongRole"]["evidenceSha256"] = \
            VERIFIER.digest_bytes(files[wrong_role_path])
        document["payload"]["suiteSha256"] = VERIFIER.digest_json({
            "authorizationSha256": document["payload"]["authorizationSha256"],
            "cases": document["payload"]["cases"],
        })
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "wrongRole HTTP status"):
            VERIFIER.validate_matrix_source_attestations(
                "negative", files, encode_json(document),
            )

        document = child_documents()["negative"]
        raw_child = encode_json(document)
        files = VERIFIER.safe_archive_files(source_archive("negative", raw_child))
        expired_path = "attestations/negative/expired.json"
        expired = json.loads(files[expired_path])
        expired["request"].update({
            "method": "GET",
            "targetClass": "viewer-product-channel",
        })
        files[expired_path] = encode_json(expired)
        document["payload"]["cases"]["expired"]["evidenceSha256"] = \
            VERIFIER.digest_bytes(files[expired_path])
        document["payload"]["suiteSha256"] = VERIFIER.digest_json({
            "authorizationSha256": document["payload"]["authorizationSha256"],
            "cases": document["payload"]["cases"],
        })
        with self.assertRaisesRegex(VERIFIER.EvidenceError, "expired method"):
            VERIFIER.validate_matrix_source_attestations(
                "negative", files, encode_json(document),
            )


if __name__ == "__main__":
    unittest.main()
