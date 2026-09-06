"""Behavioural guard for the d35 admin persona step of `fullats-live-browser-acceptance.sh`.

Closes the `tracked_pending` left by the #3569 review: the wrapper's fail-closed order
(Vault username+uid → resolve the user BY UID in Keycloak → id/username/enabled checks →
only then the password-reset branch) was pinned textually; this suite executes the real
step-2 region of the script under `bash -euo pipefail` with stubbed `docker`/Vault/token
functions and asserts what actually happens:

* uid from Vault does not resolve in Keycloak  -> non-zero exit, ZERO reset, ZERO persist
* username drifted between Vault and Keycloak  -> non-zero exit, ZERO reset, ZERO persist
* persona disabled                              -> non-zero exit, ZERO reset, ZERO persist
* identity matches and the Vault password works -> exit 0, ZERO reset, ZERO persist
* identity matches, Vault password rejected     -> exactly one reset on the Vault uid, verified
                                                   BEFORE persist, persisted bytes newline-free
* identity matches, reset password not accepted -> non-zero exit, Vault NOT written

2026-09-06 background: the e-mail lookup that preceded this guard reset a *different*
user's password and overwrote the Vault persona password (kv/platform/d35-3 v18).
"""

import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WRAPPER = REPO_ROOT / "scripts/ats/fullats-live-browser-acceptance.sh"

UID = "cbc9a869-1833-4d9c-beea-a9fa52fa851e"
USERNAME = "d35-admin-persona"

START = 'echo "2/6 Sentetik d35 admin credential ve product API authority hazirla"'
END = 'header_from_token "$ADMIN_TOKEN_FILE" "$ADMIN_HEADER_FILE"'


def step_two_region() -> str:
    text = WRAPPER.read_text(encoding="utf-8")
    start, end = text.index(START), text.index(END)
    assert start < end, "step 2/6 region markers out of order"
    return text[start:end]


# Stubs replace every external effect of the region. `docker` answers the kcadm user lookup
# from the fixture and records reset-password calls (with the JSON body it received);
# the Vault helpers read fixture files; token_from_password succeeds or fails per fixture.
HARNESS = textwrap.dedent(r'''
    set -euo pipefail
    KC_CONTAINER=fake-kc; KCADM=/opt/keycloak/bin/kcadm.sh; REALM=platform-test
    SECRET_DIR="$FIX/secrets"; mkdir -p "$SECRET_DIR"; chmod 700 "$SECRET_DIR"
    ADMIN_USERNAME_FILE="$SECRET_DIR/d35-admin.username"
    ADMIN_PASSWORD_FILE="$SECRET_DIR/d35-admin.password"
    ADMIN_TOKEN_FILE="$SECRET_DIR/d35-admin.jwt"
    PRODUCT_SECRET_FILE="$FIX/product.secret"; printf 'x' >"$PRODUCT_SECRET_FILE"
    LOG="$FIX/calls.log"; : >"$LOG"
    json_file() { local p="$FIX/$1"; : >"$p"; chmod 600 "$p"; printf '%s' "$p"; }
    vault_field_to_file() {  # $1=path $2=field $3=dest — fixture: $FIX/vault/<field>
      local src="$FIX/vault/$2"; [ -f "$src" ] || { rm -f "$3"; return 1; }
      cp "$src" "$3"; chmod 600 "$3"; [ -s "$3" ]
    }
    docker() {  # exec <container> <kcadm> get users/<uid> -r <realm>   |   update users/<uid>/reset-password -f -
      local args="$*"
      case "$args" in
        *" get users/"*)
          echo "docker-get $args" >>"$LOG"
          if [ -f "$FIX/kc/user.json" ]; then cat "$FIX/kc/user.json"; else echo "Resource not found" >&2; return 1; fi ;;
        *"/reset-password"*)
          local body; body=$(cat)
          printf 'RESET %s :: %s\n' "$(sed -E 's/.*update users\/([^/]+)\/reset-password.*/\1/' <<<"$args")" "$body" >>"$LOG"
          printf '%s' "$body" | python3 -c 'import json,sys; v=json.load(sys.stdin)["value"]; open(sys.argv[1],"w").write(v)' "$FIX/kc/password.txt"
          [ "${RESET_ACCEPTED:-1}" = 1 ] && printf '%s' "$body" | python3 -c 'import json,sys; open(sys.argv[1],"w").write(json.load(sys.stdin)["value"])' "$FIX/kc/accepted.txt" || true ;;
        *) echo "docker-other $args" >>"$LOG"; return 1 ;;
      esac
    }
    token_from_password() {  # $1=username_file $2=password_file $3=token_file [$4=client $5=secret]
      echo "TOKEN client=${4:-smoke-ats-v1} user=$(cat "$1") pw=$(od -An -c "$2" | tr -d ' \n')" >>"$LOG"
      if [ -f "$FIX/kc/accepted.txt" ] && cmp -s "$FIX/kc/accepted.txt" "$2"; then printf 'jwt' >"$3"; return 0; fi
      return 1
    }
    persist_d35_password() {
      local n; n=$(wc -c <"$ADMIN_PASSWORD_FILE" | tr -d ' ')
      local nl=no; [ -z "$(tail -c1 "$ADMIN_PASSWORD_FILE")" ] && nl=yes   # $(...) strips a trailing newline → empty means the last byte was '\n'
      echo "PERSIST bytes=$n trailing_newline=$nl" >>"$LOG"; cp "$ADMIN_PASSWORD_FILE" "$FIX/vault/persisted"
    }
''')


