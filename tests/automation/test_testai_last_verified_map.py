"""gitops#3618 — stability-window scope comes from the last PASS evidence, not
from the push's before/after diff, so a superseded or failed run's services are
never skipped."""
from __future__ import annotations

import importlib.util
import io
import json
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "automation" / "testai-last-verified-map.py"
spec = importlib.util.spec_from_file_location("last_verified_map", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

D = {f"svc{i}": f"sha256:{i:064x}" for i in range(5)}


def report(verdict="PASS", digests=None, schema="testai-backend-runtime-verification-v1"):
    return {"schemaVersion": schema, "verdict": verdict, "expectedDigests": digests}


def zipped(name, payload: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(name, json.dumps(payload))
    return buf.getvalue()


class ChangedServicesTests(unittest.TestCase):
    def test_services_whose_digest_moved_since_the_last_pass_owe_a_window(self):
        verified = {"auth-service": "sha256:" + "a" * 64, "api-gateway": "sha256:" + "b" * 64}
        current = {"auth-service": "sha256:" + "c" * 64, "api-gateway": "sha256:" + "b" * 64, "new-svc": "sha256:" + "d" * 64}
        self.assertEqual(["auth-service", "new-svc"], mod.changed_services(current, verified, False))

    def test_superseded_push_is_covered_by_the_next_push(self):
        # Push A moved auth (never verified: superseded); push B moved api-gateway.
        # A before/after diff for B would list only api-gateway; the PASS map still
        # carries auth's old digest, so auth owes its window in B.
        last_pass = {"auth-service": "sha256:" + "a" * 64, "api-gateway": "sha256:" + "b" * 64}
        after_b = {"auth-service": "sha256:" + "c" * 64, "api-gateway": "sha256:" + "e" * 64}
        self.assertEqual(["api-gateway", "auth-service"], mod.changed_services(after_b, last_pass, False))

    def test_no_evidence_or_contract_change_means_every_service(self):
        current = {"auth-service": "sha256:" + "a" * 64}
        self.assertEqual([], mod.changed_services(current, None, False))
        self.assertEqual([], mod.changed_services(current, current, True))

    def test_nothing_moved_means_no_windows(self):
        current = {"auth-service": "sha256:" + "a" * 64}
        self.assertEqual([], mod.changed_services(current, dict(current), False))
        # the verifier treats empty as "all"; the CLI caller distinguishes via the
        # evidence path, see workflow: unchanged map ⇒ should_verify=false upstream


class VerifiedMapFromReportTests(unittest.TestCase):
    def test_only_pass_reports_with_a_digest_map_count(self):
        self.assertIsNone(mod.verified_map_from_report(report("SUPERSEDED", D)))
        self.assertIsNone(mod.verified_map_from_report(report("FAIL", D)))
        self.assertIsNone(mod.verified_map_from_report(report("PASS", {})))
        self.assertIsNone(mod.verified_map_from_report(report("PASS", D, schema="other")))
        self.assertIsNone(mod.verified_map_from_report(report("PASS", {"x": "not-a-digest"})))
        self.assertEqual(D, mod.verified_map_from_report(report("PASS", D)))


class LatestVerifiedMapTests(unittest.TestCase):
    def _fetchers(self, runs):
        """runs: list of (run_id, [(artifact_name, expired, zip_bytes|None)])"""
        json_by_url = {
            "https://api.github.com/repos/o/r/actions/workflows/wf.yml/runs?status=success&branch=main&per_page=30": {
                "workflow_runs": [{"id": rid, "artifacts_url": f"https://api/runs/{rid}/artifacts"} for rid, _ in runs]
            }
        }
        bytes_by_url = {}
        for rid, artifacts in runs:
            json_by_url[f"https://api/runs/{rid}/artifacts?per_page=20"] = {
                "artifacts": [
                    {"name": name, "expired": expired, "archive_download_url": f"https://api/art/{rid}/{name}"}
                    for name, expired, _ in artifacts
                ]
            }
            for name, _, payload in artifacts:
                if payload is not None:
                    bytes_by_url[f"https://api/art/{rid}/{name}"] = payload
        return (lambda url: json_by_url[url]), (lambda url: bytes_by_url[url])

    def test_newest_pass_diagnostic_artifact_wins(self):
        older = {"auth-service": "sha256:" + "1" * 64}
        newer = {"auth-service": "sha256:" + "2" * 64}
        fj, fb = self._fetchers([
            (30, [("testai-backend-diagnostic-abc-30-1", False, zipped(mod.RUNTIME_REPORT, report("PASS", newer)))]),
            (20, [("testai-backend-diagnostic-abc-20-1", False, zipped(mod.RUNTIME_REPORT, report("PASS", older)))]),
        ])
        self.assertEqual(newer, mod.latest_verified_map(fj, fb, "o/r", "wf.yml"))

    def test_superseded_expired_and_broken_artifacts_are_skipped(self):
        good = {"auth-service": "sha256:" + "1" * 64}
        fj, fb = self._fetchers([
            (40, [("testai-backend-superseded-x-40-1", False, zipped(mod.RUNTIME_REPORT, report("SUPERSEDED", good)))]),
            (39, [("testai-backend-diagnostic-x-39-1", True, None)]),
            (38, [("testai-backend-diagnostic-x-38-1", False, b"not a zip")]),
            (37, [("testai-backend-diagnostic-x-37-1", False, zipped("other.json", report("PASS", good)))]),
            (36, [("testai-backend-diagnostic-x-36-1", False, zipped(mod.RUNTIME_REPORT, report("PASS", good)))]),
        ])
        self.assertEqual(good, mod.latest_verified_map(fj, fb, "o/r", "wf.yml"))

    def test_no_usable_evidence_is_none(self):
        fj, fb = self._fetchers([(1, [("testai-backend-diagnostic-x-1-1", False, zipped(mod.RUNTIME_REPORT, report("FAIL", D)))])])
        self.assertIsNone(mod.latest_verified_map(fj, fb, "o/r", "wf.yml"))
        fj, fb = self._fetchers([])
        self.assertIsNone(mod.latest_verified_map(fj, fb, "o/r", "wf.yml"))


class CliTests(unittest.TestCase):
    def test_contract_change_short_circuits_to_all_without_network(self):
        import contextlib, io as _io
        out = _io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = mod.main(["--current-map", json.dumps(D), "--repo", "o/r", "--contract-changed", "true"])
        self.assertEqual(0, rc)
        self.assertEqual("", out.getvalue().strip())

    def test_missing_token_is_fail_closed(self):
        import contextlib, io as _io, os
        os.environ.pop("X_NO_TOKEN", None)
        out = _io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(_io.StringIO()):
            rc = mod.main(["--current-map", json.dumps(D), "--repo", "o/r", "--token-env", "X_NO_TOKEN"])
        self.assertEqual(0, rc)
        self.assertEqual("", out.getvalue().strip())


if __name__ == "__main__":
    unittest.main()
