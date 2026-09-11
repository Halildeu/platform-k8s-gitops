"""Static contract for scripts/ops/vault-kv-patch-field.sh: value only via prompt/pipe,
root token only in-band on aiserver, patch-only semantics, metadata-only output."""

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ops" / "vault-kv-patch-field.sh"


def body() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_value_never_travels_as_an_argument():
    s = body()
    assert "read -rs -p" in s
    assert "--secret-stdin) SECRET_STDIN=1" in s
    assert '[[ ! -t 0 ]] || die "--secret-stdin expects the value on a pipe' in s
    for forbidden in ("--value", "--secret)", "--secret ", "--password"):
        assert forbidden not in s
    assert 'printf \'%s\' "$VALUE" | ssh' in s
    assert "unset VALUE" in s


def test_root_token_stays_in_band_and_patch_is_the_only_write():
    s = body()
    assert "/srv/platform/secrets/backup-auth/vault-init-test.json" in s
    assert "/srv/platform/secrets/backup-auth/vault-init-prod.json" in s
    assert "IFS= read -r VAULT_TOKEN" in s
    assert 'vault kv metadata get "$1"' in s
    assert 'exec vault kv patch -format=json "$1" "$2"=-' in s
    assert "vault kv put" not in s
    assert "vault kv delete" not in s
    assert "vault kv get" not in s  # never echoes secret data back
    assert "{path: $path, field: $field, version: .data.version" in s


def test_inputs_are_validated_before_any_ssh(tmp_path):
    for args in (
        ["--vault", "staging", "--path", "kv/platform/x", "--field", "f"],
        ["--vault", "prod", "--path", "secret/x", "--field", "f"],
        ["--vault", "prod", "--path", "kv/../x", "--field", "f"],
        ["--vault", "prod", "--path", "kv/platform/x", "--field", "bad key"],
    ):
        proc = subprocess.run(["bash", str(SCRIPT), *args, "--secret-stdin"], input="0123456789ab", capture_output=True, text=True, check=False)
        assert proc.returncode == 1, args
        assert "ERROR:" in proc.stderr
