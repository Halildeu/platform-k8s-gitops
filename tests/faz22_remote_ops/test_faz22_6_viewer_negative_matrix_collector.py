import importlib.util
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[2]
COLLECTOR = ROOT / "scripts/faz22-remote-ops/collect-view-only-viewer-negative-matrix.sh"
PRODUCER_PATH = ROOT / "scripts/faz22-remote-ops/produce-view-only-viewer-matrix-evidence.py"
SPEC = importlib.util.spec_from_file_location("negative_matrix_producer", PRODUCER_PATH)
PRODUCER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.path.insert(0, str(PRODUCER_PATH.parent))
sys.modules[SPEC.name] = PRODUCER
SPEC.loader.exec_module(PRODUCER)


FAKE_CURL = r'''#!/usr/bin/env python3
import fcntl
import json
import os
import pathlib
import signal
import sys
import time


args = sys.argv[1:]
state_path = pathlib.Path(os.environ["FAKE_CURL_STATE"])
lock_path = state_path.with_suffix(".lock")
log_path = pathlib.Path(os.environ["FAKE_CURL_LOG"])
with log_path.open("a", encoding="utf-8") as log:
    log.write(json.dumps(args) + "\n")


def value(*names):
    for index, arg in enumerate(args):
        if arg in names and index + 1 < len(args):
            return args[index + 1]
    return None


def mutate(callback):
    lock_path.touch(exist_ok=True)
    with lock_path.open("r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = json.loads(state_path.read_text(encoding="utf-8"))
        result = callback(state)
        state_path.write_text(json.dumps(state), encoding="utf-8")
        return result


def token_value():
    config = value("--config")
    if not config:
        return ""
    raw = sys.stdin.read() if config == "-" else pathlib.Path(config).read_text(encoding="utf-8")
    marker = "Authorization: Bearer "
    return raw.split(marker, 1)[1].split('"', 1)[0] if marker in raw else ""


url = next((arg for arg in reversed(args) if arg.startswith("http")), "")
method = value("--request") or "GET"
output = value("--output", "-o")
write_out = value("--write-out")
token = token_value()
body = b""
code = 200

if url.endswith("/actuator/prometheus"):
    state = mutate(lambda current: dict(current))
    body = (f"remote_access_bridge_viewer_frames_sent_total {state['frames']}\n"
            f"remote_access_bridge_viewer_rejected_total {state['rejected']}\n"
            f"remote_access_bridge_viewer_started_total {state['started']}\n"
            f"remote_access_bridge_viewer_ended_total {state['ended']}\n").encode()
elif "/negative-probes/expired-permit" in url:
    code = 422
    body = json.dumps({"kind": "DENY", "agentErrorCode":
        "operation-dispatch-failed:permit-invalid"}).encode()
elif "/negative-probes/replay" in url:
    code = 422
    body = json.dumps({"kind": "DENY", "agentErrorCode":
        "operation-dispatch-failed:seq-replay"}).encode()
elif url.endswith("/close") and method == "POST":
    mutate(lambda state: state.update(closed=True))
    code = 204
elif url.endswith("/sessions") and method == "POST":
    code = 404
elif "/view?streamId=" in url:
    if not token:
        mutate(lambda state: state.update(rejected=state["rejected"] + 1))
        code = 401
    elif token == "wrong-role-token":
        mutate(lambda state: state.update(rejected=state["rejected"] + 1))
        code = 401
    elif token == "wrong-tenant-token":
        mutate(lambda state: state.update(rejected=state["rejected"] + 1))
        code = 404
    else:
        def activate_stream(state):
            state.update(active=True, started=state["started"] + 1)
            return "stream"

        decision = mutate(lambda state: (
            "closed" if state["closed"] else "occupied" if state["active"] else
            activate_stream(state)
        ))
        if decision == "closed":
            mutate(lambda state: state.update(rejected=state["rejected"] + 1))
            code = 404
        elif decision == "occupied":
            mutate(lambda state: state.update(rejected=state["rejected"] + 1))
            code = 409
        else:
            def stop(_signum, _frame):
                mutate(lambda state: state.update(active=False, ended=state["ended"] + 1))
                raise SystemExit(0)
            signal.signal(signal.SIGTERM, stop)
            signal.signal(signal.SIGINT, stop)
            with open(output, "wb", buffering=0) as stream:
                while True:
                    stream.write(b"event: frame\ndata: fixture-only\n\n")
                    mutate(lambda state: state.update(frames=state["frames"] + 1))
                    time.sleep(0.03)
            raise SystemExit(0)

if output:
    pathlib.Path(output).write_bytes(body)
else:
    sys.stdout.buffer.write(body)
if write_out:
    sys.stdout.write(str(code))
'''


def sha(char):
    return "sha256:" + char * 64


