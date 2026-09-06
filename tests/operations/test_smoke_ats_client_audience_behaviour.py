"""Behavioural matrix for `setup-smoke-ats-client.sh` platform audience mappers.

The string pins in `test_smoke_ats_client_scope_invariant.py` say what the script *contains*;
this suite runs the script against a fake `docker` (kcadm answered from a JSON state file,
every mutation logged) and asserts what it *does*:

* exact desired set              -> `--check` 0, `--apply` performs no mapper mutation
* one desired mapper missing     -> `--check` 2, first `--apply` creates exactly it, second is a no-op
* same-name mapper, wrong config -> `--apply` updates it by id (no create, no delete)
* extra broad audience mapper    -> `--check` 2, `--apply` deletes it (least-privilege exact set)
* mapper listing fails           -> `--apply` exits 1 with ZERO create/update/delete
* postcondition read-back broken -> `--apply` exits 3 after the create

Measured 2026-09-06: without the two audiences every smoke-ats-v1 call died with 401
(permission-service, user-service and the ATS→platform delegated authz all validate `aud`).
"""

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts/keycloak/setup-smoke-ats-client.sh"

CLIENT = "cid-1"
ATS = "aid-1"

FAKE_DOCKER = r'''#!/usr/bin/env python3
"""Fake `docker` for setup-smoke-ats-client.sh: answers kcadm from FAKE_KC_STATE, logs mutations."""
import json, os, sys

STATE = os.environ["FAKE_KC_STATE"]
LOG = os.environ["FAKE_KC_LOG"]
CLIENT, ATS = "cid-1", "aid-1"

def load():
    with open(STATE) as fh:
        return json.load(fh)

def save(state):
    with open(STATE, "w") as fh:
        json.dump(state, fh)

def log(line):
    with open(LOG, "a") as fh:
        fh.write(line + "\n")

def die(msg):
    sys.stderr.write("fake-docker: " + msg + "\n")
    sys.exit(1)

argv = sys.argv[1:]
if not argv or argv[0] != "exec":
    die("only `exec` is supported: %r" % argv)
argv = argv[1:]
stdin_mode = False
while argv and argv[0].startswith("-"):
    if argv[0] == "-i":
        stdin_mode = True; argv = argv[1:]
    elif argv[0] == "-e":
        argv = argv[2:]
    else:
        die("unknown docker flag %r" % argv[0])
container, cmd = argv[0], argv[1:]
if not cmd:
    die("no command")

if cmd[0] == "mktemp":
    print("/tmp/kcadm-fake.cfg"); sys.exit(0)
if cmd[0] in ("chmod", "rm"):
    sys.exit(0)
if cmd[0] == "sh":            # isolated admin login runs inside the container
    log("login"); sys.exit(0)
if cmd[0] != "/opt/keycloak/bin/kcadm.sh":
    die("unexpected command %r" % cmd)

args = cmd[1:]
verb, endpoint = args[0], (args[1] if len(args) > 1 else "")
flags = args[2:]
def flag(name):
    return flags[flags.index(name) + 1] if name in flags else None
csv = flag("--format") == "csv"
fields = (flag("--fields") or "").split(",") if flag("--fields") else []
queries = [flags[i + 1] for i, f in enumerate(flags) if f == "-q"]
state = load()

if verb == "config":
    sys.exit(0)
if verb == "get":
    if endpoint.startswith("realms/"):
        print(json.dumps({"realm": endpoint.split("/", 1)[1]})); sys.exit(0)
    if endpoint == "clients":
        if "clientId=ats-api" in queries:
            print(ATS if csv else json.dumps([{"id": ATS}])); sys.exit(0)
        if "clientId=smoke-ats-v1" in queries:
            print(CLIENT if csv else json.dumps([{"id": CLIENT}])); sys.exit(0)
        die("unexpected clients query %r" % queries)
    if endpoint == "client-scopes":
        scopes = [("s1", "ats.read"), ("s2", "ats-api-audience"), ("s3", "profile")]
        if fields == ["name"]:
            print("\n".join(n for _, n in scopes))
        else:
            print("\n".join("%s,%s" % s for s in scopes))
        sys.exit(0)
    if endpoint == "clients/%s/roles" % ATS:
        roles = [{"id": "r1", "name": "ats.reader"}, {"id": "r2", "name": "ats.writer"}]
        print("\n".join(r["name"] for r in roles) if csv else json.dumps(roles)); sys.exit(0)
    if endpoint == "clients/%s" % CLIENT:
        print(json.dumps({"id": CLIENT, "clientId": "smoke-ats-v1", "enabled": True,
                          "publicClient": False, "serviceAccountsEnabled": False,
                          "directAccessGrantsEnabled": True, "standardFlowEnabled": False,
                          "implicitFlowEnabled": False, "fullScopeAllowed": False}))
        sys.exit(0)
    if endpoint == "clients/%s/scope-mappings/clients/%s" % (CLIENT, ATS):
        print("ats.reader\nats.writer"); sys.exit(0)
    if endpoint == "clients/%s/default-client-scopes" % CLIENT:
        print("ats-api-audience\nats.read"); sys.exit(0)
    if endpoint == "clients/%s/client-secret" % CLIENT:
        print(json.dumps({"value": "fake-secret"})); sys.exit(0)
    if endpoint == "clients/%s/protocol-mappers/models" % CLIENT:
        if state.get("mappers_read_fail"):
            die("simulated kcadm failure listing mappers")
        print(json.dumps(state["mappers"])); sys.exit(0)
    die("unexpected get %r" % endpoint)

if verb == "create":
    body = json.loads(sys.stdin.read()) if flag("-f") == "-" else None
    if endpoint == "clients/%s/protocol-mappers/models" % CLIENT:
        log("create|%s|%s" % (body["name"], body["config"]["included.client.audience"]))
        if not state.get("ignore_create"):
            body["id"] = "m%d" % (len(state["mappers"]) + 1)
            state["mappers"].append(body); save(state)
        sys.exit(0)
    if endpoint == "clients/%s/scope-mappings/clients/%s" % (CLIENT, ATS):
        log("scope-mapping"); sys.exit(0)
    die("unexpected create %r" % endpoint)

if verb == "update":
    if endpoint.startswith("clients/%s/protocol-mappers/models/" % CLIENT):
        mid = endpoint.rsplit("/", 1)[1]
        body = json.loads(sys.stdin.read())
        log("update|%s|%s|%s" % (mid, body["name"], body["config"]["included.client.audience"]))
        state["mappers"] = [dict(body, id=mid) if m.get("id") == mid else m for m in state["mappers"]]
        save(state); sys.exit(0)
    if endpoint.startswith("clients/%s/default-client-scopes/" % CLIENT) or endpoint == "clients/%s" % CLIENT:
        log("update|%s" % endpoint); sys.exit(0)
    die("unexpected update %r" % endpoint)

if verb == "delete":
    if endpoint.startswith("clients/%s/protocol-mappers/models/" % CLIENT):
        mid = endpoint.rsplit("/", 1)[1]
        log("delete|%s" % mid)
        state["mappers"] = [m for m in state["mappers"] if m.get("id") != mid]
        save(state); sys.exit(0)
    die("unexpected delete %r" % endpoint)

die("unexpected verb %r" % verb)
'''


