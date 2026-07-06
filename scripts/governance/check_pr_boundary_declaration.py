#!/usr/bin/env python3
"""
ADR-0011 BG-1 — PR boundary declaration CI gate (Codex 019dd409 PARTIAL/REVISE).

Validates that every PR includes the ADR-0011 §2.3 boundary declaration block
with required structure:

1. Exact heading: `## Boundary declaration (ADR-0011 §2.3)`
2. 7 expected checkboxes (credential-read, credential-write, state-mutation
   (test cluster), state-mutation (production), boundary-cross,
   user-communication, none of the above)
3. At least one checkbox marked `[x]` or `[X]`
4. If `none of the above` is marked, all 6 others must be unmarked
5. If user-approval-required class marked (credential-read, credential-write,
   state-mutation (production), boundary-cross, user-communication), require:
   - Body contains `User-approval evidence: <link or N/A-not-allowed>`
   - PR has `user-approval-required` label

Codex 019dd409 PARTIAL/REVISE points implemented:
- credential-read added to user-approval-required class (was missed in initial spec)
- gh pr view replaced with $GITHUB_EVENT_PATH event payload reading
- Local test via --body-file + --labels-file flags
- Hard-fail on label gate (not soft warn)

Exit codes:
  0 = pass
  1 = drift detected (missing/malformed block, missing approvals)
  2 = invocation error (event payload unreadable)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BOUNDARY_HEADING = "## Boundary declaration (ADR-0011 §2.3)"

# 7 expected boundary classes (exact match in PR body)
# ADR-0013 D45 BG-NOTIFY-1: user-communication class added (Faz 23 Notification
# Orchestration — prod template/workflow/audience/provider değişikliği için).
EXPECTED_CLASSES = [
    "credential-read",
    "credential-write",
    "state-mutation (test cluster)",
    "state-mutation (production)",
    "boundary-cross",
    "user-communication",
    "none of the above",
]

# Classes that require user-approval evidence + label (Codex 019dd409 revise:
# credential-read added to this set; ADR-0013 D45: user-communication added).
USER_APPROVAL_CLASSES = {
    "credential-read",
    "credential-write",
    "state-mutation (production)",
    "boundary-cross",
    "user-communication",
}

USER_APPROVAL_LABEL = "user-approval-required"
EVIDENCE_MARKER_REGEX = re.compile(
    r"User-approval evidence:\s*(.+?)(?:\n|$)",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Dependabot bot PR exemption (#898, Codex `019e4517` AGREE 3-iter consensus)
# ---------------------------------------------------------------------------
#
# A Dependabot-opened PR is a non-AI, machine-generated dependency bump that
# cannot fill the boundary declaration block (dep-version bumps are ADR-0011
# §2.3.1 "none of the above" boundary class — credential/state-mut/boundary-
# cross/user-comm yok). The exemption is fail-closed and bounded by FIVE gates
# running together:
#   1. branch prefix `dependabot/`
#   2. same-repo (fork PR named `dependabot/foo` blocked)
#   3. PR author = `dependabot[bot]` (immutable once opened)
#   4. event sender = `dependabot[bot]` (blocks human metadata bypass)
#   5. changed-files list present AND every path matches the diff allowlist
#
# Diff allowlist is intentionally NARROW — only `.github/workflows/*.{yml,yaml}`.
# Helm/Kustomize/Dockerfile/pom.xml/package.json paths are deliberately
# excluded. The `.github/dependabot.yml` config in this repo only enables the
# `github-actions` ecosystem; widening requires a separate consensus iter.
#
# If branch prefix is `dependabot/` but ANY gate fails, the exemption is denied
# with a `dependabot_*` finding and the audit RETURNS FAIL — it does NOT fall
# back to `run_all_checks(body, labels)`. A spoofed `dependabot/*` head with a
# forged boundary block must fail closed.

DEPENDABOT_BRANCH_PREFIX = "dependabot/"
DEPENDABOT_ACTOR = "dependabot[bot]"
DEPENDABOT_DIFF_ALLOWLIST = [
    re.compile(r"^\.github/workflows/[^/]+\.ya?ml$"),
]


def is_dependabot_head(head_ref: str) -> bool:
    """Return True if the PR head ref starts with the Dependabot prefix."""
    return (head_ref or "").startswith(DEPENDABOT_BRANCH_PREFIX)


def run_dependabot_checks(
    head_ref: str,
    actor: str,
    sender: str,
    head_repo: str,
    base_repo: str,
    changed_files: list[str] | None,
) -> "GateReport":
    """Run the 6-gate Dependabot bot PR exemption audit.

    Returns a GateReport with overall PASS only when ALL gates pass; any
    failure denies the exemption. Caller MUST NOT fall back to the normal
    boundary-block audit on failure.
    """
    checks: list[CheckResult] = []

    # 1. branch prefix (re-asserted for the report)
    prefix_ok = (head_ref or "").startswith(DEPENDABOT_BRANCH_PREFIX)
    checks.append(
        CheckResult(
            name="dependabot_branch_prefix",
            passed=prefix_ok,
            message=(
                f'head.ref "{head_ref}" matches "{DEPENDABOT_BRANCH_PREFIX}"'
                if prefix_ok
                else f'head.ref "{head_ref}" does not match "{DEPENDABOT_BRANCH_PREFIX}"'
            ),
        )
    )

    # 2. same-repo (fork blocked)
    same_repo = bool(head_repo) and bool(base_repo) and head_repo == base_repo
    checks.append(
        CheckResult(
            name="dependabot_same_repo",
            passed=same_repo,
            message=(
                f'head & base both "{base_repo}"'
                if same_repo
                else f'fork PR ("{head_repo}" != "{base_repo}") — not exemption-eligible'
            ),
        )
    )

    # 3. PR author = dependabot[bot]
    author_ok = actor == DEPENDABOT_ACTOR
    checks.append(
        CheckResult(
            name="dependabot_author",
            passed=author_ok,
            message=(
                f'pr.user.login = "{actor}"'
                if author_ok
                else f'pr.user.login = "{actor}" — must be "{DEPENDABOT_ACTOR}"'
            ),
        )
    )

    # 4. event sender = dependabot[bot] (blocks human label/synchronize)
    sender_ok = sender == DEPENDABOT_ACTOR
    checks.append(
        CheckResult(
            name="dependabot_sender",
            passed=sender_ok,
            message=(
                f'event.sender.login = "{sender}"'
                if sender_ok
                else f'event.sender.login = "{sender}" — must be "{DEPENDABOT_ACTOR}" (human metadata event blocked)'
            ),
        )
    )

    # 5. changed-files present
    files_present = isinstance(changed_files, list) and len(changed_files) > 0
    checks.append(
        CheckResult(
            name="dependabot_changed_files_present",
            passed=files_present,
            message=(
                f"{len(changed_files)} changed file(s) declared"
                if files_present
                else "changed-files null or empty — fail-closed (workflow must inject --changed-files-file)"
            ),
        )
    )

    # 6. diff allowlist — every path in github-actions ecosystem regex
    if files_present:
        bad_path: str | None = None
        for path in changed_files:
            if not any(pattern.match(path) for pattern in DEPENDABOT_DIFF_ALLOWLIST):
                bad_path = path
                break
        checks.append(
            CheckResult(
                name="dependabot_diff_allowlist",
                passed=bad_path is None,
                message=(
                    f"{len(changed_files)} file(s) all inside github-actions workflow allowlist"
                    if bad_path is None
                    else f'path "{bad_path}" not in allowlist (only .github/workflows/*.yml|.yaml accepted)'
                ),
            )
        )
    else:
        checks.append(
            CheckResult(
                name="dependabot_diff_allowlist",
                passed=False,
                message="diff allowlist gate skipped — changed-files list missing (see dependabot_changed_files_present)",
            )
        )

    overall = "PASS" if all(c.passed for c in checks) else "FAIL"
    return GateReport(overall=overall, checks=checks)


def format_dependabot_report(report: "GateReport") -> str:
    """Human-readable Dependabot exemption report (mirrors format_human shape)."""
    green = "\033[1;32m" if sys.stdout.isatty() else ""
    red = "\033[1;31m" if sys.stdout.isatty() else ""
    reset = "\033[0m" if sys.stdout.isatty() else ""

    lines: list[str] = ["[BG-1] Dependabot exemption mode"]
    for c in report.checks:
        sym = f"{green}✓{reset}" if c.passed else f"{red}✗{reset}"
        lines.append(f"  {sym} {c.name}: {c.message}")

    overall_color = green if report.overall == "PASS" else red
    passed = sum(1 for c in report.checks if c.passed)
    lines.append("")
    lines.append(
        f"{overall_color}BG-1 Dependabot exemption: {report.overall} ({passed}/{len(report.checks)}){reset}"
    )
    if report.overall == "PASS":
        lines.append(
            "BG-1 skipped: Dependabot bot PR (no code-class boundary applies)"
        )
    return "\n".join(lines)

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    name: str
    passed: bool
    message: str
    details: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class GateReport:
    overall: str  # "PASS" | "FAIL"
    checks: list[CheckResult]

    def to_dict(self) -> dict:
        return {"overall": self.overall, "checks": [c.to_dict() for c in self.checks]}


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def extract_boundary_block(body: str) -> tuple[str | None, str | None]:
    """Return (block_text, error). block_text excludes heading itself."""
    if BOUNDARY_HEADING not in body:
        return None, f"PR body missing exact heading: '{BOUNDARY_HEADING}'"

    idx = body.index(BOUNDARY_HEADING) + len(BOUNDARY_HEADING)
    rest = body[idx:]
    # Block ends at next ## heading or EOF
    next_section = re.search(r"\n##\s+", rest)
    block = rest[: next_section.start()] if next_section else rest
    return block.strip(), None


def parse_checkbox_states(block: str) -> dict[str, bool | None]:
    """Return {class_name: True/False/None}. None means class missing entirely."""
    states: dict[str, bool | None] = {cls: None for cls in EXPECTED_CLASSES}
    for cls in EXPECTED_CLASSES:
        # Match: `- [x] credential-read` or `- [ ] state-mutation (test cluster)`
        # `(?![a-zA-Z])` instead of `\b` because some classes end with `)` —
        # `\b` requires word→non-word boundary which fails after `)`.
        pattern = re.compile(
            rf"-\s*\[(\s|x|X)\]\s+{re.escape(cls)}(?![a-zA-Z])",
            re.IGNORECASE | re.MULTILINE,
        )
        match = pattern.search(block)
        if match:
            ch = match.group(1).strip().lower()
            states[cls] = (ch == "x")
    return states


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def check_block_present(body: str) -> CheckResult:
    block, err = extract_boundary_block(body)
    if err:
        return CheckResult(name="boundary_block_present", passed=False, message=err)
    return CheckResult(
        name="boundary_block_present",
        passed=True,
        message=f"Found '{BOUNDARY_HEADING}' block ({len(block)} chars)",
    )


def check_seven_classes_present(body: str) -> CheckResult:
    block, err = extract_boundary_block(body)
    if err:
        return CheckResult(name="seven_classes_present", passed=False, message=err)
    states = parse_checkbox_states(block)
    missing = [cls for cls, state in states.items() if state is None]
    if missing:
        return CheckResult(
            name="seven_classes_present",
            passed=False,
            message=f"Boundary block missing {len(missing)} class(es)",
            details=[f"missing: {m}" for m in missing],
        )
    return CheckResult(
        name="seven_classes_present",
        passed=True,
        message=f"All {len(EXPECTED_CLASSES)} boundary classes present",
    )


def check_at_least_one_marked(body: str) -> CheckResult:
    block, err = extract_boundary_block(body)
    if err:
        return CheckResult(name="at_least_one_marked", passed=False, message=err)
    states = parse_checkbox_states(block)
    marked = [cls for cls, state in states.items() if state is True]
    if not marked:
        return CheckResult(
            name="at_least_one_marked",
            passed=False,
            message="No boundary class marked [x] — at least one required",
        )
    return CheckResult(
        name="at_least_one_marked",
        passed=True,
        message=f"Marked: {', '.join(marked)}",
    )


def check_none_exclusivity(body: str) -> CheckResult:
    """If 'none of the above' marked, all 6 others must be unmarked."""
    block, err = extract_boundary_block(body)
    if err:
        return CheckResult(name="none_exclusivity", passed=False, message=err)
    states = parse_checkbox_states(block)
    if states.get("none of the above") is True:
        also_marked = [
            cls for cls, state in states.items()
            if cls != "none of the above" and state is True
        ]
        if also_marked:
            return CheckResult(
                name="none_exclusivity",
                passed=False,
                message="'none of the above' marked but other classes also marked",
                details=[f"conflict: {c}" for c in also_marked],
            )
    return CheckResult(
        name="none_exclusivity",
        passed=True,
        message="none-exclusivity rule respected",
    )


def check_user_approval_evidence(body: str) -> CheckResult:
    """If user-approval class marked, require evidence marker (not 'N/A')."""
    block, err = extract_boundary_block(body)
    if err:
        return CheckResult(name="user_approval_evidence", passed=False, message=err)
    states = parse_checkbox_states(block)
    triggered = [
        cls for cls in USER_APPROVAL_CLASSES if states.get(cls) is True
    ]
    if not triggered:
        return CheckResult(
            name="user_approval_evidence",
            passed=True,
            message="No user-approval-required class marked",
        )

    # Evidence marker (whole-body search; can be inside or outside block)
    matches = EVIDENCE_MARKER_REGEX.findall(body)
    if not matches:
        return CheckResult(
            name="user_approval_evidence",
            passed=False,
            message="User-approval-required class marked but 'User-approval evidence:' marker missing in PR body",
            details=[f"triggered class(es): {', '.join(triggered)}"],
        )

    # If any marker is N/A while user-approval class triggered → fail
    invalid = [m.strip() for m in matches if m.strip().upper() in {"N/A", "NA", ""}]
    if invalid and len(matches) == len(invalid):
        return CheckResult(
            name="user_approval_evidence",
            passed=False,
            message="'User-approval evidence:' is N/A but user-approval-required class is marked",
            details=[f"triggered class(es): {', '.join(triggered)}"],
        )
    return CheckResult(
        name="user_approval_evidence",
        passed=True,
        message=f"Evidence marker present for {len(triggered)} user-approval class(es)",
    )


def check_user_approval_label(body: str, labels: list[str]) -> CheckResult:
    """If user-approval class marked, PR must have 'user-approval-required' label."""
    block, err = extract_boundary_block(body)
    if err:
        return CheckResult(name="user_approval_label", passed=False, message=err)
    states = parse_checkbox_states(block)
    triggered = [
        cls for cls in USER_APPROVAL_CLASSES if states.get(cls) is True
    ]
    if not triggered:
        return CheckResult(
            name="user_approval_label",
            passed=True,
            message="No user-approval-required class marked",
        )

    if USER_APPROVAL_LABEL not in labels:
        return CheckResult(
            name="user_approval_label",
            passed=False,
            message=f"User-approval class marked but PR missing '{USER_APPROVAL_LABEL}' label",
            details=[f"triggered: {', '.join(triggered)}", f"current labels: {labels or '(none)'}"],
        )
    return CheckResult(
        name="user_approval_label",
        passed=True,
        message=f"'{USER_APPROVAL_LABEL}' label set for user-approval class(es): {', '.join(triggered)}",
    )


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


def read_event_payload(event_path: str) -> tuple[str, list[str], dict[str, str]]:
    """Read GitHub Actions event payload, return (body, labels, prMeta).

    `prMeta` carries the metadata the Dependabot exemption gate needs:
    head_ref / actor / sender / head_repo / base_repo. Loaded eagerly — even
    a normal (non-dependabot) PR goes through the same read; only the main
    dispatch decides whether to invoke the dependabot lane.
    """
    p = Path(event_path)
    if not p.exists():
        raise FileNotFoundError(f"event payload not found: {event_path}")
    payload = json.loads(p.read_text(encoding="utf-8"))
    pr = payload.get("pull_request", {})
    body = pr.get("body") or ""
    labels = [lab.get("name", "") for lab in pr.get("labels", []) if lab.get("name")]
    pr_meta = {
        "head_ref": (pr.get("head") or {}).get("ref") or "",
        "head_repo": ((pr.get("head") or {}).get("repo") or {}).get("full_name") or "",
        "base_repo": ((pr.get("base") or {}).get("repo") or {}).get("full_name") or "",
        "actor": (pr.get("user") or {}).get("login") or "",
        "sender": (payload.get("sender") or {}).get("login") or "",
    }
    return body, labels, pr_meta


def read_changed_files(changed_files_path: str | None) -> list[str] | None:
    """Read a workflow-prepared file of changed paths (one per line).

    Returns `None` if the path is not provided (legacy test mode or older
    workflow). The Dependabot lane treats `None`/empty as fail-closed via the
    `dependabot_changed_files_present` check.
    """
    if not changed_files_path:
        return None
    p = Path(changed_files_path)
    if not p.exists():
        return None
    return [
        line.strip()
        for line in p.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def run_all_checks(body: str, labels: list[str]) -> GateReport:
    checks = [
        check_block_present(body),
        check_seven_classes_present(body),
        check_at_least_one_marked(body),
        check_none_exclusivity(body),
        check_user_approval_evidence(body),
        check_user_approval_label(body, labels),
    ]
    overall = "PASS" if all(c.passed for c in checks) else "FAIL"
    return GateReport(overall=overall, checks=checks)


def format_human(report: GateReport, verbose: bool) -> str:
    GREEN = "\033[1;32m" if sys.stdout.isatty() else ""
    RED = "\033[1;31m" if sys.stdout.isatty() else ""
    RESET = "\033[0m" if sys.stdout.isatty() else ""

    lines: list[str] = []
    for c in report.checks:
        sym = f"{GREEN}✓{RESET}" if c.passed else f"{RED}✗{RESET}"
        lines.append(f"  {sym} {c.name}: {c.message}")
        if verbose or not c.passed:
            for d in c.details:
                lines.append(f"      → {d}")

    overall_color = GREEN if report.overall == "PASS" else RED
    summary = f"{overall_color}BG-1 PR boundary declaration: {report.overall} ({sum(1 for c in report.checks if c.passed)}/{len(report.checks)}){RESET}"
    return "\n".join(lines) + "\n\n" + summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="ADR-0011 BG-1 — PR boundary declaration CI gate.",
    )
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--event-path",
        help="Path to GitHub Actions event payload JSON ($GITHUB_EVENT_PATH)",
    )
    parser.add_argument(
        "--body-file",
        help="Local file containing PR body (test mode; overrides --event-path)",
    )
    parser.add_argument(
        "--labels-file",
        help="Local file with newline-separated labels (test mode)",
    )
    parser.add_argument(
        "--changed-files-file",
        help=(
            "Local file with newline-separated changed file paths. The workflow "
            "pre-fetches this via `gh api ... --paginate` for the Dependabot "
            "exemption diff-allowlist gate (#898)."
        ),
    )
    # #898 — Dependabot exemption test-mode overrides. In test mode the event
    # payload synthesis path is bypassed, so head ref / actor / sender / repos
    # come from these flags directly.
    parser.add_argument("--test-head-ref", help="(test mode) PR head ref override")
    parser.add_argument("--test-actor", help="(test mode) PR author login override")
    parser.add_argument("--test-sender", help="(test mode) event sender login override")
    parser.add_argument("--test-head-repo", help="(test mode) PR head repo full_name")
    parser.add_argument("--test-base-repo", help="(test mode) PR base repo full_name")
    args = parser.parse_args()

    pr_meta: dict[str, str] = {}
    if args.body_file:
        body = Path(args.body_file).read_text(encoding="utf-8")
        labels: list[str] = []
        if args.labels_file:
            labels = [
                line.strip()
                for line in Path(args.labels_file).read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        pr_meta = {
            "head_ref": args.test_head_ref or "",
            "head_repo": args.test_head_repo or "",
            "base_repo": args.test_base_repo or "",
            "actor": args.test_actor or "",
            "sender": args.test_sender or "",
        }
    elif args.event_path:
        try:
            body, labels, pr_meta = read_event_payload(args.event_path)
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            print(f"[error] {exc}", file=sys.stderr)
            return 2
    else:
        print("[error] either --event-path or --body-file required", file=sys.stderr)
        return 2

    changed_files = read_changed_files(args.changed_files_file)

    # #898 — Dependabot lane. If the head ref matches the Dependabot prefix,
    # the boundary block is irrelevant (bot doesn't fill one) and the gate is
    # the 6-check exemption audit. CRITICAL: fail-closed — when the dependabot
    # branch is detected, we DO NOT fall back to run_all_checks() on failure.
    # A spoofed `dependabot/*` head with a forged boundary block must fail.
    if is_dependabot_head(pr_meta.get("head_ref", "")):
        report = run_dependabot_checks(
            head_ref=pr_meta.get("head_ref", ""),
            actor=pr_meta.get("actor", ""),
            sender=pr_meta.get("sender", ""),
            head_repo=pr_meta.get("head_repo", ""),
            base_repo=pr_meta.get("base_repo", ""),
            changed_files=changed_files,
        )
        if args.json:
            print(json.dumps(report.to_dict(), indent=2))
        else:
            print(format_dependabot_report(report))
        return 0 if report.overall == "PASS" else 1

    report = run_all_checks(body, labels)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(format_human(report, args.verbose))
    return 0 if report.overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