class NegativeMatrixCollectorTest(unittest.TestCase):
    def test_collects_nine_digest_bound_cases_without_persisting_stream(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            fake_curl = fake_bin / "curl"
            fake_curl.write_text(FAKE_CURL, encoding="utf-8")
            fake_curl.chmod(0o755)

            state = tmp / "state.json"
            request_log = tmp / "curl-requests.jsonl"
            request_log.touch()
            state.write_text(json.dumps({
                "frames": 100, "rejected": 10, "started": 1, "ended": 1,
                "active": False, "closed": False,
            }), encoding="utf-8")
            files = {
                "operator.jwt": "operator-token",
                "wrong-role.jwt": "wrong-role-token",
                "wrong-tenant.jwt": "wrong-tenant-token",
                "operator-claims.json": json.dumps({
                    "subjectSha256": sha("3"), "tenantSha256": sha("2"),
                }),
                "wrong-role-claims.json": json.dumps({
                    "subjectSha256": sha("6"), "tenantSha256": sha("2"),
                }),
                "wrong-tenant-claims.json": json.dumps({
                    "subjectSha256": sha("7"), "tenantSha256": sha("8"),
                }),
            }
            for name, content in files.items():
                (tmp / name).write_text(content, encoding="utf-8")
            device_id = "11111111-1111-4111-8111-111111111111"
            root_binding = {
                "sessionSha256": sha("a"),
                "tenantSha256": sha("2"),
                "operatorSha256": sha("3"),
                "deviceSha256": "sha256:" + hashlib.sha256(device_id.encode()).hexdigest(),
            }
            (tmp / "root-binding.json").write_text(json.dumps(root_binding), encoding="utf-8")

            output = tmp / "output"
            env = os.environ.copy()
            env.update({
                "PATH": f"{fake_bin}:{env['PATH']}",
                "FAKE_CURL_STATE": str(state),
                "FAKE_CURL_LOG": str(request_log),
                "MATRIX_OPERATOR_BASE": "http://collector/internal/remote-bridge/operator",
                "MATRIX_MANAGEMENT_BASE": "http://collector/management",
                "MATRIX_SESSION_ID": "matrix-session-1",
                "MATRIX_STREAM_ID": "stream-1",
                "MATRIX_DEVICE_ID": device_id,
                "MATRIX_OPERATOR_TOKEN_FILE": str(tmp / "operator.jwt"),
                "MATRIX_OPERATOR_CLAIMS_FILE": str(tmp / "operator-claims.json"),
                "MATRIX_WRONG_ROLE_TOKEN_FILE": str(tmp / "wrong-role.jwt"),
                "MATRIX_WRONG_ROLE_CLAIMS_FILE": str(tmp / "wrong-role-claims.json"),
                "MATRIX_WRONG_TENANT_TOKEN_FILE": str(tmp / "wrong-tenant.jwt"),
                "MATRIX_WRONG_TENANT_CLAIMS_FILE": str(tmp / "wrong-tenant-claims.json"),
                "MATRIX_SOURCE_REVISION": "1" * 40,
                "MATRIX_AUTHORIZATION_SHA256": sha("9"),
                "MATRIX_OUTPUT_DIR": str(output),
                "MATRIX_ROOT_BINDING_FILE": str(tmp / "root-binding.json"),
            })
            try:
                completed = subprocess.run(
                    ["bash", str(COLLECTOR)], env=env, text=True,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    # The collector's production stream is independently bounded
                    # at 90 seconds.  A 30-second fixture watchdog was shorter
                    # than that contract and flaked under a loaded GitHub runner.
                    timeout=120,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                state_snapshot = state.read_text(encoding="utf-8")
                request_snapshot = request_log.read_text(encoding="utf-8")
                self.fail(
                    "negative matrix fixture exceeded its 120-second watchdog; "
                    f"state={state_snapshot}; requests={request_snapshot}; "
                    f"stdout={exc.stdout!r}; stderr={exc.stderr!r}"
                )
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertIn("raw_screen_persisted=false", completed.stdout)

            context_raw = (output / "context.json").read_bytes()
            observations_raw = (output / "observations/negative.jsonl").read_bytes()
            context = PRODUCER.load_context(context_raw, "negative", "1" * 40)
            self.assertEqual(root_binding, context["rootBinding"])
            self.assertEqual(PRODUCER.common.VERIFIER.digest_bytes(observations_raw),
                             context["observationsSha256"])
            child, produced = PRODUCER.build_negative(context, observations_raw)
            raw_child = PRODUCER.encode_json(child)
            produced["evidence/negative.json"] = raw_child
            PRODUCER.common.VERIFIER.validate_matrix_source_attestations(
                "negative", produced, raw_child,
            )
            cases = [json.loads(line) for line in observations_raw.splitlines()]
            self.assertEqual(list(PRODUCER.common.VERIFIER.NEGATIVE_CASES),
                             [case["caseName"] for case in cases])
            disconnected = next(case for case in cases if case["caseName"] == "disconnectedViewer")
            self.assertGreater(disconnected["response"]["bodyLength"], 0)
            self.assertEqual("stream-content-digested-no-persistence",
                             disconnected["response"]["bodyClass"])
            self.assertEqual({"context.json", "close.code", "observations"},
                             {path.name for path in output.iterdir()})
            raw_stream_fixture = b"event: frame\ndata: fixture-only"
            for path in output.rglob("*"):
                if path.is_file():
                    self.assertNotIn(raw_stream_fixture, path.read_bytes())
            invocations = [json.loads(line) for line in request_log.read_text().splitlines()]
            session_open = [
                args for args in invocations
                if args[-1] == "http://collector/internal/remote-bridge/operator/sessions"
            ]
            self.assertEqual(1, len(session_open))
            self.assertIn("POST", session_open[0])
            self.assertIn("--data-binary", session_open[0])


if __name__ == "__main__":
    unittest.main()
