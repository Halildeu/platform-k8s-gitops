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
TERMINATION_RUN_IDS = {
    name: 610000 + index
    for index, name in enumerate(PRODUCER.common.VERIFIER.TERMINATION_CASES, start=1)
}
TERMINATION_ARTIFACT_IDS = {
    name: 710000 + index
    for index, name in enumerate(PRODUCER.common.VERIFIER.TERMINATION_CASES, start=1)
}


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


def termination_case_files(case_name, mutate=None):
    document = fixtures.child_documents()["termination"]
    matrix_files = fixtures.matrix_attestation_files("termination", document)
    observation = next(
        line for line in matrix_files["observations/termination.jsonl"].splitlines(keepends=True)
        if json.loads(line)["caseName"] == case_name
    )
    audit = next(
        line for line in matrix_files["audit/termination.jsonl"].splitlines(keepends=True)
        if json.loads(line)["caseName"] == case_name
    )
    files = {
        f"observations/{case_name}.jsonl": observation,
        f"audit/{case_name}.jsonl": audit,
    }
    if mutate:
        mutate(files)
    context = {
        "schemaVersion": PRODUCER.TERMINATION_CASE_CONTEXT_SCHEMA,
        "evidenceType": "termination",
        "caseName": case_name,
        "sourceRevision": fixtures.HEAD_SHA,
        "collectedAt": "2026-07-14T00:05:00Z",
        "authorizationSha256": document["payload"]["authorizationSha256"],
        "rootBinding": fixtures.binding(),
        "observationSha256": fixtures.VERIFIER.digest_bytes(files[f"observations/{case_name}.jsonl"]),
        "auditSha256": fixtures.VERIFIER.digest_bytes(files[f"audit/{case_name}.jsonl"]),
    }
    files["context.json"] = fixtures.encode_json(context)
    return files


class MatrixCollectorClient(fixtures.FakeClient):
    def __init__(self, evidence_type="negative", mutate=None, head_sha=fixtures.HEAD_SHA,
                 workflow_path=None):
        super().__init__()
        self.evidence_type = evidence_type
        self.collector_archive = archive(collector_files(evidence_type, mutate))
        self.head_sha = head_sha
        self.workflow_path = workflow_path or PRODUCER.COLLECTOR_WORKFLOWS[evidence_type][0]

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
                "name": PRODUCER.COLLECTOR_WORKFLOWS[self.evidence_type][1],
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


class TerminationCollectorClient(fixtures.FakeClient):
    def __init__(self, mutate_case=None, mutate=None):
        super().__init__()
        self.archives = {
            case_name: archive(termination_case_files(
                case_name, mutate if case_name == mutate_case else None,
            ))
            for case_name in PRODUCER.common.VERIFIER.TERMINATION_CASES
        }

    def get_json(self, path):
        repository = fixtures.VERIFIER.EXPECTED_REPOSITORY
        for case_name, run_id in TERMINATION_RUN_IDS.items():
            if path == f"/repos/{repository}/actions/runs/{run_id}":
                return {
                    "id": run_id, "status": "completed", "conclusion": "success",
                    "event": "workflow_dispatch", "head_branch": "main",
                    "head_sha": fixtures.HEAD_SHA, "run_attempt": 1,
                    "name": PRODUCER.COLLECTOR_WORKFLOWS["termination"][1],
                    "path": PRODUCER.COLLECTOR_WORKFLOWS["termination"][0],
                    "run_started_at": "2026-07-14T00:00:00Z",
                    "updated_at": "2026-07-14T00:05:30Z",
                }
            if path == f"/repos/{repository}/actions/runs/{run_id}/artifacts?per_page=100":
                raw = self.archives[case_name]
                return {"total_count": 1, "artifacts": [{
                    "id": TERMINATION_ARTIFACT_IDS[case_name],
                    "name": f"faz22-6-view-only-viewer-termination-collector-{case_name}-{run_id}",
                    "expired": False, "digest": fixtures.VERIFIER.digest_bytes(raw),
                    "workflow_run": {"id": run_id, "head_sha": fixtures.HEAD_SHA},
                }]}
        return super().get_json(path)

    def get_bytes(self, path):
        repository = fixtures.VERIFIER.EXPECTED_REPOSITORY
        for case_name, artifact_id in TERMINATION_ARTIFACT_IDS.items():
            if path == f"/repos/{repository}/actions/artifacts/{artifact_id}/zip":
                return self.archives[case_name]
        return super().get_bytes(path)


class ViewerMatrixEvidenceProducerTest(unittest.TestCase):
    def produce(self, evidence_type, client=None):
        if evidence_type == "termination":
            return PRODUCER.produce_termination(
                client or TerminationCollectorClient(),
                fixtures.VERIFIER.EXPECTED_REPOSITORY,
                TERMINATION_RUN_IDS, fixtures.HEAD_SHA,
            )
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
            files["observations/localAbort.jsonl"] = fixtures.mutate_jsonl_case(
                files["observations/localAbort.jsonl"], "localAbort",
                lambda value: value["terminal"].pop("consentLeaseRevoked"),
            )

        with self.assertRaisesRegex(
            PRODUCER.common.VERIFIER.EvidenceError,
            "localAbort terminal runtime signals",
        ):
            self.produce("termination", TerminationCollectorClient("localAbort", mutate))

    def test_termination_aggregation_rejects_reused_run_and_context_drift(self):
        reused = dict(TERMINATION_RUN_IDS)
        reused["indicatorLoss"] = reused["localAbort"]
        with self.assertRaisesRegex(
            PRODUCER.common.VERIFIER.EvidenceError, "collector runs must be distinct",
        ):
            PRODUCER.produce_termination(
                TerminationCollectorClient(), fixtures.VERIFIER.EXPECTED_REPOSITORY,
                reused, fixtures.HEAD_SHA,
            )

        client = TerminationCollectorClient()
        files = termination_case_files("ttlExpiry")
        context = json.loads(files["context.json"])
        context["observationSha256"] = "sha256:" + "f" * 64
        files["context.json"] = fixtures.encode_json(context)
        client.archives["ttlExpiry"] = archive(files)
        with self.assertRaisesRegex(
            PRODUCER.common.VERIFIER.EvidenceError, "observation digest",
        ):
            self.produce("termination", client)

        client = TerminationCollectorClient()
        files = termination_case_files("heartbeatLoss")
        context = json.loads(files["context.json"])
        context["collectedAt"] = "2026-07-14T03:00:00Z"
        files["context.json"] = fixtures.encode_json(context)
        client.archives["heartbeatLoss"] = archive(files)
        with self.assertRaisesRegex(
            PRODUCER.common.VERIFIER.EvidenceError, "context is not fresh",
        ):
            self.produce("termination", client)


if __name__ == "__main__":
    unittest.main()
