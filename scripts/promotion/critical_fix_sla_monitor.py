#!/usr/bin/env python3
"""
scripts/promotion/critical_fix_sla_monitor.py

DiD-1 (defense-in-depth, 2026-05-21): track merged PRs labeled
`critical-fix` in this gitops repo and alert when their prod-deploy
lag exceeds the SLA.

PROBLEM (live incident, 2026-05-21):
  PR #640 (platform-web AuthBootstrapper stale-token fix) merged at
  2026-05-20T07:50Z, but the prod gitops digest-bump PR (#917) and
  the subsequent successful deploy-prod-gitops run did not land until
  ~22 hours later. Pre-prod tolerated the lag, but the incident was
  user-found rather than monitor-found — no automated signal fired
  when a critical-fix lingered without reaching prod.

DESIGN:
  - Scan merged PRs in this gitops repo with label `critical-fix`
    in the last `--window-hours` (default 48h).
  - For each, find a successful `deploy-prod-gitops.yml` run AFTER
    the merge timestamp where the merge commit SHA is an ancestor of
    the deployed revision (workflow_dispatch input or run headSha).
  - If no successful deploy AND merge age > critical-hours
    (default 4h) → create/refresh tracking issue.
  - If no successful deploy AND merge age > warning-hours
    (default 1h) → comment on the PR.

DEPLOY-RUN CORRELATION (acceptable temporary):
  `deploy-prod-gitops.yml` runs as `workflow_dispatch` with a
  `revision` input. `gh run view --json` does NOT expose dispatch
  inputs as machine-readable fields. This script applies (Codex
  iter-4 P1 absorb — log-first to guard against `full` rollback
  mode where headSha advances while the deployed revision rolls
  back to an older SHA):
    1. **Primary** — `gh run view <id> --log` text grep for
       `argocd app sync ... --revision <sha>` or `Revision: <sha>`
       lines. If any extracted SHA satisfies `git merge-base
       --is-ancestor <merge_sha> <revision>`, the deploy covers
       the merge.
    2. **Fallback** — only when the log produced no revisions
       (best-effort log fetch failed, or no matching lines), fall
       back to `headSha` exact-match or ancestor check.
  A separate follow-up PR should add a machine-readable
  `prod-sync-result.json` workflow artifact so the log-grep
  primary can be retired in favor of a structured signal.

IDEMPOTENCY:
  - Issue match: open issue with label `critical-fix-sla-active`
    AND body containing `<!-- critical-fix-sla pr=<N> -->` marker.
    Match → append refresh comment. No match → create new.
  - PR warning match: any existing comment with marker
    `<!-- critical-fix-sla-warning pr=<N> -->`. Stable marker (no
    timestamp); `checked_at=<iso>` is a separate line inside the
    body so 1h-skip parse stays decoupled from marker match.
  - Label `critical-fix-sla-active` is created idempotently on
    first run (`gh label create ... || true`).

USAGE:
  python3 scripts/promotion/critical_fix_sla_monitor.py \\
    --repo Halildeu/platform-k8s-gitops [--dry-run]

EXIT CODES:
  0 — scan completed (no SLA action OR action taken successfully)
  1 — at least one gh / git call failed unrecoverably
  2 — argparse / setup error

The workflow `.github/workflows/critical-fix-sla-monitor.yml` runs
this script on a `*/15 * * * *` cron + `workflow_dispatch`.
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional


# --- Configuration -----------------------------------------------------------

CRITICAL_FIX_LABEL = "critical-fix"
SLA_ACTIVE_LABEL = "critical-fix-sla-active"
DEPLOY_WORKFLOW = "deploy-prod-gitops.yml"

DEFAULT_WINDOW_HOURS = 48
DEFAULT_WARNING_HOURS = 1
DEFAULT_CRITICAL_HOURS = 4

# Revision capture patterns inside deploy workflow logs.
# Order matters — first match wins per log scan. Three forms:
#   1. argocd CLI explicit:  argocd app sync ... --revision <sha>
#   2. Workflow summary log: Revision: <sha>
#   3. Output line:          revision=<sha> (script-style)
_REVISION_PATTERNS = [
    re.compile(r"argocd\s+app\s+sync\b[^\n]*--revision\s+([a-f0-9]{7,40})", re.IGNORECASE),
    re.compile(r"^\s*Revision:\s*([a-f0-9]{7,40})\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"\brevision=([a-f0-9]{7,40})\b", re.IGNORECASE),
]


# --- Helpers -----------------------------------------------------------------


class GhError(Exception):
    """Raised when a `gh` invocation fails. Plain Exception (not dataclass-
    backed) to avoid the Python 3.13 dataclasses/importlib edge case where
    a module loaded via spec_from_file_location does not appear in
    `sys.modules` and dataclass decoration fails at class-definition time."""

    def __init__(self, args_str: str, returncode: int, stderr: str) -> None:
        super().__init__(args_str)
        self.args_str = args_str
        self.returncode = returncode
        self.stderr = stderr

    def __str__(self) -> str:
        return f"gh failed (rc={self.returncode}): {self.args_str}\n  stderr: {self.stderr[:500]}"


def _run(cmd: list[str], check: bool = True, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    """Run a subprocess with stdout/stderr captured. Optional `check` raises GhError on nonzero."""
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if check and res.returncode != 0:
        raise GhError(args_str=shlex.join(cmd), returncode=res.returncode, stderr=res.stderr)
    return res


def gh_json(*args: str, runner=_run) -> object:
    """Run `gh <args>` and parse stdout as JSON."""
    res = runner(["gh", *args])
    return json.loads(res.stdout or "[]")


def gh_text(*args: str, runner=_run) -> str:
    """Best-effort `gh <args>` — returns "" on nonzero exit.

    USE WITH CARE: any caller that depends on the result being authoritative
    must use `gh_text_required` instead (Codex iter-4 P1 absorb: silent-empty
    semantics caused false `[OK] no critical-fix PRs` reports when auth or
    network failures occurred during `pr list` / `run list` / `issue list` /
    `pr view`). Acceptable for genuinely best-effort calls where empty ==
    "no data to grep" is semantically equivalent (e.g. `gh run view --log`
    when log-grep is an optional fallback signal).
    """
    res = runner(["gh", *args], check=False)
    if res.returncode != 0:
        return ""
    return res.stdout


def gh_text_required(*args: str, runner=_run) -> str:
    """Strict `gh <args>` — raises GhError on nonzero exit.

    Use for every read whose emptiness must NOT be conflated with "no data":
    `pr list`, `run list`, `issue list`, `pr view`. Caller is expected to
    propagate the exception so the monitor surfaces a real failure rather
    than reporting [OK] on a scan that did not happen.
    """
    res = runner(["gh", *args], check=False)
    if res.returncode != 0:
        raise GhError(
            args_str=shlex.join(["gh", *args]),
            returncode=res.returncode,
            stderr=res.stderr,
        )
    return res.stdout


def _parse_iso(ts: str) -> datetime:
    """Parse ISO-8601 with Z or offset → aware datetime."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def is_ancestor(merge_sha: str, revision: str, runner=_run) -> bool:
    """True if `merge_sha` is an ancestor of (or equal to) `revision`.

    Used to verify a deploy run carried the PR merge commit. Requires the
    git repository to be checked out with sufficient history (the workflow
    uses `fetch-depth: 0`).
    """
    if not merge_sha or not revision:
        return False
    if merge_sha == revision:
        return True
    # Some logs print only the short SHA — git accepts the short form here.
    res = runner(
        ["git", "merge-base", "--is-ancestor", merge_sha, revision],
        check=False,
        timeout=30,
    )
    return res.returncode == 0


