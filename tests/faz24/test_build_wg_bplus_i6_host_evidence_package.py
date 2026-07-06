#!/usr/bin/env python3
"""Tests for the Faz 24 WG-B+ I6 host evidence package builder."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "faz24" / "build-wg-bplus-i6-host-evidence-package.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "faz24-wg-bplus-i6-host-evidence-package.yml"


class BuildWgBplusI6HostEvidencePackageTest(unittest.TestCase):
    def run_script(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_builds_metadata_only_operator_package(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_script(
                "--output-dir",
                tmpdir,
                "--target-host",
                "staging-sw",
                "--pod-cidr",
                "10.42.0.0/16",
                "--wg-interface",
                "auto",
                "--rollback-tested-ref",
                "rollback/k3d-wg-masq-dry-run.json",
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("status=pass", result.stdout)

            output = Path(tmpdir)
            expected_files = {
                "collect-staging-i6-host-evidence.sh",
                "expected-i6-host-evidence-metadata.json",
                "README.md",
                "SHA256SUMS",
            }
            self.assertEqual(expected_files, {path.name for path in output.iterdir()})

            wrapper = output / "collect-staging-i6-host-evidence.sh"
            self.assertTrue(os.access(wrapper, os.X_OK))
            self.assertTrue(wrapper.stat().st_mode & stat.S_IXUSR)

            metadata = json.loads(
                (output / "expected-i6-host-evidence-metadata.json").read_text(encoding="utf-8")
            )
            self.assertEqual("faz24.i6.host-evidence-package.v1", metadata["schemaVersion"])
            self.assertEqual("staging-sw", metadata["targetHost"])
            self.assertEqual("10.42.0.0/16", metadata["defaults"]["podCIDR"])
            self.assertFalse(metadata["boundary"]["hostMutationByPackageBuild"])
            self.assertFalse(metadata["boundary"]["hostMutationByWrapper"])
            self.assertFalse(metadata["redaction"]["rawCommandOutputIncluded"])

            all_text = "\n".join(path.read_text(encoding="utf-8") for path in output.iterdir())
            self.assertNotIn("BEGIN OPENSSH PRIVATE KEY", all_text)
            self.assertNotIn("Bearer ", all_text)
            self.assertNotIn("eyJ", json.dumps(metadata))
            self.assertIn("--protected-evidence-path", wrapper.read_text(encoding="utf-8"))
            self.assertIn("faz24-wg-bplus-i6-masq-evidence-ingest.yml", wrapper.read_text(encoding="utf-8"))

            sha_result = subprocess.run(
                ["sha256sum", "--check", "SHA256SUMS"],
                text=True,
                capture_output=True,
                cwd=tmpdir,
                check=False,
            )
            self.assertEqual(0, sha_result.returncode, sha_result.stderr)

    def test_rejects_private_key_like_input(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_script(
                "--output-dir",
                tmpdir,
                "--target-host",
                "staging-sw",
                "--rollback-tested-ref",
                "rollback/" + "-----BEGIN OPENSSH " + "PRIVATE KEY-----",
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("must not contain private key or token-like material", result.stderr)

    def test_rejects_parent_traversal_rollback_ref(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_script(
                "--output-dir",
                tmpdir,
                "--target-host",
                "staging-sw",
                "--rollback-tested-ref",
                "../rollback.json",
            )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("must be relative and stay under protected evidence path", result.stderr)

    def test_workflow_uploads_expected_artifact_contract(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("faz24-i6-host-evidence-package-${{ github.run_id }}", workflow)
        self.assertIn('(cd "${PACKAGE_DIR}" && sha256sum --check SHA256SUMS)', workflow)
        self.assertIn("grep -Eq -- '-----BEGIN .*PRIVATE KEY-----", workflow)
        self.assertIn("package contains forbidden private/secret-like material", workflow)
        self.assertIn("does not connect to staging-sw", workflow)


if __name__ == "__main__":
    unittest.main()
