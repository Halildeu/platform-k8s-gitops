"""ADR-0011 DD-3 unit tests — schema-snapshot drift detection."""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "drift_detection" / "check_drift_reports_db_snapshot.py"

spec = importlib.util.spec_from_file_location("check_drift_reports_db_snapshot", SCRIPT_PATH)
check_dd3 = importlib.util.module_from_spec(spec)
sys.modules["check_drift_reports_db_snapshot"] = check_dd3
spec.loader.exec_module(check_dd3)

FIXTURES = REPO_ROOT / "tests" / "drift_detection" / "fixtures"


def _default_args(**overrides) -> argparse.Namespace:
    args = argparse.Namespace(
        verbose=False,
        json=False,
        strict=False,
        source_snapshot=str(REPO_ROOT / "docs/migration/workcube-schema.json"),
        actual_artifact=str(REPO_ROOT / "docs/migration/reports-db-workcube-actual-schema.json"),
        tables_yaml=str(REPO_ROOT / "scripts/migration/etl_worker/config/tables.yaml"),
    )
    for k, v in overrides.items():
        setattr(args, k, v)
    return args


class TestPendingState(unittest.TestCase):
    """Default state: actual artifact missing → PENDING (graceful pass)."""

    def test_overall_pending_when_artifact_missing(self) -> None:
        # Use tempdir-only path that definitely doesn't exist
        args = _default_args(actual_artifact="/tmp/nonexistent-dd3-artifact.json")
        report = check_dd3.run_all_checks(args)
        self.assertEqual(report.overall, "PENDING")

    def test_etl_managed_in_source_passes_independently(self) -> None:
        """Even without artifact, source-side check should still validate."""
        args = _default_args(actual_artifact="/tmp/nonexistent-dd3-artifact.json")
        report = check_dd3.run_all_checks(args)
        c = next(c for c in report.checks if c.name == "etl_managed_tables_in_source")
        self.assertTrue(c.passed)
        self.assertFalse(c.pending)


class TestPositiveWithValidArtifact(unittest.TestCase):
    """When artifact present, fresh, hash-matched, all checks PASS."""

    def setUp(self) -> None:
        # Compute current source hash + write a valid artifact with matching hash
        source_path = REPO_ROOT / "docs/migration/workcube-schema.json"
        source_hash = sha256(source_path.read_bytes()).hexdigest()

        with (FIXTURES / "dd3_actual_artifact_valid.json").open("r") as f:
            artifact = json.load(f)

        artifact["source_snapshot_sha256"] = source_hash

        # Write to tempfile
        self.tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        )
        json.dump(artifact, self.tmp)
        self.tmp.close()

    def tearDown(self) -> None:
        Path(self.tmp.name).unlink(missing_ok=True)

    def test_overall_pass(self) -> None:
        args = _default_args(actual_artifact=self.tmp.name)
        report = check_dd3.run_all_checks(args)
        for c in report.checks:
            if not c.passed and not c.pending:
                print(f"  ✗ {c.name}: {c.message}")
                for d in c.details:
                    print(f"      → {d}")
        self.assertEqual(report.overall, "PASS")


class TestNegativeStaleArtifact(unittest.TestCase):
    def test_stale_artifact_freshness_fails(self) -> None:
        args = _default_args(actual_artifact=str(FIXTURES / "dd3_actual_artifact_stale.json"))
        report = check_dd3.run_all_checks(args)
        c = next(c for c in report.checks if c.name == "actual_artifact_freshness")
        self.assertFalse(c.passed)


class TestNegativeMissingLineage(unittest.TestCase):
    def setUp(self) -> None:
        # Inject current source hash into missing-lineage fixture so freshness +
        # hash checks pass; only lineage check should fail.
        source_path = REPO_ROOT / "docs/migration/workcube-schema.json"
        source_hash = sha256(source_path.read_bytes()).hexdigest()

        with (FIXTURES / "dd3_actual_artifact_missing_lineage.json").open("r") as f:
            artifact = json.load(f)
        artifact["source_snapshot_sha256"] = source_hash

        self.tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        )
        json.dump(artifact, self.tmp)
        self.tmp.close()

    def tearDown(self) -> None:
        Path(self.tmp.name).unlink(missing_ok=True)

    def test_pg_lineage_fails(self) -> None:
        args = _default_args(actual_artifact=self.tmp.name)
        report = check_dd3.run_all_checks(args)
        c = next(c for c in report.checks if c.name == "pg_lineage_columns_present")
        self.assertFalse(c.passed)
        self.assertIn("missing lineage column", " ".join(c.details).lower())


class TestStrictMode(unittest.TestCase):
    """In --strict mode, PENDING state should be treated as failure (script
    main() would exit 1). Test the report only — main() exit handled separately."""

    def test_pending_state_recognized(self) -> None:
        args = _default_args(actual_artifact="/tmp/nonexistent.json", strict=True)
        report = check_dd3.run_all_checks(args)
        # Report itself reports PENDING regardless of strict mode
        self.assertEqual(report.overall, "PENDING")
        # Strict-mode exit logic is in main(), not run_all_checks(); covered by integration


if __name__ == "__main__":
    unittest.main(verbosity=2)