# --- gh wrappers -------------------------------------------------------------


def list_critical_fix_prs(repo: str, window_hours: int, runner=_run) -> list[dict]:
    """List merged PRs in `repo` with `critical-fix` label in the last `window_hours`.

    STRICT: raises GhError on `gh pr list` failure (Codex iter-4 P1) so the
    monitor cannot silently report [OK] on an auth/network failure that
    actually skipped the scan.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    search = f"label:{CRITICAL_FIX_LABEL} merged:>{cutoff.strftime('%Y-%m-%d')}"
    out = gh_text_required(
        "pr",
        "list",
        "--repo",
        repo,
        "--state",
        "merged",
        "--search",
        search,
        "--json",
        "number,title,mergedAt,mergeCommit,url,labels",
        "--limit",
        "30",
        runner=runner,
    )
    if not out:
        return []
    return json.loads(out)


def list_recent_deploy_success_runs(repo: str, runner=_run) -> list[dict]:
    """Most recent successful runs of the prod-deploy workflow (newest first).

    STRICT: raises GhError on `gh run list` failure (Codex iter-4 P1).
    """
    out = gh_text_required(
        "run",
        "list",
        "--repo",
        repo,
        "--workflow",
        DEPLOY_WORKFLOW,
        "--status",
        "success",
        "--json",
        "databaseId,createdAt,headSha,conclusion",
        "--limit",
        "50",
        runner=runner,
    )
    if not out:
        return []
    return json.loads(out)


def fetch_run_log(repo: str, run_id: int, runner=_run) -> str:
    """Best-effort `gh run view --log` text. Empty string on failure.

    Intentionally non-strict — log-grep is an OPTIONAL correlation signal
    (Codex iter-4 P1 P2 note). If the log call fails (large logs paginated
    awkwardly, transient API issue, etc.) the correlator falls through to
    headSha-ancestor as a last resort.
    """
    return gh_text("run", "view", str(run_id), "--repo", repo, "--log", runner=runner)


def find_existing_sla_issue(repo: str, pr_number: int, runner=_run) -> Optional[int]:
    """Search for an OPEN issue carrying the SLA-active label + the PR marker.

    STRICT: raises GhError on `gh issue list` failure (Codex iter-4 P1) so
    a read failure cannot cause a duplicate issue to be created.

    Marker match: full prefix with trailing whitespace OR explicit closer
    (Codex iter-4 P2 — substring `pr=640` previously matched bodies with
    `pr=6400`). Acceptable terminators are space, newline, end-of-string,
    or the HTML-comment closer `-->`.
    """
    out = gh_text_required(
        "issue",
        "list",
        "--repo",
        repo,
        "--state",
        "open",
        "--label",
        SLA_ACTIVE_LABEL,
        "--json",
        "number,body,title",
        "--limit",
        "30",
        runner=runner,
    )
    if not out:
        return None
    # Use a boundary regex rather than substring containment. The marker is
    # written by make_issue_body() as `<!-- critical-fix-sla pr=<N>
    # merge_sha=<sha> -->`, so the next char after `<N>` is a space.
    marker_re = re.compile(
        rf"<!--\s*critical-fix-sla\s+pr={pr_number}(?:\s|-->|$)"
    )
    for issue in json.loads(out):
        if marker_re.search(issue.get("body") or ""):
            return issue["number"]
    return None


def pr_comments(repo: str, pr_number: int, runner=_run) -> list[dict]:
    """Return the list of comments on a PR (newest gh API form).

    STRICT: raises GhError on `gh pr view` failure (Codex iter-4 P1).
    """
    out = gh_text_required(
        "pr",
        "view",
        str(pr_number),
        "--repo",
        repo,
        "--json",
        "comments",
        runner=runner,
    )
    if not out:
        return []
    payload = json.loads(out)
    return payload.get("comments", []) or []


# --- Correlation -------------------------------------------------------------


def find_successful_deploy(
    repo: str,
    merge_sha: str,
    merged_at: datetime,
    runner=_run,
) -> Optional[dict]:
    """Return the first deploy-prod-gitops success run whose deployed
    revision contains `merge_sha`, or None if no match within the candidate
    window.

    Match priority for a given run (Codex iter-4 P1 absorb — REVERSED from
    iter-3 design):

      1. **Log-extracted revision** + ancestor check.
         `deploy-prod-gitops.yml` runs as `workflow_dispatch` with an explicit
         `revision` input. In `full` rollback mode the workflow can run
         FROM current `main` (so `headSha` advances) while it SYNCS an OLDER
         revision (so the deployed revision is NOT main HEAD). Trusting
         `headSha` as the deployed-revision proxy would false-positive
         match a rollback run that pushed a pre-fix revision. Always read
         the log first and prefer an explicit `--revision <sha>` or
         `Revision: <sha>` line.

      2. **headSha fallback** (`exact` or `ancestor`).
         Only when the log call returned no text OR no revision could be
         extracted from it. In the normal `resources`-mode flow (no rollback),
         the deployed revision == workflow's `headSha`, so the fallback
         still correlates correctly in the common case.

    The match scope is bounded to runs where `createdAt > merged_at`.
    """
    runs = list_recent_deploy_success_runs(repo, runner=runner)
    for run in runs:
        try:
            created_at = _parse_iso(run["createdAt"])
        except (ValueError, KeyError):
            continue
        if created_at <= merged_at:
            continue

        # Priority 1: explicit revision extracted from workflow log.
        log = fetch_run_log(repo, run["databaseId"], runner=runner)
        revisions_from_log: list[str] = []
        if log:
            for pattern in _REVISION_PATTERNS:
                revisions_from_log.extend(pattern.findall(log))
        if revisions_from_log:
            for match in revisions_from_log:
                if is_ancestor(merge_sha, match, runner=runner):
                    return run
            # Log had explicit revisions but none was an ancestor → this
            # run did NOT deploy our merge_sha. Continue to next run; DO
            # NOT fall through to headSha (rollback false-positive guard).
            continue

        # Priority 2 fallback: headSha (only when log produced no revisions).
        head_sha = run.get("headSha") or ""
        if head_sha and (head_sha == merge_sha or is_ancestor(merge_sha, head_sha, runner=runner)):
            return run

    return None


# --- Issue / PR actions ------------------------------------------------------


def ensure_label(repo: str, name: str, color: str, description: str, runner=_run) -> None:
    """Create label idempotently; ignore failure when label already exists."""
    try:
        runner(
            [
                "gh",
                "label",
                "create",
                name,
                "--repo",
                repo,
                "--color",
                color,
                "--description",
                description,
            ],
            check=False,
        )
    except Exception:
        # gh label create exits nonzero on existing label — that's expected;
        # we intentionally swallow here.
        pass


def make_issue_body(pr: dict, age_hours: float, repo: str, threshold_hours: int) -> str:
    """Render the body of an SLA tracking issue with the stable marker."""
    merge_sha = (pr.get("mergeCommit") or {}).get("oid") or ""
    return f"""<!-- critical-fix-sla pr={pr['number']} merge_sha={merge_sha} -->

