"""gitops#3618 — the post-merge backend verifier must not hold the single
self-hosted runner for 13 sequential stability windows nor keep waiting on a
backend map a newer main already replaced.

Observed 2026-09-10 (twice): a run whose expectation was superseded mid-run,
or whose step simply walked all 13 windows, stayed 24-42 min in "Verify exact
pod digests, public edge, readiness and stability" while the Explorer browser
acceptance lane sat queued behind it.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "verify-testai-backend-rollout.yml"
RUNTIME = REPO_ROOT / "scripts" / "deploy" / "verify-testai-backend-runtime.sh"
RECONCILE = REPO_ROOT / "scripts" / "deploy" / "reconcile-testai-backend-sequential.sh"


class RolloutVerifySupersededTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.runtime = RUNTIME.read_text(encoding="utf-8")
        cls.reconcile = RECONCILE.read_text(encoding="utf-8")

    # --- stability windows scoped to the services this push moved ---------
    def test_pin_step_exports_changed_services(self):
        self.assertIn('echo "changed_services=$changed_services"', self.workflow)
        self.assertIn("before.get(k) != v", self.workflow)

    def test_runtime_verifier_scopes_stability_windows_to_changed_services(self):
        self.assertIn('CHANGED_SERVICES="${CHANGED_SERVICES:-}"', self.runtime)
        self.assertIn("is_changed_service()", self.runtime)
        window = re.search(
            r'CURRENT_GATE="stability-window"\n(?P<body>.*?)\ndone', self.runtime, re.DOTALL
        )
        self.assertIsNotNone(window, "stability-window loop not found")
        body = window.group("body")
        self.assertIn('if ! is_changed_service "$service"; then', body)
        self.assertIn("assert_current_backend_map", body)
        self.assertIn("gate-stability-window.sh", body)

    def test_workflow_passes_changed_services_to_the_verifier(self):
        self.assertIn("CHANGED_SERVICES: ${{ steps.pin.outputs.changed_services }}", self.workflow)

    def test_exact_imageid_and_readiness_still_cover_every_service(self):
        # Scoping applies to the stability windows only.
        imageid = re.search(r'CURRENT_GATE="exact-pod-imageid"\n(?P<body>.*?)\ndone', self.runtime, re.DOTALL)
        readiness = re.search(r'CURRENT_GATE="in-cluster-readiness"\n(?P<body>.*?)\ndone', self.runtime, re.DOTALL)
        self.assertIsNotNone(imageid)
        self.assertIsNotNone(readiness)
        self.assertNotIn("is_changed_service", imageid.group("body"))
        self.assertNotIn("is_changed_service", readiness.group("body"))

    # --- supersession is a distinct, non-red outcome ------------------------
    def test_scripts_exit_75_when_superseded(self):
        for source in (self.runtime, self.reconcile):
            self.assertIn("SUPERSEDED_EXIT=75", source)
        self.assertEqual(2, self.runtime.count('return "$SUPERSEDED_EXIT"'), "runtime map + contract fences")
        self.assertEqual(2, self.reconcile.count('return "$SUPERSEDED_EXIT"'), "reconcile map + contract fences")
        self.assertIn('VERDICT="SUPERSEDED"', self.runtime)
        self.assertNotIn("FAIL: runtime backend map was superseded on main", self.runtime)
        # the convergence loop propagates the fence status instead of flattening it to 1
        self.assertIn('fence_status=$?\n      exit "$fence_status"', self.reconcile)

    def test_workflow_records_superseded_instead_of_failing(self):
        self.assertEqual(2, self.workflow.count('if [[ "$rc" -eq 75 ]]; then'))
        self.assertEqual(2, self.workflow.count('echo "superseded=true" >> "$GITHUB_OUTPUT"'))
        self.assertIn("steps.reconcile.outputs.superseded != 'true'", self.workflow)
        self.assertIn("steps.verify.outputs.superseded != 'true'", self.workflow)
        self.assertIn('echo "kind=superseded" >> "$GITHUB_OUTPUT"', self.workflow)
        # a real failure still propagates
        self.assertEqual(2, self.workflow.count('exit "$rc"'))


if __name__ == "__main__":
    unittest.main()
