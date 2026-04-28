"""
ADR-0011 DD-1 unit tests — drift detection script positive + negative cases.

Codex 019dd409 PARTIAL/AGREE-with-revisions: pytest dependency yok; stdlib
unittest yeterli. Run:
    python3 -m unittest tests.drift_detection.test_check_drift_anchor_table -v
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import unittest
from pathlib import Path

# Import target script as module (not on sys.path by default)
REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "drift_detection" / "check_drift_anchor_table.py"

spec = importlib.util.spec_from_file_location("check_drift_anchor_table", SCRIPT_PATH)
check_drift = importlib.util.module_from_spec(spec)
sys.modules["check_drift_anchor_table"] = check_drift
spec.loader.exec_module(check_drift)


class TestPositiveRun(unittest.TestCase):
    """Current main repo state should produce all-green drift report."""

    def setUp(self) -> None:
        self.args = argparse.Namespace(
            verbose=False,
            json=False,
            v25_path=str(REPO_ROOT / "sql/migration/V25__tenant_anchor_fix.sql"),
            v26_path=str(REPO_ROOT / "sql/migration/V26__source_pk_dual_format.sql"),
            schema_path=str(REPO_ROOT / "docs/migration/workcube-schema.json"),
            adr_0008_path=str(REPO_ROOT / "docs/adr/0008-multi-org-explicit-scope-zanzibar.md"),
        )

    def test_overall_pass(self) -> None:
        report = check_drift.run_all_checks(self.args)
        # Verbose listing of any failures for diagnostic
        for c in report.checks:
            if not c.passed:
                print(f"\n  ✗ {c.name}: {c.message}")
                for d in c.details:
                    print(f"      → {d}")
        self.assertEqual(report.overall, "PASS", f"Expected PASS, got {report.overall}")

    def test_all_six_checks_run(self) -> None:
        report = check_drift.run_all_checks(self.args)
        self.assertEqual(len(report.checks), 6, "Expected 6 checks")
        names = {c.name for c in report.checks}
        expected = {
            "v25_check_constraint_pairs",
            "v25_v26_validate_scope_ref_anchor",
            "v25_organization_company_default",
            "v26_dual_format_predicate",
            "workcube_schema_anchor_tables",
            "adr_0008_object_id_encoding",
        }
        self.assertEqual(names, expected)


class TestNegativeRegression(unittest.TestCase):
    """V25 corrupted fixture should trigger drift detection."""

    def setUp(self) -> None:
        # Use the regression fixture as V25 source
        self.args = argparse.Namespace(
            verbose=False,
            json=False,
            v25_path=str(REPO_ROOT / "tests/drift_detection/fixtures/V25_company_anchor_regression.sql"),
            v26_path=str(REPO_ROOT / "sql/migration/V26__source_pk_dual_format.sql"),
            schema_path=str(REPO_ROOT / "docs/migration/workcube-schema.json"),
            adr_0008_path=str(REPO_ROOT / "docs/adr/0008-multi-org-explicit-scope-zanzibar.md"),
        )

    def test_overall_fail(self) -> None:
        report = check_drift.run_all_checks(self.args)
        self.assertEqual(report.overall, "FAIL", "Regression fixture should produce FAIL")

    def test_check_v25_constraint_fails(self) -> None:
        report = check_drift.run_all_checks(self.args)
        c = next(c for c in report.checks if c.name == "v25_check_constraint_pairs")
        self.assertFalse(c.passed, "V25 CHECK constraint check should fail on regression fixture")
        # Specifically the company → OUR_COMPANY pair is missing (replaced with COMPANY)
        joined = " ".join(c.details).lower()
        self.assertIn("company", joined)

    def test_check_v25_anchor_fails(self) -> None:
        report = check_drift.run_all_checks(self.args)
        c = next(c for c in report.checks if c.name == "v25_v26_validate_scope_ref_anchor")
        self.assertFalse(c.passed, "V25 anchor check should fail on regression fixture")

    def test_check_organization_company_default_fails(self) -> None:
        report = check_drift.run_all_checks(self.args)
        c = next(c for c in report.checks if c.name == "v25_organization_company_default")
        self.assertFalse(c.passed, "organization_company default check should fail on regression fixture")


class TestSqlParserHelpers(unittest.TestCase):
    """Smoke tests for parser helpers (regex sanity)."""

    def test_strip_sql_comments(self) -> None:
        sql = """-- header
SELECT 1;  -- inline
-- another
SELECT 'don''t strip me'; -- but strip this
"""
        out = check_drift.strip_sql_comments(sql)
        self.assertNotIn("header", out)
        self.assertNotIn("inline", out)
        self.assertIn("don''t strip me", out)

    def test_extract_function_body(self) -> None:
        sql = """
CREATE OR REPLACE FUNCTION data_access.validate_scope_ref(p_kind TEXT) RETURNS BOOLEAN AS $$
BEGIN
    RETURN p_kind = 'company';
END;
$$ LANGUAGE plpgsql;
"""
        body = check_drift.extract_function_body(sql)
        self.assertIsNotNone(body)
        self.assertIn("p_kind = 'company'", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
