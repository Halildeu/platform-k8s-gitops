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
TEST_ROOT = ROOT / "kustomize/overlays/test/kustomization.yaml"
SERVICES_CATALOG = ROOT / "docs/operations/services.yaml"
ESO_POLICY = ROOT / "bootstrap/vault-policies/common/eso-runtime.hcl"
BOOTSTRAP_WRITER_POLICY = ROOT / "bootstrap/vault-policies/common/bootstrap-writer.hcl"
VAULT_PATCH_WRAPPER = ROOT / "scripts/ops/platform-ops-vault-patch.sh"
VAULT_RECONCILER = ROOT / "scripts/ops/vault-policy-reconcile.sh"
BOOTSTRAP_WRITER_VERIFY = (
    ROOT / "bootstrap/vault-policies/test/bootstrap-writer-verify.sh"
)
LIVE_OBSERVER_WORKFLOW = ROOT / ".github/workflows/verify-cross-ai-observer.yml"


def load_yaml(name: str) -> dict[str, object]:
    value = yaml.safe_load((ACTIVATION / name).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"{name} is not one YAML object")
    return value


class PackagingContractTests(unittest.TestCase):
    def test_live_probe_separates_workload_and_argocd_hub_contexts(self) -> None:
        workflow = LIVE_OBSERVER_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("K8S_CONTEXT: k3d-test", workflow)
        self.assertIn("ARGOCD_CONTEXT: k3d-prod", workflow)
        self.assertEqual(
            workflow.count('kubectl --context "$ARGOCD_CONTEXT" -n argocd'),
            6,
        )
        self.assertNotIn(
            'kubectl --context "$K8S_CONTEXT" -n argocd',
            workflow,
        )

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

    def test_container_smoke_uses_valid_fixture_and_retains_failure_logs(self) -> None:
        workflow = (
            ROOT
            / ".github/workflows/build-cross-ai-deployment-protection-image.yml"
        ).read_text(encoding="utf-8")
        fixture = "synthetic-contract-secret-for-ci-only-0001"
        self.assertGreaterEqual(len(fixture.encode("utf-8")), 32)
        self.assertIn(fixture, workflow)
        self.assertIn('chmod 444 "$RUNNER_TEMP/github-webhook-current"', workflow)
        self.assertNotIn("docker run --detach --rm", workflow)
        self.assertIn(
            "docker logs cross-ai-deployment-protection-contract 2>&1 || true",
            workflow,
        )
        self.assertIn(
            "docker rm --force cross-ai-deployment-protection-contract",
            workflow,
        )

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
        secret_volume = next(
            volume for volume in pod_spec["volumes"] if volume["name"] == "webhook-secret"
        )
        self.assertEqual(secret_volume["secret"]["defaultMode"], 0o440)
        self.assertEqual(
            container["image"],
            "ghcr.io/halildeu/platform-k8s-gitops-cross-ai-deployment-protection"
            "@sha256:0a79f6facfadb29daaeb096f5491e07fd8b01eabfbbb4db7d896f5663f9e9285",
        )

        test_root = yaml.safe_load(TEST_ROOT.read_text(encoding="utf-8"))
        self.assertIn(
            "activation/cross-ai-deployment-protection-observe",
            test_root["resources"],
        )

        catalog = yaml.safe_load(SERVICES_CATALOG.read_text(encoding="utf-8"))
        service = next(
            item
            for item in catalog["services"]
            if item["name"] == "cross-ai-deployment-protection"
        )
        self.assertEqual(service["environments"], {"test": "enabled", "prod": "deferred"})
        self.assertEqual(service["route_external"], True)
        self.assertEqual(service["probe_contract"], "exempt")

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

    def test_eso_policy_grants_only_read_on_dedicated_test_path(self) -> None:
        policy = ESO_POLICY.read_text(encoding="utf-8")
        match = re.search(
            r'path "kv/data/platform/cross-ai-deployment-protection-test"\s*'
            r'\{\s*capabilities\s*=\s*\[([^]]+)]\s*}',
            policy,
        )
        self.assertIsNotNone(
            match,
            "ExternalSecret path must be allowlisted before receive-only activation",
        )
        self.assertEqual(match.group(1).strip(), '"read"')  # type: ignore[union-attr]

    def test_bootstrap_writer_and_wrapper_allow_only_audited_test_seed_path(self) -> None:
        policy = BOOTSTRAP_WRITER_POLICY.read_text(encoding="utf-8")
        match = re.search(
            r'path "kv/data/platform/cross-ai-deployment-protection-test"\s*'
            r'\{\s*capabilities\s*=\s*\[([^]]+)]\s*}',
            policy,
        )
        self.assertIsNotNone(match, "test seed path must be explicitly allowlisted")
        capabilities = {
            value.strip().strip('"')
            for value in match.group(1).split(",")  # type: ignore[union-attr]
        }
        self.assertEqual(capabilities, {"create", "update", "read"})
        self.assertNotIn("delete", capabilities)

        wrapper = VAULT_PATCH_WRAPPER.read_text(encoding="utf-8")
        self.assertRegex(
            wrapper,
            r"cross-ai-deployment-protection-test\|"
            r"meeting-analysis-capability\|openfga\)\s*\n\s*KV_PATH=",
        )
        self.assertIn("--field-from-stdin", wrapper)
        self.assertIn("--field-from-file", wrapper)
        self.assertIn("--cleanup-field-files", wrapper)
        self.assertIn("--cleanup-secret-id-file", wrapper)
        self.assertIn('CURRENT_VERSION=0', wrapper)
        self.assertIn('"options": {"cas":', wrapper)
        self.assertIn(
            "accepts only github_webhook_secret_current from stdin or "
            "github_app_private_key_pem from file",
            wrapper,
        )
        self.assertIn('private_key = b"PRIVATE" + b" KEY"', wrapper)

        for path in (VAULT_PATCH_WRAPPER, VAULT_RECONCILER, BOOTSTRAP_WRITER_VERIFY):
            script = path.read_text(encoding="utf-8")
            self.assertNotIn('-H "X-Vault-Token: $TOKEN"', script)
            self.assertNotIn('-d "{\\"role_id\\":\\"$ROLE_ID\\"', script)
        self.assertNotIn('-d "$PATCHED_DATA"', wrapper)
        self.assertIn("--data-binary @-", wrapper)

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
        self.assertEqual(evaluator["name"], "Acik Cross-AI Deploy Protection")
        self.assertLessEqual(
            len(evaluator["name"]),
            34,
            "GitHub App registration rejects names longer than 34 characters",
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
