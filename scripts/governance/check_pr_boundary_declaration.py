#!/usr/bin/env python3
"""
ADR-0011 BG-1 — PR boundary declaration CI gate (Codex 019dd409 PARTIAL/REVISE).

Validates that every PR includes the ADR-0011 §2.3 boundary declaration block
with required structure:

1. Exact heading: `## Boundary declaration (ADR-0011 §2.3)`
2. 6 expected checkboxes (credential-read, credential-write, state-mutation
   (test cluster), state-mutation (production), boundary-cross, none of the
   above)
3. At least one checkbox marked `[x]` or `[X]`
4. If `none of the above` is marked, all 5 others must be unmarked
5. If user-approval-required class marked (credential-read, credential-write,
   state-mutation (production), boundary-cross), require:
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

# 6 expected boundary classes (exact match in PR body)
EXPECTED_CLASSES = [
    "credential-read",
    "credential-write",
    "state-mutation (test cluster)",
    "state-mutation (production)",
    "boundary-cross",
    "none of the above",
]

# Classes that require user-approval evidence + label (Codex 019dd409 revise:
# credential-read added to this set)
USER_APPROVAL_CLASSES = {
    "credential-read",
    "credential-write",
    "state-mutation (production)",
    "boundary-cross",
}

USER_APPROVAL_LABEL = "user-approval-required"
EVIDENCE_MARKER_REGEX = re.compile(
    r"User-approval evidence:\s*(.+?)(?:\n|$)",
    re.IGNORECASE,
)

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


def check_six_classes_present(body: str) -> CheckResult:
    block, err = extract_boundary_block(body)
    if err:
        return CheckResult(name="six_classes_present", passed=False, message=err)
    states = parse_checkbox_states(block)
    missing = [cls for cls, state in states.items() if state is None]
    if missing:
        return CheckResult(
            name="six_classes_present",
            passed=False,
            message=f"Boundary block missing {len(missing)} class(es)",
            details=[f"missing: {m}" for m in missing],
        )
    return CheckResult(
        name="six_classes_present",
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
    """If 'none of the above' marked, all 5 others must be unmarked."""
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


def read_event_payload(event_path: str) -> tuple[str, list[str]]:
    """Read GitHub Actions event payload, return (body, labels)."""
    p = Path(event_path)
    if not p.exists():
        raise FileNotFoundError(f"event payload not found: {event_path}")
    payload = json.loads(p.read_text(encoding="utf-8"))
    pr = payload.get("pull_request", {})
    body = pr.get("body") or ""
    labels = [lab.get("name", "") for lab in pr.get("labels", []) if lab.get("name")]
    return body, labels


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def run_all_checks(body: str, labels: list[str]) -> GateReport:
    checks = [
        check_block_present(body),
        check_six_classes_present(body),
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
    args = parser.parse_args()

    if args.body_file:
        body = Path(args.body_file).read_text(encoding="utf-8")
        labels: list[str] = []
        if args.labels_file:
            labels = [
                line.strip()
                for line in Path(args.labels_file).read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
    elif args.event_path:
        try:
            body, labels = read_event_payload(args.event_path)
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            print(f"[error] {exc}", file=sys.stderr)
            return 2
    else:
        print("[error] either --event-path or --body-file required", file=sys.stderr)
        return 2

    report = run_all_checks(body, labels)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(format_human(report, args.verbose))
    return 0 if report.overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
