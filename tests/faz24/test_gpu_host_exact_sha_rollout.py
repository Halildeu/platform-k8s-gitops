from __future__ import annotations

import base64
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "faz24"))

import run_gpu_host_exact_sha_rollout as runner  # noqa: E402
import scan_metadata_evidence as scanner  # noqa: E402
import verify_gpu_host_exact_sha_rollout_evidence as verifier  # noqa: E402


COMMIT = "d85cb11ccd34dea50b47eed472345cf6477a3c18"


def accepted_evidence() -> dict:
    return {
        "schemaVersion": verifier.SCHEMA_VERSION,
        "generatedAt": "2026-07-15T19:00:00Z",
        "status": "go",
        "targetCommit": COMMIT,
        "beforeCommit": "5b716c3281ba5df4a63c391f6cf13cce62e68a45",
        "afterCommit": COMMIT,
        "sourceCommitVerified": True,
        "whatIfExitCode": 0,
        "deployExitCode": 0,
        "failureClass": "none",
        "controller": {"exactTarget": True, "cleanupExitCode": 0},
        "taskMigration": {
            "required": True,
            "pinWithoutRestartExitCode": 0,
            "whatIfExitCode": 0,
            "migrationExitCode": 0,
            "sourceRollbackExitCode": -1,
        },
        "tasksBefore": {
            "liveStt": {
                "present": True,
                "state": 4,
                "actionCanonical": False,
                "actionMigratable": True,
                "actionCount": 1,
                "executeClass": "windows-powershell",
                "executeTrusted": True,
                "scriptPathClass": "legacy-user-repo",
                "workingDirectoryClass": "empty",
                "actionArgumentsSha256": "a" * 64,
            },
            "meetingAi": {
                "present": True,
                "state": 4,
                "actionCanonical": False,
                "actionMigratable": True,
                "actionCount": 1,
                "executeClass": "windows-powershell",
                "executeTrusted": True,
                "scriptPathClass": "legacy-user-repo",
                "workingDirectoryClass": "empty",
                "actionArgumentsSha256": "b" * 64,
            },
        },
        "principal": {"expectedIdentity": True, "administrator": True},
        "ledger": {
            "currentCommit": COMMIT,
            "previousCommit": "5b716c3281ba5df4a63c391f6cf13cce62e68a45",
            "action": "deploy",
            "lastResult": "tasks-restarted",
            "timestampUtc": "2026-07-15T19:00:00Z",
        },
        "tasks": {
            "liveStt": {"present": True, "state": 4, "actionCanonical": True},
            "meetingAi": {"present": True, "state": 4, "actionCanonical": True},
        },
        "health": {
            "liveStt": {
                "reachable": True,
                "status": "ok",
                "model": "medium",
                "device": "cuda",
                "computeType": "float16",
                "backend": "",
            },
            "meetingAi": {
                "reachable": True,
                "status": "ok",
                "model": "",
                "device": "",
                "computeType": "",
                "backend": "ollama",
            },
        },
        "webSocket": {"ready": True, "eventType": "ready", "failureClass": "none"},
        "privacy": {
            "rawAudioIncluded": False,
            "transcriptTextIncluded": False,
            "secretMaterialIncluded": False,
        },
    }


