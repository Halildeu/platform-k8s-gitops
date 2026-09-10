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

    def test_unchanged_backend_map_skip_semantics_are_preserved(self):
        # A frontend-only overlay change with an unchanged backend map and an
        # unchanged verifier contract keeps skipping, exactly as before
        # (Codex 01a08891 round 2): the overlay file is not part of the
        # contract diff and no extra overlay condition is added.
        self.assertIn('if [[ "$contract_changed" == "false" ]]; then', self.workflow)
        self.assertNotIn("overlay_changed", self.workflow)
        self.assertIn('contract_changed_since "$BEFORE_SHA" || contract_changed=true', self.workflow)
        fn = re.search(r"contract_changed_since\(\) \{\n(?P<body>.*?)\n          \}", self.workflow, re.DOTALL)
        self.assertIsNotNone(fn)
        self.assertNotIn("kustomize/overlays/test/kustomization.yaml", fn.group("body"))
        self.assertIn("scripts/automation/testai-last-verified-map.py", fn.group("body"))

    def test_window_inheritance_requires_an_unchanged_contract_since_the_verified_revision(self):
        # Codex 01a08891 round 3: a PASS map from before a contract change must
        # not be inherited — the evidence names its revision and the contract is
        # diffed between that revision and the current one.
        self.assertIn("verified_revision=$(jq -r '.verified_revision // empty'", self.workflow)
        self.assertIn('&& contract_changed_since "$verified_revision"; then', self.workflow)
        self.assertIn('[[ -n "$changed_services" ]] || changed_services="none"', self.workflow)
        self.assertIn('[[ "$CHANGED_SERVICES" != "none" ]] || return 1', self.runtime)
        # the helper is part of the verifier contract everywhere the contract is compared
        for source in (self.workflow, self.runtime, self.reconcile):
            self.assertIn("scripts/automation/testai-last-verified-map.py", source)
        # trigger path, contract_changed_since list, latest-main list, invocation
        self.assertEqual(4, self.workflow.count("scripts/automation/testai-last-verified-map.py"))

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
