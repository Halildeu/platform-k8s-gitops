#!/usr/bin/env python3

import hashlib
import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WATCHER = ROOT / "scripts/deploy/watch-faz25-p5-frontend-routes.sh"
VALIDATOR = ROOT / "scripts/deploy/verify-faz25-p5-frontend-routes.py"
INGRESS_UID = "11111111-1111-4111-8111-111111111111"


def ingress(namespace="platform-test", name="platform", service="frontend"):
    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "Ingress",
        "metadata": {
            "namespace": namespace,
            "name": name,
            "uid": INGRESS_UID,
            "annotations": {},
        },
        "spec": {
            "rules": [
                {
                    "host": "testai.acik.com",
                    "http": {
                        "paths": [
                            {
                                "path": "/",
                                "pathType": "Prefix",
                                "backend": {
                                    "service": {
                                        "name": service,
                                        "port": {"number": 80},
                                    }
                                },
                            }
                        ]
                    },
                }
            ]
        },
    }


class Faz25P5RouteWatcherTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.report = self.root / "route-watch.json"
        self.stop = self.root / "route-watch.stop"
        self.ready = self.root / "route-watch.ready"
        self.browser_report = self.root / "browser-report.json"
        self.payload = self.root / "ingresses.json"
        self.fake_kubectl = self.root / "kubectl"
        self.fake_kubectl.write_text(
            "#!/usr/bin/env python3\n"
            "import os, sys, time\n"
            "from pathlib import Path\n"
            "if '--watch-only' in sys.argv:\n"
            "    event = os.environ.get('FAKE_INGRESS_EVENT', '')\n"
            "    if event:\n"
            "        print(event, flush=True)\n"
            "    while True:\n"
            "        time.sleep(1)\n"
            "else:\n"
            "    source = os.environ['FAKE_INGRESS_JSON']\n"
            "    if Path(os.environ['STOP_PATH']).exists() and os.environ.get('FAKE_FINAL_INGRESS_JSON'):\n"
            "        source = os.environ['FAKE_FINAL_INGRESS_JSON']\n"
            "    print(Path(source).read_text())\n"
        )
        self.fake_kubectl.chmod(0o700)
        self.browser_report.write_text(
            json.dumps(
                {"runtime": {"frontendAssetPaths": ["/assets/application.js"]}}
            )
        )

    def tearDown(self):
        self.tempdir.cleanup()

    def env(self):
        return {
            **os.environ,
            "REPORT_PATH": str(self.report),
            "STOP_PATH": str(self.stop),
            "READY_PATH": str(self.ready),
            "EXPECTED_INGRESS_UID": INGRESS_UID,
            "BROWSER_REPORT_PATH": str(self.browser_report),
            "ROUTE_VALIDATOR": str(VALIDATOR),
            "KUBECTL_BIN": str(self.fake_kubectl),
            "FAKE_INGRESS_JSON": str(self.payload),
        }

    def wait_until(self, predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.025)
        self.fail("timed out waiting for route watcher")

    def test_pass_report_spans_multiple_canonical_route_samples(self):
        self.payload.write_text(
            json.dumps(
                {
                    "metadata": {"resourceVersion": "101"},
                    "items": [ingress()],
                }
            )
        )
        process = subprocess.Popen(
            ["bash", str(WATCHER)],
            cwd=ROOT,
            env=self.env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.wait_until(lambda: self.ready.exists())
        time.sleep(0.4)
        self.stop.touch()
        stdout, stderr = process.communicate(timeout=5)
        self.assertEqual(process.returncode, 0, (stdout, stderr))

        report = json.loads(self.report.read_text())
        self.assertEqual(report["verdict"], "PASS")
        self.assertEqual(report["failureReason"], "")
        self.assertGreaterEqual(report["sampleCount"], 2)
        self.assertEqual(report["violationCount"], 0)
        self.assertTrue(report["eventWatchEstablished"])
        self.assertEqual(report["eventWatchResourceVersion"], "101")
        self.assertEqual(report["finalResourceVersion"], "101")
        self.assertEqual(report["eventCount"], 0)
        self.assertEqual(report["browserAssetPathCount"], 1)
        canonical_asset_paths = json.dumps(
            ["/assets/application.js"], sort_keys=True, separators=(",", ":")
        )
        self.assertEqual(
            report["browserAssetPathsSha256"],
            hashlib.sha256(f"{canonical_asset_paths}\n".encode()).hexdigest(),
        )
        self.assertEqual(len(report["routeProjectionSha256s"]), 1)
        self.assertEqual(
            report["target"]["canonicalIngress"]["uid"], INGRESS_UID
        )

    def test_route_collision_fails_closed_before_browser_ready(self):
        collision = ingress(
            namespace="attacker", name="collision", service="frontend"
        )
        collision["metadata"]["uid"] = "22222222-2222-4222-8222-222222222222"
        self.payload.write_text(
            json.dumps(
                {
                    "metadata": {"resourceVersion": "101"},
                    "items": [ingress(), collision],
                }
            )
        )
        result = subprocess.run(
            ["bash", str(WATCHER)],
            cwd=ROOT,
            env=self.env(),
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.ready.exists())
        report = json.loads(self.report.read_text())
        self.assertEqual(report["verdict"], "FAIL")
        self.assertEqual(
            report["failureReason"], "route-policy-or-collection-failure"
        )
        self.assertEqual(report["violationCount"], 1)

    def test_any_ingress_watch_event_fails_closed_during_browser_window(self):
        self.payload.write_text(
            json.dumps(
                {
                    "metadata": {"resourceVersion": "101"},
                    "items": [ingress()],
                }
            )
        )
        environment = self.env()
        environment["FAKE_INGRESS_EVENT"] = "102"
        result = subprocess.run(
            ["bash", str(WATCHER)],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertNotEqual(result.returncode, 0)
        report = json.loads(self.report.read_text())
        self.assertEqual(report["verdict"], "FAIL")
        self.assertEqual(report["failureReason"], "route-event-observed")
        self.assertGreaterEqual(report["eventCount"], 1)
        self.assertEqual(report["violationCount"], 1)

    def test_missing_list_resource_version_fails_closed(self):
        self.payload.write_text(json.dumps({"items": [ingress()]}))
        result = subprocess.run(
            ["bash", str(WATCHER)],
            cwd=ROOT,
            env=self.env(),
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertNotEqual(result.returncode, 0)
        report = json.loads(self.report.read_text())
        self.assertEqual(report["failureReason"], "missing-list-resource-version")
        self.assertFalse(report["eventWatchEstablished"])

    def test_observed_frontend_asset_route_collision_fails_closed(self):
        collision = ingress(
            namespace="attacker", name="asset-hijack", service="attacker"
        )
        collision["metadata"]["uid"] = "22222222-2222-4222-8222-222222222222"
        collision["spec"]["rules"][0]["http"]["paths"][0]["path"] = "/assets"
        self.payload.write_text(
            json.dumps(
                {
                    "metadata": {"resourceVersion": "101"},
                    "items": [ingress(), collision],
                }
            )
        )
        process = subprocess.Popen(
            ["bash", str(WATCHER)],
            cwd=ROOT,
            env=self.env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.wait_until(lambda: self.ready.exists())
        time.sleep(0.4)
        self.stop.touch()
        stdout, stderr = process.communicate(timeout=5)
        self.assertNotEqual(process.returncode, 0, (stdout, stderr))
        report = json.loads(self.report.read_text())
        self.assertEqual(
            report["failureReason"], "browser-asset-route-policy-failure"
        )
        self.assertEqual(report["violationCount"], 1)
        self.assertEqual(report["browserAssetPathCount"], 1)
        self.assertRegex(report["browserAssetPathsSha256"], r"^[0-9a-f]{64}$")

    def test_final_resource_version_drift_cannot_escape_after_browser(self):
        self.payload.write_text(
            json.dumps(
                {
                    "metadata": {"resourceVersion": "101"},
                    "items": [ingress()],
                }
            )
        )
        final_payload = self.root / "ingresses-final.json"
        final_payload.write_text(
            json.dumps(
                {
                    "metadata": {"resourceVersion": "102"},
                    "items": [ingress()],
                }
            )
        )
        environment = self.env()
        environment["FAKE_FINAL_INGRESS_JSON"] = str(final_payload)
        process = subprocess.Popen(
            ["bash", str(WATCHER)],
            cwd=ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.wait_until(lambda: self.ready.exists())
        self.stop.touch()
        stdout, stderr = process.communicate(timeout=5)
        self.assertNotEqual(process.returncode, 0, (stdout, stderr))
        report = json.loads(self.report.read_text())
        self.assertEqual(report["failureReason"], "route-resource-version-changed")
        self.assertEqual(report["eventWatchResourceVersion"], "101")
        self.assertEqual(report["finalResourceVersion"], "102")


if __name__ == "__main__":
    unittest.main()
