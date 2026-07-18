from __future__ import annotations

import copy
import json
import subprocess
import unittest
from pathlib import Path

import yaml

from scripts.github_apps.cross_ai_deployment_policy.policy import load_policy
from scripts.github_apps.cross_ai_deployment_policy.workflow import inspect_workflow


ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "config/github-apps/cross-ai-deployment-policy.example.json"
ACTION_COMMIT = "bfb2a880f4fc26c727a02fda8ad5643cc03412d6"
ZERO_TRUST_PIN = "sha256:" + ("0" * 64)


class ProtectedWorkflowSourceContractTest(unittest.TestCase):
    def test_gate_triggers_for_every_protected_runtime_authority_file(self) -> None:
        workflow = yaml.load(
            (
                ROOT / ".github/workflows/gate-cross-ai-deployment-protection.yml"
            ).read_text(encoding="utf-8"),
            Loader=yaml.BaseLoader,
        )
        required_paths = {
            ".github/workflows/gate-cross-ai-deployment-protection.yml",
            "scripts/faz22-remote-ops/extract-cross-ai-browser-runtime.py",
            "scripts/faz22-remote-ops/run-cross-ai-protected-view-only-stage.sh",
            "scripts/faz22-remote-ops/verify-watchdog-network-policy.jq",
            "scripts/faz22-remote-ops/view-only-viewer-pilot-watchdog.template.yaml",
        }
        for event in ("pull_request", "push"):
            configured_paths = set(workflow["on"][event]["paths"])
            self.assertTrue(
                required_paths <= configured_paths,
                f"{event} does not trigger the fail-closed gate for every authority file",
            )

    def test_all_signed_stage_paths_are_no_input_and_statically_reproducible(
        self,
    ) -> None:
        policy = load_policy(POLICY)
        inspections = []
        for stage in policy.stages.values():
            path = ROOT / stage.workflow_path
            raw = path.read_bytes()
            inspection = inspect_workflow(
                raw,
                stage_policy=stage,
                environment=policy.environment,
                expected_bootstrap_url=policy.runner_bootstrap_url,
            )
            inspections.append(inspection)
            self.assertIn(f"@{ACTION_COMMIT}", raw.decode("utf-8"))
            self.assertIn(ZERO_TRUST_PIN, raw.decode("utf-8"))
        self.assertEqual(
            len({item.concurrency_group_sha256 for item in inspections}),
            1,
        )

    def test_release_artifacts_are_absent_until_owner_transit_bootstrap(self) -> None:
        for name in (
            "cross-ai-deployment-policy.json",
            "cross-ai-deployment-trust-root.json",
            "cross-ai-deployment-revocations.json",
        ):
            self.assertFalse(
                (ROOT / "config/github-apps" / name).exists(),
                f"{name} must enter through the separate trust-root release",
            )

    def test_stage_runner_opens_bootstrap_as_private_owned_regular_file(self) -> None:
        script = (
            ROOT / "scripts/faz22-remote-ops/run-cross-ai-protected-view-only-stage.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("flags |= os.O_NOFOLLOW", script)
        self.assertIn("metadata.st_uid != os.getuid()", script)
        self.assertIn("stat.S_IMODE(metadata.st_mode) != 0o600", script)
        self.assertIn("gateway route index 28 is not clean", script)
        self.assertIn("watchdog expiry differs from signed grant", script)
        self.assertIn("apply failure compensation verified", script)
        self.assertNotIn("npm --prefix", script)
        self.assertIn("extract-cross-ai-browser-runtime.py", script)
        self.assertIn("runtimeBundleSha256", script)
        self.assertIn(
            "/opt/acik/cross-ai/browser-runtime/playwright-1.60.0-linux-x64.tar",
            script,
        )
        self.assertGreaterEqual(script.count("verify_watchdog_active"), 4)
        self.assertIn("(.status.active // 0) == 1", script)
        self.assertIn("(.status.failed // 0) == 0", script)
        self.assertIn('.status.phase == "Running"', script)
        self.assertIn('.type == "Ready" and .status == "True"', script)
        self.assertIn('.state.running.startedAt | type == "string"', script)
        self.assertIn("auth can-i $permission", script)
        self.assertIn("get rolebinding faz22-view-only-pilot-watchdog -o json", script)
        self.assertIn(
            "get networkpolicy allow-faz22-view-only-watchdog-kubernetes-api -o json",
            script,
        )
        self.assertLess(
            script.index(
                '"networkpolicy/allow-faz22-view-only-watchdog-kubernetes-api"'
            ),
            script.index("delete job/faz22-view-only-pilot-watchdog"),
        )

    def test_watchdog_network_policy_filter_rejects_authority_expansion(self) -> None:
        policy_filter = (
            ROOT / "scripts/faz22-remote-ops/verify-watchdog-network-policy.jq"
        )
        valid = {
            "metadata": {"deletionTimestamp": None},
            "spec": {
                "podSelector": {
                    "matchLabels": {
                        "app.kubernetes.io/component": "safety-controller",
                        "app.kubernetes.io/name": "faz22-view-only-pilot-watchdog",
                    }
                },
                "policyTypes": ["Egress"],
                "egress": [
                    {
                        "to": [{"ipBlock": {"cidr": "10.45.0.1/32"}}],
                        "ports": [{"protocol": "TCP", "port": 443}],
                    },
                    {
                        "to": [{"ipBlock": {"cidr": "172.19.0.0/16"}}],
                        "ports": [{"protocol": "TCP", "port": 6443}],
                    },
                ],
            },
        }

        def accepts(value: dict) -> bool:
            return (
                subprocess.run(
                    ["jq", "-e", "-f", str(policy_filter)],
                    input=json.dumps(value),
                    text=True,
                    capture_output=True,
                    check=False,
                ).returncode
                == 0
            )

        self.assertTrue(accepts(valid))
        mutations = []
        extra_selector = copy.deepcopy(valid)
        extra_selector["spec"]["podSelector"]["matchExpressions"] = [
            {"key": "never-present", "operator": "Exists"}
        ]
        mutations.append(extra_selector)
        extra_destination = copy.deepcopy(valid)
        extra_destination["spec"]["egress"][0]["to"].append(
            {"ipBlock": {"cidr": "0.0.0.0/0"}}
        )
        mutations.append(extra_destination)
        extra_port = copy.deepcopy(valid)
        extra_port["spec"]["egress"][0]["ports"].append(
            {"protocol": "TCP", "port": 4444}
        )
        mutations.append(extra_port)
        except_range = copy.deepcopy(valid)
        except_range["spec"]["egress"][0]["to"][0]["ipBlock"]["except"] = [
            "10.45.0.2/32"
        ]
        mutations.append(except_range)
        for mutated in mutations:
            self.assertFalse(accepts(mutated))

    def test_watchdog_readiness_proves_live_api_access(self) -> None:
        template = (
            ROOT
            / "scripts/faz22-remote-ops/view-only-viewer-pilot-watchdog.template.yaml"
        ).read_text(encoding="utf-8")
        self.assertIn("readinessProbe:", template)
        self.assertIn("kubernetes.default.svc/api/v1/namespaces/", template)
        self.assertIn("configmaps/api-gateway-config", template)
        self.assertIn("Authorization: Bearer $token", template)

    def test_canonical_outcome_is_last_fallible_action_step(self) -> None:
        actions = {
            "protected-apply": "apply",
            "protected-browser-evidence": "browser",
            "protected-rollback": "rollback",
        }
        for directory, label in actions.items():
            raw = (ROOT / ".github/actions" / directory / "action.yml").read_text(
                encoding="utf-8"
            )
            upload = f"Upload canonical {label} outcome evidence"
            self.assertIn("id: cleanup", raw)
            self.assertLess(raw.index("id: cleanup"), raw.index(upload))
            self.assertNotIn(
                "Remove private bootstrap response", raw[raw.index(upload) :]
            )
            self.assertIn("steps.cleanup.outcome == 'success'", raw)

        browser = (
            ROOT / ".github/actions/protected-browser-evidence/action.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("id: product_evidence", browser)
        self.assertIn("steps.product_evidence.outcome == 'success'", browser)


if __name__ == "__main__":
    unittest.main()
