import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[2]
COLLECTOR = ROOT / "scripts/faz22-remote-ops/collect-view-only-viewer-termination-case.sh"
SESSION = "termination-session-1"
STREAM = "termination-stream-1"
TENANT = "11111111-1111-4111-8111-111111111111"
DEVICE = "22222222-2222-4222-8222-222222222222"
OPERATOR = "termination-operator"


FAKE_CURL = r'''#!/usr/bin/env python3
import json
import os
import pathlib
import sys
import time

args = sys.argv[1:]
state_path = pathlib.Path(os.environ["FAKE_STATE"])

def load():
    return json.loads(state_path.read_text(encoding="utf-8"))

def save(state):
    state_path.write_text(json.dumps(state), encoding="utf-8")

def value(name):
    return args[args.index(name) + 1] if name in args else None

url = next((arg for arg in reversed(args) if arg.startswith("http")), "")
output = value("--output") or value("-o")
write_out = value("--write-out")

if url.endswith("/actuator/prometheus"):
    state = load()
    body = (
        f"remote_access_bridge_viewer_frames_sent_total {state['frames']}\n"
        f"remote_access_bridge_viewer_started_total {state['started']}\n"
        f"remote_access_bridge_viewer_ended_total {state['ended']}\n"
        "remote_access_bridge_operator_kill_ack_audit_failure_latched 0\n"
    ).encode()
    pathlib.Path(output).write_bytes(body)
    raise SystemExit(0)

if url.endswith("/close"):
    state = load()
    state["closed"] = True
    save(state)
    if output:
        pathlib.Path(output).write_bytes(b"")
    if write_out:
        sys.stdout.write("204")
    raise SystemExit(0)

if url.endswith("/termination-probes/heartbeat-loss"):
    state = load()
    state["closed"] = True
    save(state)
    pathlib.Path(output).write_text(json.dumps({
        "kind": "TERMINATED",
        "reason": "control-stream-loss-terminal-observed",
        "terminalState": "KILLED",
        "probeId": "fixture-heartbeat-probe",
    }), encoding="utf-8")
    if write_out:
        sys.stdout.write("200")
    raise SystemExit(0)

if "/view?streamId=" in url:
    state = load()
    state["started"] += 1
    save(state)
    while True:
        state = load()
        if state["closed"]:
            state["ended"] += 1
            save(state)
            raise SystemExit(0)
        state["frames"] += 1
        save(state)
        time.sleep(0.25)

raise SystemExit(2)
'''


FAKE_KUBECTL = r'''#!/usr/bin/env python3
import json
import os
import pathlib
prefix = "2026-07-14T00:00:02.000000Z"
case = os.environ["TEST_CASE"]
state_path = pathlib.Path(os.environ["FAKE_STATE"])
state = json.loads(state_path.read_text(encoding="utf-8"))
if case in {"localAbort", "ttlExpiry", "indicatorLoss"}:
    state["closed"] = True
    state_path.write_text(json.dumps(state), encoding="utf-8")
patterns = {
    "killOrRevoke": ["AGENT:AGENT_KILL_APPLIED"],
    "localAbort": ["AGENT:LOCAL_ABORT", "KILLED:local-abort"],
    "ttlExpiry": [
        "AGENT_ERROR:screen-view-permit-expired:retryable=false",
        "KILLED:screen-view-permit-expired",
    ],
    "heartbeatLoss": ["KILLED:control-stream-lost"],
    "indicatorLoss": ["AGENT:AGENT_INDICATOR_LOST", "KILLED:indicator-lost"],
}
for pattern in patterns[case]:
    print(f"{prefix} remote-bridge audit session={os.environ['TEST_SESSION']} type={pattern}")
print(f"{prefix} viewer stream END session={os.environ['TEST_SESSION']} stream={os.environ['TEST_STREAM']} framesDelivered=101")
'''