PR #{pr['number']} ({pr.get('url', '')}) was labeled `{CRITICAL_FIX_LABEL}`
and merged at **{pr.get('mergedAt')}** but has not produced a successful
`{DEPLOY_WORKFLOW}` workflow run after **{age_hours:.1f} hours**
(SLA threshold: {threshold_hours}h).

## Action

1. Check for an open prod-overlay PR that should carry this fix.
2. Approve the `production` environment gate on a queued deploy run
   (or trigger one manually):
   ```bash
   gh workflow run {DEPLOY_WORKFLOW} --repo {repo} --ref main \\
     --field revision=<gitops main HEAD> \\
     --field sync_mode=resources \\
     --field resources=<scope> \\
     --field confirm=SYNC-PROD
   ```
3. When the merge commit `{merge_sha}` reaches prod, close this issue.
   The monitor will not re-open it unless a NEW critical-fix PR crosses
   the {threshold_hours}h threshold without a deploy.

🤖 Auto-generated by `critical-fix-sla-monitor` workflow.
"""


def make_warning_body(pr_number: int, age_hours: float, now_iso: str, threshold_hours: int) -> str:
    """Render the PR-warning comment body with a stable marker + parseable checked_at."""
    return f"""<!-- critical-fix-sla-warning pr={pr_number} -->
