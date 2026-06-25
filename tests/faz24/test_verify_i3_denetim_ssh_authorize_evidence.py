#!/usr/bin/env python3
"""Tests for Denetim SSH authorization evidence verifier."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "faz24" / "verify-i3-denetim-ssh-authorize-evidence.py"


def valid_evidence() -> dict:
    return {
        "schemaVersion": "faz24.i3.denetim.ssh-authorize-package.v1.evidence",
        "collectedAt": "2026-06-25T02:55:00Z",
        "status": "pass",
        "reason": "authorized-key-added",
        "targetUser": "svc-denetim-agent",
        "expectedPublicKeyFingerprint": "SHA256:4hWKcV0D3yrRfW4srj0mQJb+297J+RnS0HuoR0D6t1Y",
        "expectedPublicKeyLineSha256": "83f4788c09f9d7e68af113e9680c4a996f95a66c230d6240780ace47734844ff",
        "expectedPublicKeyBlobSha256": "e2158a715d03df2ad17d6e2cae3d264096fedbdec9f919d2d07ba84740fab756",
        "privateKeyIncluded": False,
        "rawPublicKeyIncluded": False,
        "publicKeyFingerprint": "SHA256:4hWKcV0D3yrRfW4srj0mQJb+297J+RnS0HuoR0D6t1Y",
        "publicKeyLineSha256": "83f4788c09f9d7e68af113e9680c4a996f95a66c230d6240780ace47734844ff",
        "publicKeyBlobSha256": "e2158a715d03df2ad17d6e2cae3d264096fedbdec9f919d2d07ba84740fab756",
        "targetUserSidHash": "0123456789abcdef",
        "profilePathHash": "1111111111111111",
        "authorizedKeysPathHash": "2222222222222222",
        "keyAdded": True,
        "keyAlreadyPresent": False,
        "aclHardened": True,
        "sshdServiceStatusBefore": "Running",
        "sshdServiceStatusAfter": "Running",
        "sshdRestartAttempted": False,
    }


class VerifyI3DenetimSshAuthorizeEvidenceTest(unittest.TestCase):
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
        self.assertIn("Faz24 I3 Denetim SSH authorize evidence: PASS", result.stdout)
        self.assertIn("targetUser=svc-denetim-agent", result.stdout)

    def test_bootstrap_evidence_passes_when_consistent(self):
        data = valid_evidence()
        data.update(
            {
                "targetUserCreated": True,
                "targetUserExisted": False,
                "targetUserEnabled": True,
                "eventLogReadersGrantAttempted": True,
                "eventLogReadersMembershipPresent": True,
                "profileRegistryPresent": False,
                "profileCreated": True,
                "profileFallbackUsed": True,
            }
        )

        result = self.run_verifier(data)

        self.assertEqual(0, result.returncode, result.stderr)

    def test_blocked_status_fails(self):
        data = valid_evidence()
        data["status"] = "blocked"
        data["reason"] = "sshd-not-running"

        result = self.run_verifier(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("status", result.stderr)
        self.assertIn("reason", result.stderr)

    def test_mismatched_public_key_fingerprint_fails(self):
        data = valid_evidence()
        data["publicKeyFingerprint"] = "SHA256:wrong"

        result = self.run_verifier(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("public_key_fingerprint", result.stderr)

    def test_raw_public_key_or_secret_like_values_fail(self):
        data = valid_evidence()
        data["rawPublicKeyIncluded"] = True
        data["note"] = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMzC3yE2lx5RynM5tb6xY+a/+ye/MzZAAodDECoHS+il"

        result = self.run_verifier(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("flag_must_be_false", result.stderr)
        self.assertIn("secret_like_value", result.stderr)

    def test_raw_windows_profile_paths_fail(self):
        data = valid_evidence()
        data["operatorNote"] = r"C:\Users\svc-denetim-agent\.ssh\authorized_keys"

        result = self.run_verifier(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("secret_like_value", result.stderr)

    def test_sshd_must_be_running_for_pass(self):
        data = valid_evidence()
        data["sshdServiceStatusAfter"] = "Stopped"

        result = self.run_verifier(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("sshd_service_status", result.stderr)

    def test_key_added_and_already_present_are_mutually_exclusive(self):
        data = valid_evidence()
        data["keyAlreadyPresent"] = True

        result = self.run_verifier(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("key_presence", result.stderr)

    def test_event_log_reader_attempt_requires_membership(self):
        data = valid_evidence()
        data["eventLogReadersGrantAttempted"] = True
        data["eventLogReadersMembershipPresent"] = False

        result = self.run_verifier(data)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("event_log_readers_membership", result.stderr)


if __name__ == "__main__":
    unittest.main()
