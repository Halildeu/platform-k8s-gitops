from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
ACTIVATION = (
    ROOT
    / "kustomize/overlays/test/activation/cross-ai-deployment-protection-observe"
)


def load_yaml(name: str) -> dict[str, object]:
    value = yaml.safe_load((ACTIVATION / name).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"{name} is not one YAML object")
    return value


class PackagingContractTests(unittest.TestCase):
    def test_dockerfile_is_pinned_hash_locked_and_non_root(self) -> None:
        dockerfile = (
            ROOT / "scripts/github_apps/cross_ai_deployment_policy/Dockerfile"
        ).read_text(encoding="utf-8")
        self.assertRegex(
            dockerfile,
            r"python:3[.]12[.]11-slim-bookworm@sha256:[a-f0-9]{64}",
        )
        self.assertIn("--require-hashes", dockerfile)
        self.assertIn("--only-binary=:all:", dockerfile)
        self.assertIn("USER 10001:10001", dockerfile)
        self.assertNotIn("requirements.txt", dockerfile)

    def test_receive_only_deployment_cannot_enforce_or_call_github(self) -> None:
        deployment = load_yaml("deployment.yaml")
        pod_spec = deployment["spec"]["template"]["spec"]  # type: ignore[index]
        container = pod_spec["containers"][0]  # type: ignore[index]
        args = container["args"]
        self.assertEqual(args[args.index("--mode") + 1], "observe")
        forbidden = {
            "--github-app-id",
            "--github-app-key-file",
            "--policy-file",
            "--trust-root-file",
            "--revocations-file",
        }
        self.assertTrue(forbidden.isdisjoint(args))
        self.assertEqual(deployment["spec"]["replicas"], 1)  # type: ignore[index]
        self.assertEqual(deployment["spec"]["strategy"]["type"], "Recreate")  # type: ignore[index]
        self.assertFalse(pod_spec["automountServiceAccountToken"])
        self.assertTrue(container["securityContext"]["readOnlyRootFilesystem"])
        self.assertEqual(container["securityContext"]["capabilities"]["drop"], ["ALL"])
        self.assertRegex(
            container["image"],
            r"@sha256:0{64}$",
            "activation must retain an impossible image sentinel before publication",
        )

    def test_secret_is_vault_referenced_and_never_in_desired_state(self) -> None:
        external = load_yaml("externalsecret.yaml")
        self.assertEqual(external["kind"], "ExternalSecret")
        remote = external["spec"]["data"][0]["remoteRef"]  # type: ignore[index]
        self.assertEqual(
            remote,
            {
                "key": "kv/platform/cross-ai-deployment-protection-test",
                "property": "github_webhook_secret_current",
            },
        )
        for path in ACTIVATION.glob("*.yaml"):
            self.assertNotRegex(
                path.read_text(encoding="utf-8"),
                re.compile(r"BEGIN (?:RSA )?PRIVATE KEY|github_webhook_secret_current:\s+[^\n]+"),
            )

    def test_public_surface_is_exact_hmac_webhook_path_only(self) -> None:
        ingress = load_yaml("ingress.yaml")
        metadata = ingress["metadata"]  # type: ignore[index]
        self.assertEqual(
            metadata["annotations"]["nginx.ingress.kubernetes.io/rewrite-target"],  # type: ignore[index]
            "/webhooks/github",
        )
        path = ingress["spec"]["rules"][0]["http"]["paths"][0]  # type: ignore[index]
        self.assertEqual(path["pathType"], "Exact")
        self.assertEqual(
            path["path"], "/github-apps/cross-ai-deployment-protection"
        )
        policy = load_yaml("netpol.yaml")
        self.assertEqual(policy["spec"]["egress"], [])  # type: ignore[index]

    def test_app_registration_templates_preserve_two_app_split(self) -> None:
        evaluator = json.loads(
            (ROOT / "config/github-apps/cross-ai-protection-evaluator-app.example.json")
            .read_text(encoding="utf-8")
        )
        dispatcher = json.loads(
            (ROOT / "config/github-apps/cross-ai-intent-dispatcher-app.example.json")
            .read_text(encoding="utf-8")
        )
        self.assertEqual(
            evaluator["default_permissions"],
            {
                "actions": "read",
                "contents": "read",
                "deployments": "write",
                "metadata": "read",
            },
        )
        self.assertEqual(evaluator["default_events"], ["deployment_protection_rule"])
        self.assertEqual(
            dispatcher["default_permissions"],
            {"actions": "write", "contents": "write", "metadata": "read"},
        )
        self.assertEqual(dispatcher["default_events"], [])
        self.assertFalse(dispatcher["hook_attributes"]["active"])


if __name__ == "__main__":
    unittest.main()
