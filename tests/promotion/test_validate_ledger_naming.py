"""gitops#3677 — ledger file names: <git_sha>.json (legacy) or <git_sha>-<service>.json.

Runs the real validator module from scripts/promotion so the name grammar
tested here is the one CI enforces.
"""
import importlib.util
import pathlib
import subprocess
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "scripts" / "promotion" / "validate-ledger-schema.py"


def _load():
    spec = importlib.util.spec_from_file_location("validate_ledger_schema", VALIDATOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SHA = "f4749ec98de825af0127aa76da4fd9dcb739139c"


@pytest.mark.parametrize(
    "name,expected",
    [
        (f"{SHA}.json", (SHA, None)),
        (f"{SHA}-schema-service.json", (SHA, "schema-service")),
        (f"{SHA}-notification-orchestrator.json", (SHA, "notification-orchestrator")),
        # 64-hex digest-as-sha entries from the old workaround stay parseable
        ("fce3096eb994cdd8c3911c3c9e64369b082ca066d5a24ce430146a22a8585541.json",
         ("fce3096eb994cdd8c3911c3c9e64369b082ca066d5a24ce430146a22a8585541", None)),
        (f"{SHA}-Schema.json", (None, None)),   # service must be lowercase
        (f"{SHA}-.json", (None, None)),          # empty service
        ("sha-f4749ec.json", (None, None)),       # tag, not a sha
        (f"{SHA[:39]}.json", (None, None)),       # too short
    ],
)
def test_split_ledger_filename(name, expected):
    assert _load().split_ledger_filename(name) == expected


def test_every_existing_ledger_entry_still_validates():
    """The migration must not invalidate a single existing entry."""
    result = subprocess.run(
        [sys.executable, str(VALIDATOR)], cwd=REPO_ROOT, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
