"""ADR-0011 DD-2 unit tests — ETL contract drift detection."""
from __future__ import annotations

import argparse
import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "drift_detection" / "check_drift_etl_contract.py"

spec = importlib.util.spec_from_file_location("check_drift_etl_contract", SCRIPT_PATH)
check_etl = importlib.util.module_from_spec(spec)
sys.modules["check_drift_etl_contract"] = check_etl
spec.loader.exec_module(check_etl)


def _default_args(**overrides) -> argparse.Namespace:
    args = argparse.Namespace(
        verbose=False,
        json=False,
        transform_path=str(REPO_ROOT / "scripts/migration/etl_worker/etl_worker/transform.py"),
        test_transform_path=str(REPO_ROOT / "scripts/migration/etl_worker/tests/test_transform.py"),
        tables_yaml_path=str(REPO_ROOT / "scripts/migration/etl_worker/config/tables.yaml"),
        v16_path=str(REPO_ROOT / "sql/migration/V16__reports.sql"),
        v17_path=str(REPO_ROOT / "sql/migration/V17__etl_lineage_columns.sql"),
        v26_path=str(REPO_ROOT / "sql/migration/V26__source_pk_dual_format.sql"),
    )
    for k, v in overrides.items():
        setattr(args, k, v)
    return args


class TestPositiveRun(unittest.TestCase):
    def test_overall_pass(self) -> None:
        report = check_etl.run_all_checks(_default_args())
        for c in report.checks:
            if not c.passed:
                print(f"  ✗ {c.name}: {c.message}")
                for d in c.details:
                    print(f"      → {d}")
        self.assertEqual(report.overall, "PASS")

    def test_all_six_checks_run(self) -> None:
        report = check_etl.run_all_checks(_default_args())
        self.assertEqual(len(report.checks), 6)
        names = {c.name for c in report.checks}
        expected = {
            "make_source_pk_static_contract",
            "make_source_pk_runtime_outputs",
            "make_source_pk_unit_tests_present",
            "v26_accepts_etl_canonical_p_ref",
            "pg_lineage_source_pk_text_contract",
            "anchor_idempotency_keys_documented",
        }
        self.assertEqual(names, expected)


class TestNegativeTransformRegression(unittest.TestCase):
    def test_corrupted_transform_static_check_fails(self) -> None:
        args = _default_args(
            transform_path=str(REPO_ROOT / "tests/drift_detection/fixtures/transform_etl_contract_regression.py")
        )
        report = check_etl.run_all_checks(args)
        c = next(c for c in report.checks if c.name == "make_source_pk_static_contract")
        self.assertFalse(c.passed)

    def test_corrupted_transform_runtime_check_fails(self) -> None:
        args = _default_args(
            transform_path=str(REPO_ROOT / "tests/drift_detection/fixtures/transform_etl_contract_regression.py")
        )
        report = check_etl.run_all_checks(args)
        c = next(c for c in report.checks if c.name == "make_source_pk_runtime_outputs")
        self.assertFalse(c.passed)

    def test_overall_fail(self) -> None:
        args = _default_args(
            transform_path=str(REPO_ROOT / "tests/drift_detection/fixtures/transform_etl_contract_regression.py")
        )
        report = check_etl.run_all_checks(args)
        self.assertEqual(report.overall, "FAIL")


class TestNegativeV26Regression(unittest.TestCase):
    def test_v26_missing_canonical_p_ref_fails(self) -> None:
        args = _default_args(
            v26_path=str(REPO_ROOT / "tests/drift_detection/fixtures/V26_no_canonical_p_ref_regression.sql")
        )
        report = check_etl.run_all_checks(args)
        c = next(c for c in report.checks if c.name == "v26_accepts_etl_canonical_p_ref")
        self.assertFalse(c.passed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
