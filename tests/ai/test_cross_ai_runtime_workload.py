from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.ai.cross_ai_runtime_workload import KubernetesWorkloadVerifier
from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError


class StaticPodTransport:
    def __init__(self, pod) -> None:
        self.pod = pod
        self.calls = []

    def get(self, *, path, token):
        self.calls.append((path, token))
        return json.dumps(self.pod).encode()


class KubernetesWorkloadVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.token = Path(self.directory.name) / "api-token"
        self.token.write_text("synthetic.jwt." + ("a" * 120), encoding="ascii")
        self.token.chmod(0o400)
        self.pod_uid = "90000000-0000-4000-8000-000000000001"
        self.digest = "sha256:" + ("b" * 64)
        self.pod = {
            "metadata": {
                "name": "runtime-attestor-0",
                "namespace": "cross-ai",
                "uid": self.pod_uid,
                "deletionTimestamp": None,
            },
            "spec": {"serviceAccountName": "provider-review-issuer"},
            "status": {
                "phase": "Running",
                "containerStatuses": [
                    {
                        "name": "runtime-attestor",
                        "ready": True,
                        "imageID": (
                            "docker-pullable://ghcr.io/halildeu/runtime@"
                            + self.digest
                        ),
                        "state": {"running": {"startedAt": "2026-07-20T00:00:00Z"}},
                    }
                ],
            },
        }

    def tearDown(self) -> None:
        self.directory.cleanup()

    def verifier(self, pod=None):
        return KubernetesWorkloadVerifier(
            namespace="cross-ai",
            pod_name="runtime-attestor-0",
            pod_uid=self.pod_uid,
            service_account="provider-review-issuer",
            container_name="runtime-attestor",
            api_token_file=self.token,
            transport=StaticPodTransport(pod or self.pod),
        )

    def test_measures_exact_running_service_account_and_image_digest(self) -> None:
        measurement = self.verifier().measure()
        self.assertEqual(
            "spiffe://testai.acik.com/ns/cross-ai/sa/provider-review-issuer",
            measurement.workload_identity,
        )
        self.assertEqual(self.digest, measurement.image_digest)
        self.assertEqual(self.pod_uid, measurement.pod_uid)

    def test_rejects_wrong_image_unready_deleting_or_wrong_service_account(
        self,
    ) -> None:
        mutations = [
            lambda pod: pod["status"]["containerStatuses"][0].update(
                {"imageID": "docker-pullable://example.invalid/x:mutable"}
            ),
            lambda pod: pod["status"]["containerStatuses"][0].update(
                {"ready": False}
            ),
            lambda pod: pod["metadata"].update(
                {"deletionTimestamp": "2026-07-20T00:01:00Z"}
            ),
            lambda pod: pod["spec"].update({"serviceAccountName": "default"}),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                pod = json.loads(json.dumps(self.pod))
                mutate(pod)
                with self.assertRaisesRegex(
                    PolicyError,
                    "KUBERNETES_WORKLOAD_INVALID",
                ):
                    self.verifier(pod).measure()

    def test_rejects_symlink_or_world_readable_projected_token(self) -> None:
        self.token.chmod(0o404)
        with self.assertRaisesRegex(
            PolicyError,
            "KUBERNETES_WORKLOAD_TOKEN_INVALID",
        ):
            self.verifier().measure()
        self.token.chmod(0o400)
        alias = Path(self.directory.name) / "alias"
        alias.symlink_to(self.token)
        verifier = KubernetesWorkloadVerifier(
            namespace="cross-ai",
            pod_name="runtime-attestor-0",
            pod_uid=self.pod_uid,
            service_account="provider-review-issuer",
            container_name="runtime-attestor",
            api_token_file=alias,
            transport=StaticPodTransport(self.pod),
        )
        with self.assertRaisesRegex(
            PolicyError,
            "KUBERNETES_WORKLOAD_TOKEN_UNAVAILABLE",
        ):
            verifier.measure()


if __name__ == "__main__":
    unittest.main()