FAKE_DOCKER = r'''#!/usr/bin/env python3
import hashlib
import importlib.util
import json
import os
import pathlib
import sys

if len(sys.argv) > 1 and sys.argv[1] == "inspect":
    raise SystemExit(0)
sql = sys.stdin.read()
root = pathlib.Path(os.environ["TEST_ROOT"])
audit_path = root / "scripts/faz22-remote-ops/build-view-only-viewer-audit-summary.py"
spec = importlib.util.spec_from_file_location("audit_fixture_runtime", audit_path)
audit = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = audit
spec.loader.exec_module(audit)

term_path = root / "scripts/faz22-remote-ops/build-view-only-viewer-termination-audit.py"
spec2 = importlib.util.spec_from_file_location("term_fixture_runtime", term_path)
term = importlib.util.module_from_spec(spec2)
assert spec2 and spec2.loader
sys.modules[spec2.name] = term
spec2.loader.exec_module(term)

session = os.environ["TEST_SESSION"]
tenant = os.environ["TEST_TENANT"]
operator = os.environ["TEST_OPERATOR"]
device = os.environ["TEST_DEVICE"]
stream = os.environ["TEST_STREAM"]

if "endpoint_audit_events" in sql:
    base = {
        "sessionId": session, "deviceId": device, "streamId": stream,
        "recording": False, "attended": True, "capability": "VIEW_ONLY",
    }
    def row(event_id, action, occurred_at, metadata, previous=None):
        value = {
            "id": event_id, "tenant_id": tenant, "device_id": None,
            "command_id": None, "event_type": audit.EVENT_TYPE, "action": action,
            "performed_by_subject": operator, "correlation_id": session,
            "metadata": metadata, "before_state": None, "after_state": None,
            "occurred_at": occurred_at, "prev_event_hash": previous,
            "event_hash": "0" * 64, "event_hash_alg": audit.HASH_ALGORITHM,
            "event_hash_version": audit.HASH_VERSION,
        }
        value["event_hash"] = audit.computed_event_hash(value)
        return value
    start = row("00000000-0000-0000-0000-000000000001", "VIEW_START",
                "2026-07-14T00:00:00.000000Z", base)
    stop = row("00000000-0000-0000-0000-000000000002", "VIEW_STOP",
               "2026-07-14T00:00:02.000000Z",
               dict(base, framesDelivered=101, framesRenderAcknowledged=1), start["event_hash"])
    print(json.dumps(start, sort_keys=True))
    print(json.dumps(stop, sort_keys=True))
elif "session_recording_entry" in sql:
    permit = {
        "chainId": session, "seq": 0, "timestampMillis": 1783987200000,
        "kind": "POLICY_EVENT", "contentHash": hashlib.sha256(b"permit").hexdigest(),
        "previousHash": term.GENESIS_HASH, "entryHash": "0" * 64,
    }
    permit["entryHash"] = term.recording_entry_hash(permit)
    print(json.dumps(permit, sort_keys=True))
    if os.environ["TEST_CASE"] == "killOrRevoke":
        ack = {
            "chainId": session, "seq": 1, "timestampMillis": 1783987200001,
            "kind": "POLICY_EVENT",
            "contentHash": hashlib.sha256(term.KILL_ACK_EVENT.encode()).hexdigest(),
            "previousHash": permit["entryHash"], "entryHash": "0" * 64,
        }
        ack["entryHash"] = term.recording_entry_hash(ack)
        print(json.dumps(ack, sort_keys=True))
else:
    raise SystemExit(2)
'''


def sha256_text(value):
    import hashlib
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


