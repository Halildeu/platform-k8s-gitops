import hashlib
import importlib.util
import io
import json
import sys
import unittest
import zipfile
from pathlib import Path

from tests.faz22_remote_ops import test_faz22_6_viewer_product_evidence_verifier as fixtures


MODULE_PATH = Path(__file__).parents[2] / "scripts/faz22-remote-ops/produce-view-only-viewer-d30-evidence.py"
SPEC = importlib.util.spec_from_file_location("viewer_d30_producer", MODULE_PATH)
PRODUCER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.path.insert(0, str(MODULE_PATH.parent))
sys.modules[SPEC.name] = PRODUCER
SPEC.loader.exec_module(PRODUCER)

RUNTIME_ARTIFACT_ID = 700001


def runtime_archive(mismatch=False, malformed_alias=False):
    backend = "a" * 64
    web_desired = "b" * 64
    web_live = "c" * 64 if mismatch else web_desired
    snapshot = {
        "schemaVersion": "faz22.6-viewer-d30-raw-v2",
        "capturedAt": "2026-07-14T00:05:00Z",
        "images": [
            {
                "component": "backend",
                "deployment": "endpoint-admin-remote-bridge-device-key",
                "desiredImage": f"ghcr.io/example/backend@sha256:{backend}",
                "liveImageId": f"ghcr.io/example/backend@sha256:{backend}",
                "runtimeBinding": None,
            },
            {
                "component": "web",
                "deployment": "frontend",
                "desiredImage": f"ghcr.io/example/web:sha-test@sha256:{web_desired}",
                "liveImageId": f"ghcr.io/example/web@sha256:{web_live}",
                "runtimeBinding": (
                    {
                        "kind": "cri-repo-digest-alias-v1",
                        "expectedRepoDigest": (
                            f"ghcr.io/halildeu/platform-web-frontend-testai@sha256:{web_desired}"
                        ),
                        "observedRepoDigest": f"ghcr.io/example/web@sha256:{web_live}",
                        "contentId": f"sha256:{'d' * 64}",
                    }
                    if mismatch else None
                ),
            },
        ],
    }
    if malformed_alias:
        snapshot["images"][1]["runtimeBinding"]["contentId"] = "sha256:bad"
    files = {
        "snapshots/d30-snapshot.json": (json.dumps(snapshot, sort_keys=True) + "\n").encode(),
        "snapshots/metrics-before.prom": b"remote_access_bridge_viewer_started_total 0.0\n",
        "snapshots/metrics-after.prom": b"remote_access_bridge_viewer_started_total 1.0\n",
        "snapshots/frame-flow-summary.json": b'{"schemaVersion":"faz22.6-viewer-frame-flow-raw-v1"}\n',
        "snapshots/audit-summary.json": b'{"schemaVersion":"faz22.6-viewer-audit-raw-v1"}\n',
    }
    files["SHA256SUMS"] = "".join(
        f"{hashlib.sha256(raw).hexdigest()}  {name}\n" for name, raw in sorted(files.items())
    ).encode("ascii")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, raw in files.items():
            archive.writestr(name, raw)
    return output.getvalue()


class RuntimeClient(fixtures.FakeClient):
    def __init__(self, mismatch=False, malformed_alias=False):
        super().__init__()
        self.runtime_archive = runtime_archive(mismatch, malformed_alias)

    def get_json(self, path):
        browser_run = fixtures.SOURCE_RUN_IDS["browser"]
        if path == f"/repos/{fixtures.VERIFIER.EXPECTED_REPOSITORY}/actions/runs/{browser_run}/artifacts?per_page=100":
            value = super().get_json(path)
            value["artifacts"].append({
                "id": RUNTIME_ARTIFACT_ID,
                "name": f"faz22-6-view-only-viewer-runtime-snapshots-{browser_run}",
                "expired": False,
                "digest": fixtures.VERIFIER.digest_bytes(self.runtime_archive),
                "workflow_run": {"id": browser_run, "head_sha": fixtures.HEAD_SHA},
            })
            return value
        return super().get_json(path)

    def get_bytes(self, path):
        if path == f"/repos/{fixtures.VERIFIER.EXPECTED_REPOSITORY}/actions/artifacts/{RUNTIME_ARTIFACT_ID}/zip":
            return self.runtime_archive
        return super().get_bytes(path)


class ViewerD30EvidenceProducerTest(unittest.TestCase):
    def test_produces_digest_equal_d30_child(self):
        child = PRODUCER.produce(
            RuntimeClient(), fixtures.VERIFIER.EXPECTED_REPOSITORY,
            fixtures.SOURCE_RUN_IDS["browser"], fixtures.HEAD_SHA,
        )
        self.assertEqual("d30", child["evidenceType"])
        self.assertEqual(["backend", "web"], [item["component"] for item in child["payload"]["images"]])
        self.assertEqual(
            ["direct-imageid-digest-v1", "direct-imageid-digest-v1"],
            [item["verificationMode"] for item in child["payload"]["images"]],
        )

    def test_accepts_uniquely_verified_web_cri_alias(self):
        child = PRODUCER.produce(
            RuntimeClient(mismatch=True), fixtures.VERIFIER.EXPECTED_REPOSITORY,
            fixtures.SOURCE_RUN_IDS["browser"], fixtures.HEAD_SHA,
        )
        web = next(item for item in child["payload"]["images"] if item["component"] == "web")
        self.assertEqual("cri-repo-digest-alias-v1", web["verificationMode"])
        self.assertEqual(f"sha256:{'d' * 64}", web["runtimeContentId"])

    def test_rejects_malformed_web_cri_alias(self):
        with self.assertRaisesRegex(PRODUCER.common.VERIFIER.EvidenceError, "content ID"):
            PRODUCER.produce(
                RuntimeClient(mismatch=True, malformed_alias=True),
                fixtures.VERIFIER.EXPECTED_REPOSITORY,
                fixtures.SOURCE_RUN_IDS["browser"], fixtures.HEAD_SHA,
            )


if __name__ == "__main__":
    unittest.main()
