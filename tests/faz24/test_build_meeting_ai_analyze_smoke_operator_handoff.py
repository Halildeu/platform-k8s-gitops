#!/usr/bin/env python3
"""Tests for the Faz 24 Meeting AI analyze smoke operator handoff builder."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "faz24" / "build-meeting-ai-analyze-smoke-operator-handoff.py"
WORKFLOW = (
    REPO_ROOT
    / ".github"
    / "workflows"
    / "faz24-meeting-ai-analyze-smoke-operator-handoff.yml"
)


class BuildMeetingAiAnalyzeSmokeOperatorHandoffTest(unittest.TestCase):
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
                    "faz24-meeting-ai-analyze-smoke-operator-handoff.json",
                },
                {path.name for path in output.iterdir()},
            )

            manifest = json.loads(
                (
                    output / "faz24-meeting-ai-analyze-smoke-operator-handoff.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(
                "faz24.meetingAiAnalyzeSmoke.operator-handoff.v1",
                manifest["schemaVersion"],
            )
            self.assertEqual(
                "faz24-analyze-smoke-20260713", manifest["operatorBatchId"]
            )
            self.assertEqual(
                "platform-k8s-gitops#1615", manifest["issues"]["gitopsRollup"]
            )
            self.assertEqual(
                "platform-k8s-gitops#2186",
                manifest["issues"]["transcriptDeliveryRollout"],
            )
            self.assertEqual(
                "platform-k8s-gitops#2263", manifest["issues"]["analyzeSmokeTooling"]
            )

            acceptance = manifest["acceptanceBoundary"]
            self.assertEqual("needs-runtime-smoke", acceptance["issueStatus"])
            self.assertTrue(acceptance["operatorExecutionRequired"])
            self.assertTrue(acceptance["stagingReachabilityRestoreRequired"])
            self.assertTrue(acceptance["scopedTestTokenSeedRequired"])
            self.assertTrue(acceptance["analyzeSmokeExecutionRequired"])
            self.assertTrue(acceptance["analyzeVerifierPassRequired"])
            self.assertTrue(acceptance["reviewerAcceptanceRequired"])
            self.assertTrue(acceptance["doesNotSeedToken"])
            self.assertTrue(acceptance["doesNotRunSmoke"])
            self.assertTrue(acceptance["doesNotConnectStaging"])
            self.assertTrue(acceptance["doesNotAcceptDesktopLiveSmoke"])
            self.assertTrue(acceptance["doesNotAcceptGpuHostStt"])
            self.assertTrue(acceptance["doesNotAcceptProductionReadiness"])
            self.assertTrue(acceptance["doesNotAcceptLegalGo"])

            mutation = manifest["mutationBoundary"]
            self.assertFalse(mutation["packageBuildEvidenceMutation"])
            self.assertFalse(mutation["packageBuildClusterMutation"])
            self.assertFalse(mutation["packageBuildTokenMutation"])
            self.assertFalse(mutation["packageBuildKeycloakMutation"])
            self.assertFalse(mutation["packageBuildHostMutation"])
            self.assertFalse(mutation["packageBuildNetworkMutation"])
            self.assertFalse(mutation["containsCredentials"])
            self.assertFalse(mutation["containsTokens"])
            self.assertFalse(mutation["containsSourceText"])
            self.assertFalse(mutation["containsAnalyzeOutput"])
            self.assertFalse(mutation["containsPii"])

            target = manifest["target"]
            self.assertEqual("staging-sw", target["stagingHost"])
            self.assertEqual("https://testai.acik.com", target["baseUrl"])
            self.assertEqual(
                "https://testai.acik.com/realms/platform-test",
                target["expectedIssuer"],
            )
            self.assertEqual("/api/v1/admin/meetings", target["externalMeetingsPath"])
            self.assertEqual("/intelligence/analyze", target["analyzePathSuffix"])
            self.assertEqual(
                "scripts/faz24/run_meeting_ai_analyze_smoke.py", target["runScript"]
            )
            self.assertEqual(
                "scripts/faz24/verify_meeting_ai_analyze_smoke_evidence.py",
                target["verifier"],
            )
            self.assertEqual("platform-k8s-gitops#2263", target["toolingSource"])
            self.assertEqual(
                "faz24.meetingAiAnalyzeSmoke.v1", target["evidenceSchema"]
            )
            self.assertEqual(
                "faz24.meetingAiAnalyzeSmokeVerifier.v1", target["verifierSchema"]
            )
            self.assertEqual(
                ["token_contract", "create_meeting", "meeting_ai_analyze"],
                target["requiredSteps"],
            )

            layers = manifest["requiredEvidenceLayers"]
            self.assertIn("testai-base-url-reachable", layers["up"])
            self.assertIn(
                "create_meeting-POST-/api/v1/admin/meetings-201", layers["functional"]
            )
            self.assertIn("structured-analyze-envelope", layers["functional"])
            self.assertIn("tokenIncluded==false", layers["secured"])
            self.assertIn("rawSourceTextIncluded==false", layers["secured"])
            self.assertIn("erpSpecificContract==false", layers["secured"])

            self.assertEqual(
                [
                    "staging-reachability-restore",
                    "scoped-test-token-seed",
                    "analyze-smoke-execution",
                    "evidence-verify",
                    "reviewer-acceptance",
                ],
                [gate["id"] for gate in manifest["orderedGates"]],
            )
            gates = {gate["id"]: gate for gate in manifest["orderedGates"]}
            self.assertIn(
                "run_meeting_ai_analyze_smoke.py",
                gates["analyze-smoke-execution"]["commands"]["run"],
            )
            self.assertIn(
                "verify_meeting_ai_analyze_smoke_evidence.py",
                gates["evidence-verify"]["commands"]["verify"],
            )
            self.assertIn(
                "faz24.meetingAiAnalyzeSmokeVerifier.v1",
                gates["evidence-verify"]["commands"]["verify"],
            )

            readme = (output / "README.md").read_text(encoding="utf-8")
            self.assertIn("coordination artifact only", readme)
            self.assertIn("Gate 0", readme)
            self.assertIn("Gate 1", readme)
            self.assertIn("Gate 2", readme)
            self.assertIn("Gate 3", readme)
            self.assertIn("Gate 4", readme)
            self.assertIn("A single analyze 200 is not acceptance", readme)

            all_text = "\n".join(
                path.read_text(encoding="utf-8") for path in output.iterdir()
            )
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

    def test_rejects_non_https_base_url(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_script(
                "--output-dir",
                tmpdir,
                "--base-url",
                "http://testai.acik.com",
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("must be an https:// URL", result.stderr)

    def test_rejects_path_escape_evidence_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_script(
                "--output-dir",
                tmpdir,
                "--evidence-path",
                "../faz24-meeting-ai-analyze-smoke.json",
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("must not escape the handoff boundary", result.stderr)

    def test_rejects_non_tmp_absolute_evidence_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_script(
                "--output-dir",
                tmpdir,
                "--evidence-path",
                "/etc/faz24-meeting-ai-analyze-smoke.json",
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("absolute paths are only allowed under /tmp", result.stderr)

    def test_workflow_contract(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn('default: "faz24-analyze-smoke-20260713"', workflow)
        self.assertIn(
            "faz24-meeting-ai-analyze-smoke-operator-handoff-${{ github.run_id }}",
            workflow,
        )
        self.assertIn("does not connect to staging-sw", workflow)
        self.assertIn('(cd "${HANDOFF_DIR}" && sha256sum --check SHA256SUMS)', workflow)
        self.assertIn('"faz24.meetingAiAnalyzeSmoke.operator-handoff.v1"', workflow)
        self.assertIn('--operator-batch-id "${OPERATOR_BATCH_ID}"', workflow)
        self.assertIn('--base-url "${BASE_URL}"', workflow)
        self.assertIn('--expected-issuer "${EXPECTED_ISSUER}"', workflow)
        self.assertIn("scopedTestTokenSeedRequired", workflow)
        self.assertIn("packageBuildTokenMutation", workflow)
        self.assertIn("containsTokens", workflow)
        self.assertIn("containsSourceText", workflow)
        self.assertIn("reject_url_chars base_url", workflow)
        self.assertIn("reject_url_chars expected_issuer", workflow)
        self.assertIn("reject_path_chars evidence_path", workflow)
        self.assertIn("hvs\\.[A-Za-z0-9._-]+", workflow)
        self.assertNotIn("--base-url ${{ inputs.base_url }}", workflow)


if __name__ == "__main__":
    unittest.main()
