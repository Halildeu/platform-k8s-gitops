#!/usr/bin/env python3
"""Tests for the Faz 24 direct-STT operator handoff package builder."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "faz24" / "build-direct-stt-operator-handoff.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "faz24-direct-stt-operator-handoff.yml"


class BuildDirectSttOperatorHandoffTest(unittest.TestCase):
    def run_script(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_builds_metadata_only_direct_stt_handoff(self):
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
                    "faz24-direct-stt-operator-handoff.json",
                },
                {path.name for path in output.iterdir()},
            )

            manifest = json.loads(
                (output / "faz24-direct-stt-operator-handoff.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual("faz24.directStt.operator-handoff.v1", manifest["schemaVersion"])
            self.assertEqual("faz24-direct-stt-20260628", manifest["operatorBatchId"])
            self.assertEqual("platform-ai#182", manifest["issues"]["directSttE2e"])
            self.assertEqual("needs-verify", manifest["acceptanceBoundary"]["issueStatus"])
            self.assertTrue(manifest["acceptanceBoundary"]["approvedCredentialSeedRequired"])
            self.assertTrue(manifest["acceptanceBoundary"]["seedEvidenceRequired"])
            self.assertTrue(manifest["acceptanceBoundary"]["seedEvidenceIngestRequired"])
            self.assertTrue(manifest["acceptanceBoundary"]["preflightVerifierPassRequired"])
            self.assertTrue(manifest["acceptanceBoundary"]["flagFlipRequiresSeparateReviewedChange"])
            self.assertTrue(manifest["acceptanceBoundary"]["e2eVerifierPassRequired"])
            self.assertFalse(manifest["mutationBoundary"]["packageBuildVaultMutation"])
            self.assertFalse(manifest["mutationBoundary"]["packageBuildClusterMutation"])
            self.assertFalse(manifest["mutationBoundary"]["containsSecrets"])
            self.assertFalse(manifest["mutationBoundary"]["containsCertificates"])
            self.assertFalse(manifest["mutationBoundary"]["containsRawAudio"])
            self.assertEqual("k3d-test", manifest["target"]["kubeContext"])
            self.assertEqual("platform-test", manifest["target"]["namespace"])
            self.assertEqual("live-stt.denetim", manifest["target"]["transcribeHost"])
            self.assertEqual(
                "audio-gateway-direct-stt-mtls",
                manifest["target"]["mtlsObjectName"],
            )
            self.assertEqual("audio-gateway-secrets", manifest["target"]["aggregateObjectName"])
            self.assertEqual(
                "docs/faz-24-evidence/direct-stt-mtls-seed-evidence.json",
                manifest["target"]["seedEvidencePath"],
            )
            self.assertNotIn("mtlsSecret", manifest["target"])
            self.assertNotIn("aggregateSecret", manifest["target"])

            seed = manifest["orderedGates"][0]
            self.assertEqual("credential-seed", seed["id"])
            self.assertEqual(
                "docs/faz-24-evidence/direct-stt-mtls-seed-evidence.json",
                seed["redactedEvidencePath"],
            )
            self.assertIn(
                "direct_stt_mtls_seed_operator.py",
                seed["commands"]["validateOnly"],
            )
            self.assertIn(
                "--vault-path kv/platform/audio-gateway-service",
                seed["commands"]["apply"],
            )
            self.assertIn("--apply", seed["commands"]["apply"])
            self.assertIn(
                "verify_direct_stt_mtls_seed_operator_evidence.py",
                seed["commands"]["verifySeedEvidence"],
            )
            self.assertIn(
                "--summary-json /tmp/faz24-direct-stt-mtls-seed.verify.json",
                seed["commands"]["verifySeedEvidence"],
            )
            self.assertIn(
                "faz24-direct-stt-mtls-seed-evidence-ingest.yml",
                seed["commands"]["ingestSeedEvidence"],
            )
            self.assertIn(
                'evidence_json_base64="${DIRECT_STT_MTLS_SEED_B64}"',
                seed["commands"]["ingestSeedEvidence"],
            )
            self.assertIn(
                "faz24-direct-stt-mtls-preflight-collect.yml",
                seed["commands"]["postSeedReadinessProbe"],
            )

            preflight = manifest["orderedGates"][1]
            self.assertEqual("preflight", preflight["id"])
            self.assertIn(
                "collect_direct_stt_mtls_enablement_preflight.py",
                preflight["commands"]["collect"],
            )
            self.assertIn(
                "faz24-direct-stt-mtls-preflight-ingest.yml",
                preflight["commands"]["ingest"],
            )
            e2e = manifest["orderedGates"][3]
            self.assertIn("verify_direct_stt_e2e_evidence.py", e2e["commands"]["verify"])
            self.assertIn(
                "faz24-direct-stt-e2e-evidence-ingest.yml",
                e2e["commands"]["ingest"],
            )

            readme = (output / "README.md").read_text(encoding="utf-8")
            self.assertIn("coordination artifact only", readme)
            self.assertIn("validate-only", readme)
            self.assertIn("Vault KV v2 merge patch", readme)
            self.assertIn("/secure/operator-vault.token", readme)
            self.assertIn("redacted seed evidence path", readme)
            self.assertIn("Verify the applied seed evidence", readme)
            self.assertIn("seed evidence verifier/ingest", readme)
            self.assertIn("Seed evidence PASS is not Direct-STT acceptance", readme)
            self.assertIn("Gate 1", readme)
            self.assertIn("Gate 2", readme)
            self.assertIn("Gate 3", readme)
            self.assertIn("Reviewer acceptance is required", readme)

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

    def test_rejects_absolute_evidence_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_script(
                "--output-dir",
                tmpdir,
                "--preflight-evidence-path",
                "/tmp/faz24-direct-stt.json",
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("must be a relative path", result.stderr)

    def test_rejects_invalid_transcribe_ip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_script(
                "--output-dir",
                tmpdir,
                "--transcribe-ip",
                "999.10.1.1",
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("must be an IPv4 address", result.stderr)

    def test_workflow_contract(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("faz24-direct-stt-operator-handoff-${{ github.run_id }}", workflow)
        self.assertIn("does not connect to Vault, Kubernetes, Denetim PC, or production", workflow)
        self.assertIn("does not read or write credentials", workflow)
        self.assertIn('(cd "${HANDOFF_DIR}" && sha256sum --check SHA256SUMS)', workflow)
        self.assertIn('"faz24.directStt.operator-handoff.v1"', workflow)
        self.assertIn('--operator-batch-id "${OPERATOR_BATCH_ID}"', workflow)
        self.assertIn("reject_unsupported_chars operator_batch_id", workflow)
        self.assertIn("reject_path_escape preflight_evidence_path", workflow)
        self.assertIn("EXPECTED_KUBE_CONTEXT", workflow)
        self.assertIn('os.environ["EXPECTED_KUBE_CONTEXT"]', workflow)
        self.assertNotIn("--operator-batch-id ${{ inputs.operator_batch_id }}", workflow)
        self.assertNotIn('data["target"]["kubeContext"] == "${{ inputs.kube_context }}"', workflow)
        self.assertLessEqual(workflow.count("description:"), 6)


if __name__ == "__main__":
    unittest.main()