class RunnerContractTests(unittest.TestCase):
    def test_commit_must_be_full_lowercase_sha(self) -> None:
        self.assertEqual(runner.validate_commit(COMMIT), COMMIT)
        for invalid in ("main", COMMIT[:-1], COMMIT.upper(), COMMIT + "\nwhoami"):
            with self.assertRaises(ValueError):
                runner.validate_commit(invalid)

    def test_remote_script_has_fixed_target_and_canonical_paths(self) -> None:
        script = runner.build_remote_script(COMMIT)
        self.assertIn(f"$TargetCommit = '{COMMIT}'", script)
        self.assertIn("$RepoRoot = 'C:\\platform-ai'", script)
        self.assertIn("platform-ai-rollout-controller-", script)
        self.assertIn("function Invoke-GitSilent", script)
        self.assertIn("'worktree', 'add', '--detach'", script)
        self.assertIn("'worktree', 'remove', '--force'", script)
        self.assertIn("controller-cleanup-rejected", script)
        self.assertIn("$UpdateScript = Join-Path $ControllerRoot", script)
        self.assertIn("$env:GIT_CONFIG_COUNT = '1'", script)
        self.assertIn("$env:GIT_CONFIG_KEY_0 = 'safe.directory'", script)
        self.assertIn("$env:GIT_CONFIG_VALUE_0 = 'C:/platform-ai'", script)
        self.assertIn("'\\denetimpc'", script)
        self.assertIn("rollout-principal-not-admin", script)
        self.assertIn("actionArgumentsSha256", script)
        self.assertIn("scriptPathClass = 'canonical-repo'", script)
        self.assertIn("scriptPathClass = 'legacy-user-repo'", script)
        self.assertIn("executeClass = 'windows-powershell'", script)
        self.assertIn("executeTrusted = $false", script)
        self.assertIn("workingDirectoryClass = 'missing'", script)
        self.assertIn("actionMigratable = $false", script)
        self.assertIn(
            "scriptPathClass -in @('canonical-repo', 'legacy-user-repo')",
            script,
        )
        self.assertNotIn("arguments = $arguments", script)
        self.assertNotIn("__TARGET_COMMIT__", script)
        self.assertIn("Invoke-UpdaterChild -WhatIfOnly", script)
        self.assertIn("Invoke-UpdaterChild -NoRestartOnly", script)
        self.assertIn("Invoke-TaskActionMigration -WhatIfOnly", script)
        self.assertIn("$migrationExitCode = Invoke-TaskActionMigration", script)
        self.assertIn("Invoke-UpdaterChild -RollbackOnly -NoRestartOnly", script)
        self.assertIn("function Invoke-PowerShellChild", script)
        self.assertIn("function ConvertTo-PowerShellLiteral", script)
        self.assertIn("$Value.Replace(\"'\", \"''\")", script)
        self.assertIn("$Command | & powershell.exe @arguments", script)
        self.assertIn("'-Command', '-'", script)
        self.assertIn("$ConfirmPreference = ''None''; &", script)
        self.assertIn("' -Confirm:$false'", script)
        self.assertNotIn("'-File', $UpdateScript", script)
        self.assertNotIn("'-File', $MigrationScript", script)
        self.assertIn("throw 'task-action-unrecognized'", script)
        self.assertIn("Get-RolloutFailureClass -ErrorRecord $_", script)
        self.assertIn("Test-WebSocketReady", script)

        reject_index = script.index("throw 'task-action-unrecognized'")
        preflight_index = script.index("$whatIfExitCode = Invoke-UpdaterChild")
        pin_index = script.index("$pinWithoutRestartExitCode = Invoke-UpdaterChild")
        migration_index = script.index("$migrationExitCode = Invoke-TaskActionMigration")
        final_deploy_index = script.index("$deployExitCode = Invoke-UpdaterChild")
        self.assertLess(reject_index, preflight_index)
        self.assertLess(preflight_index, pin_index)
        self.assertLess(pin_index, migration_index)
        self.assertLess(migration_index, final_deploy_index)

    def test_ssh_command_is_strict_and_fixed_target(self) -> None:
        command = runner.ssh_command(Path("/ssh/config"), Path("/ssh/known_hosts"))
        self.assertIn("/ssh/config", command)
        self.assertIn("UserKnownHostsFile=/ssh/known_hosts", command)
        self.assertIn("StrictHostKeyChecking=yes", command)
        self.assertIn("IdentitiesOnly=yes", command)
        self.assertIn(runner.CANONICAL_TARGET, command)
        self.assertEqual(command[-2:], ["-Command", "-"])
        self.assertNotIn("-EncodedCommand", command)
        self.assertNotIn(COMMIT, command)
        self.assertNotIn("svc-denetim-agent", command)
        self.assertNotIn("StrictHostKeyChecking=no", command)

    def test_rollout_streams_remote_script_over_stdin(self) -> None:
        payload = accepted_evidence()
        encoded = base64.b64encode(json.dumps(payload).encode()).decode()
        completed = runner.subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=f"{runner.EVIDENCE_MARKER}{encoded}\n",
            stderr="",
        )
        with patch.object(runner.subprocess, "run", return_value=completed) as run:
            exit_code, evidence = runner.run_rollout(
                target_commit=COMMIT,
                ssh_config=Path("/ssh/config"),
                known_hosts=Path("/ssh/known_hosts"),
                timeout_seconds=1200,
            )

        command = run.call_args.args[0]
        self.assertEqual(exit_code, 0)
        self.assertEqual(evidence["targetCommit"], COMMIT)
        self.assertNotIn("-EncodedCommand", command)
        self.assertNotIn(COMMIT, command)
        self.assertEqual(run.call_args.kwargs["input"], runner.build_remote_script(COMMIT))

    def test_evidence_marker_is_parsed_without_other_output(self) -> None:
        payload = accepted_evidence()
        encoded = base64.b64encode(json.dumps(payload).encode()).decode()
        parsed = runner.parse_evidence(f"{runner.EVIDENCE_MARKER}{encoded}\n")
        self.assertEqual(parsed["targetCommit"], COMMIT)

    def test_multiple_evidence_markers_are_rejected(self) -> None:
        encoded = base64.b64encode(b"{}").decode()
        output = (
            f"{runner.EVIDENCE_MARKER}{encoded}\n{runner.EVIDENCE_MARKER}{encoded}\n"
        )
        with self.assertRaises(ValueError):
            runner.parse_evidence(output)

    def test_failure_evidence_is_metadata_only_no_go(self) -> None:
        evidence = runner.failure_evidence(COMMIT, "remote-evidence-unavailable")
        self.assertEqual(evidence["status"], "no-go")
        self.assertEqual(evidence["targetCommit"], COMMIT)
        self.assertFalse(evidence["sourceCommitVerified"])
        self.assertFalse(evidence["principal"]["expectedIdentity"])
        self.assertFalse(evidence["principal"]["administrator"])
        self.assertFalse(evidence["taskMigration"]["required"])
        self.assertEqual(
            evidence["taskMigration"]["pinWithoutRestartExitCode"], -1
        )
        self.assertFalse(evidence["privacy"]["rawAudioIncluded"])
        self.assertFalse(evidence["privacy"]["transcriptTextIncluded"])
        self.assertFalse(evidence["privacy"]["secretMaterialIncluded"])


