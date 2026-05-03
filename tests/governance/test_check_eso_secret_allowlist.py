"""Unit tests for DD-EA-5 ESO secret path allowlist gate."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO_ROOT / "scripts" / "governance" / "check_eso_secret_allowlist.py"
FIXTURES = REPO_ROOT / "tests" / "governance" / "fixtures"


def run_script(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )


class TestDdEa5(unittest.TestCase):
    def test_compliant_fixture_returns_pass(self) -> None:
        result = run_script([
            "--fixture", str(FIXTURES / "eso-allowlist-compliant.yaml"),
            "--json",
        ])
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["verdict"], "pass")
        self.assertEqual(len(data["allowed_keys"]), 3)
        self.assertEqual(len(data["violation_keys"]), 0)

    def test_violation_fixture_returns_fail(self) -> None:
        result = run_script([
            "--fixture", str(FIXTURES / "eso-allowlist-violation.yaml"),
            "--json",
        ])
        self.assertEqual(result.returncode, 1)
        data = json.loads(result.stdout)
        self.assertEqual(data["verdict"], "fail")
        self.assertEqual(len(data["violation_keys"]), 3)
        violations_text = json.dumps(data["violation_keys"])
        # Code signing key supply-chain boundary korumalı
        self.assertIn("code-signing-key", violations_text)
        # Diğer servis path scope'u
        self.assertIn("permission-service", violations_text)
        # Global path allowlist dışı
        self.assertIn("kv/global", violations_text)

    def test_strict_allowlist_no_wildcard(self) -> None:
        """Verify ALLOWED_KEYS exact-match enforcement, no wildcard prefix."""
        # code-signing-key kv/platform/endpoint-admin/ ile başlasa bile reject
        result = run_script([
            "--fixture", str(FIXTURES / "eso-allowlist-violation.yaml"),
            "--json",
        ])
        data = json.loads(result.stdout)
        violations_text = json.dumps(data["violation_keys"])
        self.assertIn(
            "kv/platform/endpoint-admin/code-signing-key", violations_text,
            msg="Strict allowlist code-signing-key reject etmeli "
                "(supply-chain pipeline boundary)",
        )

    def test_allowed_keys_constant_matches_adr_spec(self) -> None:
        """ALLOWED_KEYS exactly matches ADR-0012-EA §111-117 list."""
        # Direct import to verify constant
        sys.path.insert(0, str(REPO_ROOT / "scripts" / "governance"))
        try:
            from check_eso_secret_allowlist import (  # type: ignore[import-not-found]
                ALLOWED_KEYS,
            )
        finally:
            sys.path.pop(0)

        expected = {
            "kv/platform/endpoint-admin/oidc-client-secret",
            "kv/platform/endpoint-admin/audit-log-dsn",
            "kv/platform/endpoint-admin/ad-bind-credentials",
            "kv/platform/endpoint-admin/entra-app-credentials",
            "kv/platform/endpoint-admin/internal-api-key",
            "kv/platform/endpoint-admin/agent-enrollment-secret",
        }
        self.assertEqual(ALLOWED_KEYS, frozenset(expected))


if __name__ == "__main__":
    unittest.main()
