#!/usr/bin/env python3
"""Tests for the Faz 24 WG-B+ I6 MASQ metadata collector."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[2]
COLLECTOR_PATH = REPO_ROOT / "scripts" / "faz24" / "collect-wg-bplus-i6-masq-evidence.py"
VERIFIER_PATH = REPO_ROOT / "scripts" / "faz24" / "verify-wg-bplus-i6-masq-evidence.py"

spec = importlib.util.spec_from_file_location("collect_wg_bplus_i6_masq_evidence", COLLECTOR_PATH)
collector = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = collector
spec.loader.exec_module(collector)


class FakeHostRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def __call__(self, argv: list[str], timeout: int = 12):
        self.commands.append(argv)
        command, args = self._normalize(argv)

        if command == "wg" and args == ["show", "interfaces"]:
            return collector.CommandResult(0, "wg0\n", "")

        if command == "ip" and args[:2] == ["route", "get"]:
            return collector.CommandResult(0, "10.99.0.2 dev wg0 src 10.99.0.1\n", "")

        if command in {"iptables", "iptables-nft", "iptables-legacy", "iptables-save"}:
            return collector.CommandResult(
                0,
                "-A POSTROUTING -s 10.42.0.0/16 -o wg0 -j MASQUERADE\n",
                "",
            )

        if command == "systemctl":
            if args[:1] == ["is-active"]:
                return collector.CommandResult(0, "active\n", "")
            if args[:1] == ["is-enabled"]:
                return collector.CommandResult(0, "enabled\n", "")
            if args[:1] == ["show"]:
                return collector.CommandResult(
                    0,
                    "ActiveState=active\n"
                    "UnitFileState=enabled\n"
                    "ExecStart={ path=/usr/local/sbin/k3d-wg-masq }\n"
                    "ExecStop={ path=/usr/local/sbin/k3d-wg-masq-rollback }\n",
                    "",
                )

        if command == "kubectl" and "get" in args and "pods" in args:
            return collector.CommandResult(
                0,
                json.dumps(
                    {
                        "items": [
                            {
                                "metadata": {"name": "audio-gateway-0"},
                                "status": {"phase": "Running"},
                            }
                        ]
                    }
                ),
                "",
            )

        if command == "kubectl" and "exec" in args:
            return collector.CommandResult(0, "404", "")

        return collector.CommandResult(127, "", f"unexpected command: {argv}")

    def _normalize(self, argv: list[str]) -> tuple[str, list[str]]:
        normalized = list(argv)
        if normalized[:2] == ["sudo", "-n"]:
            normalized = normalized[2:]
        if normalized and Path(normalized[0]).name == "nsenter":
            marker = normalized.index("--")
            normalized = normalized[marker + 1 :]
        return Path(normalized[0]).name, normalized[1:]


class WgBplusI6MasqEvidenceCollectorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.original_runner = collector.run_command
        self.original_hostname = collector.socket.gethostname

    def tearDown(self) -> None:
        collector.run_command = self.original_runner
        collector.socket.gethostname = self.original_hostname

    def args(self, protected_path: str = "") -> SimpleNamespace:
        return SimpleNamespace(
            output=Path("/tmp/unused.json"),
            kube_context="k3d-test",
            namespace="platform-test",
            pod_cidr="10.42.0.0/16",
            service_cidr="",
            wg_interface="auto",
            platform_ai_host="10.99.0.2",
            platform_ai_port=8200,
            probe_path="/",
            systemd_unit="k3d-wg-masq.service",
            drift_timer="k3d-wg-masq.timer",
            drift_interval_minutes=5,
            rollback_tested_ref="rollback/k3d-wg-masq-dry-run.json",
            protected_evidence_path=protected_path,
            github_run_id="12345",
        )

    def run_verifier(self, data: dict) -> subprocess.CompletedProcess[str]:
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as tmp:
            json.dump(data, tmp)
            tmp.flush()
            return subprocess.run(
                [sys.executable, str(VERIFIER_PATH), tmp.name],
                text=True,
                capture_output=True,
                check=False,
            )

    def test_operator_protected_path_evidence_can_pass_verifier(self):
        collector.run_command = FakeHostRunner()
        collector.socket.gethostname = lambda: "staging-sw"

        evidence = collector.build_evidence(
            self.args("operator://staging-sw/protected/faz24/i6/20260625T060000Z")
        )

        self.assertEqual("pass", evidence["status"])
        self.assertEqual(
            "operator://staging-sw/protected/faz24/i6/20260625T060000Z",
            evidence["protectedEvidencePath"],
        )
        self.assertTrue(all(check["status"] == "pass" for check in evidence["checks"]))
        self.assertFalse(evidence["redaction"]["rawCommandOutputIncluded"])

        result = self.run_verifier(evidence)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("Faz24 WG-B+ I6 MASQ evidence: PASS", result.stdout)

    def test_default_protected_path_uses_github_run_id(self):
        evidence_path = collector.protected_evidence_path(self.args())

        self.assertEqual(
            "github-actions://Halildeu/platform-k8s-gitops/actions/runs/12345",
            evidence_path,
        )


if __name__ == "__main__":
    unittest.main()
