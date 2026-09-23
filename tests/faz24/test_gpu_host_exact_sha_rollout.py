from __future__ import annotations

import base64
import copy
import gzip
import json
import subprocess
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
                "status": "loading",
                "model": "medium",
                "device": "cpu",
                "computeType": "int8",
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
        "readiness": {
            "liveStt": {
                "reachable": True, "httpStatus": 200, "status": "ready",
                "runtimeCommit": COMMIT, "preloadEnabled": True, "workersHealthy": True,
                "roles": {"live": "ready", "final": "ready"},
                "runtime": {
                    "legacy": {"device": "cpu", "computeType": "int8"},
                    "live": {"device": "cuda", "computeType": "int8"},
                    "final": {"device": "cuda", "computeType": "float16"},
                },
                "speechGateProfile": "silero-balanced-v1",
            }
        },
        "webSocket": {
            "ready": True,
            "eventType": "ready",
            "protocol": "source-ranges-v1",
            "failureClass": "none",
        },
        "privacy": {
            "rawAudioIncluded": False,
            "transcriptTextIncluded": False,
            "secretMaterialIncluded": False,
        },
    }


class RunnerContractTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "requires Windows PowerShell")
    def test_windows_fenced_recovery_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "remote-source.ps1"
            source.write_text(runner.build_remote_script(COMMIT, True), encoding="utf-8")
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                 "-File", str(ROOT / "tests/faz24/windows_gpu_fenced_recovery.ps1"),
                 "-SourcePath", str(source)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("PASS Windows recovery guard and updater switch", result.stdout)

    def test_recovery_is_explicit_and_preserves_source_and_acceptance(self) -> None:
        self.assertIn('$RecoverFencedRuntime = $false', runner.build_remote_script(COMMIT))
        self.assertIn('$RecoverFencedRuntime = $true', runner.build_remote_script(COMMIT, True))
        with self.assertRaises(ValueError):
            runner.build_remote_script(COMMIT, 'true')
        data = accepted_evidence()
        data['fencedRuntimeRecovery'] = True
        data['beforeCommit'] = COMMIT
        data['taskMigration'] = {'required': False, 'pinWithoutRestartExitCode': -1,
                                 'whatIfExitCode': -1, 'migrationExitCode': -1,
                                 'sourceRollbackExitCode': -1}
        for task in data['tasksBefore'].values():
            task.update(state=1, actionCanonical=True, scriptPathClass='canonical-repo')
        verifier.verify(data, COMMIT)
        for path, bad in ((('beforeCommit',), 'a' * 40),
                          (('taskMigration', 'required'), True),
                          (('fencedRuntimeRecovery',), 'true'),
                          (('tasks', 'liveStt', 'state'), 1),
                          (('readiness', 'liveStt', 'status'), 'loading')):
            broken = copy.deepcopy(data)
            target = broken
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = bad
            with self.subTest(path=path), self.assertRaises(verifier.EvidenceError):
                verifier.verify(broken, COMMIT)
        for task in data['tasksBefore'].values():
            task['state'] = 4
        with self.assertRaises(verifier.EvidenceError):
            verifier.verify(data, COMMIT)

    def test_streaming_readiness_contract_not_legacy_cuda(self) -> None:
        script = runner.build_remote_script(COMMIT)
        self.assertIn("http://127.0.0.1:8200/ready", script)
        self.assertIn("$Readiness.streaming_preload_enabled -is [bool]", script)
        self.assertIn("$Readiness.workers_healthy -is [bool]", script)
        self.assertIn("Test-StreamingReadinessMetadata -Readiness $streamReadiness", script)
        self.assertNotIn("$liveHealth.device -eq 'cuda'", script)
        self.assertIn("action = [string]$state.lastAction", script)
        self.assertNotIn("action = [string]$state.action", script)
        # /health loading/cpu is the expected lazy legacy model, not admission.
        verifier.verify(accepted_evidence(), COMMIT)

    def test_streaming_readiness_rejects_missing_or_invalid_evidence(self) -> None:
        cases = [
            (("readiness",), None),
            (("readiness", "liveStt", "reachable"), False),
            (("readiness", "liveStt", "httpStatus"), 503),
            (("readiness", "liveStt", "status"), "loading"),
            (("readiness", "liveStt", "runtimeCommit"), "a" * 40),
            (("readiness", "liveStt", "runtimeCommit"), None),
            (("readiness", "liveStt", "roles", "live"), "loading"),
            (("readiness", "liveStt", "roles", "final"), None),
            (("readiness", "liveStt", "runtime", "live", "device"), "cpu"),
            (("readiness", "liveStt", "runtime", "final", "device"), "cpu"),
            (("readiness", "liveStt", "runtime", "live", "computeType"), "float16"),
            (("readiness", "liveStt", "runtime", "final", "computeType"), "int8"),
            (("readiness", "liveStt", "runtime", "legacy", "device"), "cuda"),
            (("readiness", "liveStt", "speechGateProfile"), "development-unpinned"),
            (("health", "liveStt", "status"), "degraded"),
            (("health", "liveStt", "reachable"), False),
        ]
        for field in ("preloadEnabled", "workersHealthy"):
            for invalid in (False, "true", 1, None):
                cases.append((("readiness", "liveStt", field), invalid))
        for path, invalid in cases:
            with self.subTest(path=path, invalid=invalid):
                data = copy.deepcopy(accepted_evidence())
                parent = data
                for name in path[:-1]:
                    parent = parent[name]
                if invalid is None:
                    del parent[path[-1]]
                else:
                    parent[path[-1]] = invalid
                with self.assertRaises(verifier.EvidenceError):
                    verifier.verify(data, COMMIT)

    def test_child_exit_and_protocol_contract(self) -> None:
        script = runner.build_remote_script(COMMIT)
        self.assertIn("'exit $LASTEXITCODE'", script)
        self.assertIn("$null -eq $child.ExitCode", script)
        self.assertIn("/ws/stream?protocol=source-ranges-v1", script)
        self.assertIn("$event.protocol -cne 'source-ranges-v1'", script)
        self.assertIn("($candidate | ConvertTo-Json -Compress) -cne $raw", script)
        for protocol in (None, "legacy"):
            evidence = accepted_evidence()
            evidence["webSocket"]["protocol"] = protocol
            with self.assertRaises(verifier.EvidenceError):
                verifier.verify(evidence, COMMIT)
        evidence = accepted_evidence()
        evidence["acceptanceDiagnostic"] = {"reason": "readiness-failed"}
        with self.assertRaises(verifier.EvidenceError):
            verifier.verify(evidence, COMMIT)

    @unittest.skipUnless(sys.platform == "win32", "requires real Windows PowerShell 5.1")
    def test_windows_child_and_diagnostic_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "remote-source.ps1"
            source.write_text(runner.build_remote_script(COMMIT), encoding="utf-8")
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                 "-File", str(ROOT / "tests/faz24/windows_gpu_rollout_diagnostics.ps1"),
                 "-SourcePath", str(source),
                 "-EncodedBootstrap", runner.ENCODED_STDIN_BOOTSTRAP,
                 "-RunnerPath", str(ROOT / "scripts/faz24/run_gpu_host_exact_sha_rollout.py"),
                 "-PythonExe", sys.executable],
                capture_output=True, text=True, timeout=180,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("PASS Windows PowerShell 5.1 rollout diagnostics", result.stdout)

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
        # The child command still stays out of argv, but it must not be piped
        # into a native powershell.exe call: under PowerShell 5.1 the child's
        # stderr becomes ErrorRecords before the redirection applies, and the
        # updater's stderr progress killed the parent mid-format so no evidence
        # line was emitted at all. The command travels through a temp .ps1
        # (argv carries only its path) and the child runs isolated.
        self.assertNotIn("$Command | & powershell.exe", script)
        self.assertIn("Start-Process -FilePath 'powershell.exe'", script)
        self.assertIn("-RedirectStandardOutput $StdoutPath", script)
        self.assertIn("-RedirectStandardError $StderrPath", script)
        self.assertIn("Remove-Item -LiteralPath $scriptPath", script)
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
        self.assertIn(str(Path("/ssh/config")), command)
        self.assertIn(f"UserKnownHostsFile={Path('/ssh/known_hosts')}", command)
        self.assertIn("StrictHostKeyChecking=yes", command)
        self.assertIn("IdentitiesOnly=yes", command)
        self.assertIn(runner.CANONICAL_TARGET, command)
        self.assertEqual(command[-2:], ["-EncodedCommand", runner.ENCODED_STDIN_BOOTSTRAP])
        bootstrap = base64.b64decode(command[-1]).decode("utf-16-le")
        self.assertEqual(bootstrap, runner.STDIN_BOOTSTRAP)
        self.assertIn("[Console]::In.ReadLine()", bootstrap)
        self.assertNotIn("ReadToEnd", bootstrap)
        self.assertIn("[ScriptBlock]::Create($source)", bootstrap)
        self.assertLess(
            bootstrap.index("$ProgressPreference = 'SilentlyContinue'"),
            bootstrap.index("New-Object"),
        )
        self.assertNotIn(COMMIT, bootstrap)
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
        self.assertEqual(command[-2:], ["-EncodedCommand", runner.ENCODED_STDIN_BOOTSTRAP])
        self.assertNotIn(COMMIT, command)
        self.assertEqual(run.call_args.kwargs["input"],
                         runner.encode_remote_input(runner.build_remote_script(COMMIT)))

    def test_compressed_frame_is_bounded_deterministic_and_exact(self) -> None:
        for source in (runner.build_remote_script(COMMIT), "#" + "x" * 65535,
                       "#" + "x" * (runner.MAX_SOURCE_BYTES - 1), "# Turkce: \u0131\u015f\u011f\n"):
            with self.subTest(size=len(source.encode("utf-8"))):
                frame = runner.encode_remote_input(source)
                self.assertEqual(frame, runner.encode_remote_input(source))
                self.assertEqual(frame.count("\n"), 1)
                self.assertTrue(frame.endswith("\n"))
                self.assertLessEqual(len(frame) - 1, runner.MAX_WIRE_BYTES)
                self.assertEqual(gzip.decompress(base64.b64decode(frame[:-1], validate=True)),
                                 source.encode("utf-8"))
        self.assertLess(len(runner.encode_remote_input(runner.build_remote_script(COMMIT))),
                        12000)

    def test_compressed_frame_rejects_source_and_wire_limits(self) -> None:
        for source in ("", "x" * (runner.MAX_SOURCE_BYTES + 1),
                       "\u0131" * (runner.MAX_SOURCE_BYTES // 2 + 1)):
            with self.subTest(size=len(source)):
                with self.assertRaises(ValueError):
                    runner.encode_remote_input(source)
        with patch.object(runner.gzip, "compress", return_value=b"x" * 13000):
            with self.assertRaises(ValueError):
                runner.encode_remote_input("valid source")

    def test_evidence_marker_is_parsed_without_other_output(self) -> None:
        payload = accepted_evidence()
        encoded = base64.b64encode(json.dumps(payload).encode()).decode()
        parsed = runner.parse_evidence(f"{runner.EVIDENCE_MARKER}{encoded}\n")
        self.assertEqual(parsed["targetCommit"], COMMIT)

    def test_missing_marker_retains_only_metadata_safe_transport_diagnostics(self) -> None:
        completed = runner.subprocess.CompletedProcess(
            args=[],
            returncode=255,
            stdout="",
            stderr="Connection to fixed-host closed by remote host\n",
        )
        with patch.object(runner.subprocess, "run", return_value=completed):
            with self.assertRaises(runner.RemoteEvidenceUnavailable) as raised:
                runner.run_rollout(
                    target_commit=COMMIT,
                    ssh_config=Path("/ssh/config"),
                    known_hosts=Path("/ssh/known_hosts"),
                    timeout_seconds=1200,
                )

        transport = raised.exception.transport
        self.assertEqual(transport["returnCode"], 255)
        self.assertEqual(transport["evidenceMarkerCount"], 0)
        self.assertEqual(transport["stderrClass"], "ssh-connection-closed")
        self.assertEqual(len(transport["stderrSha256"]), 64)
        self.assertNotIn("closed by remote host", json.dumps(transport))

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

    def test_failure_evidence_can_include_redacted_transport_metadata(self) -> None:
        transport = {
            "returnCode": 1,
            "evidenceMarkerCount": 0,
            "stdoutBytes": 0,
            "stderrBytes": 12,
            "stderrClass": "powershell-parser-error",
            "stderrSha256": "a" * 64,
        }
        evidence = runner.failure_evidence(
            COMMIT,
            "remote-evidence-unavailable",
            transport=transport,
        )
        self.assertEqual(evidence["transport"], transport)


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
