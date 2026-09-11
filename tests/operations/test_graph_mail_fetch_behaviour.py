"""Client-side behaviour of graph-mail-fetch.sh with a fake ssh.

The fake ssh records its argument vector and heredoc body and emits an empty tar
stream on stdout, which is what the real remote side does after fetching.
"""

import os
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER = REPO_ROOT / "scripts" / "ops" / "graph-mail-fetch.sh"
MSG = "AQMkAGU0NAMzNS03ZjY3LTQxY2UtOGJhMy1lM2E0ZmFkNjM0NmQARgAAA"


@pytest.fixture
def fake_ssh(tmp_path):
    shim_dir = tmp_path / "bin"
    shim_dir.mkdir()
    args_file = tmp_path / "ssh-args.txt"
    stdin_file = tmp_path / "ssh-stdin.txt"
    empty = tmp_path / "empty"
    empty.mkdir()
    shim = shim_dir / "ssh"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        'printf "%s\\n" "$@" > "$SHIM_ARGS"\n'
        'cat > "$SHIM_STDIN"\n'
        'tar -C "$SHIM_EMPTY" -cf - .\n',
        encoding="utf-8",
    )
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR)
    env = dict(os.environ)
    env["PATH"] = f"{shim_dir}{os.pathsep}{env['PATH']}"
    env["SHIM_ARGS"] = str(args_file)
    env["SHIM_STDIN"] = str(stdin_file)
    env["SHIM_EMPTY"] = str(empty)

    def run(*args):
        proc = subprocess.run(["bash", str(HELPER), *args], env=env, capture_output=True, text=True, check=False)
        argv = args_file.read_text(encoding="utf-8") if args_file.exists() else None
        body = stdin_file.read_text(encoding="utf-8") if stdin_file.exists() else None
        return proc, argv, body

    return run


def test_top_selection_uses_the_read_identity_and_creates_dest(fake_ssh, tmp_path):
    dest = tmp_path / "out"
    proc, argv, body = fake_ssh("--mailbox", "halil.kocoglu@acik.com", "--top", "2", "--dest", str(dest))
    assert proc.returncode == 0, proc.stderr
    assert dest.is_dir()
    assert "IDENTITY='graph-read' " in argv
    assert "VAULT_PATH='kv/platform/graph-read' " in argv
    assert "MAILBOX='halil.kocoglu@acik.com' " in argv
    assert "TOP='2' " in argv
    assert "MAX_TOTAL_MB='100' " in argv
    assert 'EXPECTED_VAULT_POLICY="graph-mail-read-ops-ro"' in body
    assert "graph-mail-ops-ro" not in body


def test_message_ids_travel_newline_separated(fake_ssh, tmp_path):
    dest = tmp_path / "out"
    proc, argv, _ = fake_ssh("--mailbox", "ai@acik.com", "--message-id", MSG, "--message-id", MSG + "B", "--dest", str(dest))
    assert proc.returncode == 0, proc.stderr
    assert f"MSG_IDS_JOINED='{MSG}\n{MSG}B' " in argv
    assert "TOP='0' " in argv


def test_refuses_non_empty_dest_without_force(fake_ssh, tmp_path):
    dest = tmp_path / "out"
    dest.mkdir()
    (dest / "existing").write_text("x", encoding="utf-8")
    proc, argv, _ = fake_ssh("--mailbox", "ai@acik.com", "--top", "1", "--dest", str(dest))
    assert proc.returncode == 1
    assert "not empty" in proc.stderr
    assert argv is None
    proc, argv, _ = fake_ssh("--mailbox", "ai@acik.com", "--top", "1", "--dest", str(dest), "--force")
    assert proc.returncode == 0, proc.stderr
    assert argv is not None


def test_rejects_bad_selectors_before_any_ssh(fake_ssh, tmp_path):
    dest = tmp_path / "out"
    for args in (
        ("--mailbox", "ai@acik.com", "--dest", str(dest)),
        ("--mailbox", "ai@acik.com", "--top", "3", "--message-id", MSG, "--dest", str(dest)),
        ("--mailbox", "ai@acik.com", "--top", "50", "--dest", str(dest)),
        ("--mailbox", "not-an-address", "--top", "1", "--dest", str(dest)),
        ("--mailbox", "ai@acik.com", "--message-id", "../x", "--dest", str(dest)),
    ):
        proc, argv, _ = fake_ssh(*args)
        assert proc.returncode == 1, args
        assert argv is None, args
