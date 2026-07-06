#!/usr/bin/env python3
"""Tests for the Faz 22.6 Denetim SSH key evidence verifier."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "faz22-remote-ops" / "verify-denetim-ssh-key-evidence.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "faz22-6-denetim-ssh-key-evidence-ingest.yml"


def valid_evidence() -> dict:
    return {
        "schemaVersion": "faz22.6-denetim-ssh-key-operator-v1",
        "userName": "svc-denetim-agent",
        "userSid": "S-1-5-21-100-200-300-1001",
        "profilePath": r"C:\Users\svc-denetim-agent",
        "authorizedKeysPath": r"C:\Users\svc-denetim-agent\.ssh\authorized_keys",
        "authorizedKeysContainsRunnerPublicKey": True,
        "runnerPublicKeyFingerprint": "SHA256:4hWKcV0D3yrRfW4srj0mQJb+297J+RnS0HuoR0D6t1Y",
        "runnerPublicKeyLineSha256": "83f4788c09f9d7e68af113e9680c4a996f95a66c230d6240780ace47734844ff",
        "sshdStatus": "Running",
        "sshdStartType": "Automatic",
        "isLocalAdministratorMember": False,
        "createdAtUtc": "2026-07-03T01:35:00.0000000Z",
        "evidenceHygiene": {
            "privateKeyIncluded": False,
            "rawSecretIncluded": False,
            "tokenIncluded": False,
            "publicKeyOnly": True,
        },
    }


class Faz226DenetimSshKeyEvidenceVerifierTest(unittest.TestCase):
    def run_verifier(self, data: dict) -> subprocess.CompletedProcess[str]:
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as tmp:
            json.dump(data, tmp)
            tmp.flush()
            return subprocess.run(
                [sys.executable, str(SCRIPT), tmp.name],
                text=True,
                capture_output=True,
                check=False,
            )

    def test_valid_evidence_passes(self):
        result = self.run_verifier(valid_evidence())

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("Faz22.6 Denetim SSH key evidence: PASS", result.stdout)
        self.assertIn("userName=svc-denetim-agent", result.stdout)

    def test_missing_authorized_key_fails(self):
        data = valid_evidence()
        data["authorizedKeysContainsRunnerPublicKey"] = False

        result = self.run_verifier(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("authorizedKeysContainsRunnerPublicKey", result.stderr)

    def test_admin_membership_fails(self):
        data = valid_evidence()
        data["isLocalAdministratorMember"] = True

        result = self.run_verifier(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("isLocalAdministratorMember", result.stderr)

    def test_wrong_public_key_hash_fails(self):
        data = valid_evidence()
        data["runnerPublicKeyLineSha256"] = "0" * 64

        result = self.run_verifier(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("runner_public_key_line_sha256", result.stderr)

    def test_sshd_disabled_or_stopped_fails(self):
        data = valid_evidence()
        data["sshdStatus"] = "Stopped"
        data["sshdStartType"] = "Disabled"

        result = self.run_verifier(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("sshd_status", result.stderr)
        self.assertIn("sshd_start_type", result.stderr)

    def test_secret_like_values_fail(self):
        data = valid_evidence()
        data["operatorNote"] = "Bearer abcdefghijklmnopqrstuvwxyz"

        result = self.run_verifier(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("secret_like_value", result.stderr)

    def test_workflow_is_fail_closed_and_metadata_only(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("RUN_FAZ22_6_DENETIM_SSH_KEY_EVIDENCE_INGEST", workflow)
        self.assertIn("verify-denetim-ssh-key-evidence.py", workflow)
        self.assertIn("issues: write", workflow)
        self.assertIn("Fail workflow when evidence is rejected", workflow)
        self.assertNotIn("continue-on-error: true", workflow)
        self.assertIn("not VIEW_ONLY evidence", workflow)
        self.assertIn("not #1580 marker", workflow)


if __name__ == "__main__":
    unittest.main()