class VerifierContractTests(unittest.TestCase):
    def test_accepts_complete_metadata_only_evidence(self) -> None:
        verifier.verify(accepted_evidence(), COMMIT)

    def test_rejects_non_ready_stream(self) -> None:
        data = accepted_evidence()
        data["webSocket"]["ready"] = False
        with self.assertRaises(verifier.EvidenceError):
            verifier.verify(data, COMMIT)

    def test_rejects_controller_cleanup_failure(self) -> None:
        data = accepted_evidence()
        data["controller"]["cleanupExitCode"] = 1
        with self.assertRaises(verifier.EvidenceError):
            verifier.verify(data, COMMIT)

    def test_rejects_noncanonical_task_action(self) -> None:
        data = accepted_evidence()
        data["tasks"]["liveStt"]["actionCanonical"] = False
        with self.assertRaises(verifier.EvidenceError):
            verifier.verify(data, COMMIT)

    def test_rejects_failed_required_task_migration(self) -> None:
        data = accepted_evidence()
        data["taskMigration"]["migrationExitCode"] = 1
        with self.assertRaises(verifier.EvidenceError):
            verifier.verify(data, COMMIT)

    def test_accepts_canonical_task_path_without_migration(self) -> None:
        data = accepted_evidence()
        data["taskMigration"] = {
            "required": False,
            "pinWithoutRestartExitCode": -1,
            "whatIfExitCode": -1,
            "migrationExitCode": -1,
            "sourceRollbackExitCode": -1,
        }
        for task in data["tasksBefore"].values():
            task["actionCanonical"] = True
            task["scriptPathClass"] = "canonical-repo"
        verifier.verify(data, COMMIT)

    def test_rejects_migration_flag_contradicting_tasks_before(self) -> None:
        data = accepted_evidence()
        data["taskMigration"]["required"] = False
        data["taskMigration"]["pinWithoutRestartExitCode"] = -1
        data["taskMigration"]["whatIfExitCode"] = -1
        data["taskMigration"]["migrationExitCode"] = -1
        with self.assertRaises(verifier.EvidenceError):
            verifier.verify(data, COMMIT)

    def test_rejects_untrusted_pre_migration_executable(self) -> None:
        data = accepted_evidence()
        data["tasksBefore"]["liveStt"]["executeTrusted"] = False
        with self.assertRaises(verifier.EvidenceError):
            verifier.verify(data, COMMIT)

    def test_rejects_unexpected_source_rollback(self) -> None:
        data = accepted_evidence()
        data["taskMigration"]["sourceRollbackExitCode"] = 0
        with self.assertRaises(verifier.EvidenceError):
            verifier.verify(data, COMMIT)

    def test_rejects_non_admin_rollout_principal(self) -> None:
        data = accepted_evidence()
        data["principal"]["administrator"] = False
        with self.assertRaises(verifier.EvidenceError):
            verifier.verify(data, COMMIT)

    def test_rejects_mock_meeting_ai_backend(self) -> None:
        data = accepted_evidence()
        data["health"]["meetingAi"]["backend"] = "mock"
        with self.assertRaises(verifier.EvidenceError):
            verifier.verify(data, COMMIT)

    def test_rejects_transcript_field(self) -> None:
        data = accepted_evidence()
        data["transcript"] = "sensitive content"
        with self.assertRaises(verifier.EvidenceError):
            verifier.verify(data, COMMIT)

    def test_rejects_bearer_material(self) -> None:
        data = accepted_evidence()
        data["failureClass"] = "Bearer abc.def.ghi"
        with self.assertRaises(verifier.EvidenceError):
            verifier.verify(data, COMMIT)

    def test_rejects_uppercase_expected_commit(self) -> None:
        with self.assertRaises(verifier.EvidenceError):
            verifier.verify(accepted_evidence(), COMMIT.upper())


class EvidenceScannerTests(unittest.TestCase):
    def test_accepts_metadata_only_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "evidence.json").write_text(
                json.dumps(accepted_evidence()),
                encoding="utf-8",
            )
            scanner.scan_directory(root)

    def test_rejects_private_key_marker(self) -> None:
        self._assert_rejected("-----BEGIN OPENSSH PRIVATE KEY-----")

    def test_rejects_bearer_material(self) -> None:
        self._assert_rejected("Bearer abcdefghijklmnopqrstuvwxyz")

    def test_rejects_jwt_shaped_material(self) -> None:
        self._assert_rejected(
            "eyJabcdefghijklm.abcdefghijklmnop.abcdefghijk",
        )

    def test_rejects_symlink_in_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "safe.txt"
            target.write_text("metadata only", encoding="utf-8")
            (root / "linked.txt").symlink_to(target)
            with self.assertRaises(scanner.EvidenceScanError):
                scanner.scan_directory(root)

    def _assert_rejected(self, content: str) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "unsafe.txt").write_text(content, encoding="utf-8")
            with self.assertRaises(scanner.EvidenceScanError):
                scanner.scan_directory(root)


if __name__ == "__main__":
    unittest.main()