class ViewerTerminationCollectorTest(unittest.TestCase):
    def test_all_cases_require_runtime_end_and_both_hash_chains(self):
        expected_triggers = {
            "localAbort": "local-abort",
            "killOrRevoke": "kill-or-revoke",
            "ttlExpiry": "ttl-expiry",
            "heartbeatLoss": "heartbeat-loss",
            "indicatorLoss": "indicator-loss",
        }
        for case_name, expected_trigger in expected_triggers.items():
            with self.subTest(case_name=case_name):
                self.run_case(case_name, expected_trigger)

    def run_case(self, case_name, expected_trigger):
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            for name, content in {
                "curl": FAKE_CURL, "kubectl": FAKE_KUBECTL, "docker": FAKE_DOCKER,
            }.items():
                path = fake_bin / name
                path.write_text(textwrap.dedent(content), encoding="utf-8")
                path.chmod(0o755)
            state = tmp / "state.json"
            state.write_text(json.dumps({
                "frames": 100, "started": 0, "ended": 0, "closed": False,
            }), encoding="utf-8")
            token = tmp / "operator.jwt"
            token.write_text("fixture-token", encoding="utf-8")
            claims = tmp / "claims.json"
            claims.write_text(json.dumps({
                "tenantSha256": sha256_text(TENANT),
                "subjectSha256": sha256_text(OPERATOR),
            }), encoding="utf-8")
            output = tmp / "output"
            env = os.environ.copy()
            env.update({
                "PATH": f"{fake_bin}:{env['PATH']}",
                "FAKE_STATE": str(state),
                "TEST_ROOT": str(ROOT),
                "TEST_SESSION": SESSION,
                "TEST_STREAM": STREAM,
                "TEST_TENANT": TENANT,
                "TEST_DEVICE": DEVICE,
                "TEST_OPERATOR": OPERATOR,
                "TEST_CASE": case_name,
                "MATRIX_OPERATOR_BASE": "http://fixture/operator",
                "MATRIX_MANAGEMENT_BASE": "http://fixture/management",
                "MATRIX_SESSION_ID": SESSION,
                "MATRIX_STREAM_ID": STREAM,
                "MATRIX_DEVICE_ID": DEVICE,
                "MATRIX_OPERATOR_TOKEN_FILE": str(token),
                "MATRIX_OPERATOR_CLAIMS_FILE": str(claims),
                "MATRIX_SOURCE_REVISION": "a" * 40,
                "MATRIX_AUTHORIZATION_SHA256": "sha256:" + "b" * 64,
                "MATRIX_OUTPUT_DIR": str(output),
                "MATRIX_TERMINATION_CASE": case_name,
                "MATRIX_K8S_CONTEXT": "fixture",
                "MATRIX_K8S_NAMESPACE": "fixture",
                "MATRIX_REMOTE_BRIDGE_DEPLOYMENT": "fixture",
                "MATRIX_TENANT_ID": TENANT,
                "MATRIX_PG_CONTAINER": "fixture",
                "MATRIX_PG_DATABASE": "fixture",
                "MATRIX_PG_USER": "fixture",
                "MATRIX_DB_SCHEMA": "endpoint_admin_service",
            })
            completed = subprocess.run(
                ["bash", str(COLLECTOR)], env=env, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertIn("raw_screen_persisted=false", completed.stdout)
            observation = json.loads(
                (output / f"observations/{case_name}.jsonl").read_text(encoding="utf-8")
            )
            audit = json.loads(
                (output / f"audit/{case_name}.jsonl").read_text(encoding="utf-8")
            )
            self.assertEqual(expected_trigger, observation["trigger"])
            self.assertEqual(observation["counters"]["globalFramesSentAtEnd"],
                             observation["counters"]["globalFramesSentAfterObservationWindow"])
            self.assertEqual(observation["counters"]["sessionFramesDeliveredAtEnd"], 101)
            self.assertEqual(observation["counters"]["observationWindowMillis"], 3000)
            self.assertTrue(audit["chainVerified"])
            self.assertEqual(audit["framesDelivered"], 101)
            serialized = json.dumps({"observation": observation, "audit": audit})
            self.assertNotIn(SESSION, serialized)
            self.assertNotIn(OPERATOR, serialized)
            self.assertEqual(
                {"audit", "observations"}, {path.name for path in output.iterdir()},
            )


if __name__ == "__main__":
    unittest.main()
