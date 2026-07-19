#!/usr/bin/env python3
"""Regression tests for the exact-scope PII review attestation helper."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/ai/attest_cross_ai_scope_pii.py"
FAKE_GH = r'''#!/usr/bin/env python3
import json
import os
import sys

path = sys.argv[sys.argv.index("api") + 1]
login = os.environ.get("FAKE_GH_LOGIN", "Halildeu")
if path == "user":
    print(json.dumps({"login": login, "id": 101}))
elif path == "repos/Halildeu/platform-k8s-gitops":
    print(json.dumps({
        "id": 202,
        "full_name": "Halildeu/platform-k8s-gitops",
        "owner": {"login": "Halildeu", "id": 101},
        "permissions": {"admin": os.environ.get("FAKE_GH_ADMIN", "1") == "1"},
    }))
else:
    raise SystemExit(2)
'''


class ScopePiiAttestationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.scope = self.root / "scope.patch"
        self.scope.write_text("diff --git a/a b/a\n+safe change\n", encoding="utf-8")
        self.scope.chmod(0o600)
        self.digest = hashlib.sha256(self.scope.read_bytes()).hexdigest()
        self.output = self.root / "pii-attestation.json"
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()
        gh = self.bin_dir / "gh"
        gh.write_text(FAKE_GH, encoding="utf-8")
        gh.chmod(0o700)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_helper(self, **environment: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--scope-file",
                str(self.scope),
                "--scope-sha256",
                self.digest,
                "--decision",
                "no-sensitive-pii",
                "--repo",
                "Halildeu/platform-k8s-gitops",
                "--output",
                str(self.output),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={
                **os.environ,
                "PATH": f"{self.bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
                **environment,
            },
            check=False,
        )

    def test_creates_owner_only_exact_scope_attestation_once(self) -> None:
        result = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        receipt = json.loads(result.stdout)
        attestation = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertTrue(receipt["ok"])
        self.assertEqual(attestation["scope_sha256"], self.digest)
        self.assertEqual(attestation["decision"], "no-sensitive-pii")
        self.assertEqual(attestation["repository"], "Halildeu/platform-k8s-gitops")
        self.assertEqual(attestation["repository_id"], 202)
        self.assertEqual(attestation["reviewer_login"], "Halildeu")
        self.assertEqual(attestation["reviewer_id"], 101)
        self.assertEqual(
            attestation["reviewer_role"], "authenticated-repository-owner"
        )
        self.assertEqual(os.stat(self.output).st_mode & 0o777, 0o600)
        self.assertEqual(
            receipt["attestation_sha256"],
            hashlib.sha256(self.output.read_bytes()).hexdigest(),
        )
        second = self.run_helper()
        self.assertNotEqual(second.returncode, 0)
        self.assertIn("pii_attestation_output_exists", second.stdout)

    def test_rejects_wrong_scope_digest(self) -> None:
        self.digest = "f" * 64
        result = self.run_helper()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("scope_identity_unverifiable", result.stdout)
        self.assertFalse(self.output.exists())

    def test_rejects_authenticated_non_owner_or_non_admin(self) -> None:
        for environment in (
            {"FAKE_GH_LOGIN": "contributor"},
            {"FAKE_GH_ADMIN": "0"},
        ):
            with self.subTest(environment=environment):
                result = self.run_helper(**environment)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("pii_reviewer_not_repository_owner", result.stdout)
                self.assertFalse(self.output.exists())

    def test_rejects_scope_readable_by_group_or_other(self) -> None:
        self.scope.chmod(0o644)
        result = self.run_helper()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("scope_identity_unverifiable", result.stdout)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
