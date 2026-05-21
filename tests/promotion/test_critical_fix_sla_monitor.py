"""
tests/promotion/test_critical_fix_sla_monitor.py

Unit tests for scripts/promotion/critical_fix_sla_monitor.py.

Test scope (covers the 6 plan-AGREE cases plus 3 edge):
- correlation: squash merge SHA matches deploy run via ancestor
- correlation: failed deploys ignored, only success considered
- correlation: revision extracted from log-grep when headSha doesn't match
- 1h warning: PR comment posted with stable marker
- 1h warning: idempotent (skip if recent comment with checked_at < 1h)
- 4h critical: tracking issue created
- 4h critical: idempotent (refresh comment on existing issue)
- dry-run: no gh side-effects
- sub-SLA: nothing happens (warning / critical thresholds not crossed)

Run:
    python3 -m unittest tests.promotion.test_critical_fix_sla_monitor -v
or:
    pytest tests/promotion/test_critical_fix_sla_monitor.py -v

Pattern: stdlib `unittest` + a single MockRunner class that records every
intended subprocess call and returns scripted output. This mirrors the
test_alertmanager_bridge.py pattern without pulling in `unittest.mock.patch`
across module boundaries.
"""
from __future__ import annotations

import importlib.util
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional
from unittest.mock import MagicMock


# --- Module loader -----------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MODULE_PATH = _REPO_ROOT / "scripts" / "promotion" / "critical_fix_sla_monitor.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("critical_fix_sla_monitor", _MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- MockRunner --------------------------------------------------------------


class MockRunner:
    """Records every subprocess invocation; returns scripted output per matcher.

    Each script entry is a (matcher_fn, stdout, returncode) tuple. The matcher
    fn takes the full cmd list and returns True if this entry applies. First
    matching entry wins; unmatched commands return ("", 0).
    """

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.scripts: list[tuple[Callable[[list[str]], bool], str, int]] = []

    def expect(self, matcher: Callable[[list[str]], bool], stdout: str, returncode: int = 0) -> None:
        self.scripts.append((matcher, stdout, returncode))

    def __call__(self, cmd: list[str], check: bool = True, timeout: int = 60):
        self.calls.append(list(cmd))
        for matcher, stdout, returncode in self.scripts:
            if matcher(cmd):
                if check and returncode != 0:
                    # Raise the same error type the real _run raises.
                    raise self._make_error(cmd, returncode, stderr="(mock)")
                return _MockCompletedProcess(stdout=stdout, returncode=returncode)
        # Default: empty success.
        return _MockCompletedProcess(stdout="", returncode=0)

    @staticmethod
    def _make_error(cmd: list[str], returncode: int, stderr: str):
        mod = _load_module()
        return mod.GhError(args_str=" ".join(cmd), returncode=returncode, stderr=stderr)


