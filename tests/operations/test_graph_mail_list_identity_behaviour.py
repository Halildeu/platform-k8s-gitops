"""Behavioural pins for graph-mail-list.sh identity selection (client side).

The helper never runs Vault or Graph locally; everything happens on aiserver via a
single `ssh` call. A fake `ssh` on PATH captures the argument vector (the env
prefix that selects the identity) and the heredoc body, so we can prove which
Vault identity a given flag combination would select before any network exists.
"""

import os
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER = REPO_ROOT / "scripts" / "ops" / "graph-mail-list.sh"


@pytest.fixture
def fake_ssh(tmp_path):
    shim_dir = tmp_path / "bin"
    shim_dir.mkdir()
    args_file = tmp_path / "ssh-args.txt"
    stdin_file = tmp_path / "ssh-stdin.txt"
    shim = shim_dir / "ssh"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        'printf "%s\\n" "$@" > "$SHIM_ARGS"\n'
        'cat > "$SHIM_STDIN"\n'
        "exit 0\n",
        encoding="utf-8",
    )
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR)
    env = dict(os.environ)
    env["PATH"] = f"{shim_dir}{os.pathsep}{env['PATH']}"
    env["SHIM_ARGS"] = str(args_file)
    env["SHIM_STDIN"] = str(stdin_file)

    def run(*args):
        proc = subprocess.run(
            ["bash", str(HELPER), *args],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        argv = args_file.read_text(encoding="utf-8") if args_file.exists() else None
        body = stdin_file.read_text(encoding="utf-8") if stdin_file.exists() else None
        return proc, argv, body

    return run


def test_default_identity_is_the_legacy_app(fake_ssh):
    # Reverted 2026-09-11 (owner): graph-read is denied for ai@acik.com by Graph while
    # Exchange says Granted; the legacy identity stays the default until resolved.
    proc, argv, body = fake_ssh("--top", "1")
    assert proc.returncode == 0, proc.stderr
    assert "IDENTITY='graph' " in argv
    assert "VAULT_PATH='kv/platform/graph' " in argv
    assert "SHOW_ROLES='0' " in argv
    assert "aiadmin@aiserver" in argv
    assert 'EXPECTED_VAULT_PATH="kv/platform/graph"' in body
    assert "/v1/auth/token/revoke-self" in body


def test_read_only_identity_is_explicit(fake_ssh):
    proc, argv, body = fake_ssh("--identity", "graph-read", "--top", "1")
    assert proc.returncode == 0, proc.stderr
    assert "IDENTITY='graph-read' " in argv
    assert "VAULT_PATH='kv/platform/graph-read' " in argv
    assert 'EXPECTED_VAULT_PATH="kv/platform/graph-read"' in body


def test_read_identity_selects_its_own_vault_path_and_can_expose_roles(fake_ssh):
    proc, argv, body = fake_ssh(
        "--identity", "graph-read", "--show-roles", "--mailbox", "halil.kocoglu@acik.com"
    )
    assert proc.returncode == 0, proc.stderr
    assert "IDENTITY='graph-read' " in argv
    assert "VAULT_PATH='kv/platform/graph-read' " in argv
    assert "SHOW_ROLES='1' " in argv
    assert "MAILBOX='halil.kocoglu@acik.com' " in argv
    # The remote body carries both identity tables and refuses anything else.
    assert 'EXPECTED_VAULT_POLICY="graph-mail-read-ops-ro"' in body
    assert "/srv/platform/secrets/graph-mail-read-vault/role-id" in body
    assert "unknown Graph mail identity" in body
    assert "jq -c '.roles // []'" in body


def test_unknown_identity_fails_before_any_ssh(fake_ssh):
    proc, argv, body = fake_ssh("--identity", "graph-send")
    assert proc.returncode == 1
    assert "--identity must be graph or graph-read" in proc.stderr
    assert argv is None and body is None


def test_identity_name_cannot_smuggle_a_path(fake_ssh):
    proc, argv, _ = fake_ssh("--identity", "../graph")
    assert proc.returncode == 1
    assert argv is None
