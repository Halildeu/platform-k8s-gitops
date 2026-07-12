#!/usr/bin/env python3
"""Tests for the Faz 24 I3 Denetim SSH authorization package builder."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "faz24" / "build-i3-denetim-ssh-authorize-package.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "faz24-i3-denetim-ssh-authorize-package.yml"
INGEST_WORKFLOW = (
    REPO_ROOT / ".github" / "workflows" / "faz24-i3-denetim-ssh-authorize-evidence-ingest.yml"
)

SAMPLE_PUBLIC_KEY = (
    "ssh-ed25519 "
    "AAAAC3NzaC1lZDI1NTE5AAAAIMzC3yE2lx5RynM5tb6xY+a/+ye/MzZAAodDECoHS+il "
    "unit-test-faz24"
)

spec = importlib.util.spec_from_file_location("build_i3_denetim_ssh_authorize_package", SCRIPT)
package_builder = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = package_builder
spec.loader.exec_module(package_builder)


class BuildI3DenetimSshAuthorizePackageTest(unittest.TestCase):
    def run_script(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_builds_public_key_only_operator_package(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_script(
                "--public-key",
                SAMPLE_PUBLIC_KEY,
                "--output-dir",
                tmpdir,
                "--target-user",
                "svc-denetim-agent",
                "--source-identity-run-id",
                "28142166373",
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("status=pass", result.stdout)

            output = Path(tmpdir)
            expected_files = {
                "authorize-denetim-i3-public-key.ps1",
                "expected-public-key-metadata.json",
                "faz24-i3-denetim_ed25519.pub",
                "README.md",
                "SHA256SUMS",
            }
            self.assertEqual(expected_files, {path.name for path in output.iterdir()})

            metadata = json.loads((output / "expected-public-key-metadata.json").read_text(encoding="utf-8"))
            self.assertEqual("faz24.i3.denetim.ssh-authorize-package.v1", metadata["schemaVersion"])
            self.assertEqual("svc-denetim-agent", metadata["targetUser"])
            self.assertEqual("28142166373", metadata["sourceIdentityRunId"])
            self.assertFalse(metadata["privateKeyIncluded"])
            self.assertFalse(metadata["rawPublicKeyIncludedInMetadata"])
            self.assertTrue(metadata["supportsTargetUserBootstrap"])
            self.assertEqual(["CreateTargetUser", "GrantEventLogReaders"], metadata["recommendedMissingUserFlags"])
            self.assertEqual("unit-test-faz24", metadata["publicKeyComment"])
            self.assertTrue(metadata["publicKeyFingerprint"].startswith("SHA256:"))
            self.assertNotIn(SAMPLE_PUBLIC_KEY, json.dumps(metadata))

            all_text = "\n".join(path.read_text(encoding="utf-8") for path in output.iterdir())
            self.assertNotIn("BEGIN OPENSSH PRIVATE KEY", all_text)
            self.assertNotIn("Bearer ", all_text)
            self.assertNotIn("eyJ", json.dumps(metadata))
            self.assertIn(SAMPLE_PUBLIC_KEY, (output / "faz24-i3-denetim_ed25519.pub").read_text(encoding="utf-8"))
            powershell = (output / "authorize-denetim-i3-public-key.ps1").read_text(encoding="utf-8")
            self.assertIn("administrator-required", powershell)
            self.assertIn("sshd-not-running", powershell)
            self.assertIn("$sshdStatusAfter -ne 'Running'", powershell)
            self.assertIn("[switch]$CreateTargetUser", powershell)
            self.assertIn("[switch]$GrantEventLogReaders", powershell)
            self.assertIn("target-user-not-found", powershell)
            self.assertIn("New-RandomSecurePassword", powershell)
            self.assertIn("Get-LocalGroup -SID $groupSid.Value", powershell)
            self.assertIn("New-Object Text.UTF8Encoding($false)", powershell)
            self.assertNotIn("Out-File -LiteralPath $EvidencePath -Encoding utf8", powershell)
            readme = (output / "README.md").read_text(encoding="utf-8")
            self.assertIn("Event Log Readers", readme)
            self.assertIn("Administrators read-only", readme)

    def test_rejects_private_key_material(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_script(
                "--public-key",
                "-----BEGIN OPENSSH PRIVATE KEY-----",
                "--output-dir",
                tmpdir,
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("private key material is not accepted", result.stderr)

    def test_rejects_multiline_public_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_script(
                "--public-key",
                SAMPLE_PUBLIC_KEY + "\n" + SAMPLE_PUBLIC_KEY,
                "--output-dir",
                tmpdir,
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("public key must be exactly one non-empty line", result.stderr)

    def test_rejects_non_ed25519_key_type(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_script(
                "--public-key",
                SAMPLE_PUBLIC_KEY.replace("ssh-ed25519", "ssh-rsa", 1),
                "--output-dir",
                tmpdir,
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("public key must be an ssh-ed25519 public key line", result.stderr)

    def test_parser_normalizes_trailing_newline_from_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            key_file = Path(tmpdir) / "key.pub"
            key_file.write_text(SAMPLE_PUBLIC_KEY + "\n", encoding="utf-8")
            output_dir = Path(tmpdir) / "package"

            result = self.run_script(
                "--public-key-file",
                str(key_file),
                "--output-dir",
                str(output_dir),
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(
                SAMPLE_PUBLIC_KEY + "\n",
                (output_dir / "faz24-i3-denetim_ed25519.pub").read_text(encoding="utf-8"),
            )

    def test_workflow_keeps_input_public_key_outside_package_dir(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn(
            "PUBLIC_KEY_INPUT_FILE: /tmp/faz24-i3-denetim-ssh-authorize-input-${{ github.run_id }}.pub",
            workflow,
        )
        self.assertNotIn("PUBLIC_KEY_INPUT_FILE: /tmp/faz24-i3-denetim-ssh-authorize-package-", workflow)
        self.assertIn('rm -f "${PUBLIC_KEY_INPUT_FILE}"', workflow)

    def test_ingest_workflow_accepts_historical_utf8_bom(self):
        workflow = INGEST_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn('encoding="utf-8-sig"', workflow)


if __name__ == "__main__":
    unittest.main()
