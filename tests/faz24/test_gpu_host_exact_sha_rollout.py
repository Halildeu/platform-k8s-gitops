from __future__ import annotations

import base64
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "faz24"))

import run_gpu_host_exact_sha_rollout as runner  # noqa: E402
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
        self.assertNotIn("__TARGET_COMMIT__", script)
        self.assertIn("Invoke-UpdaterChild -WhatIfOnly", script)
        self.assertIn("Test-WebSocketReady", script)

    def test_ssh_command_is_strict_and_fixed_target(self) -> None:
        command = runner.ssh_command(Path("/key"), Path("/known_hosts"), "encoded")
        self.assertIn("StrictHostKeyChecking=yes", command)
        self.assertIn("IdentitiesOnly=yes", command)
        self.assertIn(runner.CANONICAL_TARGET, command)
        self.assertNotIn("StrictHostKeyChecking=no", command)

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

    def test_rejects_noncanonical_task_action(self) -> None:
        data = accepted_evidence()
        data["tasks"]["liveStt"]["actionCanonical"] = False
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


if __name__ == "__main__":
    unittest.main()
