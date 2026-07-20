#!/usr/bin/env python3
"""Regression tests for the exact-scope PII review attestation helper."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/ai/attest_cross_ai_scope_pii.py"
SPEC = importlib.util.spec_from_file_location("attest_cross_ai_scope_pii", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
FAKE_GH = r'''#!/usr/bin/env python3
import json
import os
import sys

if sys.argv[1:] == ["--version"]:
    print("gh version 2.92.0 (2026-04-28)")
    raise SystemExit(0)
path = sys.argv[sys.argv.index("--hostname") + 2]
login = os.environ.get("FAKE_GH_LOGIN", "Halildeu")
if path == "user":
    print(json.dumps({
        "login": login,
        "id": 101,
        "url": f"https://api.github.com/users/{login}",
        "html_url": f"https://github.com/{login}",
    }))
elif path == "repos/Halildeu/platform-k8s-gitops":
    print(json.dumps({
        "id": 202,
        "full_name": "Halildeu/platform-k8s-gitops",
        "url": "https://api.github.com/repos/Halildeu/platform-k8s-gitops",
        "html_url": "https://github.com/Halildeu/platform-k8s-gitops",
        "owner": {
            "login": "Halildeu",
            "id": 101,
            "url": "https://api.github.com/users/Halildeu",
            "html_url": "https://github.com/Halildeu",
        },
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
        self.gh = gh
        self.trusted_pins = {
            ("2.92.0", "gh-darwin-arm64"): hashlib.sha256(
                gh.read_bytes()
            ).hexdigest()
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_helper(self, **environment: str) -> subprocess.CompletedProcess[str]:
        arguments = [
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
        ]
        env = {
                **os.environ,
                "PATH": f"{self.bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
                **environment,
        }
        stdout = io.StringIO()
        stderr = io.StringIO()
        returncode = 0
        with (
            mock.patch.object(sys, "argv", arguments),
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.object(
                MODULE, "TRUSTED_GH_NATIVE_SHA256", self.trusted_pins
            ),
            mock.patch.object(
                MODULE.platform, "system", return_value="Darwin"
            ),
            mock.patch.object(
                MODULE.platform, "machine", return_value="arm64"
            ),
            mock.patch("sys.stdout", stdout),
            mock.patch("sys.stderr", stderr),
        ):
            try:
                MODULE.main()
            except SystemExit as exc:
                returncode = int(exc.code or 0)
        return subprocess.CompletedProcess(
            arguments, returncode, stdout.getvalue(), stderr.getvalue()
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

    def test_rejects_unpinned_path_gh_before_identity_api_calls(self) -> None:
        self.trusted_pins = {}
        result = self.run_helper()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("gh_native_untrusted", result.stdout)
        self.assertFalse(self.output.exists())

    def test_accepts_an_explicit_pin_from_a_bounded_platform_pin_set(self) -> None:
        digest = hashlib.sha256(self.gh.read_bytes()).hexdigest()
        self.trusted_pins = {
            ("2.92.0", "gh-darwin-arm64"): ("0" * 64, digest)
        }
        result = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
