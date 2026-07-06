#!/usr/bin/env python3
"""Tests for the Faz 24 I7 app-mTLS operator handoff package builder."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "faz24" / "build-i7-app-mtls-operator-handoff.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "faz24-i7-app-mtls-operator-handoff.yml"


class BuildI7AppMtlsOperatorHandoffTest(unittest.TestCase):
    def run_script(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_builds_metadata_only_i7_handoff(self):
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
                    "faz24-i7-app-mtls-operator-handoff.json",
                },
                {path.name for path in output.iterdir()},
            )

            manifest = json.loads(
                (output / "faz24-i7-app-mtls-operator-handoff.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                "faz24.i7AppMtls.operator-handoff.v1",
                manifest["schemaVersion"],
            )
            self.assertEqual("faz24-i7-app-mtls-20260628", manifest["operatorBatchId"])
            self.assertEqual("platform-k8s-gitops#1615", manifest["issues"]["gitopsRollup"])
            self.assertEqual("platform-ai#198", manifest["issues"]["i7ProdGate"])
            self.assertEqual("platform-ai#188", manifest["issues"]["computePlaneAudit"])
            self.assertEqual("platform-ai#182", manifest["issues"]["directSttE2e"])
            self.assertEqual("needs-verify", manifest["acceptanceBoundary"]["issueStatus"])
            self.assertTrue(manifest["acceptanceBoundary"]["operatorExecutionRequired"])
            self.assertTrue(manifest["acceptanceBoundary"]["endpointPolicyEvidenceRequired"])
            self.assertTrue(
                manifest["acceptanceBoundary"]["liveSttPreflightVerifierPassRequired"]
            )
            self.assertTrue(manifest["acceptanceBoundary"]["prodGateVerifierPassRequired"])
            self.assertTrue(manifest["acceptanceBoundary"]["reviewerAcceptanceRequired"])
            self.assertTrue(
                manifest["acceptanceBoundary"]["liveSttPreflightDoesNotAcceptFullI7"]
            )
            self.assertTrue(manifest["acceptanceBoundary"]["prodGateRequiresMeetingAi8343"])
            self.assertTrue(manifest["acceptanceBoundary"]["doesNotEnableDirectStt"])
            self.assertTrue(manifest["acceptanceBoundary"]["doesNotAcceptProductionReadiness"])
            self.assertFalse(manifest["mutationBoundary"]["packageBuildEvidenceMutation"])
            self.assertFalse(manifest["mutationBoundary"]["packageBuildClusterMutation"])
            self.assertFalse(manifest["mutationBoundary"]["packageBuildVaultMutation"])
            self.assertFalse(manifest["mutationBoundary"]["packageBuildDenetimMutation"])
            self.assertFalse(manifest["mutationBoundary"]["packageBuildFirewallMutation"])
            self.assertFalse(manifest["mutationBoundary"]["packageBuildEndpointSecurityMutation"])
            self.assertFalse(manifest["mutationBoundary"]["containsCredentials"])
            self.assertFalse(manifest["mutationBoundary"]["containsPrivateKeys"])
            self.assertFalse(manifest["mutationBoundary"]["containsCertificates"])
            self.assertFalse(manifest["mutationBoundary"]["containsRawAudio"])
            self.assertFalse(manifest["mutationBoundary"]["containsRawTranscript"])
            self.assertFalse(manifest["mutationBoundary"]["containsPacketCapture"])
            self.assertEqual(
                ".github/workflows/faz24-i7-app-mtls-evidence-ingest.yml",
                manifest["target"]["ingestWorkflow"],
            )
            self.assertEqual("10.99.0.1", manifest["target"]["sourceWgIp"])
            self.assertEqual("10.99.0.2", manifest["target"]["denetimWgIp"])
            self.assertEqual(8243, manifest["target"]["liveStt"]["port"])
            self.assertEqual(8343, manifest["target"]["meetingAi"]["port"])
            self.assertEqual(
                "/tmp/faz24-i7-live-stt-preflight.json",
                manifest["target"]["liveStt"]["evidencePath"],
            )
            self.assertEqual(
                "/tmp/faz24-i7-prod-gate.json",
                manifest["target"]["prodGate"]["evidencePath"],
            )

            self.assertEqual(
                [
                    "endpoint-policy-evidence",
                    "live-stt-preflight",
                    "prod-gate-evidence",
                    "reviewer-acceptance",
                ],
                [gate["id"] for gate in manifest["orderedGates"]],
            )
            gates = {gate["id"]: gate for gate in manifest["orderedGates"]}
            self.assertEqual(
                {
                    "source": "10.99.0.1",
                    "destination": "10.99.0.2",
                    "protocol": "TCP",
                    "liveSttPort": 8243,
                    "program": "C:/caddy/caddy.exe",
                    "ttlOrRollbackRequired": True,
                },
                gates["endpoint-policy-evidence"]["requiredTuple"],
            )
            self.assertIn(
                "verify-i7-app-mtls-evidence.py",
                gates["live-stt-preflight"]["commands"]["verify"],
            )
            self.assertIn(
                'evidenceProfile == "live-stt-preflight"',
                gates["live-stt-preflight"]["commands"]["verify"],
            )
            self.assertIn(
                "faz24-i7-app-mtls-evidence-ingest.yml",
                gates["live-stt-preflight"]["commands"]["ingest"],
            )
            self.assertIn(
                "/tmp/faz24-i7-live-stt-preflight.json",
                gates["live-stt-preflight"]["commands"]["ingest"],
            )
            self.assertIn(
                'evidenceProfile == "prod-gate"',
                gates["prod-gate-evidence"]["commands"]["verify"],
            )
            self.assertIn(
                "/tmp/faz24-i7-prod-gate.json",
                gates["prod-gate-evidence"]["commands"]["ingest"],
            )

            self.assertIn("tcp-8243-reachable", manifest["requiredChecks"]["liveSttPreflight"])
            self.assertIn("tcp-8343-reachable", manifest["requiredChecks"]["prodGate"])
            self.assertIn("cert-rotation-drill", manifest["requiredChecks"]["prodGate"])
            self.assertIn("failure-drill-fail-fast", manifest["requiredChecks"]["prodGate"])

            readme = (output / "README.md").read_text(encoding="utf-8")
            self.assertIn("coordination artifact only", readme)
            self.assertIn("Gate 0", readme)
            self.assertIn("Gate 1", readme)
            self.assertIn("Gate 2", readme)
            self.assertIn("Gate 3", readme)
            self.assertIn("disable endpoint security to force the gate open", readme.lower())
            self.assertIn("A passing ingest artifact is not reviewer acceptance", readme)

            all_text = "\n".join(path.read_text(encoding="utf-8") for path in output.iterdir())
            self.assertNotIn("BEGIN CERTIFICATE", all_text)
            self.assertNotIn("BEGIN OPENSSH PRIVATE KEY", all_text)
            self.assertNotIn("Bearer ", all_text)
            self.assertNotIn("eyJ", all_text)
            self.assertNotIn("data:audio/", all_text)
            self.assertNotIn("raw_packet_payload", all_text)

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

    def test_rejects_path_escape_evidence_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_script(
                "--output-dir",
                tmpdir,
                "--live-stt-preflight-path",
                "../faz24-i7-live-stt-preflight.json",
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("must not escape the handoff boundary", result.stderr)

    def test_rejects_non_tmp_absolute_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_script(
                "--output-dir",
                tmpdir,
                "--prod-gate-evidence-path",
                "/etc/faz24-i7-prod-gate.json",
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("absolute paths are only allowed under /tmp", result.stderr)

    def test_rejects_invalid_ip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_script(
                "--output-dir",
                tmpdir,
                "--denetim-wg-ip",
                "10.99.0.999",
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("must be an IPv4 address", result.stderr)

    def test_workflow_contract(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn('default: "faz24-i7-app-mtls-20260628"', workflow)
        self.assertIn("faz24-i7-app-mtls-operator-handoff-${{ github.run_id }}", workflow)
        self.assertIn("does not connect to Denetim PC", workflow)
        self.assertIn('(cd "${HANDOFF_DIR}" && sha256sum --check SHA256SUMS)', workflow)
        self.assertIn('"faz24.i7AppMtls.operator-handoff.v1"', workflow)
        self.assertIn('--operator-batch-id "${OPERATOR_BATCH_ID}"', workflow)
        self.assertIn('--source-wg-ip "${SOURCE_WG_IP}"', workflow)
        self.assertIn('--denetim-wg-ip "${DENETIM_WG_IP}"', workflow)
        self.assertIn("liveSttPreflightDoesNotAcceptFullI7", workflow)
        self.assertIn("packageBuildFirewallMutation", workflow)
        self.assertIn("packageBuildEndpointSecurityMutation", workflow)
        self.assertIn("reject_ip_shape source_wg_ip", workflow)
        self.assertIn("reject_path_chars live_stt_preflight_path", workflow)
        self.assertNotIn("--operator-batch-id ${{ inputs.operator_batch_id }}", workflow)


if __name__ == "__main__":
    unittest.main()
