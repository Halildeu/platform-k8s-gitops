#!/usr/bin/env python3

import base64
import hashlib
import json
import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COLLECTOR = ROOT / "scripts/deploy/collect-faz25-p5-frontend-lineage.sh"
SOURCE_SHA = "7c8cef6547d4408cc705f9c6afae49b67ed80d1a"
DIGEST = "sha256:d3a4b4e7f3fa752a3247eb49d0b1c842fd5be2463ce71e436b8454f341f3db38"
DEPLOYMENT_UID = "11111111-1111-4111-8111-111111111111"
REPLICASET_UID = "22222222-2222-4222-8222-222222222222"
POD_UID = "33333333-3333-4333-8333-333333333333"
KUBE_SYSTEM_UID = "55555555-5555-4555-8555-555555555555"
CLUSTER_SERVER = "https://127.0.0.1:6445"
CLUSTER_CA = b"faz25-test-ca"


class CollectorTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp.name)
        self.fixture_path = self.temp_path / "fixtures.json"
        self.mock_kubectl = self.temp_path / "kubectl"
        self.mock_curl = self.temp_path / "curl"
        self.kubectl_calls = self.temp_path / "kubectl-calls.jsonl"
        self.report = self.temp_path / "lineage.json"
        self._write_mocks()

    def tearDown(self):
        self.temp.cleanup()

    def _write_mocks(self):
        self.mock_kubectl.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import base64
                import json
                import os
                import sys

                fixtures = json.load(open(os.environ["FIXTURE_PATH"]))
                args = sys.argv[1:]
                with open(os.environ["KUBECTL_CALLS"], "a") as calls:
                    calls.write(json.dumps(args) + "\\n")
                if args == ["config", "current-context"]:
                    print("k3d-prod")
                elif args[:4] == ["--context", "k3d-test", "config", "view"] and "--raw" not in args:
                    print("https://127.0.0.1:6445", end="")
                elif args[:4] == ["--context", "k3d-test", "config", "view"] and "--raw" in args:
                    print(base64.b64encode(b"faz25-test-ca").decode(), end="")
                elif args[:5] == ["--context", "k3d-test", "get", "namespace", "kube-system"]:
                    print("55555555-5555-4555-8555-555555555555", end="")
                elif args[:2] == ["--context", "k3d-test"] and "deployment" in args:
                    print(json.dumps(fixtures["deployment"]))
                elif args[:2] == ["--context", "k3d-test"] and "replicasets" in args:
                    print(json.dumps(fixtures["replicasets"]))
                elif args[:2] == ["--context", "k3d-test"] and "pods" in args:
                    print(json.dumps(fixtures["pods"]))
                else:
                    raise SystemExit(f"unexpected kubectl args: {args}")
                """
            )
        )
        self.mock_curl.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env python3
                import json
                import os
                import sys
                url = sys.argv[-1]
                if "/artifacts" in url:
                    print(json.dumps({{
                        "artifacts": [{{
                            "id": 8309092914,
                            "name": "Halildeu~platform-web~R1TBO1.dockerbuild",
                            "digest": os.environ.get(
                                "MOCK_ARTIFACT_DIGEST",
                                "sha256:4086a69a90e6557aadbd909bb6cbc83e339b7feac9254a8ffbe79f5b19558d6e"
                            ),
                            "size_in_bytes": 107153,
                            "expired": False
                        }}]
                    }}))
                else:
                    print(json.dumps({{
                        "id": 29328643364,
                        "status": "completed",
                        "conclusion": "success",
                        "event": "push",
                        "head_branch": "main",
                        "head_sha": "{SOURCE_SHA}",
                        "path": ".github/workflows/ci-web-image-push.yml"
                    }}))
                """
            )
        )
        self.mock_kubectl.chmod(0o755)
        self.mock_curl.chmod(0o755)

    def _fixtures(self, pod_owner_uid=REPLICASET_UID):
        image = f"ghcr.io/halildeu/platform-web-frontend-testai:sha-7c8cef6@{DIGEST}"
        return {
            "deployment": {
                "metadata": {
                    "uid": DEPLOYMENT_UID,
                    "resourceVersion": "101",
                    "generation": 9,
                    "annotations": {"deployment.kubernetes.io/revision": "12"},
                },
                "spec": {
                    "replicas": 1,
                    "selector": {"matchLabels": {"app.kubernetes.io/name": "frontend"}},
                    "template": {"spec": {"containers": [{"name": "frontend", "image": image}]}},
                },
                "status": {"observedGeneration": 9, "availableReplicas": 1},
            },
            "replicasets": {
                "items": [
                    {
                        "metadata": {
                            "name": "frontend-abc123",
                            "uid": REPLICASET_UID,
                            "annotations": {"deployment.kubernetes.io/revision": "12"},
                            "ownerReferences": [{"kind": "Deployment", "uid": DEPLOYMENT_UID}],
                        },
                        "spec": {
                            "replicas": 1,
                            "template": {
                                "spec": {"containers": [{"name": "frontend", "image": image}]}
                            },
                        },
                        "status": {"readyReplicas": 1},
                    }
                ]
            },
            "pods": {
                "items": [
                    {
                        "metadata": {
                            "uid": POD_UID,
                            "deletionTimestamp": None,
                            "ownerReferences": [{"kind": "ReplicaSet", "uid": pod_owner_uid}],
                        },
                        "status": {
                            "phase": "Running",
                            "conditions": [{"type": "Ready", "status": "True"}],
                            "containerStatuses": [
                                {
                                    "name": "frontend",
                                    "ready": True,
                                    "imageID": (
                                        "docker-pullable://ghcr.io/halildeu/"
                                        f"platform-web-frontend-testai@{DIGEST}"
                                    ),
                                }
                            ],
                        },
                    }
                ]
            },
        }

    def _run(self, fixtures, extra_env=None):
        self.fixture_path.write_text(json.dumps(fixtures))
        env = os.environ | {
            "FIXTURE_PATH": str(self.fixture_path),
            "KUBECTL_CALLS": str(self.kubectl_calls),
            "KUBECTL_BIN": str(self.mock_kubectl),
            "CURL_BIN": str(self.mock_curl),
            "REPORT_PATH": str(self.report),
            "PHASE": "pre",
            "EXPECTED_CONTEXT": "k3d-test",
            "EXPECTED_SOURCE_SHA": SOURCE_SHA,
            "EXPECTED_IMAGE_DIGEST": DIGEST,
            "EXPECTED_BUILD_RUN_ID": "29328643364",
            "EXPECTED_CLUSTER_SERVER_SHA256": hashlib.sha256(
                CLUSTER_SERVER.encode()
            ).hexdigest(),
            "EXPECTED_CLUSTER_CA_SHA256": hashlib.sha256(CLUSTER_CA).hexdigest(),
            "EXPECTED_KUBE_SYSTEM_UID": KUBE_SYSTEM_UID,
        }
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            ["bash", str(COLLECTOR)],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_emits_strict_owner_bound_lineage(self):
        result = self._run(self._fixtures())
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(self.report.read_text())
        self.assertEqual(payload["schemaVersion"], "faz25-p5-frontend-lineage-v1")
        self.assertEqual(payload["deployment"]["uid"], DEPLOYMENT_UID)
        self.assertEqual(payload["replicaSet"]["uid"], REPLICASET_UID)
        self.assertEqual(payload["pods"]["uids"], [POD_UID])
        self.assertEqual(payload["lineage"]["observedDigest"], DIGEST)
        self.assertEqual(payload["lineage"]["buildArtifactId"], "8309092914")
        self.assertEqual(payload["cluster"]["kubeSystemNamespaceUid"], KUBE_SYSTEM_UID)
        self.assertEqual(stat.S_IMODE(self.report.stat().st_mode), 0o600)

    def test_ignores_current_context_and_pins_every_cluster_read(self):
        result = self._run(self._fixtures())
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [
            json.loads(line)
            for line in self.kubectl_calls.read_text().splitlines()
        ]
        self.assertNotIn(["config", "current-context"], calls)
        self.assertEqual(len(calls), 6)
        self.assertTrue(all(call[:2] == ["--context", "k3d-test"] for call in calls))
        self.assertEqual(
            [(call[2:4], "--raw" in call) for call in calls[:2]],
            [(["config", "view"], False), (["config", "view"], True)],
        )
        self.assertEqual(
            [call[2:] for call in calls[2:]],
            [
                ["get", "namespace", "kube-system", "-o", "jsonpath={.metadata.uid}"],
                ["-n", "platform-test", "get", "deployment", "frontend", "-o", "json"],
                ["-n", "platform-test", "get", "replicasets", "-l", "app.kubernetes.io/name=frontend", "-o", "json"],
                ["-n", "platform-test", "get", "pods", "-l", "app.kubernetes.io/name=frontend", "-o", "json"],
            ],
        )

    def test_rejects_non_test_context_before_any_kubectl_read(self):
        result = self._run(self._fixtures(), {"EXPECTED_CONTEXT": "k3d-prod"})
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.kubectl_calls.exists())
        self.assertFalse(self.report.exists())

    def test_rejects_pod_not_owned_by_active_replicaset(self):
        result = self._run(self._fixtures("44444444-4444-4444-8444-444444444444"))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.report.exists())

    def test_rejects_wrong_cluster_identity(self):
        result = self._run(
            self._fixtures(),
            {"EXPECTED_CLUSTER_SERVER_SHA256": "0" * 64},
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.report.exists())

    def test_rejects_build_artifact_digest_drift(self):
        result = self._run(
            self._fixtures(),
            {"MOCK_ARTIFACT_DIGEST": "sha256:" + "0" * 64},
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.report.exists())


if __name__ == "__main__":
    unittest.main()
