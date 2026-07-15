#!/usr/bin/env python3
"""Tests for the Faz 24 WG-B+ I3 metadata collector."""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
COLLECTOR_PATH = REPO_ROOT / "scripts" / "faz24" / "collect-wg-bplus-i3-evidence.py"
VERIFIER_PATH = REPO_ROOT / "scripts" / "faz24" / "verify-wg-bplus-i3-evidence.py"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "faz24-wg-bplus-i3-evidence.yml"

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
        journal_stdout: str | None = None,
        route_device: str = "wg-denetim",
    ):
        self.ssh_stdout = ssh_stdout
        self.ssh_returncode = ssh_returncode
        self.ssh_stderr = ssh_stderr
        self.wg_requires_sudo = wg_requires_sudo
        self.wg_binary_path_only = wg_binary_path_only
        self.journal_stdout = journal_stdout
        self.route_device = route_device
        self.audit_record = ""
        self.commands: list[list[str]] = []
        self.stdins: list[str | None] = []

    def __call__(self, argv: list[str], stdin: str | None = None, timeout: int = 30):
        self.commands.append(argv)
        self.stdins.append(stdin)
        if argv[:3] == ["ip", "route", "get"]:
            return collector.CommandResult(
                0,
                f"10.99.0.2 dev {self.route_device} src 10.99.0.1\n",
                "",
            )
        if argv and argv[0] == "journalctl":
            journal = self.audit_record if self.journal_stdout is None else self.journal_stdout
            return collector.CommandResult(0, journal, "")
        if argv and argv[0] == "logger":
            self.audit_record = argv[-1] + "\n"
            return collector.CommandResult(0, "", "")
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
    collected_at = datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    def control(expected: dict, observed: dict) -> dict:
        return {
            "contractVersion": "faz24.windows-audit-control.v1",
            "expected": expected,
            "observed": observed,
            "verdict": "pass",
            "collectedAt": collected_at,
            "maxAgeSeconds": 900,
            "errorClass": "none",
        }

    return json.dumps(
        {
            "collectedAt": collected_at,
            "checks": {
                "opensshEventLog": {"ok": True, "queryOk": True, "count": 1},
                "auditSnapshot": {
                    "ok": True,
                    "queryOk": True,
                    "schemaVersion": "faz24.windows-audit-snapshot.v1",
                    "collectedAt": collected_at,
                    "controls": {
                        "powershell-transcription": control(
                            {
                                "queryOk": True,
                                "policyEnabled": True,
                                "invocationHeaderEnabled": True,
                                "protectedOutputAcl": True,
                                "protectedSnapshotDirectoryAcl": True,
                                "protectedSnapshotFileAcl": True,
                            },
                            {
                                "queryOk": True,
                                "policyEnabled": True,
                                "invocationHeaderEnabled": True,
                                "protectedOutputAcl": True,
                                "protectedSnapshotDirectoryAcl": True,
                                "protectedSnapshotFileAcl": True,
                            },
                        ),
                        "powershell-script-block": control(
                            {"queryOk": True, "policyEnabled": True, "minimumEventCount": 1},
                            {"queryOk": True, "policyEnabled": True, "eventCount": 2},
                        ),
                        "failed-login": control(
                            {"securityLogQueryable": True, "auditFailureEnabled": True},
                            {
                                "securityLogQueryable": True,
                                "auditFailureEnabled": True,
                                "eventCount": 0,
                            },
                        ),
                        "wireguard-health": control(
                            {
                                "queryOk": True,
                                "minimumRunningServiceCount": 1,
                                "minimumInterfaceCount": 1,
                                "minimumPeerCount": 1,
                                "maximumHandshakeAgeSeconds": 300,
                            },
                            {
                                "queryOk": True,
                                "dumpExitCode": 0,
                                "runningServiceCount": 1,
                                "interfaceCount": 1,
                                "peerCount": 1,
                                "latestHandshakeAgeSeconds": 20,
                            },
                        ),
                        "eset-firewall-drift": control(
                            {
                                "queryOk": True,
                                "expectedRuleCount": 3,
                                "minimumEsetCoreRunningCount": 2,
                            },
                            {
                                "queryOk": True,
                                "expectedRuleCount": 3,
                                "expectedRuleMatchCount": 3,
                                "broadConflictCount": 0,
                                "esetCoreRunningCount": 2,
                            },
                        ),
                        "time-sync": control(
                            {
                                "queryOk": True,
                                "serviceState": "Running",
                                "statusCommandExitCode": 0,
                                "sourcePresent": True,
                                "sourceSynchronized": True,
                                "syncTypeConfigured": True,
                                "maximumSuccessEventAgeSeconds": 86400,
                            },
                            {
                                "queryOk": True,
                                "serviceState": "Running",
                                "statusCommandExitCode": 0,
                                "sourcePresent": True,
                                "sourceSynchronized": True,
                                "syncTypeConfigured": True,
                                "latestSuccessEventAgeSeconds": 120,
                            },
                        ),
                    },
                },
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
        wg_interface: str = "auto",
        ssh_identity_path: str | None = None,
    ) -> dict:
        if ssh_identity_path is None:
            with tempfile.TemporaryDirectory() as tmpdir:
                key_path = Path(tmpdir) / "faz24-i3-denetim_ed25519"
                key_path.write_text("test-private-key-placeholder\n", encoding="utf-8")
                key_path.with_name(key_path.name + ".pub").write_text(
                    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFakePublicKey faz24-i3\n",
                    encoding="utf-8",
                )
                return self.build(
                    runner,
                    wg_interface=wg_interface,
                    ssh_identity_path=str(key_path),
                )
        timestamp = datetime.now(timezone.utc).replace(microsecond=0)
        return collector.build_evidence(
            timestamp=timestamp,
            protected_path="github-actions://Halildeu/platform-k8s-gitops/actions/runs/1/artifacts/faz24-wg-bplus-i3-evidence",
            retention_days=14,
            denetim_target="svc-denetim-agent@10.99.0.2",
            lookback_hours=2,
            wg_interface=wg_interface,
            connect_timeout_seconds=1,
            runner=runner,
            tcp_probe=self.tcp_ok,
            ssh_identity_path=ssh_identity_path,
            clock=lambda: timestamp,
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
        self.assertEqual("faz24.wg-bplus.i3.audit.v2", evidence["schemaVersion"])
        self.assertNotIn("svc-denetim-agent", evidence["acl"]["writers"])
        self.assertNotIn("svc-denetim-agent@10.99.0.2", json.dumps(evidence))
        self.assertNotIn("svc-denetim-agent", json.dumps(evidence))
        self.assertNotIn("denetim-pc", json.dumps(evidence).lower())

        result = self.run_verifier(evidence)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("Faz24 WG-B+ I3 evidence: PASS", result.stdout)

    def test_stale_snapshot_fails_closed(self):
        remote = json.loads(remote_success_json())
        remote["checks"]["auditSnapshot"]["collectedAt"] = "2026-06-24T23:00:00Z"
        for control in remote["checks"]["auditSnapshot"]["controls"].values():
            control["collectedAt"] = "2026-06-24T23:00:00Z"
        evidence = self.build(FakeRunner(json.dumps(remote)))

        statuses = {check["id"]: check["status"] for check in evidence["checks"]}
        self.assertEqual("fail", statuses["powershell-transcription"])
        self.assertEqual(
            "stale-or-invalid-snapshot",
            next(
                check["control"]["errorClass"]
                for check in evidence["checks"]
                if check["id"] == "powershell-transcription"
            ),
        )

    def test_zero_failed_login_events_remain_valid_when_audit_is_proven(self):
        evidence = self.build(FakeRunner(remote_success_json()))
        check = next(check for check in evidence["checks"] if check["id"] == "failed-login")

        self.assertEqual("pass", check["status"])
        self.assertEqual(0, check["control"]["observed"]["eventCount"])
        self.assertTrue(check["control"]["observed"]["auditFailureEnabled"])

    def test_firewall_broad_conflict_cannot_pass_verifier(self):
        remote = json.loads(remote_success_json())
        control = remote["checks"]["auditSnapshot"]["controls"]["eset-firewall-drift"]
        control["observed"]["broadConflictCount"] = 1
        evidence = self.build(FakeRunner(json.dumps(remote)))

        result = self.run_verifier(evidence)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("broad inbound conflict count must be zero", result.stderr)

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
        self.assertIn("-EncodedCommand", ssh_commands[0])
        encoded_index = ssh_commands[0].index("-EncodedCommand") + 1
        self.assertGreater(len(ssh_commands[0][encoded_index]), 100)
        ssh_command_index = runner.commands.index(ssh_commands[0])
        self.assertIsNone(runner.stdins[ssh_command_index])
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
        self.assertEqual("auto", probe["requestedMode"])
        self.assertTrue(probe["interfacesQueryable"])
        self.assertEqual(1, probe["detectedCount"])
        self.assertEqual(collector.sha256_short("wg-denetim"), probe["selectedInterfaceHash"])

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
        self.assertEqual("absolute-path", probe["wgToolKind"])
        self.assertTrue(probe["interfacesQueryable"])
        self.assertEqual(collector.sha256_short("wg-denetim"), probe["selectedInterfaceHash"])

        result = self.run_verifier(evidence)

        self.assertEqual(0, result.returncode, result.stderr)

    def test_staging_requires_same_line_target_and_ssh_result_correlation(self):
        runner = FakeRunner(
            remote_success_json(),
            journal_stdout=(
                "2026-06-25T00:00:00Z staging sshd Accepted publickey for unrelated-user\n"
                "2026-06-25T00:00:01Z monitoring mentions svc-denetim-agent only\n"
            ),
        )
        evidence = self.build(runner)
        staging = next(
            check for check in evidence["checks"] if check["id"] == "staging-connection-log"
        )

        self.assertEqual(0, evidence["collector"]["stagingJournalMatchCount"])
        self.assertEqual("fail", staging["status"])
        self.assertEqual(
            0,
            staging["control"]["observed"]["journalMatchCount"],
        )

    def test_staging_route_must_use_selected_wireguard_interface(self):
        evidence = self.build(
            FakeRunner(remote_success_json(), route_device="eth0"),
            wg_interface="auto",
        )
        preflight = evidence["collector"]["denetimSshPreflight"]
        staging = next(
            check for check in evidence["checks"] if check["id"] == "staging-connection-log"
        )

        self.assertFalse(preflight["routeUsesSelectedWireGuardInterface"])
        self.assertNotEqual(
            preflight["routeDeviceHash"],
            evidence["collector"]["stagingWireGuardProbe"]["selectedInterfaceHash"],
        )
        self.assertEqual("fail", staging["status"])
        self.assertNotEqual(0, self.run_verifier(evidence).returncode)

    def test_secure_writer_is_atomic_and_restricts_permissions(self):
        evidence = self.build(FakeRunner(remote_success_json()))
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "protected"
            output = root / "evidence.json"
            collector.write_evidence_atomically(output, evidence)

            self.assertEqual(0o700, stat.S_IMODE(root.stat().st_mode))
            self.assertEqual(0o600, stat.S_IMODE(output.stat().st_mode))
            self.assertEqual(evidence, json.loads(output.read_text(encoding="utf-8")))
            self.assertEqual([], list(root.glob(".evidence.json.*.tmp")))

    def test_secure_writer_rejects_output_symlink(self):
        evidence = self.build(FakeRunner(remote_success_json()))
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "protected"
            root.mkdir(mode=0o700)
            target = root / "target.json"
            target.write_text("unchanged\n", encoding="utf-8")
            output = root / "evidence.json"
            os.symlink(target, output)

            with self.assertRaisesRegex(OSError, "symbolic link"):
                collector.write_evidence_atomically(output, evidence)

            self.assertEqual("unchanged\n", target.read_text(encoding="utf-8"))

    def test_workflow_pins_canonical_denetim_target(self):
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

        self.assertIn("svc-denetim-agent@10.99.0.2", workflow)
        self.assertIn("must match the canonical Denetim endpoint", workflow)


if __name__ == "__main__":
    unittest.main()
