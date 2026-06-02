"""Paired-PR protocol — ADR-0031 §I6.

Parses the fenced block from a PR description:

    <!-- cross-repo-enum-drift:paired-pr -->
    paired_pr_url: https://github.com/<owner>/<repo>/pull/<N>

Exactly ONE `paired_pr_url:` line per PR. Multiple → exit 2.

Canonical-first merge invariant (asymmetric, machine-enforced):
  - Canonical-side PR passes when set(canonical@PR-head) == set(mirror@paired-PR-head).
    Mirror PR does NOT need to merge first.
  - Mirror-side PR REQUIRES paired canonical PR `merged_at != null` AND
    set(canonical@main) == set(mirror@PR-head). If paired canonical PR is
    open or closed-unmerged, exit 1 with merge_order_violation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from .fetcher import FetchError, Fetcher, PullKey, PullResult


PAIRED_PR_BLOCK_RE = re.compile(
    r"<!--\s*cross-repo-enum-drift:paired-pr\s*-->(?P<body>.*?)(?:<!--|$)",
    flags=re.DOTALL,
)
PAIRED_PR_URL_RE = re.compile(
    r"^\s*paired_pr_url:\s*(?P<url>https?://github\.com/[^/\s]+/[^/\s]+/pull/\d+)\s*$",
    flags=re.MULTILINE,
)
PR_URL_PARSE_RE = re.compile(
    r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<num>\d+)$"
)


class PairingError(ValueError):
    """Raised when the paired-PR block is structurally invalid (exit 2)."""


class MergeOrderViolation(RuntimeError):
    """Raised when the canonical-first invariant is violated (exit 1)."""


Mode = Literal["paired", "unpaired-main"]


@dataclass(frozen=True)
class PairedPRRef:
    repo: str  # owner/repo
    number: int


@dataclass(frozen=True)
class PairingResult:
    mode: Mode
    paired_pr_url: str | None
    paired_pull: PullResult | None
    reciprocal_pairing: bool


def extract_paired_pr_url(body: str) -> str | None:
    """Return the single paired_pr_url from the PR body, or None if no block.
    Raises PairingError on:
      - block present but with zero paired_pr_url lines
      - block present but with multiple paired_pr_url lines
    """
    block_matches = PAIRED_PR_BLOCK_RE.findall(body or "")
    if not block_matches:
        return None
    block_text = block_matches[0]
    urls = PAIRED_PR_URL_RE.findall(block_text)
    if not urls:
        raise PairingError(
            "cross-repo-enum-drift:paired-pr block present but no paired_pr_url line"
        )
    if len(urls) > 1:
        raise PairingError(
            f"multiple paired_pr_url entries — paired-PR protocol expects exactly one per PR; "
            f"found {len(urls)}"
        )
    return urls[0]


def parse_pr_url(url: str) -> PairedPRRef:
    m = PR_URL_PARSE_RE.match(url.strip())
    if not m:
        raise PairingError(f"paired_pr_url does not match GitHub PR URL shape: {url!r}")
    return PairedPRRef(
        repo=f"{m.group('owner')}/{m.group('repo')}",
        number=int(m.group("num")),
    )


def validate_paired_pr(
    *,
    paired_url: str,
    own_repo: str,
    expected_other_repo: str,
    own_pr_url: str,
    fetcher: Fetcher,
) -> PairingResult:
    """Fetch the paired PR and validate:
      - paired PR repo matches `expected_other_repo` (NOT same as `own_repo`)
      - paired PR base ref is `main`
      - paired PR body's reciprocal `paired_pr_url` (if present) matches `own_pr_url`

    Returns PairingResult with mode='paired' on success.
    """
    ref = parse_pr_url(paired_url)
    if ref.repo == own_repo:
        raise PairingError(
            f"paired PR repo mismatch: paired URL points to own repo {own_repo!r}; "
            f"expected opposite side {expected_other_repo!r}"
        )
    if ref.repo != expected_other_repo:
        raise PairingError(
            f"paired PR repo mismatch: paired URL is in {ref.repo!r}; "
            f"expected {expected_other_repo!r}"
        )
    paired = fetcher.get_pull(PullKey(repo=ref.repo, number=ref.number))
    if paired.base_ref != "main":
        raise PairingError(
            f"paired PR base must be main; got {paired.base_ref!r} for {paired_url}"
        )
    # reciprocal check — paired PR body should reference our PR url
    try:
        reciprocal_url = extract_paired_pr_url(paired.body or "")
    except PairingError:
        reciprocal_url = None
    reciprocal = bool(reciprocal_url and reciprocal_url.strip().rstrip("/") == own_pr_url.strip().rstrip("/"))
    return PairingResult(
        mode="paired",
        paired_pr_url=paired_url,
        paired_pull=paired,
        reciprocal_pairing=reciprocal,
    )


def check_canonical_first(
    *,
    own_role: Literal["canonical", "mirror"],
    paired: PairingResult,
) -> None:
    """ADR-0031 §I6 — raise MergeOrderViolation if the canonical-first invariant
    is violated. Asymmetric semantics:
      - canonical-side PR: paired mirror PR may be open; closed-unmerged → exit 1.
      - mirror-side PR: paired canonical PR MUST be merged; open or
        closed-unmerged → exit 1.
    """
    pull = paired.paired_pull
    if pull is None:
        return
    if own_role == "canonical":
        if pull.state == "closed" and not pull.merged_at:
            raise MergeOrderViolation(
                f"paired mirror PR closed without merge ({paired.paired_pr_url}); "
                "reopen or remove paired_pr_url"
            )
        if pull.state == "closed" and pull.merged_at:
            raise MergeOrderViolation(
                f"paired mirror PR already merged ({paired.paired_pr_url}) but canonical "
                "still open — canonical-first invariant violated; mirror landed first"
            )
        # state == open → OK; canonical-side does NOT require mirror merge
        return
    # mirror-side
    if pull.state == "open":
        raise MergeOrderViolation(
            f"canonical PR {paired.paired_pr_url} must merge first; "
            "current canonical main lacks the new value-set"
        )
    if pull.state == "closed" and not pull.merged_at:
        raise MergeOrderViolation(
            f"paired canonical PR closed without merge ({paired.paired_pr_url}); "
            "remove paired_pr_url or reopen"
        )
    # state == closed AND merged_at != null → OK; caller will re-fetch canonical main
