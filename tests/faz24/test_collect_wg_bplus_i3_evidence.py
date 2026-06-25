#!/usr/bin/env python3
"""Tests for the Faz 24 WG-B+ I3 metadata collector."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
COLLECTOR_PATH = REPO_ROOT / "scripts" / "faz24" / "collect-wg-bplus-i3-evidence.py"
VERIFIER_PATH = REPO_ROOT / "scripts" / "faz24" / "verify-wg-bplus-i3-evidence.py"

spec = importlib.util.spec_from_file_location("collect_wg_bplus_i3_evidence", COLLECTOR_PATH)
collector = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = collector
spec.loader.exec_module(collector)


class FakeRunner:
    def __init__(
        self,
        ssh_stdout: str | None,
        ssh_returncode: int = 0,
        ssh_stderr: str = "",
        wg_requires_sudo: bool = False,
        wg_binary_path_only: bool = False,
    ):
        self.ssh_stdout = ssh_stdout
        self.ssh_returncode = ssh_returncode
        self.ssh_stderr = ssh_stderr
        self.wg_requires_sudo = wg_requires_sudo
        self.wg_binary_path_only = wg_binary_path_only
        self.commands: list[list[str]] = []

    def __call__(self, argv: list[str], stdin: str | None = None, timeout: int = 30):
        self.commands.append(argv)
        if argv[:3] == ["ip", "route", "get"]:
            return collector.CommandResult(0, "10.99.0.2 dev wg-denetim src 10.99.0.1\n", "")
        if argv and argv[0] == "journalctl":
            return collector.CommandResult(
                0,
                "2026-06-25T00:00:00Z staging sshd Accepted publickey for svc-denetim-agent\n",
                "",
            )
        if len(argv) >= 3 and argv[:2] == ["sudo", "-n"] and argv[2].endswith("/wg"):
            return self._wg_result(argv[2:])
        if argv[:3] == ["sudo", "-n", "wg"]:
            return self._wg_result(argv[3:])
        if argv and argv[0].endswith("/wg"):
            return self._wg_result(argv)
        if argv and argv[0] == "wg":
            if self.wg_binary_path_only:
                return collector.CommandResult(127, "", "command-not-found")
            if self.wg_requires_sudo:
                return collector.CommandResult(1, "", "permission-denied")
            return self._wg_result(argv)
        if argv and argv[0] == "ss":
            return collector.CommandResult(0, "ESTAB 0 0 10.99.0.1:49152 10.99.0.2:22\n", "")
        if argv and argv[0] == "ssh":
            return collector.CommandResult(self.ssh_returncode, self.ssh_stdout or "", self.ssh_stderr)
        return collector.CommandResult(127, "", "unexpected-command")

    def _wg_result(self, argv: list[str]):
        if "--version" in argv:
            return collector.CommandResult(0, "wireguard-tools v1.0\n", "")
        if argv[-2:] == ["show", "interfaces"]:
            return collector.CommandResult(0, "wg-denetim\n", "")
        if "latest-handshakes" in argv:
            return collector.CommandResult(0, "peerprefix 1782345600\n", "")
        if "transfer" in argv:
            return collector.CommandResult(0, "peerprefix 1024 2048\n", "")
        if "endpoints" in argv:
            return collector.CommandResult(0, "peerprefix 10.99.0.2:51820\n", "")
        return collector.CommandResult(127, "", "unexpected-wg-command")


def remote_success_json() -> str:
    return json.dumps(
        {
            "collectedAt": "2026-06-25T00:00:00Z",
            "host": "DENETIM-PC",
            "checks": {
                "opensshEventLog": {"ok": True, "queryOk": True, "count": 1},
                "powershellTranscription": {
                    "ok": True,
                    "queryOk": True,
                    "enabled": True,
                    "hasProtectedPath": True,
                },
                "powershellScriptBlock": {
                    "ok": True,
                    "queryOk": True,
                    "enabled": True,
                    "count": 2,
                },
                "failedLogin": {"ok": True, "queryOk": True, "count": 0},
                "wireguardHealth": {
                    "ok": True,
                    "queryOk": True,
                    "interfaceCount": 1,
                    "handshakeCount": 1,
                    "transferCount": 1,
                },
                "firewallDrift": {"ok": True, "queryOk": True, "matchingRuleCount": 3},
                "timeSync": {"ok": True, "queryOk": True, "lineCount": 8},
            },
        }
    )


class WgBplusI3EvidenceCollectorTest(unittest.TestCase):
    def tcp_ok(self, host: str, port: int, timeout: int) -> dict:
        return {
            "tcp22Reachable": True,
            "tcp22ErrorClass": "",
            "tcp22Errno": None,
        }

    def build(
        self,
        runner: FakeRunner,
        wg_interface: str = "wg0",
        ssh_identity_path: str | None = None,
    ) -> dict:
        return collector.build_evidence(
            timestamp=datetime(2026, 6, 25, 0, 0, 0, tzinfo=timezone.utc),
            protected_path="github-actions://Halildeu/platform-k8s-gitops/actions/runs/1/artifacts/faz24-wg-bplus-i3-evidence",
            retention_days=14,
            denetim_target="svc-denetim-agent@10.99.0.2",
            lookback_hours=2,
            wg_interface=wg_interface,
            connect_timeout_seconds=1,
            runner=runner,
            tcp_probe=self.tcp_ok,
            ssh_identity_path=ssh_identity_path,
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

    def test_successful_metadata_collection_passes_existing_verifier(self):
        evidence = self.build(FakeRunner(remote_success_json()))

        self.assertEqual(
            set(collector.CHECK_ORDER),
            {check["id"] for check in evidence["checks"]},
        )
        self.assertTrue(all(check["status"] == "pass" for check in evidence["checks"]))
        self.assertFalse(evidence["redaction"]["rawAudioIncluded"])
        self.assertNotIn("svc-denetim-agent@10.99.0.2", json.dumps(evidence))

        result = self.run_verifier(evidence)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("Faz24 WG-B+ I3 evidence: PASS", result.stdout)

    def test_denetim_ssh_failure_writes_safe_rejected_evidence(self):
        evidence = self.build(FakeRunner(None, ssh_returncode=255))
        statuses = {check["id"]: check["status"] for check in evidence["checks"]}
        preflight = evidence["collector"]["denetimSshPreflight"]

        self.assertEqual("fail", statuses["openssh-event-log"])
        self.assertEqual("fail", statuses["staging-connection-log"])
        self.assertTrue(preflight["tcp22Reachable"])
        self.assertEqual(255, preflight["sshExitCode"])
        self.assertEqual("ssh-exit-255-unclassified", preflight["sshFailureClass"])
        self.assertNotIn("password", json.dumps(evidence).lower())
        self.assertNotIn("token", json.dumps(evidence).lower())

        result = self.run_verifier(evidence)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("status must be 'pass'", result.stderr)

    def test_denetim_ssh_failure_classifies_publickey_without_stderr_leak(self):
        evidence = self.build(
            FakeRunner(
                None,
                ssh_returncode=255,
                ssh_stderr="Permission denied (publickey).",
            )
        )
        preflight = evidence["collector"]["denetimSshPreflight"]
        serialized = json.dumps(evidence)

        self.assertEqual("ssh-auth-publickey", preflight["sshFailureClass"])
        self.assertTrue(preflight["sshStderrPresent"])
        self.assertTrue(preflight["sshErrorFingerprint"])
        self.assertNotIn("Permission denied", serialized)

    def test_denetim_ssh_uses_configured_runner_identity_without_key_leak(self):
        runner = FakeRunner(remote_success_json())
        with tempfile.TemporaryDirectory() as tmpdir:
            key_path = Path(tmpdir) / "faz24-i3-denetim_ed25519"
            key_path.write_text("not-a-real-private-key\n", encoding="utf-8")
            key_path.with_name(key_path.name + ".pub").write_text(
                "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFakePublicKey faz24-i3\n",
                encoding="utf-8",
            )

            evidence = self.build(runner, ssh_identity_path=str(key_path))

        preflight = evidence["collector"]["denetimSshPreflight"]
        ssh_commands = [argv for argv in runner.commands if argv and argv[0] == "ssh"]
        self.assertEqual(1, len(ssh_commands))
        self.assertIn("-i", ssh_commands[0])
        self.assertIn("IdentitiesOnly=yes", ssh_commands[0])
        self.assertTrue(preflight["sshIdentityConfigured"])
        self.assertTrue(preflight["sshIdentityPublicKeyPresent"])
        self.assertTrue(preflight["sshIdentityPublicKeyFingerprint"])
        self.assertNotIn("FakePublicKey", json.dumps(evidence))

    def test_staging_wireguard_uses_sudo_fallback(self):
        original_which = collector.shutil.which
        collector.shutil.which = lambda name: "/usr/bin/sudo" if name == "sudo" else None
        try:
            evidence = self.build(FakeRunner(remote_success_json(), wg_requires_sudo=True))
        finally:
            collector.shutil.which = original_which

        self.assertTrue(evidence["collector"]["stagingWireGuardQueryable"])
        self.assertEqual(1, evidence["collector"]["stagingWireGuardPeerCount"])

        result = self.run_verifier(evidence)

        self.assertEqual(0, result.returncode, result.stderr)

    def test_staging_wireguard_auto_detects_interface(self):
        evidence = self.build(FakeRunner(remote_success_json()), wg_interface="auto")
        probe = evidence["collector"]["stagingWireGuardProbe"]

        self.assertTrue(evidence["collector"]["stagingWireGuardQueryable"])
        self.assertEqual("auto", probe["requested"])
        self.assertTrue(probe["interfacesQueryable"])
        self.assertEqual(1, probe["detectedCount"])
        self.assertEqual("wg-denetim", probe["selectedInterface"])

        result = self.run_verifier(evidence)

        self.assertEqual(0, result.returncode, result.stderr)

    def test_staging_wireguard_uses_common_binary_path_when_path_misses_wg(self):
        original_which = collector.shutil.which
        collector.shutil.which = lambda name: None
        try:
            evidence = self.build(
                FakeRunner(remote_success_json(), wg_binary_path_only=True),
                wg_interface="auto",
            )
        finally:
            collector.shutil.which = original_which
        probe = evidence["collector"]["stagingWireGuardProbe"]

        self.assertTrue(probe["wgToolFound"])
        self.assertEqual("/usr/bin/wg", probe["wgToolSelected"])
        self.assertTrue(probe["interfacesQueryable"])
        self.assertEqual("wg-denetim", probe["selectedInterface"])

        result = self.run_verifier(evidence)

        self.assertEqual(0, result.returncode, result.stderr)


if __name__ == "__main__":
    unittest.main()
