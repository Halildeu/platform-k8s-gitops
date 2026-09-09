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

    # --- stability windows scoped to the services still owing one -----------
    def test_pin_step_scopes_windows_from_the_last_pass_evidence(self):
        # Not the push's before/after diff: a service moved by a superseded or
        # failed earlier push must still get its window (Codex 01a08891 P1).
        self.assertIn('echo "changed_services=$changed_services"', self.workflow)
        self.assertIn("scripts/automation/testai-last-verified-map.py", self.workflow)
        self.assertIn('--contract-changed "$contract_changed"', self.workflow)
        self.assertIn("actions: read", self.workflow)
        self.assertNotIn("before.get(k) != v", self.workflow)

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
        self.assertIn('VERDICT="SUPERSEDED"', self.reconcile)
        self.assertNotIn("FAIL: runtime backend map was superseded on main", self.runtime)
        # the convergence loop calls the fence as a plain statement so `set -e`
        # exits with the fence's own status; `if ! fn` would read $? as 0
        self.assertNotIn("if ! refresh_semantic_main_fence", self.reconcile)
        self.assertEqual(2, len(re.findall(r"^\s*refresh_semantic_main_fence\s*$", self.reconcile, re.M)))

    def test_git_diff_status_distinguishes_supersession_from_git_errors(self):
        # `git diff --quiet`: 1 = differs, >1 = git error (128); only 1 is a supersession
        for source in (self.runtime, self.reconcile):
            self.assertIn('if git diff --quiet "$REVISION" "$latest_main" --', source)
            self.assertIn('diff_status=$?', source)
            self.assertIn('case "$diff_status" in', source)
            self.assertIn("unable to compare the verifier contract with main", source)

    def test_missing_evidence_report_fails_even_when_superseded(self):
        for source in (self.runtime, self.reconcile):
            block = re.search(r"if ! write_report; then\n(?P<body>.*?)\n  fi", source, re.DOTALL)
            self.assertIsNotNone(block)
            self.assertIn("original_status=1", block.group("body"))
            self.assertNotIn("original_status == 0", block.group("body"))

    def test_set_e_propagates_a_function_status_through_the_exit_trap(self):
        # the mechanism the plain fence call relies on
        import subprocess
        proc = subprocess.run(
            ["bash", "-c", 'set -euo pipefail; trap \'exit $?\' EXIT; f() { return 75; }; f; echo unreachable'],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(75, proc.returncode)
        self.assertNotIn("unreachable", proc.stdout)

    def test_workflow_records_superseded_instead_of_failing(self):
        self.assertEqual(2, self.workflow.count('if [[ "$rc" -eq 75 ]]; then'))
        self.assertEqual(2, self.workflow.count('echo "superseded=true" >> "$GITHUB_OUTPUT"'))
        self.assertIn("steps.reconcile.outputs.superseded != 'true'", self.workflow)
        self.assertIn("steps.verify.outputs.superseded != 'true'", self.workflow)
        self.assertIn('echo "kind=superseded" >> "$GITHUB_OUTPUT"', self.workflow)
        # superseded is only accepted with its own evidence report on disk
        self.assertEqual(2, self.workflow.count("jq -e '.verdict == \"SUPERSEDED\"' \"$REPORT_PATH\""))
        self.assertIn("if-no-files-found: error", self.workflow)
        # a real failure still propagates
        self.assertEqual(2, self.workflow.count('exit "$rc"'))


if __name__ == "__main__":
    unittest.main()
