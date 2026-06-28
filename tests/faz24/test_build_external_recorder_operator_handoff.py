#!/usr/bin/env python3
"""Tests for the Faz 24 external recorder operator handoff package builder."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "faz24" / "build-external-recorder-operator-handoff.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "faz24-external-recorder-operator-handoff.yml"


class BuildExternalRecorderOperatorHandoffTest(unittest.TestCase):
    def run_script(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_builds_metadata_only_external_recorder_handoff(self):
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
                    "faz24-external-recorder-operator-handoff.json",
                },
                {path.name for path in output.iterdir()},
            )

            manifest = json.loads(
                (output / "faz24-external-recorder-operator-handoff.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                "faz24.externalRecorder.operator-handoff.v1",
                manifest["schemaVersion"],
            )
            self.assertEqual("faz24-external-recorder-20260628", manifest["operatorBatchId"])
            self.assertEqual("platform-k8s-gitops#1615", manifest["issues"]["gitopsRollup"])
            self.assertEqual("platform-k8s-gitops#1995", manifest["issues"]["tokenContract"])
            self.assertEqual("platform-k8s-gitops#1996", manifest["issues"]["externalRecorderRunner"])
            self.assertEqual("platform-k8s-gitops#1997", manifest["issues"]["externalRecorderVerifier"])
            self.assertEqual("platform-k8s-gitops#2027", manifest["issues"]["gcapAggregate"])
            self.assertEqual("needs-verify", manifest["acceptanceBoundary"]["issueStatus"])
            self.assertTrue(manifest["acceptanceBoundary"]["approvedShortLivedTokenRequired"])
            self.assertTrue(manifest["acceptanceBoundary"]["tokenContractPassRequired"])
            self.assertTrue(manifest["acceptanceBoundary"]["externalSmokePassRequired"])
            self.assertTrue(manifest["acceptanceBoundary"]["smokeVerifierPassRequired"])
            self.assertTrue(manifest["acceptanceBoundary"]["gcapRequiresMultipleVerifierSummaries"])
            self.assertFalse(manifest["mutationBoundary"]["packageBuildKeycloakMutation"])
            self.assertFalse(manifest["mutationBoundary"]["packageBuildClusterMutation"])
            self.assertFalse(manifest["mutationBoundary"]["packageBuildVaultMutation"])
            self.assertFalse(manifest["mutationBoundary"]["containsCredentials"])
            self.assertFalse(manifest["mutationBoundary"]["containsRawAudio"])
            self.assertFalse(manifest["mutationBoundary"]["containsRawTranscript"])
            self.assertEqual("https://testai.acik.com", manifest["target"]["baseUrl"])
            self.assertEqual(
                "https://testai.acik.com/realms/platform-test",
                manifest["target"]["expectedIssuer"],
            )
            self.assertEqual("FAZ24_PLATFORM_DESKTOP_TOKEN_FILE", manifest["target"]["tokenFileEnv"])

            gates = {gate["id"]: gate for gate in manifest["orderedGates"]}
            self.assertEqual(
                [
                    "token-file-prep",
                    "token-contract",
                    "external-recorder-smoke",
                    "external-recorder-verifier",
                    "gcap-aggregate",
                ],
                [gate["id"] for gate in manifest["orderedGates"]],
            )
            self.assertIn(
                "validate_faz24_platform_desktop_token_contract.py",
                gates["token-contract"]["commands"]["validate"],
            )
            self.assertIn(
                "run_external_recorder_smoke.py",
                gates["external-recorder-smoke"]["commands"]["run"],
            )
            self.assertIn(
                "verify_external_recorder_smoke_evidence.py",
                gates["external-recorder-verifier"]["commands"]["verify"],
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
                "faz24-desktop-capture-evidence.verify.json",
                gates["gcap-aggregate"]["commands"]["prepareIngestInput"],
            )
            self.assertNotIn(
                "faz24-desktop-capture-evidence-04.verify.json",
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
            self.assertIn("Gate 4", readme)
            self.assertIn("single smoke is not aggregate product evidence", readme)

            all_text = "\n".join(path.read_text(encoding="utf-8") for path in output.iterdir())
            self.assertNotIn("BEGIN CERTIFICATE", all_text)
            self.assertNotIn("BEGIN OPENSSH PRIVATE KEY", all_text)
            self.assertNotIn("Bearer ", all_text)
            self.assertNotIn("eyJ", all_text)

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

    def test_rejects_non_https_base_url(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_script(
                "--output-dir",
                tmpdir,
                "--base-url",
                "http://testai.acik.com",
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("must be a bounded https URL", result.stderr)

    def test_rejects_path_escape_batch_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_script(
                "--output-dir",
                tmpdir,
                "--operator-batch-id",
                "../faz24-external-recorder",
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

    def test_rejects_url_with_credentials(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_script(
                "--output-dir",
                tmpdir,
                "--expected-issuer",
                "https://user:pass@testai.acik.com/realms/platform-test",
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("without credentials", result.stderr)

    def test_workflow_contract(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("faz24-external-recorder-operator-handoff-${{ github.run_id }}", workflow)
        self.assertIn("does not mint/read tokens", workflow)
        self.assertIn('(cd "${HANDOFF_DIR}" && sha256sum --check SHA256SUMS)', workflow)
        self.assertIn('"faz24.externalRecorder.operator-handoff.v1"', workflow)
        self.assertIn('--operator-batch-id "${OPERATOR_BATCH_ID}"', workflow)
        self.assertIn("reject_symbol_unsupported_chars operator_batch_id", workflow)
        self.assertIn("require_https_url base_url", workflow)
        self.assertIn("EXPECTED_BASE_URL", workflow)
        self.assertIn('os.environ["EXPECTED_BASE_URL"]', workflow)
        self.assertNotIn("--operator-batch-id ${{ inputs.operator_batch_id }}", workflow)
        self.assertNotIn('data["target"]["baseUrl"] == "${{ inputs.base_url }}"', workflow)
        self.assertEqual(4, workflow.count("description:"))


if __name__ == "__main__":
    unittest.main()
