import importlib.util
import io
import json
import sys
import unittest
import zipfile
from pathlib import Path

from tests.faz22_remote_ops import test_faz22_6_viewer_product_evidence_verifier as fixtures


MODULE_PATH = Path(__file__).parents[2] / "scripts/faz22-remote-ops/produce-view-only-viewer-matrix-evidence.py"
SPEC = importlib.util.spec_from_file_location("viewer_matrix_producer", MODULE_PATH)
PRODUCER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.path.insert(0, str(MODULE_PATH.parent))
sys.modules[SPEC.name] = PRODUCER
SPEC.loader.exec_module(PRODUCER)

COLLECTOR_RUN_ID = 600001
COLLECTOR_ARTIFACT_ID = 700003


def archive(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, raw in files.items():
            bundle.writestr(name, raw)
    return output.getvalue()


def collector_files(evidence_type, mutate=None):
    document = fixtures.child_documents()[evidence_type]
    matrix_files = fixtures.matrix_attestation_files(evidence_type, document)
    observations_path = f"observations/{evidence_type}.jsonl"
    files = {observations_path: matrix_files[observations_path]}
    if evidence_type == "termination":
        files["audit/termination.jsonl"] = matrix_files["audit/termination.jsonl"]
    if mutate:
        mutate(files)
    context = {
        "schemaVersion": PRODUCER.CONTEXT_SCHEMA,
        "evidenceType": evidence_type,
        "sourceRevision": fixtures.HEAD_SHA,
        "collectedAt": "2026-07-14T00:05:00Z",
        "authorizationSha256": document["payload"]["authorizationSha256"],
        "rootBinding": fixtures.binding(),
        "observationsSha256": fixtures.VERIFIER.digest_bytes(files[observations_path]),
        "auditSha256": (
            fixtures.VERIFIER.digest_bytes(files["audit/termination.jsonl"])
            if evidence_type == "termination" else None
        ),
    }
    files["context.json"] = fixtures.encode_json(context)
    return files


class MatrixCollectorClient(fixtures.FakeClient):
    def __init__(self, evidence_type="negative", mutate=None, head_sha=fixtures.HEAD_SHA,
                 workflow_path=PRODUCER.COLLECTOR_WORKFLOW_PATH):
        super().__init__()
        self.evidence_type = evidence_type
        self.collector_archive = archive(collector_files(evidence_type, mutate))
        self.head_sha = head_sha
        self.workflow_path = workflow_path

    def get_json(self, path):
        repository = fixtures.VERIFIER.EXPECTED_REPOSITORY
        if path == f"/repos/{repository}/actions/runs/{COLLECTOR_RUN_ID}":
            return {
                "id": COLLECTOR_RUN_ID,
                "status": "completed",
                "conclusion": "success",
                "event": "workflow_dispatch",
                "head_branch": "main",
                "head_sha": self.head_sha,
                "run_attempt": 1,
                "name": PRODUCER.COLLECTOR_WORKFLOW_NAME,
                "path": self.workflow_path,
                "run_started_at": "2026-07-14T00:00:00Z",
                "updated_at": "2026-07-14T00:05:30Z",
            }
        if path == f"/repos/{repository}/actions/runs/{COLLECTOR_RUN_ID}/artifacts?per_page=100":
            return {
                "total_count": 1,
                "artifacts": [{
                    "id": COLLECTOR_ARTIFACT_ID,
                    "name": (
                        "faz22-6-view-only-viewer-matrix-collector-"
                        f"{self.evidence_type}-{COLLECTOR_RUN_ID}"
                    ),
                    "expired": False,
                    "digest": fixtures.VERIFIER.digest_bytes(self.collector_archive),
                    "workflow_run": {"id": COLLECTOR_RUN_ID, "head_sha": self.head_sha},
                }],
            }
        return super().get_json(path)

    def get_bytes(self, path):
        repository = fixtures.VERIFIER.EXPECTED_REPOSITORY
        if path == f"/repos/{repository}/actions/artifacts/{COLLECTOR_ARTIFACT_ID}/zip":
            return self.collector_archive
        return super().get_bytes(path)


class ViewerMatrixEvidenceProducerTest(unittest.TestCase):
    def produce(self, evidence_type, client=None):
        return PRODUCER.produce(
            client or MatrixCollectorClient(evidence_type),
            fixtures.VERIFIER.EXPECTED_REPOSITORY,
            COLLECTOR_RUN_ID, fixtures.HEAD_SHA, evidence_type,
        )

    def test_produces_negative_source_envelope(self):
        files = self.produce("negative")
        self.assertEqual(11, len(files))
        self.assertEqual(fixtures.VERIFIER.source_artifact_files("negative"), set(files))
        child = json.loads(files["evidence/negative.json"])
        self.assertEqual("negative", child["evidenceType"])
        self.assertEqual(
            "operator-session-open-channel",
            json.loads(files["attestations/negative/wrongDevice.json"])["request"]["targetClass"],
        )
        wrong_device = json.loads(files["attestations/negative/wrongDevice.json"])
        self.assertEqual("POST", wrong_device["request"]["method"])
        self.assertEqual("/internal/remote-bridge/operator/sessions",
                         wrong_device["request"]["pathTemplate"])
        self.assertNotEqual(PRODUCER.common.VERIFIER.digest_bytes(b""),
                            wrong_device["request"]["bodySha256"])
        self.assertEqual(fixtures.binding()["operatorSha256"],
                         wrong_device["request"]["subjectSha256"])
        fixtures.VERIFIER.validate_matrix_source_attestations(
            "negative", files, files["evidence/negative.json"],
        )

    def test_produces_termination_source_envelope(self):
        files = self.produce("termination")
        self.assertEqual(8, len(files))
        self.assertEqual(fixtures.VERIFIER.source_artifact_files("termination"), set(files))
        local_abort = json.loads(files["attestations/termination/localAbort.json"])
        self.assertTrue(local_abort["productSignals"]["consentLeaseRevoked"])
        fixtures.VERIFIER.validate_matrix_source_attestations(
            "termination", files, files["evidence/termination.json"],
        )

    def test_rejects_collector_from_wrong_workflow_or_revision(self):
        with self.assertRaisesRegex(PRODUCER.common.VERIFIER.EvidenceError, "run path"):
            self.produce("negative", MatrixCollectorClient("negative", workflow_path="wrong.yml"))
        with self.assertRaisesRegex(PRODUCER.common.VERIFIER.EvidenceError, "head SHA"):
            self.produce("negative", MatrixCollectorClient("negative", head_sha="f" * 40))

    def test_rejects_context_digest_not_matching_observation_bytes(self):
        client = MatrixCollectorClient("negative")
        files = collector_files("negative")
        context = json.loads(files["context.json"])
        context["observationsSha256"] = "sha256:" + "f" * 64
        files["context.json"] = fixtures.encode_json(context)
        client.collector_archive = archive(files)
        with self.assertRaisesRegex(PRODUCER.common.VERIFIER.EvidenceError, "observations digest"):
            self.produce("negative", client)

    def test_rejects_local_abort_without_digest_bound_consent_withdrawal(self):
        def mutate(files):
            files["observations/termination.jsonl"] = fixtures.mutate_jsonl_case(
                files["observations/termination.jsonl"], "localAbort",
                lambda value: value["terminal"].pop("consentLeaseRevoked"),
            )

        with self.assertRaisesRegex(
            PRODUCER.common.VERIFIER.EvidenceError,
            "localAbort terminal runtime signals",
        ):
            self.produce("termination", MatrixCollectorClient("termination", mutate=mutate))


if __name__ == "__main__":
    unittest.main()
