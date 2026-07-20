from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path

from scripts.ai.cross_ai_runtime_workload import (
    KubernetesWorkloadVerifier,
    pod_security_projection_sha256,
)
from scripts.github_apps.cross_ai_deployment_policy.canonical import sha256_digest
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
        self.pod_uid = "90000000-0000-4000-8000-000000000001"
        self.digest = "sha256:" + ("b" * 64)
        self.command = ["python", "-m", "scripts.ai.run_cross_ai_runtime_attestor"]
        self.args = ["--authority-file", "/app/config/authority.json"]
        self.security_context = {
            "allowPrivilegeEscalation": False,
            "capabilities": {"drop": ["ALL"]},
            "readOnlyRootFilesystem": True,
            "runAsNonRoot": True,
            "runAsUser": 10002,
            "seccompProfile": {"type": "RuntimeDefault"},
        }
        self._write_token(self.pod_uid)
        self.pod = {
            "metadata": {
                "name": "runtime-attestor-0",
                "namespace": "cross-ai",
                "uid": self.pod_uid,
                "deletionTimestamp": None,
            },
            "spec": {
                "serviceAccountName": "provider-review-issuer",
                "automountServiceAccountToken": False,
                "containers": [
                    {
                        "name": "runtime-attestor",
                        "image": "ghcr.io/halildeu/runtime@" + self.digest,
                        "command": self.command,
                        "args": self.args,
                        "securityContext": self.security_context,
                    }
                ],
            },
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
        self.pod_security_projection_sha256 = pod_security_projection_sha256(
            self.pod["spec"]
        )

    def tearDown(self) -> None:
        self.directory.cleanup()

    def _write_token(self, pod_uid: str) -> None:
        if self.token.exists():
            self.token.chmod(0o600)
        encode = lambda value: base64.urlsafe_b64encode(  # noqa: E731
            json.dumps(value, separators=(",", ":")).encode()
        ).decode().rstrip("=")
        claims = {
            "aud": ["https://kubernetes.default.svc.cluster.local"],
            "sub": "system:serviceaccount:cross-ai:provider-review-issuer",
            "kubernetes.io": {
                "namespace": "cross-ai",
                "pod": {"name": "runtime-attestor-0", "uid": pod_uid},
                "serviceaccount": {
                    "name": "provider-review-issuer",
                    "uid": "91000000-0000-4000-8000-000000000001",
                },
            },
        }
        self.token.write_text(
            f"{encode({'alg': 'RS256'})}.{encode(claims)}." + ("a" * 86),
            encoding="ascii",
        )
        self.token.chmod(0o400)

    def verifier(self, pod=None):
        return KubernetesWorkloadVerifier(
            namespace="cross-ai",
            pod_name="runtime-attestor-0",
            pod_uid=self.pod_uid,
            service_account="provider-review-issuer",
            container_name="runtime-attestor",
            expected_image_digest=self.digest,
            expected_command=self.command,
            expected_args_sha256=sha256_digest(self.args),
            expected_security_context_sha256=sha256_digest(self.security_context),
            expected_pod_security_projection_sha256=(
                self.pod_security_projection_sha256
            ),
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
            lambda pod: pod["spec"]["containers"][0].update({"command": ["sh"]}),
            lambda pod: pod["spec"]["containers"][0]["securityContext"].update(
                {"allowPrivilegeEscalation": True}
            ),
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
            expected_image_digest=self.digest,
            expected_command=self.command,
            expected_args_sha256=sha256_digest(self.args),
            expected_security_context_sha256=sha256_digest(self.security_context),
            expected_pod_security_projection_sha256=(
                self.pod_security_projection_sha256
            ),
            api_token_file=alias,
            transport=StaticPodTransport(self.pod),
        )
        with self.assertRaisesRegex(
            PolicyError,
            "KUBERNETES_WORKLOAD_TOKEN_UNAVAILABLE",
        ):
            verifier.measure()

    def test_rejects_token_bound_to_another_pod(self) -> None:
        self._write_token("90000000-0000-4000-8000-000000000099")
        with self.assertRaisesRegex(
            PolicyError,
            "KUBERNETES_WORKLOAD_TOKEN_BINDING_MISMATCH",
        ):
            self.verifier().measure()

    def test_rejects_unpinned_pod_execution_surfaces(self) -> None:
        mutations = [
            lambda pod: pod["spec"]["containers"][0].update(
                {"env": [{"name": "PYTHONPATH", "value": "/host"}]}
            ),
            lambda pod: pod["spec"]["containers"][0].update(
                {"envFrom": [{"secretRef": {"name": "attacker"}}]}
            ),
            lambda pod: pod["spec"]["containers"][0].update(
                {"volumeMounts": [{"name": "host", "mountPath": "/app"}]}
            ),
            lambda pod: pod["spec"].update(
                {"volumes": [{"name": "host", "hostPath": {"path": "/tmp"}}]}
            ),
            lambda pod: pod["spec"]["containers"].append(
                {"name": "sidecar", "image": "example.invalid/sidecar:latest"}
            ),
            lambda pod: pod["spec"].update(
                {"initContainers": [{"name": "init", "image": "busybox"}]}
            ),
            lambda pod: pod["spec"].update({"hostNetwork": True}),
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


if __name__ == "__main__":
    unittest.main()
