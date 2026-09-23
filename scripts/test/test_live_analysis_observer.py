"""Offline negative/ordering cases for the live-before-EOF acceptance evidence."""

import asyncio
import copy
import json
from pathlib import Path
import sys
import subprocess
import time
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "faz24"))
from live_analysis_observer import AnalysisObserver, snapshot_counts
from meeting_source_runtime_metadata import parse_live_diagnostics, mtls_health_probe
from run_speechmatics_realtime_lifecycle_acceptance import stream_audio

SNAPSHOT = {
    "version": 1,
    "is_partial": True,
    "grounding_policy": "verified_only",
    "summary": "Sentetik proje özeti",
    "summary_grounding_status": "verified",
    "decisions": ["Sentetik karar"],
    "action_items": [{"text": "Sentetik görev"}],
}


def frame(value=SNAPSHOT):
    return (
        "event: analysis\r\ndata: " + json.dumps(value, ensure_ascii=False) + "\r\n\r\n"
    ).encode()


class ParserTests(unittest.TestCase):
    def test_mtls_probe_keeps_trust_and_does_not_export_response_or_credentials(self):
        commands = []

        def run(command, **kwargs):
            commands.append(command)
            return types.SimpleNamespace(returncode=60, stdout="000 0.01 0.00 0.02 20",
                                         stderr="private diagnostic must not be exported")

        result = mtls_health_probe("synthetic-pod", 8244, run)
        self.assertEqual(result["exitCode"], 60)
        self.assertEqual(result["sslVerifyResult"], 20)
        self.assertEqual(result["httpStatus"], 0)
        self.assertNotIn("private", json.dumps(result))
        self.assertNotIn("--insecure", commands[0])
        self.assertNotIn("--location", commands[0])
        self.assertIn("--cacert", commands[0])
        self.assertIn("/dev/null", commands[0])
        with self.assertRaises(ValueError):
            mtls_health_probe("synthetic-pod", 443, run)
        self.assertEqual(len(commands), 1)

    def test_server_diagnostics_export_only_allowlisted_fields(self):
        result = parse_live_diagnostics(
            'audio_gw_live_analyze_publish_error_total{ignored="private"} 2.0\n'
            'unrelated_secret_metric 42\n',
            'private transcript / bearer should not appear\n'
            'WARN live-analyze trigger failed err_class=TimeoutException http_status=0 '
            'meeting_id=00000000-0000-0000-0000-000000000000 seq=5 elapsed_ms=120000\n',
        )
        self.assertEqual(result["counters"], {"audio_gw_live_analyze_publish_error_total": 2.0})
        self.assertEqual(result["recentErrors"][0]["errorClass"], "TimeoutException")
        self.assertNotIn("private", json.dumps(result))
        self.assertNotIn("bearer", json.dumps(result))

    def test_helper_can_be_loaded_by_other_tools_without_sys_path_change(self):
        helper = Path(__file__).resolve().parents[1] / "faz24/run_speechmatics_realtime_lifecycle_acceptance.py"
        result = subprocess.run([sys.executable, "-I", "-c",
                                 "import importlib.util, sys; s=importlib.util.spec_from_file_location('helper',sys.argv[1]); "
                                 "m=importlib.util.module_from_spec(s); s.loader.exec_module(m)", str(helper)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def observer(self):
        result = AnalysisObserver()
        result.recording = True
        result.audio_started_at = time.monotonic()
        return result

    def test_split_utf8_and_crlf(self):
        observer = self.observer()
        for byte in frame():
            observer.push(bytes([byte]))
        self.assertTrue(observer.metrics["usableBeforeEof"])
        self.assertEqual(observer.metrics["accepted"], 1)
        self.assertNotIn("Sentetik", json.dumps(observer.metrics))

    def test_heartbeat_and_malformed_are_not_success(self):
        observer = self.observer()
        observer.push(
            b": heartbeat\n\nevent: analysis\ndata: {\n\nevent: other\ndata: {}\n\n"
        )
        self.assertEqual(observer.metrics["heartbeats"], 1)
        self.assertEqual(observer.metrics["invalidJson"], 1)
        self.assertEqual(observer.metrics["unknownEvents"], 1)
        self.assertFalse(observer.usable.is_set())

    def test_post_eof_and_pre_audio_never_satisfy(self):
        observer = AnalysisObserver()
        observer.push(frame())
        observer.audio_started_at = time.monotonic()
        observer.push(frame())
        self.assertEqual(observer.metrics["accepted"], 2)
        self.assertFalse(observer.metrics["usableBeforeEof"])

    def test_empty_or_unverified_output_is_not_product_success(self):
        for field, value in (
            ("decisions", []),
            ("action_items", []),
            ("summary", " "),
            ("summary_grounding_status", "unverified"),
        ):
            with self.subTest(field=field):
                snapshot = copy.deepcopy(SNAPSHOT)
                snapshot[field] = value
                observer = self.observer()
                observer.push(frame(snapshot))
                self.assertFalse(observer.usable.is_set())

    def test_contract_rejects_wrong_shapes(self):
        for field, value in (
            ("version", True),
            ("version", -1),
            ("version", 2**53),
            ("is_partial", "true"),
            ("decisions", [7]),
            ("action_items", [{"text": "ok", "owner": 7}]),
            ("grounding_policy", "unverified"),
        ):
            with self.subTest(field=field):
                snapshot = copy.deepcopy(SNAPSHOT)
                snapshot[field] = value
                self.assertIsNone(snapshot_counts(snapshot))

    def test_bound_on_unterminated_event(self):
        observer = self.observer()
        with self.assertRaisesRegex(ValueError, "frame-limit"):
            observer.push(b"x" * 262145)
        self.assertEqual(observer.metrics["overflows"], 1)
        self.assertFalse(observer.usable.is_set())


class StreamOrderingTests(unittest.IsolatedAsyncioTestCase):
    async def test_transport_preserves_auth_boundary_and_closes_process(self):
        for status, content_type, expected in (
            (200, "text/event-stream", True),
            (302, "text/event-stream", False),
            (200, "application/json", False),
        ):
            with self.subTest(status=status, content_type=content_type):
                output = asyncio.StreamReader()
                output.feed_data(
                    (
                        f"HTTP/1.1 {status} Test\r\nContent-Type: {content_type}\r\n\r\n"
                    ).encode()
                    + frame()
                )
                output.feed_eof()

                class Input:
                    data = b""

                    def write(self, value):
                        self.data += value

                    async def drain(self):
                        pass

                    def close(self):
                        pass

                class Process:
                    returncode = None
                    stdin = Input()
                    stdout = output

                    def kill(self):
                        self.returncode = -9

                    async def wait(self):
                        return self.returncode

                process = Process()
                arguments = []

                async def spawn(*args, **kwargs):
                    arguments.extend(args)
                    return process

                observer = AnalysisObserver()
                observer.recording = True
                observer.audio_started_at = time.monotonic()
                with patch("asyncio.create_subprocess_exec", spawn):
                    await observer.observe(
                        "https://testai.acik.com/synthetic", "synthetic-bearer", 150
                    )
                self.assertEqual(observer.metrics["usableBeforeEof"], expected)
                self.assertNotIn("synthetic-bearer", " ".join(arguments))
                self.assertIn(b"synthetic-bearer", process.stdin.data)
                self.assertNotIn("--location", arguments)
                self.assertEqual(arguments[1], "--disable")
                self.assertIsNotNone(process.returncode)

    async def test_snapshot_must_arrive_before_eof(self):
        for arrival in ("audio", "eof"):
            with self.subTest(arrival=arrival):
                observer = AnalysisObserver()
                queue = asyncio.Queue()
                await queue.put(
                    json.dumps(
                        {"type": "ready", "live_model": "speechmatics-realtime-v2"}
                    )
                )

                class Socket:
                    async def __aenter__(self):
                        return self

                    async def __aexit__(self, *args):
                        return False

                    def __aiter__(self):
                        return self

                    async def __anext__(self):
                        return await queue.get()

                    async def send(self, value):
                        if isinstance(value, bytes) and arrival == "audio":
                            observer.push(frame())
                        if value == '{"type":"eof"}':
                            observer.push(frame())
                            await queue.put('{"type":"eof_ack"}')
                            await queue.put('{"type":"drained"}')

                real_sleep = asyncio.sleep

                async def no_delay(_):
                    await real_sleep(0)

                fixture = (
                    Path(__file__).resolve().parents[1]
                    / "faz24/fixtures/speechmatics-realtime-tr-v1.wav"
                )
                with patch.dict(
                    sys.modules,
                    {
                        "websockets": types.SimpleNamespace(
                            connect=lambda *a, **kw: Socket()
                        )
                    },
                ), patch("asyncio.sleep", no_delay):
                    result = await stream_audio(
                        base_url="https://testai.acik.com",
                        token="synthetic",
                        session_id="SES-synthetic",
                        audio_path=fixture,
                        analysis_observer=observer,
                        live_analysis_wait_seconds=0,
                    )
                self.assertTrue(result["drained"])
                self.assertFalse(observer.recording)
                self.assertEqual(
                    observer.metrics["usableBeforeEof"], arrival == "audio"
                )


if __name__ == "__main__":
    unittest.main()
