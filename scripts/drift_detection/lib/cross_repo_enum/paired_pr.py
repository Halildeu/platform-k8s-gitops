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

from .fetcher import ContentsKey, FetchError, Fetcher, PullKey, PullResult


PAIRED_PR_BLOCK_RE = re.compile(
    # Codex post-impl iter-2 axis 3 must-fix: the terminator must be a
    # NON-CONSUMING lookahead. The iter-2 version used `(?:<!--|$)` which
    # consumed the opening `<!--` of the following block — two adjacent
    # paired blocks would leave only the first URL visible to findall.
    r"<!--\s*cross-repo-enum-drift:paired-pr\s*-->(?P<body>.*?)(?=<!--|\Z)",
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

    Aggregates paired_pr_url lines across ALL fenced blocks (Codex post-impl
    iter-1 axis 3 must-fix: a second block was bypassed in iter-2 by reading
    only block_matches[0]).

    Raises PairingError on:
      - block present but with zero paired_pr_url lines
      - any number of blocks containing a total of != 1 paired_pr_url lines
    """
    block_matches = PAIRED_PR_BLOCK_RE.findall(body or "")
    if not block_matches:
        return None
    urls: list[str] = []
    for block_text in block_matches:
        urls.extend(PAIRED_PR_URL_RE.findall(block_text))
    if not urls:
        raise PairingError(
            "cross-repo-enum-drift:paired-pr block present but no paired_pr_url line"
        )
    if len(urls) > 1:
        raise PairingError(
            f"multiple paired_pr_url entries (across {len(block_matches)} fenced block(s)) — "
            f"paired-PR protocol expects exactly one per PR; found {len(urls)}"
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
    own_changed_paths: set[str] | None,
    guarded_paths_by_repo: dict[str, set[str]],
    fetcher: Fetcher,
) -> PairingResult:
    """Fetch the paired PR and validate ADR-0031 §I6:
      - paired PR repo matches `expected_other_repo` (NOT same as `own_repo`)
      - paired PR base ref is `main`
      - paired PR body's reciprocal `paired_pr_url` (if present) matches `own_pr_url`
      - **same guarded mapping touched** invariant (Codex post-impl iter-1 axis
        3 must-fix): the paired PR's changed-file list intersects the spec's
        guarded paths for the opposite repo, AND when `own_changed_paths` is
        provided, this PR's changes also intersect the spec's guarded paths
        for `own_repo`. Otherwise PairingError — the paired URL points at an
        unrelated PR.

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
    # ADR §I6 same-guarded-mapping check — fetch the paired PR's changed
    # files and assert it touches at least one guarded path for its repo.
    paired_changed = _fetch_changed_paths(ref.repo, ref.number)
    paired_guarded = guarded_paths_by_repo.get(ref.repo, set())
    if not (paired_changed & paired_guarded):
        raise PairingError(
            f"paired PR {paired_url} does not touch any guarded path for {ref.repo!r}; "
            f"paired-PR protocol requires both sides to mutate a guarded mapping"
        )
    # And our side — when we know our changed paths — must also touch a
    # guarded path for own_repo. (Allow None for spec-host runs.)
    if own_changed_paths is not None:
        own_guarded = guarded_paths_by_repo.get(own_repo, set())
        if not (own_changed_paths & own_guarded):
            raise PairingError(
                f"current PR does not touch any guarded path for {own_repo!r}; "
                f"remove paired_pr_url or open the actual paired mutation"
            )
    # reciprocal check — paired PR body should reference our PR url
    try:
        reciprocal_url = extract_paired_pr_url(paired.body or "")
    except PairingError:
        reciprocal_url = None
    reciprocal = bool(
        reciprocal_url
        and reciprocal_url.strip().rstrip("/") == own_pr_url.strip().rstrip("/")
    )
    return PairingResult(
        mode="paired",
        paired_pr_url=paired_url,
        paired_pull=paired,
        reciprocal_pairing=reciprocal,
    )


def _fetch_changed_paths(repo: str, number: int) -> set[str]:
    """Return the set of paths modified by the PR (added / modified / deleted).

    Uses `gh api repos/<repo>/pulls/<num>/files` directly via subprocess so
    the fetcher cache is not poisoned (this is a one-shot lookup per paired
    PR resolution).
    """
    import json as _json
    import subprocess as _sp

    proc = _sp.run(
        ["gh", "api", f"repos/{repo}/pulls/{number}/files", "--paginate"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        err_low = proc.stderr.lower()
        if "404" in err_low or "not found" in err_low:
            raise PairingError(
                f"paired PR file list not found at {repo}#{number}"
            )
        if "403" in err_low or "forbidden" in err_low:
            raise PairingError(
                f"auth insufficient for paired PR file list at {repo}#{number}: "
                "required Pull requests:Read"
            )
        raise PairingError(
            f"gh api files failed for {repo}#{number}: {proc.stderr.strip()[:200]}"
        )
    payload = _json.loads(proc.stdout) if proc.stdout.strip() else []
    return {entry.get("filename", "") for entry in payload if entry.get("filename")}


def guarded_paths_from_spec(spec_mappings: list[dict]) -> dict[str, set[str]]:
    """Build a {repo: {paths}} index from the spec for the same-mapping check."""
    out: dict[str, set[str]] = {}
    for m in spec_mappings:
        c = m["canonical"]
        out.setdefault(c["repo"], set()).add(c["path"])
        for mr in m["mirrors"]:
            out.setdefault(mr["repo"], set()).add(mr["path"])
    return out


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