checked_at={now_iso}

⚠️ **Critical-fix SLA warning** — PR labeled `{CRITICAL_FIX_LABEL}`,
merged {age_hours:.1f}h ago, no successful `{DEPLOY_WORKFLOW}` run yet.
SLA escalates to a tracking issue at {threshold_hours}h.

🤖 Auto-generated by `critical-fix-sla-monitor` workflow.
"""


def warning_within(comments: list[dict], pr_number: int, age_hours_cap: float = 1.0) -> bool:
    """Return True if a warning comment with the stable marker exists AND its
    `checked_at` is younger than `age_hours_cap` (default 1h)."""
    marker = f"<!-- critical-fix-sla-warning pr={pr_number} -->"
    cutoff = datetime.now(timezone.utc) - timedelta(hours=age_hours_cap)
    iso_re = re.compile(r"checked_at=(\S+)")
    for c in comments:
        body = c.get("body") or ""
        if marker not in body:
            continue
        match = iso_re.search(body)
        if not match:
            # Stale comment without timestamp — treat as old (allow re-warn).
            continue
        try:
            ts = _parse_iso(match.group(1))
        except ValueError:
            continue
        if ts > cutoff:
            return True
    return False


def warn_on_pr(repo: str, pr: dict, age_hours: float, threshold_hours: int, dry_run: bool, runner=_run) -> None:
    """Post a warning comment on the PR if not already done within the last hour."""
    pr_number = pr["number"]
    comments = pr_comments(repo, pr_number, runner=runner)
    if warning_within(comments, pr_number, age_hours_cap=1.0):
        return
    body = make_warning_body(pr_number, age_hours, datetime.now(timezone.utc).isoformat(), threshold_hours)
    if dry_run:
        print(f"  [DRY-RUN] would post warning comment on PR #{pr_number}")
        return
    runner(["gh", "pr", "comment", str(pr_number), "--repo", repo, "--body", body], check=True)
    print(f"  [WARN] posted warning comment on PR #{pr_number}")


def create_or_update_issue(
    repo: str,
    pr: dict,
    age_hours: float,
    threshold_hours: int,
    dry_run: bool,
    runner=_run,
) -> None:
    """Create a new SLA tracking issue, or append a refresh comment to an existing one."""
    pr_number = pr["number"]
    title_short = (pr.get("title") or "").strip()[:60]
    issue_title = f"[critical-fix-SLA] PR #{pr_number} — {title_short} exceeded {threshold_hours}h prod-deploy SLA"
    body = make_issue_body(pr, age_hours, repo, threshold_hours)

    if dry_run:
        print(f"  [DRY-RUN] would create/update SLA issue: {issue_title}")
        return

    existing = find_existing_sla_issue(repo, pr_number, runner=runner)
    if existing:
        comment_body = f"SLA still active — age now {age_hours:.1f}h."
        runner(
            ["gh", "issue", "comment", str(existing), "--repo", repo, "--body", comment_body],
            check=True,
        )
        print(f"  [SLA] refreshed existing issue #{existing} for PR #{pr_number}")
        return

    # Codex iter-4 P1 absorb: only use `critical-fix-sla-active` label —
    # the previous `critical-fix-sla` second label was never ensured by
    # `ensure_label()` on workflow startup, so `gh issue create` would fail
    # on the first real SLA breach if that label did not pre-exist.
    runner(
        [
            "gh",
            "issue",
            "create",
            "--repo",
            repo,
            "--title",
            issue_title,
            "--body",
            body,
            "--label",
            SLA_ACTIVE_LABEL,
        ],
        check=True,
    )
    print(f"  [SLA] created tracking issue for PR #{pr_number}")


# --- Main --------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Critical-fix prod-deploy SLA monitor.")
    parser.add_argument("--repo", default="Halildeu/platform-k8s-gitops")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--critical-hours", type=int, default=DEFAULT_CRITICAL_HOURS)
    parser.add_argument("--warning-hours", type=int, default=DEFAULT_WARNING_HOURS)
    parser.add_argument("--window-hours", type=int, default=DEFAULT_WINDOW_HOURS)
    args = parser.parse_args(argv)

    if not args.dry_run:
        ensure_label(
            args.repo,
            SLA_ACTIVE_LABEL,
            "FFA500",
            "Active critical-fix prod-deploy SLA breach (auto-managed).",
        )

    try:
        prs = list_critical_fix_prs(args.repo, args.window_hours)
    except (GhError, json.JSONDecodeError) as e:
        print(f"ERR: failed to list critical-fix PRs: {e}", file=sys.stderr)
        return 1

    if not prs:
        print(f"[OK] no critical-fix PRs merged in last {args.window_hours}h")
        return 0

    print(f"[INFO] scanning {len(prs)} critical-fix PRs merged in last {args.window_hours}h")

    now = datetime.now(timezone.utc)
    warnings = 0
    issues = 0
    correlation_errors = 0
    for pr in prs:
        merge_commit = (pr.get("mergeCommit") or {}).get("oid") or ""
        if not merge_commit:
            print(f"  [WARN] PR #{pr.get('number')} has no mergeCommit.oid; skipping")
            continue
        try:
            merged_at = _parse_iso(pr["mergedAt"])
        except (KeyError, ValueError):
            print(f"  [WARN] PR #{pr.get('number')} has malformed mergedAt; skipping")
            continue

        age_hours = (now - merged_at).total_seconds() / 3600.0
        try:
            deployed = find_successful_deploy(args.repo, merge_commit, merged_at)
        except (GhError, json.JSONDecodeError) as e:
            # Codex iter-5 P1 absorb: correlation read failures (gh run list /
            # gh issue list / gh pr view) must escalate to a non-zero exit
            # code at the end of main(), not be silently swallowed. Otherwise
            # the scheduled workflow's success/failure indicator is decoupled
            # from whether the monitor actually scanned anything — defeating
            # the entire purpose of the SLA monitor.
            print(f"  [WARN] correlation check failed for PR #{pr['number']}: {e}", file=sys.stderr)
            correlation_errors += 1
            continue

        if deployed:
            print(
                f"  [OK]  PR #{pr['number']} reached prod via run "
                f"{deployed['databaseId']} (merge_age={age_hours:.1f}h)"
            )
            continue

        if age_hours >= args.critical_hours:
            print(
                f"  [LAG-CRIT] PR #{pr['number']} merged {age_hours:.1f}h ago "
                f"(>={args.critical_hours}h) — no successful deploy"
            )
            create_or_update_issue(args.repo, pr, age_hours, args.critical_hours, args.dry_run)
            issues += 1
        elif age_hours >= args.warning_hours:
            print(
                f"  [LAG-WARN] PR #{pr['number']} merged {age_hours:.1f}h ago "
                f"(>={args.warning_hours}h) — no successful deploy"
            )
            warn_on_pr(args.repo, pr, age_hours, args.critical_hours, args.dry_run)
            warnings += 1
        else:
            print(
                f"  [SUB-SLA] PR #{pr['number']} merged {age_hours:.1f}h ago — "
                f"within {args.warning_hours}h window"
            )

    print(f"[SUMMARY] warnings={warnings} sla_issues={issues} correlation_errors={correlation_errors}")
    # Codex iter-5 P1 — any correlation read failure escalates to exit 1 so
    # the scheduled GitHub Actions run is marked failed and observable in
    # Actions UI / via alertmanager-bridge gate-alertmanager-bridge-tests.
    return 1 if correlation_errors > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
