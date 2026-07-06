"""
tests/promotion/test_d29_evidence_policy.py

Unit tests for scripts/promotion/d29_evidence_policy.py.

Scope:
- check_tiers() policy semantics across the 7 representative cases
  (strict GREEN-only, lenient GREEN-or-AMBER, unknown service default,
   d29_up degraded, d29_functional degraded, malformed tiers, missing tier)
- load_jwt_validates_map() reads a temp services.yaml fixture
- CLI mode (check-tiers subcommand) exit codes 0 / 1 / 2

Run:
    python3 -m unittest tests.promotion.test_d29_evidence_policy -v
or
    pytest tests/promotion/test_d29_evidence_policy.py -v

Pattern: same as tests/alerting/test_alertmanager_bridge.py (stdlib unittest,
no external test framework dependency; runs in any Python 3.10+ environment).
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


# --- Module loader -----------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MODULE_PATH = _REPO_ROOT / "scripts" / "promotion" / "d29_evidence_policy.py"


def _load_module():
    """Import d29_evidence_policy.py as a module via importlib.

    Using importlib (not regular `import`) because the script path has hyphens
    in its parent directory naming and is not on sys.path by default.
    """
    spec = importlib.util.spec_from_file_location(
        "d29_evidence_policy", _MODULE_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- Tier-policy unit tests --------------------------------------------------


class CheckTiersTests(unittest.TestCase):
    """Cover the 4 explicit policy cases from the plan + 3 edge cases."""

    def setUp(self) -> None:
        self.mod = _load_module()
        # Representative jwt_validates_map: backend strict, frontend lenient.
        self.jwt_map = {
            "user-service": True,        # strict (zanzibar GREEN required)
            "auth-service": False,       # lenient (Codex iter-2: KC issuer, no own decoder)
            "frontend": False,           # lenient SPA (ADR-0022)
            "core-data-service": True,   # strict
            # Intentionally NOT listing "future-service" — tests the default.
        }

    def _tiers(
        self,
        up: str = "GREEN",
        functional: str = "GREEN",
        zanzibar: str = "GREEN",
    ) -> dict:
        return {
            "d29_up": {"status": up, "checked_at": "2026-05-21T00:00:00Z", "details": ""},
            "d29_functional": {
                "status": functional,
                "checked_at": "2026-05-21T00:00:00Z",
                "details": "",
                "endpoints": [],
            },
            "d29_zanzibar": {
                "status": zanzibar,
                "checked_at": "2026-05-21T00:00:00Z",
                "details": "",
                "allow_deny_synthetic": "PASS" if zanzibar == "GREEN" else "SKIP",
            },
        }

    # 4 explicit policy cases from the plan -----------------------------------

    def test_backend_zanzibar_green_marks(self) -> None:
        ok, reason = self.mod.check_tiers(
            "user-service",
            self._tiers(up="GREEN", functional="GREEN", zanzibar="GREEN"),
            self.jwt_map,
        )
        self.assertTrue(ok, msg=reason)
        self.assertIn("GREEN-required", reason)

    def test_backend_zanzibar_amber_skips(self) -> None:
        ok, reason = self.mod.check_tiers(
            "user-service",
            self._tiers(up="GREEN", functional="GREEN", zanzibar="AMBER"),
            self.jwt_map,
        )
        self.assertFalse(ok, msg=reason)
        self.assertIn("d29_zanzibar status=AMBER", reason)
        self.assertIn("Zanzibar-required", reason)

    def test_frontend_zanzibar_amber_marks(self) -> None:
        ok, reason = self.mod.check_tiers(
            "frontend",
            self._tiers(up="GREEN", functional="GREEN", zanzibar="AMBER"),
            self.jwt_map,
        )
        self.assertTrue(ok, msg=reason)
        self.assertIn("GREEN-or-AMBER", reason)
        self.assertIn("AMBER", reason)

    def test_frontend_zanzibar_red_skips(self) -> None:
        ok, reason = self.mod.check_tiers(
            "frontend",
            self._tiers(up="GREEN", functional="GREEN", zanzibar="RED"),
            self.jwt_map,
        )
        self.assertFalse(ok, msg=reason)
        self.assertIn("d29_zanzibar status=RED", reason)
        self.assertIn("jwt_validates=false", reason)

    # Edge cases --------------------------------------------------------------

    def test_missing_service_strict_default(self) -> None:
        """Unknown service defaults to strict (fail-closed) — AMBER on zanzibar skips."""
        ok, reason = self.mod.check_tiers(
            "future-service-not-in-catalog",
            self._tiers(zanzibar="AMBER"),
            self.jwt_map,
        )
        self.assertFalse(ok, msg=reason)
        self.assertIn("Zanzibar-required", reason)

    def test_d29_up_amber_skips_even_for_lenient_service(self) -> None:
        """d29_up is always strict GREEN, regardless of jwt_validates."""
        ok, reason = self.mod.check_tiers(
            "frontend",
            self._tiers(up="AMBER", functional="GREEN", zanzibar="AMBER"),
            self.jwt_map,
        )
        self.assertFalse(ok, msg=reason)
        self.assertIn("d29_up status=AMBER", reason)

    def test_d29_functional_red_skips_even_for_lenient_service(self) -> None:
        """d29_functional is always strict GREEN, regardless of jwt_validates."""
        ok, reason = self.mod.check_tiers(
            "frontend",
            self._tiers(up="GREEN", functional="RED", zanzibar="AMBER"),
            self.jwt_map,
        )
        self.assertFalse(ok, msg=reason)
        self.assertIn("d29_functional status=RED", reason)

    def test_malformed_tiers_returns_false(self) -> None:
        ok, reason = self.mod.check_tiers("frontend", "not-a-dict", self.jwt_map)  # type: ignore[arg-type]
        self.assertFalse(ok)
        self.assertIn("malformed report", reason)

    def test_missing_tier_status_treated_as_missing(self) -> None:
        tiers = {
            "d29_up": {"status": "GREEN"},
            "d29_functional": {},  # no status key
            "d29_zanzibar": {"status": "GREEN"},
        }
        ok, reason = self.mod.check_tiers("frontend", tiers, self.jwt_map)
        self.assertFalse(ok)
        self.assertIn("d29_functional status=MISSING", reason)


# --- load_jwt_validates_map() ------------------------------------------------


class LoadJwtValidatesMapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = _load_module()
        try:
            import yaml  # noqa: F401
            self.yaml_available = True
        except ImportError:
            self.yaml_available = False

    def _write_catalog(self, repo_root: Path, body: str) -> Path:
        (repo_root / "docs" / "operations").mkdir(parents=True, exist_ok=True)
        path = repo_root / "docs" / "operations" / "services.yaml"
        path.write_text(body)
        return path

    def test_loads_jwt_validates_correctly(self) -> None:
        if not self.yaml_available:
            self.skipTest("PyYAML not available in test env")
        body = textwrap.dedent(
            """\
            schema_version: "1.0"
            services:
              - name: alpha
                repo: platform-backend
                jwt_validates: true
                environments: {test: enabled, prod: enabled}
              - name: bravo
                repo: platform-backend
                jwt_validates: false
                environments: {test: enabled, prod: enabled}
              - name: charlie
                repo: platform-web
                # jwt_validates absent → default True
                environments: {test: enabled, prod: enabled}
            """
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_catalog(root, body)
            m = self.mod.load_jwt_validates_map(root)
        self.assertEqual(m, {"alpha": True, "bravo": False, "charlie": True})

    def test_missing_catalog_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            m = self.mod.load_jwt_validates_map(Path(tmp))
        self.assertEqual(m, {})

    def test_malformed_yaml_returns_empty(self) -> None:
        if not self.yaml_available:
            self.skipTest("PyYAML not available — malformed-yaml path tested in PyYAML branch only")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_catalog(root, "this: is: not: yaml:\n  - [invalid")
            m = self.mod.load_jwt_validates_map(root)
        self.assertEqual(m, {})


# --- CLI subcommand integration ---------------------------------------------


class CliCheckTiersTests(unittest.TestCase):
    """Exercise the `check-tiers` subcommand via subprocess to lock in
    the exit-code contract that ledger-mark-verified.sh depends on."""

    def setUp(self) -> None:
        self.script = _MODULE_PATH

    def _write_report(self, body: dict) -> Path:
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        )
        json.dump(body, tmp)
        tmp.close()
        self.addCleanup(lambda: Path(tmp.name).unlink(missing_ok=True))
        return Path(tmp.name)

    def _run(self, service: str, report: Path, repo_root: Path | None = None) -> subprocess.CompletedProcess[str]:
        cmd = [
            sys.executable,
            str(self.script),
            "check-tiers",
            "--service",
            service,
            "--report",
            str(report),
        ]
        if repo_root is not None:
            cmd.extend(["--repo-root", str(repo_root)])
        return subprocess.run(cmd, capture_output=True, text=True)

    def test_cli_exit_0_on_policy_pass(self) -> None:
        report = self._write_report(
            {
                "tiers": {
                    "d29_up": {"status": "GREEN"},
                    "d29_functional": {"status": "GREEN"},
                    "d29_zanzibar": {"status": "GREEN"},
                }
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs" / "operations").mkdir(parents=True)
            (root / "docs" / "operations" / "services.yaml").write_text(
                "schema_version: '1.0'\nservices:\n  - name: user-service\n    jwt_validates: true\n"
            )
            res = self._run("user-service", report, repo_root=root)
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        self.assertIn("ok=True", res.stderr)

    def test_cli_exit_1_on_policy_fail(self) -> None:
        report = self._write_report(
            {
                "tiers": {
                    "d29_up": {"status": "GREEN"},
                    "d29_functional": {"status": "GREEN"},
                    "d29_zanzibar": {"status": "RED"},
                }
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs" / "operations").mkdir(parents=True)
            (root / "docs" / "operations" / "services.yaml").write_text(
                "schema_version: '1.0'\nservices:\n  - name: frontend\n    jwt_validates: false\n"
            )
            res = self._run("frontend", report, repo_root=root)
        self.assertEqual(res.returncode, 1, msg=res.stderr)
        self.assertIn("ok=False", res.stderr)

    def test_cli_exit_2_on_missing_report(self) -> None:
        res = self._run("frontend", Path("/tmp/definitely-not-existing-report-xyz.json"))
        self.assertEqual(res.returncode, 2)
        self.assertIn("not found", res.stderr)

    def test_cli_exit_2_on_invalid_json(self) -> None:
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        )
        tmp.write("this is not valid json {{{")
        tmp.close()
        self.addCleanup(lambda: Path(tmp.name).unlink(missing_ok=True))
        res = self._run("frontend", Path(tmp.name))
        self.assertEqual(res.returncode, 2)
        self.assertIn("not valid JSON", res.stderr)

    def test_cli_exit_2_on_missing_tiers_field(self) -> None:
        report = self._write_report({"environment": "test"})  # no .tiers
        res = self._run("frontend", report)
        self.assertEqual(res.returncode, 2)
        self.assertIn("no .tiers field", res.stderr)


if __name__ == "__main__":
    unittest.main()
