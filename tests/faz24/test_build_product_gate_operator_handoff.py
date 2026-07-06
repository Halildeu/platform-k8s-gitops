#!/usr/bin/env python3
"""Tests for the Faz 24 product-gate operator handoff package builder."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "faz24" / "build-product-gate-operator-handoff.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "faz24-product-gate-operator-handoff.yml"


class BuildProductGateOperatorHandoffTest(unittest.TestCase):
    def run_script(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_builds_metadata_only_product_gate_handoff(self):
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
                    "faz24-product-gate-operator-handoff.json",
                },
                {path.name for path in output.iterdir()},
            )

            manifest = json.loads(
                (output / "faz24-product-gate-operator-handoff.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                "faz24.productGate.operator-handoff.v1",
                manifest["schemaVersion"],
            )
            self.assertEqual("faz24-product-gate-20260628", manifest["operatorBatchId"])
            self.assertEqual("platform-k8s-gitops#1615", manifest["issues"]["gitopsRollup"])
            self.assertEqual("platform-k8s-gitops#2027", manifest["issues"]["gcapAggregate"])
            self.assertEqual("platform-k8s-gitops#2022", manifest["issues"]["gopsVerifier"])
            self.assertEqual("platform-k8s-gitops#2024", manifest["issues"]["gcompVerifier"])
            self.assertEqual("platform-k8s-gitops#2027", manifest["issues"]["productGateIngest"])
            self.assertEqual("needs-verify", manifest["acceptanceBoundary"]["issueStatus"])
            self.assertTrue(manifest["acceptanceBoundary"]["acceptedRedactedEvidenceRequired"])
            self.assertTrue(manifest["acceptanceBoundary"]["gcapVerifierPassRequired"])
            self.assertTrue(manifest["acceptanceBoundary"]["gopsVerifierPassRequired"])
            self.assertTrue(manifest["acceptanceBoundary"]["gcompVerifierPassRequired"])
            self.assertTrue(manifest["acceptanceBoundary"]["productGateIngestRequired"])
            self.assertTrue(manifest["acceptanceBoundary"]["reviewerAcceptanceRequired"])
            self.assertTrue(manifest["acceptanceBoundary"]["legalTrackParallel"])
            self.assertTrue(
                manifest["acceptanceBoundary"]["kvkkOwnerLegalAcceptanceNotEngineeringBlocker"]
            )
            self.assertTrue(manifest["acceptanceBoundary"]["retentionDurationsParametric"])
            self.assertFalse(manifest["mutationBoundary"]["packageBuildEvidenceMutation"])
            self.assertFalse(manifest["mutationBoundary"]["packageBuildClusterMutation"])
            self.assertFalse(manifest["mutationBoundary"]["packageBuildVaultMutation"])
            self.assertFalse(manifest["mutationBoundary"]["packageBuildLegalMutation"])
            self.assertFalse(manifest["mutationBoundary"]["containsCredentials"])
            self.assertFalse(manifest["mutationBoundary"]["containsRawAudio"])
            self.assertFalse(manifest["mutationBoundary"]["containsRawTranscript"])
            self.assertFalse(manifest["mutationBoundary"]["containsUnredactedPersonalData"])
            self.assertEqual(
                ".github/workflows/faz24-product-gate-evidence-ingest.yml",
                manifest["target"]["ingestWorkflow"],
            )
            self.assertEqual(
                "/tmp/faz24-gcap-capture-gate.ingest-input.json",
                manifest["target"]["gcapIngestInputPath"],
            )
            self.assertIn(
                "/tmp/faz24-desktop-capture-evidence.verify.json",
                manifest["target"]["gcapInputPaths"],
            )
            self.assertEqual(
                "/tmp/faz24-gops-operability-gate.ingest-input.json",
                manifest["target"]["gopsIngestInputPath"],
            )
            self.assertEqual(
                "/tmp/faz24-gcomp-compliance-gate.ingest-input.json",
                manifest["target"]["gcompIngestInputPath"],
            )

            self.assertEqual(
                [
                    "redacted-evidence-selection",
                    "gcap-aggregate",
                    "gops-operability",
                    "gcomp-compliance",
                    "reviewer-acceptance",
                ],
                [gate["id"] for gate in manifest["orderedGates"]],
            )
            gates = {gate["id"]: gate for gate in manifest["orderedGates"]}
            self.assertIn(
                "verify_gcap_capture_gate_evidence.py",
                gates["gcap-aggregate"]["commands"]["verify"],
            )
            self.assertIn(
                'jq -s \'{"reports": .}\'',
                gates["gcap-aggregate"]["commands"]["prepareIngestInput"],
            )
            self.assertIn(
                "faz24-product-gate-evidence-ingest.yml",
                gates["gcap-aggregate"]["commands"]["ingest"],
            )
            self.assertIn(
                "verify_gops_operability_gate_evidence.py",
                gates["gops-operability"]["commands"]["verify"],
            )
            self.assertIn(
                "-f gate=gops",
                gates["gops-operability"]["commands"]["ingest"],
            )
            self.assertIn(
                "faz24-gops-operability-gate.ingest-input.json",
                gates["gops-operability"]["commands"]["prepareIngestInput"],
            )
            self.assertIn(
                "faz24-gops-operability-gate.ingest-input.json",
                gates["gops-operability"]["commands"]["ingest"],
            )
            self.assertIn(
                "verify_gcomp_compliance_gate_evidence.py",
                gates["gcomp-compliance"]["commands"]["verify"],
            )
            self.assertIn(
                "-f gate=gcomp",
                gates["gcomp-compliance"]["commands"]["ingest"],
            )
            self.assertIn(
                "faz24-gcomp-compliance-gate.ingest-input.json",
                gates["gcomp-compliance"]["commands"]["prepareIngestInput"],
            )
            self.assertIn(
                "faz24-gcomp-compliance-gate.ingest-input.json",
                gates["gcomp-compliance"]["commands"]["ingest"],
            )

            readme = (output / "README.md").read_text(encoding="utf-8")
            self.assertIn("coordination artifact only", readme)
            self.assertIn("Gate 1", readme)
            self.assertIn("Gate 2", readme)
            self.assertIn("Gate 3", readme)
            self.assertIn("Gate 4", readme)
            self.assertIn("not an engineering completion blocker", readme)
            self.assertIn("Prepare the workflow input from the verifier summaries", readme)

            all_text = "\n".join(path.read_text(encoding="utf-8") for path in output.iterdir())
            self.assertNotIn("BEGIN CERTIFICATE", all_text)
            self.assertNotIn("BEGIN OPENSSH PRIVATE KEY", all_text)
            self.assertNotIn("Bearer ", all_text)
            self.assertNotIn("eyJ", all_text)
            self.assertNotIn("data:audio/", all_text)
            self.assertNotIn("personal_data", all_text)

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
        self.assertIn(
            "must not contain certificate, private key, token-like, or raw-audio material",
            result.stderr,
        )

    def test_rejects_path_escape_batch_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_script(
                "--output-dir",
                tmpdir,
                "--operator-batch-id",
                "../faz24-product-gate",
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

        self.assertIn("faz24-product-gate-operator-handoff-${{ github.run_id }}", workflow)
        self.assertIn("does not collect", workflow)
        self.assertIn("does not collect runtime evidence", workflow)
        self.assertIn('(cd "${HANDOFF_DIR}" && sha256sum --check SHA256SUMS)', workflow)
        self.assertIn('"faz24.productGate.operator-handoff.v1"', workflow)
        self.assertIn('--operator-batch-id "${OPERATOR_BATCH_ID}"', workflow)
        self.assertIn("reject_unsupported_chars operator_batch_id", workflow)
        self.assertIn("reject_path_escape operator_batch_id", workflow)
        self.assertIn("kvkkOwnerLegalAcceptanceNotEngineeringBlocker", workflow)
        self.assertNotIn("--operator-batch-id ${{ inputs.operator_batch_id }}", workflow)
        self.assertEqual(2, workflow.count("description:"))


if __name__ == "__main__":
    unittest.main()
