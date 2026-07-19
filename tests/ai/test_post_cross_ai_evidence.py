#!/usr/bin/env python3
"""Unit tests for secret-safe Cross-AI evidence posting validation."""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/ai/post_cross_ai_evidence.py"
SPEC = importlib.util.spec_from_file_location("post_cross_ai_evidence", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def trusted_source_digests() -> dict[str, str]:
    return {
        key: hashlib.sha256((ROOT / relative_path).read_bytes()).hexdigest()
        for key, relative_path in MODULE.TRUSTED_SOURCE_PATHS.items()
    }


def evidence() -> dict:
    response = "## P0\nNone\n## P1\nNone\n## P2\nNone\nVERDICT: AGREE"
    return {
        "schema": "cross-ai-provider-evidence/v4",
        "provider": "openai",
        "requested_model": "gpt-5.6-sol",
        "actual_model": "not-provider-attested",
        "execution_profile": "codex-exec-ephemeral-read-only-exact-scope-no-tools-v2",
        "execution_provenance": {
            "schema": "codex-native-execution-provenance/v2",
            "thread_id": "019f7785-c66d-7992-a21a-d4097d9eb3f9",
            "cli_version": "0.144.1",
            "cli_native_target": "codex-linux-x64",
            "cli_native_sha256": "a96f944d1a596dbfb7fdd84f482be5c50e34b04bb371126840d873e4ebf26902",
            "trust_root": "repo-pinned-codex-native-sha256-v1",
            "stderr_classification": "empty",
            "source_trust_root": "trusted-base-cross-ai-sources-sha256-v1",
            "trusted_base_sha": "a" * 40,
            **trusted_source_digests(),
            "pii_review_status": "no-sensitive-pii",
            "pii_attestation_sha256": "e" * 64,
        },
        "base_tip_sha": "a" * 40,
        "base_sha": "b" * 40,
        "head_sha": "c" * 40,
        "scope_sha256": "d" * 64,
        "verdict": "AGREE",
        "response_sha256": hashlib.sha256(response.encode()).hexdigest(),
        "response": response,
    }


class EvidenceValidationTests(unittest.TestCase):
    @staticmethod
    def validate(text: str) -> tuple[dict, str]:
        return MODULE.validate_evidence_text(
            text,
            trusted_source_loader=lambda _trusted_base_sha: trusted_source_digests(),
            pr_base_sha="a" * 40,
            ancestor_checker=lambda _trusted_base_sha, _pr_base_sha: True,
        )

    def assert_rejected(self, payload: dict) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.validate(json.dumps(payload))

    def test_accepts_exact_builder_schema_and_digest(self) -> None:
        text = json.dumps(evidence(), separators=(",", ":"))
        parsed, digest = self.validate(text)
        self.assertEqual(parsed["provider"], "openai")
        self.assertEqual(digest, hashlib.sha256(text.encode()).hexdigest())

    def test_status_ledger_binds_pr_head_digest_thread_and_verdict(self) -> None:
        payload = evidence()
        digest = "f" * 64
        status = MODULE.status_ledger_payload(
            payload,
            digest,
            2638,
            "https://github.com/Halildeu/platform-k8s-gitops/pull/2638",
        )
        self.assertEqual(status["state"], "success")
        self.assertEqual(status["context"], f"cross-ai/evidence/{digest}")
        self.assertEqual(
            status["description"],
            "v4 openai AGREE pr=2638 "
            "thread=019f7785-c66d-7992-a21a-d4097d9eb3f9",
        )
        self.assertEqual(
            status["target_url"],
            "https://github.com/Halildeu/platform-k8s-gitops/pull/2638",
        )

    def test_publication_invalidates_audit_before_comment_and_retriggers_it(self) -> None:
        payload = evidence()
        text = json.dumps(payload, separators=(",", ":"))
        digest = hashlib.sha256(text.encode()).hexdigest()
        calls: list[list[str]] = []
        status_contexts: list[str] = []

        def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            if "/statuses/" in command[2]:
                posted = json.loads(str(kwargs["input"]))
                status_contexts.append(posted["context"])
                identifier = 11 if posted["context"].startswith("cross-ai/evidence/") else 10
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=json.dumps({
                        **posted,
                        "id": identifier,
                        "url": f"https://api.github.com/repos/Halildeu/platform-k8s-gitops/statuses/{identifier}",
                        "creator": {"login": "Halildeu"},
                    }),
                )
            if "/comments" in command[2]:
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=json.dumps({
                        "url": "https://api.github.com/repos/Halildeu/platform-k8s-gitops/issues/comments/1",
                        "created_at": "2026-07-19T18:00:01Z",
                        "updated_at": "2026-07-19T18:00:01Z",
                    }),
                )
            posted = json.loads(str(kwargs["input"]))
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps({
                    "body": posted["body"],
                    "state": "open",
                    "head": {"sha": payload["head_sha"]},
                }),
            )

        result = MODULE.publish_evidence(
            repo="Halildeu/platform-k8s-gitops",
            issue_number=2638,
            evidence=payload,
            evidence_text=text,
            body_sha256=digest,
            pr_url="https://github.com/Halildeu/platform-k8s-gitops/pull/2638",
            pr_body="## Cross-AI\nConsultation mode: single\n",
            runner=runner,
        )
        self.assertEqual(
            calls[0][2],
            f"repos/Halildeu/platform-k8s-gitops/statuses/{payload['head_sha']}",
        )
        self.assertEqual(calls[1][2], "repos/Halildeu/platform-k8s-gitops/pulls/2638")
        self.assertEqual(calls[2][2], calls[0][2])
        self.assertEqual(
            status_contexts,
            ["cross-ai-audit", f"cross-ai/evidence/{digest}"],
        )
        self.assertIn("/comments", calls[3][2])
        self.assertEqual(calls[4][2], "repos/Halildeu/platform-k8s-gitops/pulls/2638")
        self.assertEqual(result["ledger_context"], f"cross-ai/evidence/{digest}")
        self.assertEqual(
            result["audit_recheck_marker"],
            f"<!-- cross-ai-audit-recheck:10:11:{digest} -->",
        )

    def test_invalidation_failure_never_creates_binding_evidence(self) -> None:
        payload = evidence()
        text = json.dumps(payload, separators=(",", ":"))
        calls: list[list[str]] = []

        def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            return subprocess.CompletedProcess(command, 1, stdout="")

        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):
                MODULE.publish_evidence(
                    repo="Halildeu/platform-k8s-gitops",
                    issue_number=2638,
                    evidence=payload,
                    evidence_text=text,
                    body_sha256=hashlib.sha256(text.encode()).hexdigest(),
                    pr_url="https://github.com/Halildeu/platform-k8s-gitops/pull/2638",
                    pr_body="body",
                    runner=runner,
                )
        self.assertEqual(len(calls), 1)
        self.assertIn("/statuses/", calls[0][2])

    def test_ledger_failure_after_invalidation_never_creates_comment(self) -> None:
        payload = evidence()
        text = json.dumps(payload, separators=(",", ":"))
        calls: list[list[str]] = []

        def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            posted = json.loads(str(kwargs["input"]))
            if posted.get("context") == "cross-ai-audit":
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=json.dumps({
                        **posted,
                        "id": 1,
                        "url": "https://api.github.com/statuses/1",
                        "creator": {"login": "Halildeu"},
                    }),
                )
            if "/pulls/" in command[2]:
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=json.dumps({
                        "body": posted["body"],
                        "state": "open",
                        "head": {"sha": payload["head_sha"]},
                    }),
                )
            return subprocess.CompletedProcess(command, 1, stdout="")

        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):
                MODULE.publish_evidence(
                    repo="Halildeu/platform-k8s-gitops",
                    issue_number=2638,
                    evidence=payload,
                    evidence_text=text,
                    body_sha256=hashlib.sha256(text.encode()).hexdigest(),
                    pr_url="https://github.com/Halildeu/platform-k8s-gitops/pull/2638",
                    pr_body="body",
                    runner=runner,
                )
        self.assertEqual(len(calls), 3)
        self.assertIn("/statuses/", calls[0][2])
        self.assertIn("/pulls/", calls[1][2])
        self.assertIn("/statuses/", calls[2][2])

    def test_comment_failure_occurs_after_durable_ledger(self) -> None:
        payload = evidence()
        text = json.dumps(payload, separators=(",", ":"))
        digest = hashlib.sha256(text.encode()).hexdigest()
        calls: list[list[str]] = []

        def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            if "/statuses/" in command[2]:
                posted = json.loads(str(kwargs["input"]))
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=json.dumps({
                        **posted,
                        "id": len(calls),
                        "url": "https://api.github.com/repos/Halildeu/platform-k8s-gitops/statuses/2",
                        "creator": {"login": "Halildeu"},
                    }),
                )
            if "/pulls/" in command[2]:
                posted = json.loads(str(kwargs["input"]))
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=json.dumps({
                        "body": posted["body"],
                        "state": "open",
                        "head": {"sha": payload["head_sha"]},
                    }),
                )
            return subprocess.CompletedProcess(command, 1, stdout="")

        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):
                MODULE.publish_evidence(
                    repo="Halildeu/platform-k8s-gitops",
                    issue_number=2638,
                    evidence=payload,
                    evidence_text=text,
                    body_sha256=digest,
                    pr_url="https://github.com/Halildeu/platform-k8s-gitops/pull/2638",
                    pr_body="body",
                    runner=runner,
                )
        self.assertEqual(len(calls), 4)
        self.assertIn("/statuses/", calls[0][2])
        self.assertIn("/pulls/", calls[1][2])
        self.assertIn("/statuses/", calls[2][2])
        self.assertIn("/comments", calls[3][2])

    def test_body_recheck_failure_leaves_pending_invalidation_after_comment(self) -> None:
        payload = evidence()
        text = json.dumps(payload, separators=(",", ":"))
        digest = hashlib.sha256(text.encode()).hexdigest()
        calls: list[list[str]] = []

        def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            if "/statuses/" in command[2]:
                posted = json.loads(str(kwargs["input"]))
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=json.dumps({
                        **posted,
                        "id": len(calls),
                        "url": f"https://api.github.com/statuses/{len(calls)}",
                        "creator": {"login": "Halildeu"},
                    }),
                )
            if "/comments" in command[2]:
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=json.dumps({
                        "url": "https://api.github.com/comments/1",
                        "created_at": "2026-07-19T18:00:01Z",
                        "updated_at": "2026-07-19T18:00:01Z",
                    }),
                )
            if "/pulls/" in command[2] and len(calls) == 2:
                posted = json.loads(str(kwargs["input"]))
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=json.dumps({
                        "body": posted["body"],
                        "state": "open",
                        "head": {"sha": payload["head_sha"]},
                    }),
                )
            return subprocess.CompletedProcess(command, 1, stdout="")

        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):
                MODULE.publish_evidence(
                    repo="Halildeu/platform-k8s-gitops",
                    issue_number=2638,
                    evidence=payload,
                    evidence_text=text,
                    body_sha256=digest,
                    pr_url="https://github.com/Halildeu/platform-k8s-gitops/pull/2638",
                    pr_body="body",
                    runner=runner,
                )
        self.assertEqual(len(calls), 5)
        self.assertIn("/pulls/", calls[1][2])
        self.assertIn("/statuses/", calls[2][2])
        self.assertIn("/comments", calls[3][2])
        self.assertIn("/pulls/", calls[4][2])

    def test_invalid_pr_body_fails_before_any_github_mutation(self) -> None:
        payload = evidence()
        text = json.dumps(payload, separators=(",", ":"))
        calls: list[list[str]] = []

        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):
                MODULE.publish_evidence(
                    repo="Halildeu/platform-k8s-gitops",
                    issue_number=2638,
                    evidence=payload,
                    evidence_text=text,
                    body_sha256=hashlib.sha256(text.encode()).hexdigest(),
                    pr_url="https://github.com/Halildeu/platform-k8s-gitops/pull/2638",
                    pr_body=None,
                    runner=lambda command, **_kwargs: calls.append(command),
                )
        self.assertEqual(calls, [])

    def test_trusted_workflow_can_clear_pending_audit_only_after_success(self) -> None:
        workflow = (
            ROOT / ".github/workflows/gate-cross-ai-audit.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("statuses: write", workflow)
        self.assertIn("Mark exact-head Cross-AI audit status current", workflow)
        self.assertIn("scripts/ai/complete_cross_ai_audit_status.py", workflow)

    def test_accepts_exact_spark_model(self) -> None:
        payload = evidence()
        payload["requested_model"] = "gpt-5.3-codex-spark"
        payload["actual_model"] = "not-provider-attested"
        parsed, _ = self.validate(
            json.dumps(payload, separators=(",", ":"))
        )
        self.assertEqual(parsed["requested_model"], "gpt-5.3-codex-spark")

    def test_accepts_historical_producer_digests_from_evidence_trusted_base(self) -> None:
        payload = evidence()
        historical_digests = {
            key: str(index) * 64
            for index, key in enumerate(MODULE.TRUSTED_SOURCE_PATHS, start=1)
        }
        payload["execution_provenance"].update(historical_digests)
        requested_shas: list[str] = []

        def load_historical(trusted_base_sha: str) -> dict[str, str]:
            requested_shas.append(trusted_base_sha)
            return historical_digests

        parsed, _ = MODULE.validate_evidence_text(
            json.dumps(payload, separators=(",", ":")),
            trusted_source_loader=load_historical,
            pr_base_sha="a" * 40,
            ancestor_checker=lambda _trusted_base_sha, _pr_base_sha: True,
        )
        self.assertEqual(
            parsed["execution_provenance"]["review_harness_sha256"], "1" * 64
        )
        self.assertEqual(requested_shas, ["a" * 40])

    def test_rejects_trusted_producer_commit_outside_pr_base_ancestry(self) -> None:
        payload = evidence()
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):
                MODULE.validate_evidence_text(
                    json.dumps(payload, separators=(",", ":")),
                    trusted_source_loader=lambda _trusted_base_sha: trusted_source_digests(),
                    pr_base_sha="b" * 40,
                    ancestor_checker=lambda _trusted_base_sha, _pr_base_sha: False,
                )

    def test_rejects_extra_schema_key(self) -> None:
        payload = evidence()
        payload["untrusted"] = True
        self.assert_rejected(payload)

    def test_rejects_response_digest_mismatch(self) -> None:
        payload = evidence()
        payload["response_sha256"] = "f" * 64
        self.assert_rejected(payload)

    def test_rejects_non_isolated_codex_execution_profile(self) -> None:
        payload = evidence()
        payload["execution_profile"] = "codex-current-chat"
        self.assert_rejected(payload)

    def test_rejects_provider_model_mismatch_before_post(self) -> None:
        payload = evidence()
        payload["actual_model"] = "auto"
        self.assert_rejected(payload)

    def test_rejects_requested_model_repeated_as_provider_attested_actual(self) -> None:
        payload = evidence()
        payload["actual_model"] = payload["requested_model"]
        self.assert_rejected(payload)

    def test_rejects_unpinned_native_binary_provenance(self) -> None:
        payload = evidence()
        payload["execution_provenance"]["cli_native_sha256"] = "f" * 64
        self.assert_rejected(payload)

    def test_rejects_untrusted_producer_or_missing_pii_gate(self) -> None:
        mutations = (
            ("review_harness_sha256", "f" * 64),
            ("pii_attester_sha256", "f" * 64),
            ("trusted_base_sha", "f" * 40),
            ("pii_review_status", "tracked_pending"),
            ("pii_attestation_sha256", "not-a-digest"),
        )
        for key, value in mutations:
            with self.subTest(key=key):
                payload = evidence()
                payload["execution_provenance"][key] = value
                self.assert_rejected(payload)

    def test_rejects_null_digest_for_unknown_native_tuple(self) -> None:
        payload = evidence()
        payload["execution_provenance"]["cli_version"] = "99.99.99"
        payload["execution_provenance"]["cli_native_target"] = "unknown-target"
        payload["execution_provenance"]["cli_native_sha256"] = None
        self.assert_rejected(payload)

    def test_rejects_sensitive_response_before_gh_invocation(self) -> None:
        for value in (
            "person@example.com",
            "+90 532 123 45 67",
            "-----BEGIN " + "PRIVATE KEY-----",
            "Authorization: " + "Bearer " + "abcdefghijklmnop",
            "Bearer " + "abcdefghijklmnop",
            "eyJ" + "a" * 16 + "." + "b" * 16 + "." + "c" * 16,
            "AKIA" + "A" * 16,
            "ghp_" + "a" * 30,
            "sk-" + "a" * 30,
            "password=" + "a" * 16,
            "secret_access_key=" + "a" * 32,
            "service_account_key=" + "a" * 32,
            "webhook_url=https://example.invalid/" + "a" * 20,
            "Cookie: session=" + "a" * 20,
        ):
            payload = evidence()
            payload["response"] = (
                f"P0\nNone\nP1\nNone\nP2\n{value}\nVERDICT: AGREE"
            )
            payload["response_sha256"] = hashlib.sha256(
                payload["response"].encode("utf-8")
            ).hexdigest()
            with self.subTest(value=value):
                self.assert_rejected(payload)


if __name__ == "__main__":
    unittest.main()
