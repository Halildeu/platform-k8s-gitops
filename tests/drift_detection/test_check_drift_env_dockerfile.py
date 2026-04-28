"""ADR-0011 DD-4 unit tests — env + Dockerfile + Python compat lint."""
from __future__ import annotations

import argparse
import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "drift_detection" / "check_drift_env_dockerfile.py"

spec = importlib.util.spec_from_file_location("check_drift_env_dockerfile", SCRIPT_PATH)
check_dd4 = importlib.util.module_from_spec(spec)
sys.modules["check_drift_env_dockerfile"] = check_dd4
spec.loader.exec_module(check_dd4)

FIXTURES = REPO_ROOT / "tests" / "drift_detection" / "fixtures"


def _default_args(**overrides) -> argparse.Namespace:
    args = argparse.Namespace(
        verbose=False,
        json=False,
        config_path=str(REPO_ROOT / "scripts/migration/etl_worker/etl_worker/config.py"),
        dockerfile_path=str(REPO_ROOT / "scripts/migration/etl_worker/Dockerfile"),
        pyproject_path=str(REPO_ROOT / "scripts/migration/etl_worker/pyproject.toml"),
        tables_yaml_path=str(REPO_ROOT / "scripts/migration/etl_worker/config/tables.yaml"),
        readme_path=str(REPO_ROOT / "scripts/migration/etl_worker/README.md"),
        workflow_path=str(REPO_ROOT / ".github/workflows/etl-worker-tests.yml"),
    )
    for k, v in overrides.items():
        setattr(args, k, v)
    return args


class TestPositiveRun(unittest.TestCase):
    def test_overall_pass(self) -> None:
        report = check_dd4.run_all_checks(_default_args())
        for c in report.checks:
            if not c.passed and not c.is_warning:
                print(f"  ✗ {c.name}: {c.message}")
                for d in c.details:
                    print(f"      → {d}")
        self.assertEqual(report.overall, "PASS")

    def test_all_five_checks_run(self) -> None:
        report = check_dd4.run_all_checks(_default_args())
        self.assertEqual(len(report.checks), 5)


class TestNegativeMissingEnvPrefix(unittest.TestCase):
    def test_config_missing_prefix_fails(self) -> None:
        args = _default_args(config_path=str(FIXTURES / "config_dd4_missing_prefix.py"))
        report = check_dd4.run_all_checks(args)
        c = next(c for c in report.checks if c.name == "env_prefix_consistency")
        self.assertFalse(c.passed)
        self.assertIn("SCHEMA_MSSQL_", " ".join(c.details))


class TestNegativeDockerfileSigning(unittest.TestCase):
    def test_dockerfile_no_signed_by_fails(self) -> None:
        args = _default_args(dockerfile_path=str(FIXTURES / "Dockerfile_dd4_no_signed_by.txt"))
        report = check_dd4.run_all_checks(args)
        c = next(c for c in report.checks if c.name == "dockerfile_keyring_signing")
        self.assertFalse(c.passed)
        joined = " ".join(c.details).lower()
        self.assertTrue("signed-by" in joined or "packages-microsoft-prod" in joined)


if __name__ == "__main__":
    unittest.main(verbosity=2)