def mapper(name, audience, mid, access="true"):
    return {
        "id": mid,
        "name": name,
        "protocol": "openid-connect",
        "protocolMapper": "oidc-audience-mapper",
        "config": {"included.client.audience": audience, "access.token.claim": access},
    }


GOOD = [
    mapper("smoke-ats-audience-permission-service", "permission-service", "m1"),
    mapper("smoke-ats-audience-user-service", "user-service", "m2"),
]


def bash_major():
    out = subprocess.run(
        ["bash", "-c", 'printf "%s" "${BASH_VERSINFO[0]}"'], capture_output=True, text=True
    )
    return int(out.stdout or "0")


class SmokeAtsAudienceBehaviour(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if bash_major() < 4:
            msg = "setup-smoke-ats-client.sh needs bash >= 4 (mapfile); bash %d on PATH" % bash_major()
            if os.environ.get("CI") == "true":
                raise AssertionError(msg + " — CI must run the behavioural matrix")
            raise unittest.SkipTest(msg)

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="smoke-ats-behaviour-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        shim = self.tmp / "bin" / "docker"
        shim.parent.mkdir()
        shim.write_text(FAKE_DOCKER, encoding="utf-8")
        shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
        self.state = self.tmp / "state.json"
        self.log = self.tmp / "mutations.log"
        self.log.touch()

    def run_script(self, mode, mappers, **extra_state):
        self.state.write_text(json.dumps({"mappers": mappers, **extra_state}))
        self.log.write_text("")
        env = dict(os.environ)
        env["PATH"] = str(self.tmp / "bin") + os.pathsep + env.get("PATH", "")
        env["FAKE_KC_STATE"] = str(self.state)
        env["FAKE_KC_LOG"] = str(self.log)
        env["REALM"] = "platform-test"
        proc = subprocess.run(
            ["bash", str(SCRIPT), mode], env=env, capture_output=True, text=True, timeout=120
        )
        return proc

    def mutations(self):
        return [
            line for line in self.log.read_text().splitlines()
            if line.startswith(("create|", "update|m", "delete|"))
        ]

    def current_mappers(self):
        return json.loads(self.state.read_text())["mappers"]

    def test_exact_set_is_converged_and_apply_touches_no_mapper(self):
        check = self.run_script("--check", GOOD)
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
        self.assertIn("=== CONVERGED ===", check.stdout)
        apply = self.run_script("--apply", GOOD)
        self.assertEqual(apply.returncode, 0, apply.stdout + apply.stderr)
        self.assertEqual(self.mutations(), [])
        self.assertIn("audience mapper seti converged", apply.stdout)

    def test_missing_mapper_is_drift_then_created_once(self):
        check = self.run_script("--check", GOOD[:1])
        self.assertEqual(check.returncode, 2, check.stdout + check.stderr)
        self.assertIn("audience-eksik=1", check.stdout)
        first = self.run_script("--apply", GOOD[:1])
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual(self.mutations(), ["create|smoke-ats-audience-user-service|user-service"])
        self.assertEqual(len(self.current_mappers()), 2)
        second = self.run_script("--apply", self.current_mappers())
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(self.mutations(), [], "second --apply must be a no-op")

    def test_same_name_wrong_config_is_updated_by_id_not_recreated(self):
        wrong = [GOOD[0], mapper("smoke-ats-audience-user-service", "account", "m2")]
        check = self.run_script("--check", wrong)
        self.assertEqual(check.returncode, 2)
        apply = self.run_script("--apply", wrong)
        self.assertEqual(apply.returncode, 0, apply.stdout + apply.stderr)
        self.assertEqual(self.mutations(), ["update|m2|smoke-ats-audience-user-service|user-service"])
        audiences = sorted(m["config"]["included.client.audience"] for m in self.current_mappers())
        self.assertEqual(audiences, ["permission-service", "user-service"])

    def test_extra_broad_audience_mapper_is_drift_and_removed(self):
        extra = GOOD + [mapper("some-other-audience", "frontend", "m9")]
        check = self.run_script("--check", extra)
        self.assertEqual(check.returncode, 2, check.stdout + check.stderr)
        self.assertIn("BEKLENMEYEN mapper", check.stdout + check.stderr)
        apply = self.run_script("--apply", extra)
        self.assertEqual(apply.returncode, 0, apply.stdout + apply.stderr)
        self.assertEqual(self.mutations(), ["delete|m9"])
        self.assertEqual({m["id"] for m in self.current_mappers()}, {"m1", "m2"})

    def test_listing_failure_stops_before_any_mutation(self):
        apply = self.run_script("--apply", GOOD[:1], mappers_read_fail=True)
        self.assertEqual(apply.returncode, 1, apply.stdout + apply.stderr)
        self.assertIn("client mapper listesi okunamad", apply.stderr)
        self.assertEqual(self.mutations(), [])
        check = self.run_script("--check", GOOD, mappers_read_fail=True)
        self.assertEqual(check.returncode, 1)
        self.assertNotIn("=== CONVERGED ===", check.stdout)

    def test_postcondition_failure_is_exit_3(self):
        apply = self.run_script("--apply", GOOD[:1], ignore_create=True)
        self.assertEqual(apply.returncode, 3, apply.stdout + apply.stderr)
        self.assertIn("POSTCONDITION FAIL", apply.stderr)
        self.assertEqual(self.mutations(), ["create|smoke-ats-audience-user-service|user-service"])


if __name__ == "__main__":
    unittest.main()
