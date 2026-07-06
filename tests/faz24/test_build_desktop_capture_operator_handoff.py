#!/usr/bin/env python3
"""Tests for the Faz 24 desktop capture operator handoff package builder."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "faz24" / "build-desktop-capture-operator-handoff.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "faz24-desktop-capture-operator-handoff.yml"


class BuildDesktopCaptureOperatorHandoffTest(unittest.TestCase):
    def run_script(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_builds_metadata_only_desktop_capture_handoff(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_script("--output-dir", tmpdir)

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("status=pass", result.stdout)
            self.assertIn("acceptance=needs-operator-runtime-evidence", result.stdout)

            output = Path(tmpdir)
            self.assertEqual(
                {
                    "README.md",
                    "SHA256SUMS",
                    "faz24-desktop-capture-operator-handoff.json",
                },
                {path.name for path in output.iterdir()},
            )

            manifest = json.loads(
                (output / "faz24-desktop-capture-operator-handoff.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                "faz24.desktopCapture.operator-handoff.v1",
                manifest["schemaVersion"],
            )
            self.assertEqual("faz24-desktop-capture-20260628", manifest["operatorBatchId"])
            self.assertEqual("platform-k8s-gitops#1615", manifest["issues"]["gitopsRollup"])
            self.assertEqual("platform-k8s-gitops#2027", manifest["issues"]["gcapAggregate"])
            self.assertEqual("needs-verify", manifest["acceptanceBoundary"]["issueStatus"])
            self.assertTrue(manifest["acceptanceBoundary"]["realDesktopRunRequired"])
            self.assertTrue(manifest["acceptanceBoundary"]["microphoneRealDeviceRequired"])
            self.assertTrue(manifest["acceptanceBoundary"]["loopbackRealDeviceRequired"])
            self.assertTrue(manifest["acceptanceBoundary"]["activeIndicatorRequired"])
            self.assertTrue(manifest["acceptanceBoundary"]["consentCaptureRequired"])
            self.assertTrue(manifest["acceptanceBoundary"]["verifierPassRequired"])
            self.assertTrue(manifest["acceptanceBoundary"]["gcapRequiresMultipleVerifierSummaries"])
            self.assertFalse(manifest["mutationBoundary"]["packageBuildDesktopMutation"])
            self.assertFalse(manifest["mutationBoundary"]["packageBuildClusterMutation"])
            self.assertFalse(manifest["mutationBoundary"]["containsCredentials"])
            self.assertFalse(manifest["mutationBoundary"]["containsRawAudio"])
            self.assertFalse(manifest["mutationBoundary"]["containsRawTranscript"])
            self.assertFalse(manifest["mutationBoundary"]["containsDeviceLabels"])
            self.assertEqual(
                "/tmp/faz24-desktop-capture-evidence.json",
                manifest["target"]["desktopEvidencePath"],
            )
            self.assertEqual(
                "/tmp/faz24-desktop-capture-evidence.verify.json",
                manifest["target"]["desktopVerifierPath"],
            )

            gates = {gate["id"]: gate for gate in manifest["orderedGates"]}
            self.assertEqual(
                [
                    "desktop-run-prep",
                    "redacted-evidence-review",
                    "desktop-verifier",
                    "gcap-aggregate",
                ],
                [gate["id"] for gate in manifest["orderedGates"]],
            )
            self.assertIn(
                "verify_desktop_capture_evidence.py",
                gates["desktop-verifier"]["commands"]["verify"],
            )
            self.assertIn(
                "verify_gcap_capture_gate_evidence.py",
                gates["gcap-aggregate"]["commands"]["verify"],
            )
            self.assertIn(
                'jq -s \'{"reports": .}\'',
                gates["gcap-aggregate"]["commands"]["prepareIngestInput"],
            )
            self.assertIn(
                'all(.reports[]; .status == "pass" and .tokenIncluded == false)',
                gates["gcap-aggregate"]["commands"]["prepareIngestInput"],
            )
            self.assertIn(
                "faz24-gcap-capture-gate.ingest-input.json",
                gates["gcap-aggregate"]["commands"]["ingest"],
            )
            self.assertIn(
                "faz24-product-gate-evidence-ingest.yml",
                gates["gcap-aggregate"]["commands"]["ingest"],
            )

            readme = (output / "README.md").read_text(encoding="utf-8")
            self.assertIn("coordination artifact only", readme)
            self.assertIn("Gate 1", readme)
            self.assertIn("Gate 2", readme)
            self.assertIn("Gate 3", readme)
            self.assertIn("single desktop verifier PASS is one capture attempt", readme)

            all_text = "\n".join(path.read_text(encoding="utf-8") for path in output.iterdir())
            self.assertNotIn("BEGIN CERTIFICATE", all_text)
            self.assertNotIn("BEGIN OPENSSH PRIVATE KEY", all_text)
            self.assertNotIn("Bearer ", all_text)
            self.assertNotIn("eyJ", all_text)
            self.assertNotIn("data:audio/", all_text)

            sha_result = subprocess.run(
                ["sha256sum", "--check", "SHA256SUMS"],
                text=True,
                capture_output=True,
                cwd=tmpdir,
                check=False,
            )
            self.assertEqual(0, sha_result.returncode, sha_result.stderr)

    def test_rejects_secret_like_batch_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_script(
                "--output-dir",
                tmpdir,
                "--operator-batch-id",
                "batch/Bearer abcdefghijklmnop",
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("must not contain certificate, private key, or token-like material", result.stderr)

    def test_rejects_path_escape_batch_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_script(
                "--output-dir",
                tmpdir,
                "--operator-batch-id",
                "../faz24-desktop-capture",
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("must be relative/symbolic", result.stderr)

    def test_rejects_multiline_gitops_ref(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_script(
                "--output-dir",
                tmpdir,
                "--gitops-ref",
                "main\nnext",
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("must be single-line", result.stderr)

    def test_workflow_contract(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("faz24-desktop-capture-operator-handoff-${{ github.run_id }}", workflow)
        self.assertIn("does not run the desktop app", workflow)
        self.assertIn("does not run the desktop app, read tokens", workflow)
        self.assertIn('(cd "${HANDOFF_DIR}" && sha256sum --check SHA256SUMS)', workflow)
        self.assertIn('"faz24.desktopCapture.operator-handoff.v1"', workflow)
        self.assertIn('--operator-batch-id "${OPERATOR_BATCH_ID}"', workflow)
        self.assertIn("reject_unsupported_chars operator_batch_id", workflow)
        self.assertIn("reject_path_escape operator_batch_id", workflow)
        self.assertNotIn("--operator-batch-id ${{ inputs.operator_batch_id }}", workflow)
        self.assertNotIn('data["target"]["gitopsRef"] == "${{ inputs.gitops_ref }}"', workflow)
        self.assertEqual(2, workflow.count("description:"))


if __name__ == "__main__":
    unittest.main()
