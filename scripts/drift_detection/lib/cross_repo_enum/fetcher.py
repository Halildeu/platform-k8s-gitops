"""gh api contents/pulls wrapper with process-scoped cache.

ADR-0031 §I3:
  - 403/404 disambiguated per endpoint (contents vs pulls).
  - Auth errors NEVER silently pass as drift-free.
  - Token redacted; only set/unset boolean logged.
  - Cache keyed on (repo, path, ref) for contents; (repo, num) for pulls.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
from dataclasses import dataclass
from typing import Any


class FetchError(RuntimeError):
    """Raised on any gh api failure that should NOT pass as drift-free."""

    def __init__(self, message: str, *, exit_code: int = 2) -> None:
        super().__init__(message)
        self.exit_code = exit_code


@dataclass(frozen=True)
class ContentsKey:
    repo: str  # owner/repo
    path: str
    ref: str  # branch, tag, or SHA


@dataclass(frozen=True)
class PullKey:
    repo: str
    number: int


@dataclass(frozen=True)
class ContentsResult:
    text: str
    sha: str  # blob SHA, identifies the exact content


@dataclass(frozen=True)
class PullResult:
    state: str  # "open" | "closed"
    merged_at: str | None
    body: str
    head_sha: str
    head_ref: str
    head_repo_full_name: str
    base_ref: str
    base_repo_full_name: str


class Fetcher:
    """Process-scoped cache of gh api responses."""

    def __init__(self, *, gh_token_env: str = "GH_TOKEN") -> None:
        self._contents_cache: dict[ContentsKey, ContentsResult] = {}
        self._pulls_cache: dict[PullKey, PullResult] = {}
        self._gh_token_env = gh_token_env
        # boolean only — never log the value
        self._token_set = bool(os.environ.get(gh_token_env))

    @property
    def token_set(self) -> bool:
        return self._token_set

    def get_contents(self, key: ContentsKey) -> ContentsResult:
        cached = self._contents_cache.get(key)
        if cached is not None:
            return cached
        result = self._fetch_contents(key)
        self._contents_cache[key] = result
        return result

    def get_pull(self, key: PullKey) -> PullResult:
        cached = self._pulls_cache.get(key)
        if cached is not None:
            return cached
        result = self._fetch_pull(key)
        self._pulls_cache[key] = result
        return result

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    def _fetch_contents(self, key: ContentsKey) -> ContentsResult:
        url = f"repos/{key.repo}/contents/{key.path}"
        # `gh api -f ref=...` defaults to POST unless the method is pinned.
        # The GitHub contents endpoint is GET-only for reads.
        cmd = ["gh", "api", "--method", "GET", url, "-f", f"ref={key.ref}"]
        rc, out, err = _run(cmd)
        if rc != 0:
            self._raise_for_status_contents(key, rc, err)
        try:
            payload = json.loads(out)
        except json.JSONDecodeError as exc:
            raise FetchError(
                f"contents/{key.path}: gh api returned non-JSON for {key.repo}@{key.ref}: {exc}",
                exit_code=2,
            ) from exc
        encoding = payload.get("encoding", "base64")
        if encoding != "base64":
            raise FetchError(
                f"contents/{key.path}: unexpected encoding {encoding!r} for {key.repo}@{key.ref}",
                exit_code=2,
            )
        raw = payload.get("content", "")
        if not raw:
            raise FetchError(
                f"contents/{key.path}: empty content for {key.repo}@{key.ref}",
                exit_code=2,
            )
        try:
            text = base64.b64decode(raw, validate=False).decode("utf-8")
        except Exception as exc:
            raise FetchError(
                f"contents/{key.path}: base64 decode failed for {key.repo}@{key.ref}: {exc}",
                exit_code=2,
            ) from exc
        sha = payload.get("sha", "")
        return ContentsResult(text=text, sha=sha)

    def _fetch_pull(self, key: PullKey) -> PullResult:
        url = f"repos/{key.repo}/pulls/{key.number}"
        cmd = ["gh", "api", url]
        rc, out, err = _run(cmd)
        if rc != 0:
            self._raise_for_status_pull(key, rc, err)
        try:
            payload = json.loads(out)
        except json.JSONDecodeError as exc:
            raise FetchError(
                f"pulls/{key.number}: gh api returned non-JSON for {key.repo}: {exc}",
                exit_code=2,
            ) from exc
        state = payload.get("state", "")
        head = payload.get("head", {}) or {}
        base = payload.get("base", {}) or {}
        return PullResult(
            state=state,
            merged_at=payload.get("merged_at"),
            body=payload.get("body") or "",
            head_sha=head.get("sha", ""),
            head_ref=head.get("ref", ""),
            head_repo_full_name=(head.get("repo") or {}).get("full_name", ""),
            base_ref=base.get("ref", ""),
            base_repo_full_name=(base.get("repo") or {}).get("full_name", ""),
        )

    def _raise_for_status_contents(self, key: ContentsKey, rc: int, err: str) -> None:
        err_low = err.lower()
        if "404" in err_low or "not found" in err_low:
            raise FetchError(
                f"contents/{key.path}: canonical file not found at "
                f"{key.repo}/{key.path}@{key.ref} — verify spec or token scope",
                exit_code=2,
            )
        if "403" in err_low or "forbidden" in err_low:
            raise FetchError(
                f"contents/{key.path}: auth insufficient for contents at "
                f"{key.repo}/{key.path}: required Contents:Read "
                f"(token_set={self._token_set})",
                exit_code=2,
            )
        raise FetchError(
            f"contents/{key.path}: gh api failed (rc={rc}) for "
            f"{key.repo}/{key.path}@{key.ref}: {err.strip()[:300]}",
            exit_code=2,
        )

    def _raise_for_status_pull(self, key: PullKey, rc: int, err: str) -> None:
        err_low = err.lower()
        if "404" in err_low or "not found" in err_low:
            raise FetchError(
                f"pulls/{key.number}: paired PR not found at "
                f"{key.repo}#{key.number} — verify paired_pr_url in PR description",
                exit_code=2,
            )
        if "403" in err_low or "forbidden" in err_low:
            raise FetchError(
                f"pulls/{key.number}: auth insufficient for pull request metadata at "
                f"{key.repo}#{key.number}: required Pull requests:Read "
                f"(token_set={self._token_set})",
                exit_code=2,
            )
        raise FetchError(
            f"pulls/{key.number}: gh api failed (rc={rc}) for "
            f"{key.repo}#{key.number}: {err.strip()[:300]}",
            exit_code=2,
        )


def _run(cmd: list[str]) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise FetchError(
            f"gh CLI not found (PATH issue?): {exc}",
            exit_code=2,
        ) from exc
    return proc.returncode, proc.stdout, proc.stderr
