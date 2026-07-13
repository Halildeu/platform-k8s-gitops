import json
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts/faz24/backfill-meeting-owner-stable-sub.sh"
ALLOWED_FILTER = (
    'if (.allowed | type) == "boolean" then (.allowed | tostring) '
    'else error("allowed must be boolean") end'
)


def parse_allowed(payload: dict[str, object]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["jq", "-er", ALLOWED_FILTER],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.mark.parametrize("allowed", [True, False])
def test_allowed_parser_accepts_both_boolean_values(allowed: bool) -> None:
    result = parse_allowed({"allowed": allowed})

    assert result.returncode == 0
    assert result.stdout.strip() == str(allowed).lower()


@pytest.mark.parametrize("payload", [{}, {"allowed": "false"}, {"allowed": 0}])
def test_allowed_parser_rejects_missing_or_non_boolean_values(
    payload: dict[str, object],
) -> None:
    result = parse_allowed(payload)

    assert result.returncode != 0


def test_backfill_verifier_uses_false_safe_boolean_parser() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert ALLOWED_FILTER in source
    assert '.allowed | select(type == "boolean")' not in source
