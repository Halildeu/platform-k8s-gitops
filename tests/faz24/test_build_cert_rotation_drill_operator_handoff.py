#!/usr/bin/env python3
"""Tests for the Faz 24 cert rotation drill operator handoff package builder."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "faz24" / "build-cert-rotation-drill-operator-handoff.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "faz24-cert-rotation-drill-operator-handoff.yml"


class BuildCertRotationDrillOperatorHandoffTest(unittest.TestCase):
    def run_script(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_builds_metadata_only_handoff(self):
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
                    "faz24-cert-rotation-drill-operator-handoff.json",
                },
                {path.name for path in output.iterdir()},
            )

            manifest = json.loads(
                (output / "faz24-cert-rotation-drill-operator-handoff.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                "faz24.certRotationDrill.operator-handoff.v1",
                manifest["schemaVersion"],
            )
            self.assertEqual(
                "faz24-cert-rotation-drill-20260713", manifest["operatorBatchId"]
            )
            self.assertEqual(
                "platform-k8s-gitops#1615", manifest["issues"]["gitopsRollup"]
            )
            self.assertEqual(
                "platform-k8s-gitops#2321", manifest["issues"]["privateDeliveryRuntime"]
            )

            acceptance = manifest["acceptanceBoundary"]
            self.assertEqual("in-progress", acceptance["issueStatus"])
            self.assertTrue(acceptance["operatorExecutionRequired"])
            self.assertTrue(acceptance["scopedVaultTokenSeedRequired"])
            self.assertTrue(acceptance["gatewayActivationRequired"])
            self.assertTrue(acceptance["rotationDrillExecutionRequired"])
            self.assertTrue(acceptance["inducedReloadFailureRollbackRequired"])
            self.assertTrue(acceptance["alertFireAndClearRequired"])
            self.assertTrue(acceptance["drillVerifierPassRequired"])
            self.assertTrue(acceptance["reviewerAcceptanceRequired"])
            self.assertTrue(acceptance["doesNotSeedVault"])
            self.assertTrue(acceptance["doesNotTriggerRotation"])
            self.assertTrue(acceptance["doesNotRunDrill"])
            self.assertTrue(acceptance["doesNotActivatePrivateListener"])
            self.assertTrue(acceptance["doesNotAcceptProductionReadiness"])
            self.assertTrue(acceptance["doesNotAcceptLegalGo"])

            mutation = manifest["mutationBoundary"]
            self.assertFalse(mutation["packageBuildEvidenceMutation"])
            self.assertFalse(mutation["packageBuildClusterMutation"])
            self.assertFalse(mutation["packageBuildVaultMutation"])
            self.assertFalse(mutation["packageBuildHostMutation"])
            self.assertFalse(mutation["packageBuildSystemdMutation"])
            self.assertFalse(mutation["packageBuildCaddyMutation"])
            self.assertFalse(mutation["packageBuildFirewallMutation"])
            self.assertFalse(mutation["containsCredentials"])
            self.assertFalse(mutation["containsVaultTokens"])
            self.assertFalse(mutation["containsPrivateKeys"])
            self.assertFalse(mutation["containsCertificates"])
            self.assertFalse(mutation["containsIssuingCa"])

            target = manifest["target"]
            self.assertEqual("staging-sw", target["gatewayHost"])
            self.assertEqual("meeting-ai-private-gateway.service", target["gatewayService"])
            self.assertEqual("meeting-ai-server-cert-rotation.timer", target["rotationTimer"])
            self.assertEqual(8, target["rotationScheduleHours"])
            self.assertEqual(
                "scripts/faz24/verify_meeting_ai_cert_rotation_drill_evidence.py",
                target["verifier"],
            )
            self.assertEqual(
                ".github/workflows/faz24-cert-rotation-drill-evidence-ingest.yml",
                target["ingestWorkflow"],
            )
            self.assertEqual(
                "faz24.meetingAiCertRotationDrillEvidence.v1", target["evidenceSchema"]
            )
            self.assertEqual(
                "MeetingAIGatewayCertificateRotationFailed", target["requiredFailureAlert"]
            )

            layers = manifest["requiredEvidenceLayers"]
            self.assertIn("lastRunSuccessValue==1", layers["up"])
            self.assertIn("atomic-tls-current-pointer-swap", layers["functional"])
            self.assertIn("pointer-rolled-back-no-outage", layers["secured"])
            self.assertIn(
                "MeetingAIGatewayCertificateRotationFailed-fired", layers["secured"]
            )

            self.assertEqual(
                [
                    "scoped-vault-token-seed",
                    "gateway-activation",
                    "rotation-drill-execution",
                    "evidence-verify-ingest",
                    "reviewer-acceptance",
                ],
                [gate["id"] for gate in manifest["orderedGates"]],
            )
            gates = {gate["id"]: gate for gate in manifest["orderedGates"]}
            self.assertIn(
                "verify_meeting_ai_cert_rotation_drill_evidence.py",
                gates["evidence-verify-ingest"]["commands"]["verify"],
            )
            self.assertIn(
                'faz24.meetingAiCertRotationDrillVerifier.v1',
                gates["evidence-verify-ingest"]["commands"]["verify"],
            )
            self.assertIn(
                "faz24-cert-rotation-drill-evidence-ingest.yml",
                gates["evidence-verify-ingest"]["commands"]["ingest"],
            )

            readme = (output / "README.md").read_text(encoding="utf-8")
            self.assertIn("coordination artifact only", readme)
            self.assertIn("Gate 0", readme)
            self.assertIn("Gate 1", readme)
            self.assertIn("Gate 2", readme)
            self.assertIn("Gate 3", readme)
            self.assertIn("Gate 4", readme)
            self.assertIn("A single successful rotation is not acceptance", readme)

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
        self.assertIn(
            "must not contain certificate, private key, token-like, or raw-audio material",
            result.stderr,
        )

    def test_rejects_vault_token_like_batch_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_script(
                "--output-dir",
                tmpdir,
                "--operator-batch-id",
                "hvs.AAAAAAAAAAAAAAAAAAAAAAAA",
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn(
            "must not contain certificate, private key, token-like, or raw-audio material",
            result.stderr,
        )

    def test_rejects_path_escape_evidence_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_script(
                "--output-dir",
                tmpdir,
                "--evidence-path",
                "../faz24-cert-rotation-drill.json",
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("must not escape the handoff boundary", result.stderr)

    def test_rejects_non_tmp_absolute_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_script(
                "--output-dir",
                tmpdir,
                "--evidence-path",
                "/etc/faz24-cert-rotation-drill.json",
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("absolute paths are only allowed under /tmp", result.stderr)

    def test_workflow_contract(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn('default: "faz24-cert-rotation-drill-20260713"', workflow)
        self.assertIn(
            "faz24-cert-rotation-drill-operator-handoff-${{ github.run_id }}", workflow
        )
        self.assertIn("does not connect to staging-sw", workflow)
        self.assertIn('(cd "${HANDOFF_DIR}" && sha256sum --check SHA256SUMS)', workflow)
        self.assertIn('"faz24.certRotationDrill.operator-handoff.v1"', workflow)
        self.assertIn('--operator-batch-id "${OPERATOR_BATCH_ID}"', workflow)
        self.assertIn('--gateway-host "${GATEWAY_HOST}"', workflow)
        self.assertIn('--rotation-timer "${ROTATION_TIMER}"', workflow)
        self.assertIn("scopedVaultTokenSeedRequired", workflow)
        self.assertIn("packageBuildVaultMutation", workflow)
        self.assertIn("packageBuildSystemdMutation", workflow)
        self.assertIn("containsVaultTokens", workflow)
        self.assertIn("reject_host_chars gateway_host", workflow)
        self.assertIn("reject_unit_chars rotation_timer", workflow)
        self.assertIn("reject_path_chars evidence_path", workflow)
        self.assertIn("hvs\\.[A-Za-z0-9._-]+", workflow)
        self.assertNotIn("--operator-batch-id ${{ inputs.operator_batch_id }}", workflow)


if __name__ == "__main__":
    unittest.main()
