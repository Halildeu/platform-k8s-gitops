#!/usr/bin/env python3
"""Tests for the Faz 24 WG-B+ operator handoff package builder."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "faz24" / "build-wg-bplus-operator-handoff.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "faz24-wg-bplus-operator-handoff.yml"


class BuildWgBplusOperatorHandoffTest(unittest.TestCase):
    def run_script(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_builds_metadata_only_operator_handoff(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_script("--output-dir", tmpdir)

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("status=pass", result.stdout)
            self.assertIn("acceptance=needs-operator-evidence", result.stdout)

            output = Path(tmpdir)
            expected_files = {
                "README.md",
                "SHA256SUMS",
                "faz24-wg-bplus-operator-handoff.json",
            }
            self.assertEqual(expected_files, {path.name for path in output.iterdir()})

            manifest = json.loads(
                (output / "faz24-wg-bplus-operator-handoff.json").read_text(encoding="utf-8")
            )
            self.assertEqual("faz24.wg-bplus.operator-handoff.v1", manifest["schemaVersion"])
            self.assertEqual("faz24-wg-bplus-20260628", manifest["operatorBatchId"])
            self.assertEqual("Needs Verify", manifest["i3"]["boardStatus"])
            self.assertEqual("Needs Verify", manifest["i6"]["boardStatus"])
            self.assertTrue(manifest["acceptanceBoundary"]["operatorExecutionRequired"])
            self.assertTrue(manifest["acceptanceBoundary"]["verifierPassRequired"])
            self.assertFalse(manifest["mutationBoundary"]["packageBuildHostMutation"])
            self.assertFalse(manifest["mutationBoundary"]["packageBuildProductionMutation"])
            self.assertFalse(manifest["mutationBoundary"]["containsSecrets"])
            self.assertEqual("28326845949", manifest["i3"]["identityRunId"])
            self.assertEqual("28326859105", manifest["i3"]["authorizePackageRunId"])
            self.assertEqual("28151747361", manifest["i6"]["hostPackageRunId"])
            self.assertIn(
                "faz24-i3-denetim-ssh-authorize-evidence-ingest.yml",
                manifest["i3"]["commands"]["ingestAuthorizeEvidence"],
            )
            self.assertIn(
                "faz24-wg-bplus-i6-masq-evidence-ingest.yml",
                manifest["i6"]["commands"]["ingestMasqEvidence"],
            )

            readme = (output / "README.md").read_text(encoding="utf-8")
            self.assertIn("coordination artifact only", readme)
            self.assertIn("does not prove direct-STT Functional", readme)
            self.assertIn("verifier PASS", readme)

            all_text = "\n".join(path.read_text(encoding="utf-8") for path in output.iterdir())
            self.assertNotIn("BEGIN OPENSSH PRIVATE KEY", all_text)
            self.assertNotIn("Bearer ", all_text)
            self.assertNotIn("raw command output", json.dumps(manifest).lower())

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
                "batch/" + "-----BEGIN OPENSSH " + "PRIVATE KEY-----",
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("must not contain private key or token-like material", result.stderr)

    def test_rejects_invalid_sha(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_script(
                "--output-dir",
                tmpdir,
                "--i3-public-key-line-sha256",
                "abc123",
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("must be a lowercase SHA-256 hex digest", result.stderr)

    def test_rejects_bad_denetim_target(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_script(
                "--output-dir",
                tmpdir,
                "--denetim-ssh-target",
                "svc-denetim-agent",
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("must look like user@host", result.stderr)

    def test_workflow_contract(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("faz24-wg-bplus-operator-handoff-${{ github.run_id }}", workflow)
        self.assertIn("does not connect to Denetim PC or aiserver", workflow)
        self.assertIn("does not mutate host, cluster, WireGuard", workflow)
        self.assertIn('(cd "${HANDOFF_DIR}" && sha256sum --check SHA256SUMS)', workflow)
        self.assertIn('"faz24.wg-bplus.operator-handoff.v1"', workflow)
        self.assertIn('--operator-batch-id "${OPERATOR_BATCH_ID}"', workflow)
        self.assertNotIn('--operator-batch-id "${{ inputs.operator_batch_id }}"', workflow)
        self.assertLessEqual(workflow.count("description:"), 9)


if __name__ == "__main__":
    unittest.main()
