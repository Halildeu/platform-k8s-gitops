"""Faz 16.3 Gün 6 — CLI behavior tests (Codex iter-8 absorb).

Tests:
- `run --resume --run-id` works WITHOUT --mode (Codex iter-8 finding #1).
- `run` without --mode and without --resume fails fast.
- `status --run-id` prints all 5 buckets, zero-filled (iter-8 finding #4).
- `status --run-id --json` emits zero-filled buckets too.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from etl_worker.cli import main


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def config_dir(tmp_path):
    """Minimal manifest dir so the @main(config-dir) option exists check passes."""
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "tables.yaml").write_text("tables: []\n")
    return str(cfg)


@pytest.fixture
def audit_mock():
    """Patch psycopg.connect + AuditModule used inside cli.run/status paths."""
    with patch("psycopg.connect") as pc, patch("etl_worker.audit.AuditModule") as am_cls:
        # connect returns a context-manager yielding a fake conn
        conn = MagicMock(name="conn")
        conn.autocommit = True
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=conn)
        ctx.__exit__ = MagicMock(return_value=False)
        pc.return_value = ctx

        audit = MagicMock(name="AuditModule")
        am_cls.return_value = audit
        yield audit


# ============================================================================
# `run --resume` (mode optional path)
# ============================================================================

def test_run_resume_without_mode_succeeds(runner, config_dir, audit_mock):
    """Codex iter-8 fix #1: --resume must NOT require --mode."""
    audit_mock.get_run.return_value = {
        "run_id": "rid-1",
        "mode": "initial",
        "status": "RUNNING",
        "source_database": "wm",
        "started_at": "2026-04-25T10:00:00+00:00",
        "completed_at": None,
        "error_summary": None,
    }
    audit_mock.get_resume_state.return_value = {
        "A|s|": {"status": "VALIDATED"},
        "B|s|": {"status": "LOADING"},
        "C|s|": {"status": "PENDING"},
    }

    result = runner.invoke(
        main,
        ["--config-dir", config_dir, "run", "--resume", "--run-id", "rid-1"],
    )
    assert result.exit_code == 0, result.output
    assert "RESUME plan" in result.output
    assert "audit mode              : initial" in result.output
    assert "validated (skip)        : 1" in result.output
    assert "pending / loading       : 2" in result.output


def test_run_resume_requires_run_id(runner, config_dir):
    result = runner.invoke(main, ["--config-dir", config_dir, "run", "--resume"])
    assert result.exit_code != 0
    assert "--resume requires --run-id" in result.output


def test_run_without_mode_and_without_resume_fails(runner, config_dir):
    """New runs still need --mode."""
    result = runner.invoke(main, ["--config-dir", config_dir, "run"])
    assert result.exit_code != 0
    assert "--mode is required for new runs" in result.output


def test_run_resume_run_not_found(runner, config_dir, audit_mock):
    audit_mock.get_run.return_value = None
    result = runner.invoke(
        main,
        ["--config-dir", config_dir, "run", "--resume", "--run-id", "ghost"],
    )
    assert result.exit_code != 0
    assert "not found in migration_runs" in result.output


def test_run_resume_no_table_state_rows(runner, config_dir, audit_mock):
    audit_mock.get_run.return_value = {
        "run_id": "rid-empty",
        "mode": "initial",
        "status": "RUNNING",
        "source_database": "wm",
        "started_at": None,
        "completed_at": None,
    }
    audit_mock.get_resume_state.return_value = {}
    result = runner.invoke(
        main,
        ["--config-dir", config_dir, "run", "--resume", "--run-id", "rid-empty"],
    )
    assert result.exit_code != 0
    assert "no migration_table_state rows" in result.output


# ============================================================================
# `status` — all 5 buckets, zero-filled (Codex iter-8 fix #4)
# ============================================================================

def test_status_text_prints_all_five_buckets(runner, config_dir, audit_mock):
    """Even when only LOADING + VALIDATED exist in DB, all 5 must appear."""
    audit_mock.status_summary.return_value = {
        "run": {
            "run_id": "rid-1",
            "mode": "initial",
            "status": "RUNNING",
            "source_database": "wm",
            "started_at": "2026-04-25T10:00:00+00:00",
            "completed_at": None,
            "error_summary": None,
        },
        "buckets": {
            "LOADING": {"tables": 2, "rows_extracted": 100, "rows_loaded": 80, "rows_rejected": 0},
            "VALIDATED": {"tables": 5, "rows_extracted": 500, "rows_loaded": 500, "rows_rejected": 0},
        },
        "reject_total": 0,
    }
    result = runner.invoke(
        main, ["--config-dir", config_dir, "status", "--run-id", "rid-1"]
    )
    assert result.exit_code == 0, result.output
    for st in ("PENDING", "EXTRACTING", "LOADING", "VALIDATED", "FAILED"):
        assert st in result.output, f"missing bucket {st}"
    # Zero-fill: PENDING tables=0
    assert "PENDING      tables=0" in result.output
    assert "FAILED       tables=0" in result.output


def test_status_json_zero_fills_buckets(runner, config_dir, audit_mock):
    audit_mock.status_summary.return_value = {
        "run": {
            "run_id": "rid-1",
            "mode": "initial",
            "status": "RUNNING",
            "source_database": "wm",
            "started_at": None,
            "completed_at": None,
        },
        "buckets": {},  # nothing yet
        "reject_total": 0,
    }
    result = runner.invoke(
        main,
        ["--config-dir", config_dir, "status", "--run-id", "rid-1", "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    for st in ("PENDING", "EXTRACTING", "LOADING", "VALIDATED", "FAILED"):
        assert st in payload["buckets"]
        assert payload["buckets"][st]["tables"] == 0
        assert payload["buckets"][st]["rows_loaded"] == 0
