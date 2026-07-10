"""Transient-retry contract for the ADR-0031 cross-repo enum guard's gh wrapper.

The guard turned red twice on 2026-07-10 for reasons that said nothing about drift:
`os-type` mapping ERROR with `gh: HTTP 502`. A single-attempt fetch makes every PR
hostage to GitHub's 5xx rate. These tests pin the fix *and* the boundary of the fix:
transient statuses are retried, verdict-bearing statuses (403/404) are not, so the
fail-closed contract in ADR-0031 §I3 ("auth errors NEVER silently pass as drift-free")
still holds.
"""
from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path

import pytest

LIB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB_ROOT))

from lib.cross_repo_enum.fetcher import (  # noqa: E402
    ContentsKey,
    FetchError,
    Fetcher,
    is_transient,
)
from lib.cross_repo_enum import fetcher as fetcher_mod  # noqa: E402


class _FakeProc:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _contents_payload(text: str) -> str:
    return json.dumps(
        {
            "encoding": "base64",
            "content": base64.b64encode(text.encode()).decode(),
            "sha": "deadbeef",
        }
    )


@pytest.fixture
def spy(monkeypatch):
    """Replace subprocess.run and sleep; record calls."""
    calls: list[list[str]] = []
    slept: list[float] = []
    queue: list[_FakeProc] = []

    def fake_run(cmd, **_kwargs):
        calls.append(cmd)
        return queue.pop(0)

    monkeypatch.setattr(fetcher_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(fetcher_mod.time, "sleep", lambda s: slept.append(s))
    return {"calls": calls, "slept": slept, "queue": queue}


KEY = ContentsKey(repo="Halildeu/platform-backend", path="a/B.java", ref="main")


class TestTransientClassification:
    @pytest.mark.parametrize(
        "stderr",
        [
            "gh: HTTP 502",
            "gh: HTTP 500 Internal Server Error",
            "gh: HTTP 503",
            "gh: HTTP 504",
            "gh: HTTP 429",
            "API rate limit exceeded",
            "connection reset by peer",
            "dial tcp: i/o timeout",
            "unexpected EOF",
            "net/http: TLS handshake timeout",
        ],
    )
    def test_transient_statuses_are_retryable(self, stderr):
        assert is_transient(stderr) is True

    @pytest.mark.parametrize(
        "stderr",
        [
            "gh: Not Found (HTTP 404)",
            "gh: HTTP 403 Forbidden",
            "gh: Resource not accessible by integration (HTTP 403)",
            "gh: Validation Failed (HTTP 422)",
            "gh: HTTP 401 Bad credentials",
        ],
    )
    def test_verdict_bearing_statuses_are_not_retryable(self, stderr):
        # These carry meaning (missing spec target / insufficient token scope) and must
        # stay fail-closed on the first attempt.
        assert is_transient(stderr) is False

    def test_secondary_rate_limit_403_is_terminal_not_transient(self):
        # GitHub serves its *secondary* rate limit as HTTP 403. A message-first
        # classifier would have matched "rate limit" and retried a response that our
        # own error mapping reports as an auth failure. Status wins over message.
        stderr = (
            "gh: You have exceeded a secondary rate limit. "
            "Please wait a few minutes before you try again. (HTTP 403)"
        )
        assert is_transient(stderr) is False

    def test_primary_rate_limit_429_is_transient(self):
        assert is_transient("gh: API rate limit exceeded (HTTP 429)") is True

    def test_rate_limit_without_a_status_falls_back_to_the_message(self):
        # No HTTP status in the text at all -> fall back to transport-level matching.
        assert is_transient("API rate limit exceeded") is True

    def test_unknown_status_is_not_retried(self):
        # A status we have not classified must not be optimistically retried.
        assert is_transient("gh: HTTP 418 I'm a teapot") is False


class TestRetryBehaviour:
    def test_transient_failure_then_success(self, spy):
        spy["queue"].extend(
            [
                _FakeProc(1, stderr="gh: HTTP 502"),
                _FakeProc(0, stdout=_contents_payload("enum X { A }")),
            ]
        )
        result = Fetcher().get_contents(KEY)
        assert result.text == "enum X { A }"
        assert len(spy["calls"]) == 2, "the 502 must be retried"
        assert spy["slept"] == [2.0], "backoff applied between attempts"

    def test_not_found_is_never_retried(self, spy):
        spy["queue"].append(_FakeProc(1, stderr="gh: Not Found (HTTP 404)"))
        with pytest.raises(FetchError, match="canonical file not found"):
            Fetcher().get_contents(KEY)
        assert len(spy["calls"]) == 1, "a 404 is a verdict, not a hiccup"
        assert spy["slept"] == []

    def test_forbidden_is_never_retried(self, spy):
        spy["queue"].append(_FakeProc(1, stderr="gh: HTTP 403 Forbidden"))
        with pytest.raises(FetchError, match="auth insufficient"):
            Fetcher().get_contents(KEY)
        assert len(spy["calls"]) == 1
        assert spy["slept"] == []

    def test_secondary_rate_limit_403_is_not_retried_end_to_end(self, spy):
        spy["queue"].append(
            _FakeProc(1, stderr="gh: exceeded a secondary rate limit (HTTP 403)")
        )
        with pytest.raises(FetchError, match="auth insufficient"):
            Fetcher().get_contents(KEY)
        assert len(spy["calls"]) == 1, "a 403 stays terminal even when it says 'rate limit'"
        assert spy["slept"] == []

    def test_persistent_transient_failure_exhausts_and_fails_closed(self, spy):
        spy["queue"].extend([_FakeProc(1, stderr="gh: HTTP 502")] * 3)
        with pytest.raises(FetchError) as excinfo:
            Fetcher().get_contents(KEY)
        assert len(spy["calls"]) == 3, "attempts are bounded"
        assert spy["slept"] == [2.0, 5.0], "escalating backoff"
        # The check must not read as a one-off flake when it is not.
        assert "transient failure persisted across 3 attempts" in str(excinfo.value)
        assert excinfo.value.exit_code == 2

    def test_success_on_first_attempt_does_not_sleep(self, spy):
        spy["queue"].append(_FakeProc(0, stdout=_contents_payload("enum X { A }")))
        Fetcher().get_contents(KEY)
        assert len(spy["calls"]) == 1
        assert spy["slept"] == []

    def test_cache_prevents_a_second_fetch(self, spy):
        spy["queue"].append(_FakeProc(0, stdout=_contents_payload("enum X { A }")))
        f = Fetcher()
        f.get_contents(KEY)
        f.get_contents(KEY)
        assert len(spy["calls"]) == 1, "process-scoped cache still holds"


def test_subprocess_is_the_real_one_outside_tests():
    # Guards against a monkeypatch leaking across the module.
    assert fetcher_mod.subprocess.run is subprocess.run
