"""Fail-closed recipient guards of scripts/ops/graph-mail-send.sh (gitops#3450).

The helper is dry-run by default and performs no network/credential step before
the guard block, so every case here runs the real script safely. Send-mode cases
use recipients the guard must reject, proving the guard fires before the SSH /
Vault stage (the script would otherwise try to reach aiserver).
"""

from __future__ import annotations

import pathlib
import subprocess

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ops" / "graph-mail-send.sh"

GUARD_EXIT = 5
ZEYNEP = "zeynep.akkilic@acik.com"
HALIL = "halil.kocoglu@acik.com"
LEGACY = "zeynep.akkilic@serban.com.tr"


def run_helper(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT), "--subject", "guard-test", "--body", "guard-test", *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_legacy_domain_rejected_in_to() -> None:
    proc = run_helper("--to", LEGACY)
    assert proc.returncode == GUARD_EXIT
    assert "serban.com.tr" in proc.stderr
    assert "gitops#3450" in proc.stderr


def test_legacy_domain_rejected_in_cc() -> None:
    proc = run_helper("--to", ZEYNEP, "--cc", f"{HALIL},{LEGACY}")
    assert proc.returncode == GUARD_EXIT
    assert "serban.com.tr" in proc.stderr


def test_legacy_domain_rejected_case_insensitive() -> None:
    proc = run_helper("--to", "Zeynep.Akkilic@Serban.COM.TR")
    assert proc.returncode == GUARD_EXIT
    assert "serban.com.tr" in proc.stderr


def test_zeynep_without_halil_cc_rejected() -> None:
    proc = run_helper("--to", ZEYNEP)
    assert proc.returncode == GUARD_EXIT
    assert HALIL in proc.stderr
    assert "gitops#3450" in proc.stderr


def test_zeynep_with_unrelated_cc_rejected() -> None:
    proc = run_helper("--to", ZEYNEP, "--cc", "ops@acik.com")
    assert proc.returncode == GUARD_EXIT
    assert HALIL in proc.stderr


def test_zeynep_in_cc_also_requires_halil() -> None:
    proc = run_helper("--to", "ops@acik.com", "--cc", ZEYNEP)
    assert proc.returncode == GUARD_EXIT
    assert HALIL in proc.stderr


def test_halil_in_to_does_not_satisfy_cc_requirement() -> None:
    # The rule is explicitly "on CC" — To carrying the address is not enough.
    proc = run_helper("--to", f"{ZEYNEP},{HALIL}")
    assert proc.returncode == GUARD_EXIT


def test_zeynep_with_halil_cc_passes_dry_run() -> None:
    proc = run_helper("--to", ZEYNEP, "--cc", HALIL)
    assert proc.returncode == 0
    assert '"dry_run": true' in proc.stdout
    assert ZEYNEP in proc.stdout
    assert HALIL in proc.stdout


def test_unrelated_recipient_unaffected() -> None:
    proc = run_helper("--to", "ops@acik.com")
    assert proc.returncode == 0
    assert '"dry_run": true' in proc.stdout


def test_send_mode_guard_fires_before_confirm_and_network() -> None:
    # Matching --confirm-recipients would normally pass the mechanical check;
    # the guard must reject first (exit 5, not the confirm-mismatch exit 4)
    # and nothing may reach the SSH/Vault send stage.
    proc = run_helper(
        "--to", ZEYNEP,
        "--send", "--confirm-recipients", ZEYNEP,
    )
    assert proc.returncode == GUARD_EXIT
    assert "SENDING" not in proc.stderr


def test_send_mode_legacy_domain_guard_fires_first() -> None:
    proc = run_helper(
        "--to", LEGACY,
        "--send", "--confirm-recipients", LEGACY.lower(),
    )
    assert proc.returncode == GUARD_EXIT
    assert "SENDING" not in proc.stderr