def bash_binary() -> str:
    for candidate in ("/opt/homebrew/bin/bash", "/usr/local/bin/bash", "bash"):
        if shutil.which(candidate) or Path(candidate).exists():
            return candidate
    return "bash"


class WrapperD35PersonaGuard(unittest.TestCase):
    def setUp(self):
        self.fix = Path(tempfile.mkdtemp(prefix="d35-guard-"))
        self.addCleanup(shutil.rmtree, self.fix, ignore_errors=True)
        (self.fix / "vault").mkdir()
        (self.fix / "kc").mkdir()
        self.region = step_two_region()

    def vault(self, username=USERNAME, uid=UID, vault_value="p-from-vault-000000000000"):
        (self.fix / "vault/admin_persona_username").write_text(username)
        (self.fix / "vault/admin_persona_uid").write_text(uid)
        if vault_value is not None:  # synthetic fixture string, not a credential
            (self.fix / "vault/admin_persona_password").write_text(vault_value)

    def keycloak(self, uid=UID, username=USERNAME, enabled=True, accepted_value="p-from-vault-000000000000", raw=None):
        if raw is not None:
            (self.fix / "kc/user.json").write_text(raw)
        else:
            (self.fix / "kc/user.json").write_text(
                '{"id": "%s", "username": "%s", "enabled": %s, "email": "d35-admin-persona@acik.com"}'
                % (uid, username, "true" if enabled else "false")
            )
        if accepted_value is not None:  # what the fake Keycloak accepts; synthetic fixture string
            (self.fix / "kc/accepted.txt").write_text(accepted_value)

    def run_region(self, reset_accepted=True):
        script = HARNESS + "\n" + self.region + "\necho STEP2-OK\n"
        (self.fix / "harness.sh").write_text(script)
        env = dict(os.environ, FIX=str(self.fix), RESET_ACCEPTED="1" if reset_accepted else "0")
        return subprocess.run([bash_binary(), str(self.fix / "harness.sh")], env=env, capture_output=True, text=True, timeout=60)

    def calls(self):
        return (self.fix / "calls.log").read_text().splitlines() if (self.fix / "calls.log").exists() else []

    def assert_no_reset_no_persist(self):
        self.assertFalse([c for c in self.calls() if c.startswith(("RESET", "PERSIST"))], self.calls())
        self.assertFalse((self.fix / "vault/persisted").exists())

    def test_uid_not_resolving_in_keycloak_aborts_before_any_reset(self):
        self.vault()
        # Keycloak answers with a different user for that uid (or nothing at all)
        self.keycloak(uid="2f1a1deb-fbcc-4b8e-9ee8-84fd9eb1abbc", username="d35-admin")
        proc = self.run_region()
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("uid from Vault does not resolve in Keycloak", proc.stderr)
        self.assert_no_reset_no_persist()
        (self.fix / "kc/user.json").unlink()  # kcadm "Resource not found" path
        proc = self.run_region()
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("uid from Vault does not resolve in Keycloak", proc.stderr)
        self.assert_no_reset_no_persist()

    def test_username_drift_aborts_before_any_reset(self):
        self.vault(username="d35-admin")  # Vault says one name, Keycloak (by uid) another
        self.keycloak()
        proc = self.run_region()
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("username drifted between Vault and Keycloak", proc.stderr)
        self.assert_no_reset_no_persist()

    def test_disabled_persona_aborts_before_any_reset(self):
        self.vault()
        self.keycloak(enabled=False)
        proc = self.run_region()
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("synthetic d35 admin is disabled", proc.stderr)
        self.assert_no_reset_no_persist()

    def test_malformed_uid_in_vault_aborts_before_keycloak_lookup(self):
        self.vault(uid="not-a-keycloak-id")
        self.keycloak()
        proc = self.run_region()
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("admin_persona_uid Keycloak user id biciminde degil", proc.stderr)
        self.assertFalse([c for c in self.calls() if c.startswith("docker-get")])
        self.assert_no_reset_no_persist()

    def test_matching_identity_with_working_password_never_resets(self):
        self.vault()
        self.keycloak()
        proc = self.run_region()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("STEP2-OK", proc.stdout)
        tokens = [c for c in self.calls() if c.startswith("TOKEN")]
        self.assertEqual(len(tokens), 1)
        self.assertIn("client=smoke-client", tokens[0])
        self.assertIn("user=%s" % USERNAME, tokens[0])
        self.assert_no_reset_no_persist()

    def test_rejected_vault_password_resets_only_the_vault_uid_and_persists_newline_free(self):
        self.vault(vault_value="stale-vault-value-000000")
        self.keycloak(accepted_value=None)  # nothing accepted until the reset lands
        proc = self.run_region(reset_accepted=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        resets = [c for c in self.calls() if c.startswith("RESET")]
        self.assertEqual(len(resets), 1, self.calls())
        self.assertTrue(resets[0].startswith("RESET %s ::" % UID), resets[0])
        self.assertNotIn("\\n", resets[0].split("::", 1)[1])
        persists = [c for c in self.calls() if c.startswith("PERSIST")]
        self.assertEqual(len(persists), 1)
        self.assertIn("bytes=32 trailing_newline=no", persists[0])  # 32 hex chars, no newline
        # the second token acquisition (verification) happens BEFORE persist
        order = [c.split()[0] for c in self.calls()]
        self.assertLess(order.index("RESET"), len(order) - 1)
        self.assertEqual(order[-1], "PERSIST")
        self.assertEqual(order.count("TOKEN"), 2)
        self.assertIn("PASS sentetik d35 admin parolasi Vault ile guvenli uzlastirildi", proc.stdout)
        persisted = (self.fix / "vault/persisted").read_bytes()
        self.assertEqual(len(persisted), 32)
        self.assertNotIn(b"\n", persisted)
        self.assertEqual(persisted.decode(), (self.fix / "kc/password.txt").read_text())

    def test_reset_not_accepted_by_keycloak_leaves_vault_untouched(self):
        self.vault(vault_value="stale-vault-value-000000")
        self.keycloak(accepted_value=None)
        proc = self.run_region(reset_accepted=False)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("Vault'a YAZILMADI", proc.stderr)
        self.assertEqual(len([c for c in self.calls() if c.startswith("RESET")]), 1)
        self.assertFalse([c for c in self.calls() if c.startswith("PERSIST")])
        self.assertFalse((self.fix / "vault/persisted").exists())

    def test_region_markers_and_order_are_stable(self):
        text = WRAPPER.read_text(encoding="utf-8")
        self.assertEqual(text.count(START), 1)
        self.assertEqual(text.count(END), 1)
        region = self.region
        verify = region.index('get "users/$D35_UID" -r "$REALM"')
        reset = region.index('update "users/$D35_UID/reset-password"')
        persist = region.index("persist_d35_password")
        self.assertLess(verify, reset)
        self.assertLess(reset, persist)
        self.assertEqual(region.count("reset-password"), 2)  # one call + one comment mention
        self.assertNotIn("-q \"email=", region)
        self.assertTrue(re.search(r"openssl rand -hex 16 \| tr -d '\\r\\n' >\"\$ADMIN_PASSWORD_FILE\"", region))


if __name__ == "__main__":
    unittest.main()
