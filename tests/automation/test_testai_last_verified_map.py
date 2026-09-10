"""gitops#3618 — stability-window scope comes from the last PASS evidence, not
from the push's before/after diff, so a superseded or failed run's services are
never skipped; the evidence names the revision it verified so the workflow can
check the verifier contract did not change since."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "automation" / "testai-last-verified-map.py"
spec = importlib.util.spec_from_file_location("last_verified_map", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

D = {f"svc{i}": f"sha256:{i:064x}" for i in range(5)}
REV = "6b14d7592dfc96ffaf86e6c2eae370d298bf4a3e"


def runtime(verdict="PASS", digests=None, schema="testai-backend-runtime-verification-v1"):
    return {"schemaVersion": schema, "verdict": verdict, "expectedDigests": digests}


def reconcile(verdict="PASS", revision=REV):
    return {"schemaVersion": "testai-backend-argocd-auto-sync-v4", "verdict": verdict, "effectiveRevision": revision}


def evidence(runtime_report, reconcile_report=None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(mod.RUNTIME_REPORT, json.dumps(runtime_report))
        if reconcile_report is not None:
            z.writestr(mod.RECONCILE_REPORT, json.dumps(reconcile_report))
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


class ReportTests(unittest.TestCase):
    def test_only_pass_runtime_reports_with_a_digest_map_count(self):
        self.assertIsNone(mod.verified_map_from_report(runtime("SUPERSEDED", D)))
        self.assertIsNone(mod.verified_map_from_report(runtime("FAIL", D)))
        self.assertIsNone(mod.verified_map_from_report(runtime("PASS", {})))
        self.assertIsNone(mod.verified_map_from_report(runtime("PASS", D, schema="other")))
        self.assertIsNone(mod.verified_map_from_report(runtime("PASS", {"x": "not-a-digest"})))
        self.assertEqual(D, mod.verified_map_from_report(runtime("PASS", D)))

    def test_verified_revision_needs_a_pass_and_a_full_sha(self):
        self.assertEqual(REV, mod.verified_revision_from_report(reconcile()))
        self.assertIsNone(mod.verified_revision_from_report(reconcile("FAIL")))
        self.assertIsNone(mod.verified_revision_from_report(reconcile(revision="abc123")))
        self.assertIsNone(mod.verified_revision_from_report({"verdict": "PASS"}))


class LatestVerifiedTests(unittest.TestCase):
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

    def test_newest_pass_acceptance_artifact_wins_with_its_revision(self):
        older = {"auth-service": "sha256:" + "1" * 64}
        newer = {"auth-service": "sha256:" + "2" * 64}
        fj, fb = self._fetchers([
            (30, [("testai-backend-acceptance-abc-30-1", False, evidence(runtime("PASS", newer), reconcile(revision="f" * 40)))]),
            (20, [("testai-backend-acceptance-abc-20-1", False, evidence(runtime("PASS", older), reconcile()))]),
        ])
        self.assertEqual((newer, "f" * 40), mod.latest_verified(fj, fb, "o/r", "wf.yml"))

    def test_superseded_expired_broken_and_revisionless_artifacts_are_skipped(self):
        good = {"auth-service": "sha256:" + "1" * 64}
        fj, fb = self._fetchers([
            (40, [("testai-backend-superseded-x-40-1", False, evidence(runtime("SUPERSEDED", good), reconcile()))]),
            (39, [("testai-backend-acceptance-x-39-1", True, None)]),
            (38, [("testai-backend-acceptance-x-38-1", False, b"not a zip")]),
            (37, [("testai-backend-acceptance-x-37-1", False, evidence(runtime("PASS", good)))]),           # no reconcile report
            (36, [("testai-backend-acceptance-x-36-1", False, evidence(runtime("PASS", good), reconcile("FAIL")))]),
            (35, [("testai-backend-acceptance-x-35-1", False, evidence(runtime("PASS", good), reconcile()))]),
        ])
        self.assertEqual((good, REV), mod.latest_verified(fj, fb, "o/r", "wf.yml"))

    def test_prefix_matches_the_workflows_successful_artifact_name(self):
        # Real name observed 2026-09-10: testai-backend-acceptance-<40-hex>-<run>-<attempt>
        workflow = (ROOT / ".github" / "workflows" / "verify-testai-backend-rollout.yml").read_text()
        self.assertIn('echo "artifact_kind=acceptance" >> "$GITHUB_OUTPUT"', workflow)
        self.assertIn("name: testai-backend-${{ steps.artifact.outputs.kind }}-", workflow)
        self.assertEqual("testai-backend-acceptance-", mod.ARTIFACT_PREFIX)
        real = "testai-backend-acceptance-6b14d7592dfc96ffaf86e6c2eae370d298bf4a3e-34416723135-1"
        self.assertTrue(real.startswith(mod.ARTIFACT_PREFIX))
        # a diagnostic artifact (failed evidence contract) is never a verified map
        good = {"auth-service": "sha256:" + "1" * 64}
        fj, fb = self._fetchers([(2, [("testai-backend-diagnostic-x-2-1", False, evidence(runtime("PASS", good), reconcile()))])])
        self.assertIsNone(mod.latest_verified(fj, fb, "o/r", "wf.yml"))

    def test_no_usable_evidence_is_none(self):
        fj, fb = self._fetchers([(1, [("testai-backend-acceptance-x-1-1", False, evidence(runtime("FAIL", D), reconcile()))])])
        self.assertIsNone(mod.latest_verified(fj, fb, "o/r", "wf.yml"))
        fj, fb = self._fetchers([])
        self.assertIsNone(mod.latest_verified(fj, fb, "o/r", "wf.yml"))


class RequestTests(unittest.TestCase):
    def test_authorization_does_not_follow_redirects_to_another_origin(self):
        # GitHub answers the artifact download with a redirect to a signed storage
        # URL; urllib copies ordinary headers onto the redirected request but not
        # unredirected ones (Codex 01a08891).
        req = mod.build_request("https://api.github.com/repos/o/r/actions/artifacts/1/zip", "tok")
        self.assertEqual("Bearer tok", req.get_header("Authorization"))
        self.assertIn("Authorization", req.unredirected_hdrs)
        self.assertNotIn("Authorization", {k.title() for k in req.headers})
        self.assertEqual("application/vnd.github+json", req.get_header("Accept"))


class CliTests(unittest.TestCase):
    def test_contract_change_short_circuits_to_all_without_network(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = mod.main(["--current-map", json.dumps(D), "--repo", "o/r", "--contract-changed", "true"])
        self.assertEqual(0, rc)
        self.assertEqual("", out.getvalue().strip())

    def test_missing_token_is_fail_closed_and_out_json_says_so(self):
        os.environ.pop("X_NO_TOKEN", None)
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "scope.json")
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                rc = mod.main(["--current-map", json.dumps(D), "--repo", "o/r", "--token-env", "X_NO_TOKEN", "--out-json", path])
            self.assertEqual(0, rc)
            self.assertEqual("", out.getvalue().strip())
            with open(path, encoding="utf-8") as fh:
                summary = json.load(fh)
        self.assertEqual({"changed_services": [], "verified_revision": None, "verified_map": None}, summary)


if __name__ == "__main__":
    unittest.main()