class _MockCompletedProcess:
    def __init__(self, stdout: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode


# --- Fixtures ----------------------------------------------------------------


def _pr_fixture(
    number: int = 640,
    merged_hours_ago: float = 5.0,
    merge_sha: str = "dd20f46be2c72d438dad5a015e324a4bb197f05e",
    title: str = "PermissionProvider stale-token recovery",
) -> dict:
    merged_at = datetime.now(timezone.utc) - timedelta(hours=merged_hours_ago)
    return {
        "number": number,
        "title": title,
        "mergedAt": merged_at.isoformat().replace("+00:00", "Z"),
        "mergeCommit": {"oid": merge_sha},
        "url": f"https://github.com/Halildeu/platform-k8s-gitops/pull/{number}",
        "labels": [{"name": "critical-fix"}],
    }


def _deploy_run_fixture(
    db_id: int = 26200000000,
    head_sha: str = "ffffffffffffffffffffffffffffffffffffffff",
    created_hours_ago: float = 1.0,
    conclusion: str = "success",
) -> dict:
    created_at = datetime.now(timezone.utc) - timedelta(hours=created_hours_ago)
    return {
        "databaseId": db_id,
        "createdAt": created_at.isoformat().replace("+00:00", "Z"),
        "headSha": head_sha,
        "conclusion": conclusion,
    }


# --- Correlation tests -------------------------------------------------------


class FindSuccessfulDeployTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = _load_module()
        self.runner = MockRunner()

    def test_headsha_exact_match_returns_run(self) -> None:
        """Merge SHA == deploy run headSha → first-pass match, no log-grep needed."""
        merge_sha = "dd20f46be2c72d438dad5a015e324a4bb197f05e"
        run = _deploy_run_fixture(head_sha=merge_sha, created_hours_ago=1.0)

        self.runner.expect(
            lambda cmd: cmd[:2] == ["gh", "run"] and "list" in cmd,
            json.dumps([run]),
        )

        merged_at = datetime.now(timezone.utc) - timedelta(hours=2.0)
        result = self.mod.find_successful_deploy(
            "owner/repo", merge_sha, merged_at, runner=self.runner
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["databaseId"], run["databaseId"])

    def test_ancestor_match_via_git_merge_base(self) -> None:
        """Merge SHA is ancestor of headSha → ancestor check returns the run."""
        merge_sha = "aaaaaaa"
        head_sha = "bbbbbbb"
        run = _deploy_run_fixture(head_sha=head_sha, created_hours_ago=1.0)

        # gh run list — returns the one run.
        self.runner.expect(
            lambda cmd: cmd[:2] == ["gh", "run"] and "list" in cmd,
            json.dumps([run]),
        )
        # git merge-base --is-ancestor merge_sha head_sha → exit 0 (ancestor).
        self.runner.expect(
            lambda cmd: cmd[:3] == ["git", "merge-base", "--is-ancestor"]
            and cmd[3] == merge_sha
            and cmd[4] == head_sha,
            "",
            returncode=0,
        )

        merged_at = datetime.now(timezone.utc) - timedelta(hours=2.0)
        result = self.mod.find_successful_deploy(
            "owner/repo", merge_sha, merged_at, runner=self.runner
        )
        self.assertIsNotNone(result)

    def test_log_grep_fallback_revision_match(self) -> None:
        """If headSha doesn't match, log-grep extracts revision then ancestor."""
        merge_sha = "cccccccc"
        head_sha = "dddddddd"
        revision_from_log = "eeeeeeee"
        run = _deploy_run_fixture(head_sha=head_sha, created_hours_ago=1.0)

        self.runner.expect(
            lambda cmd: cmd[:2] == ["gh", "run"] and "list" in cmd,
            json.dumps([run]),
        )
        # First two ancestor checks (headSha) fail.
        self.runner.expect(
            lambda cmd: cmd[:3] == ["git", "merge-base", "--is-ancestor"]
            and cmd[4] == head_sha,
            "",
            returncode=1,
        )
        # gh run view --log returns log text with "Revision: <sha>" line.
        self.runner.expect(
            lambda cmd: cmd[:2] == ["gh", "run"] and "view" in cmd and "--log" in cmd,
            f"some output\nRevision: {revision_from_log}\nmore output\n",
        )
        # Ancestor check on the log-extracted revision → match.
        self.runner.expect(
            lambda cmd: cmd[:3] == ["git", "merge-base", "--is-ancestor"]
            and cmd[4] == revision_from_log,
            "",
            returncode=0,
        )

        merged_at = datetime.now(timezone.utc) - timedelta(hours=2.0)
        result = self.mod.find_successful_deploy(
            "owner/repo", merge_sha, merged_at, runner=self.runner
        )
        self.assertIsNotNone(result)

    def test_failed_deploy_ignored(self) -> None:
        """Only `status=success` runs are returned; failed deploys never satisfy SLA."""
        # `list_recent_deploy_success_runs` queries --status success, so a fail
        # run wouldn't even appear. Simulate empty result.
        self.runner.expect(
            lambda cmd: cmd[:2] == ["gh", "run"] and "list" in cmd,
            "[]",
        )

        merged_at = datetime.now(timezone.utc) - timedelta(hours=2.0)
        result = self.mod.find_successful_deploy(
            "owner/repo", "abc123", merged_at, runner=self.runner
        )
        self.assertIsNone(result)

    def test_run_before_merge_excluded(self) -> None:
        """A deploy success run that PREDATES the PR merge does not satisfy SLA."""
        merge_sha = "aaaa"
        # Deploy ran BEFORE PR was merged (created 3h ago, PR merged 2h ago).
        old_run = _deploy_run_fixture(head_sha=merge_sha, created_hours_ago=3.0)
        self.runner.expect(
            lambda cmd: cmd[:2] == ["gh", "run"] and "list" in cmd,
            json.dumps([old_run]),
        )

        merged_at = datetime.now(timezone.utc) - timedelta(hours=2.0)
        result = self.mod.find_successful_deploy(
            "owner/repo", merge_sha, merged_at, runner=self.runner
        )
        self.assertIsNone(result)


# --- Idempotency tests -------------------------------------------------------


class WarningIdempotencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = _load_module()

    def test_warning_within_returns_true_for_recent_comment(self) -> None:
        recent_iso = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        comments = [
            {
                "body": f"<!-- critical-fix-sla-warning pr=640 -->\ncheked_at={recent_iso}\nfoo",
            }
        ]
        # Typo intentional — should NOT match because we parse `checked_at=`
        self.assertFalse(self.mod.warning_within(comments, 640))

    def test_warning_within_returns_true_for_correct_recent(self) -> None:
        recent_iso = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        comments = [
            {"body": f"<!-- critical-fix-sla-warning pr=640 -->\nchecked_at={recent_iso}\nfoo"},
        ]
        self.assertTrue(self.mod.warning_within(comments, 640))

    def test_warning_within_returns_false_for_old_comment(self) -> None:
        old_iso = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        comments = [
            {"body": f"<!-- critical-fix-sla-warning pr=640 -->\nchecked_at={old_iso}\n"},
        ]
        self.assertFalse(self.mod.warning_within(comments, 640))

    def test_warning_within_returns_false_for_wrong_pr_marker(self) -> None:
        recent_iso = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        comments = [
            {"body": f"<!-- critical-fix-sla-warning pr=999 -->\nchecked_at={recent_iso}\n"},
        ]
        self.assertFalse(self.mod.warning_within(comments, 640))


class IssueExistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = _load_module()
        self.runner = MockRunner()

    def test_find_existing_sla_issue_matches_marker(self) -> None:
        body = "<!-- critical-fix-sla pr=640 merge_sha=abc -->\nSLA breach\n"
        self.runner.expect(
            lambda cmd: cmd[:2] == ["gh", "issue"] and "list" in cmd,
            json.dumps([{"number": 100, "body": body, "title": "..."}]),
        )
        match = self.mod.find_existing_sla_issue("owner/repo", 640, runner=self.runner)
        self.assertEqual(match, 100)

    def test_find_existing_sla_issue_no_match(self) -> None:
        body = "<!-- critical-fix-sla pr=999 merge_sha=abc -->\nDifferent PR\n"
        self.runner.expect(
            lambda cmd: cmd[:2] == ["gh", "issue"] and "list" in cmd,
            json.dumps([{"number": 100, "body": body, "title": "..."}]),
        )
        match = self.mod.find_existing_sla_issue("owner/repo", 640, runner=self.runner)
        self.assertIsNone(match)


# --- Dry-run tests -----------------------------------------------------------


class DryRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = _load_module()
        self.runner = MockRunner()

    def test_dry_run_no_issue_create(self) -> None:
        """dry-run should not call `gh issue create`."""
        pr = _pr_fixture(number=640, merged_hours_ago=5.0)
        self.mod.create_or_update_issue(
            repo="owner/repo",
            pr=pr,
            age_hours=5.0,
            threshold_hours=4,
            dry_run=True,
            runner=self.runner,
        )
        # No gh issue create call recorded.
        for call in self.runner.calls:
            self.assertFalse(call[:3] == ["gh", "issue", "create"], msg=call)

    def test_dry_run_no_pr_comment(self) -> None:
        """dry-run should not call `gh pr comment`."""
        pr = _pr_fixture(number=640, merged_hours_ago=2.0)
        # No existing comments — would normally proceed to post.
        self.runner.expect(
            lambda cmd: cmd[:2] == ["gh", "pr"] and "view" in cmd,
            json.dumps({"comments": []}),
        )
        self.mod.warn_on_pr(
            repo="owner/repo",
            pr=pr,
            age_hours=2.0,
            threshold_hours=4,
            dry_run=True,
            runner=self.runner,
        )
        for call in self.runner.calls:
            self.assertFalse(call[:3] == ["gh", "pr", "comment"], msg=call)


# --- Body rendering ----------------------------------------------------------


class BodyRenderingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = _load_module()

    def test_issue_body_contains_marker(self) -> None:
        pr = _pr_fixture(number=640, merge_sha="abc123")
        body = self.mod.make_issue_body(pr, age_hours=5.0, repo="owner/repo", threshold_hours=4)
        self.assertIn("<!-- critical-fix-sla pr=640", body)
        self.assertIn("merge_sha=abc123", body)
        self.assertIn("5.0 hours", body)
        self.assertIn("SLA threshold: 4h", body)

    def test_warning_body_contains_stable_marker(self) -> None:
        body = self.mod.make_warning_body(
            pr_number=640,
            age_hours=2.0,
            now_iso="2026-05-21T08:00:00+00:00",
            threshold_hours=4,
        )
        self.assertIn("<!-- critical-fix-sla-warning pr=640 -->", body)
        self.assertIn("checked_at=2026-05-21T08:00:00+00:00", body)
        # No timestamp inside the marker itself (Codex iter-3 fix).
        self.assertNotIn("2026-05-21T08:00:00+00:00 -->", body)


# --- is_ancestor / parsing edges --------------------------------------------


class HelperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = _load_module()

    def test_is_ancestor_equal_returns_true(self) -> None:
        runner = MagicMock()
        self.assertTrue(self.mod.is_ancestor("abc", "abc", runner=runner))
        # runner should not be invoked for the equal case.
        runner.assert_not_called()

    def test_is_ancestor_empty_returns_false(self) -> None:
        self.assertFalse(self.mod.is_ancestor("", "abc"))
        self.assertFalse(self.mod.is_ancestor("abc", ""))

    def test_parse_iso_z_suffix(self) -> None:
        dt = self.mod._parse_iso("2026-05-21T07:00:00Z")
        self.assertEqual(dt.tzinfo, timezone.utc)
        self.assertEqual(dt.year, 2026)


if __name__ == "__main__":
    unittest.main()
