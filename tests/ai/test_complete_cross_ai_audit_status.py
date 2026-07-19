#!/usr/bin/env python3
"""Regression tests for Cross-AI audit generation completion."""

from __future__ import annotations

import importlib.util
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/ai/complete_cross_ai_audit_status.py"
SPEC = importlib.util.spec_from_file_location("complete_cross_ai_audit_status", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CompleteCrossAiAuditStatusTests(unittest.TestCase):
    repo = "Halildeu/platform-k8s-gitops"
    issue = 2638
    head = "a" * 40
    base = "d" * 40
    evidence_body = '{"schema":"cross-ai-provider-evidence/v4"}'
    digest = hashlib.sha256(evidence_body.encode("utf-8")).hexdigest()
    comment_id = 99
    url = f"https://github.com/{repo}/pull/{issue}"
    evidence_ref = (
        f"https://api.github.com/repos/{repo}/issues/comments/{comment_id}"
    )

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.event_path = self.root / "event.json"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def body(
        self,
        pending_id: int = 10,
        ledger_id: int = 11,
        review_head: str | None = None,
    ) -> str:
        return (
            "Consultation mode: single\n"
            f"Consultation commit: {review_head or self.head}\n"
            "Codex receipt: provider=openai; requested=gpt-5.6-sol; "
            "actual=not-provider-attested; "
            f"base_tip={self.base}; base={'e' * 40}; "
            f"head={review_head or self.head}; scope={'f' * 64}; "
            "execution=codex-exec-ephemeral-read-only-exact-scope-no-tools-v2; "
            f"verdict=AGREE; ref={self.evidence_ref}; sha256={self.digest}\n\n"
            f"<!-- cross-ai-audit-recheck:{pending_id}:{ledger_id}:{self.digest} -->\n"
        )

    def write_event(self, body: str | None = None, *, draft: bool = False) -> str:
        value = self.body() if body is None else body
        self.event_path.write_text(
            json.dumps({
                "pull_request": {
                    "number": self.issue,
                    "state": "open",
                    "html_url": self.url,
                    "draft": draft,
                    "body": value,
                    "head": {"sha": self.head},
                    "base": {"sha": self.base},
                }
            }),
            encoding="utf-8",
        )
        return value

    def write_comment_event(
        self,
        action: str,
        comment_id: int,
        *,
        body: str = "routine comment",
        previous_body: str | None = None,
    ) -> None:
        event = {
                "action": action,
                "comment": {
                    "id": comment_id,
                    "body": body,
                    "user": {"login": "Halildeu"},
                    "author_association": "OWNER",
                },
                "issue": {
                    "number": self.issue,
                    "pull_request": {
                        "url": f"https://api.github.com/repos/{self.repo}/pulls/{self.issue}"
                    },
                },
            }
        if previous_body is not None:
            event["changes"] = {"body": {"from": previous_body}}
        self.event_path.write_text(json.dumps(event), encoding="utf-8")

    def current_pr(
        self,
        body: str,
        head: str | None = None,
        base: str | None = None,
        draft: bool = False,
    ) -> dict:
        return {
            "state": "open",
            "html_url": self.url,
            "draft": draft,
            "body": body,
            "head": {"sha": head or self.head},
            "base": {"sha": base or self.base},
        }

    def pending(self, identifier: int = 10) -> dict:
        return {
            "id": identifier,
            "state": "pending",
            "context": "cross-ai-audit",
            "description": "Cross-AI evidence changed; trusted audit required",
            "target_url": self.url,
            "creator": {"login": "Halildeu"},
        }

    def ledger(self, identifier: int = 11) -> dict:
        return {
            "id": identifier,
            "state": "failure",
            "context": f"cross-ai/evidence/{self.digest}",
            "target_url": self.url,
            "creator": {"login": "Halildeu"},
        }

    def comment(self, body: str | None = None, updated_at: str | None = None) -> dict:
        created_at = "2026-07-19T18:00:00Z"
        return {
            "id": self.comment_id,
            "url": self.evidence_ref,
            "issue_url": f"https://api.github.com/repos/{self.repo}/issues/{self.issue}",
            "body": self.evidence_body if body is None else body,
            "user": {"login": "Halildeu"},
            "author_association": "OWNER",
            "created_at": created_at,
            "updated_at": created_at if updated_at is None else updated_at,
        }

    def execute(self, responses: list[object]) -> tuple[dict, list[list[str]]]:
        calls: list[list[str]] = []

        def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            response = responses.pop(0)
            return subprocess.CompletedProcess(
                command, 0, stdout=json.dumps(response), stderr=""
            )

        with (
            mock.patch.object(MODULE.shutil, "which", return_value="/usr/bin/gh"),
            mock.patch.object(MODULE.subprocess, "run", side_effect=runner),
        ):
            result = MODULE.complete_status(self.repo, self.issue, self.event_path)
        return result, calls

    def test_marks_only_exact_current_pending_generation_success(self) -> None:
        body = self.write_event()
        success = {
            "id": 12,
            "state": "success",
            "context": "cross-ai-audit",
            "description": "Trusted Cross-AI audit passed generation=10",
            "target_url": self.url,
            "creator": {"login": "github-actions[bot]"},
        }
        result, calls = self.execute([
            self.current_pr(body),
            self.comment(),
            [[self.pending(), self.ledger()]],
            self.current_pr(body),
            [[self.pending(), self.ledger()]],
            self.comment(),
            success,
        ])
        self.assertEqual(result["action"], "marked-current")
        self.assertEqual(result["generation"], 10)
        self.assertEqual(len(calls), 7)
        self.assertIn(f"statuses/{self.head}", calls[-1][2])

    def test_draft_generation_stays_pending_until_ready_for_review(self) -> None:
        body = self.write_event(draft=True)
        result, calls = self.execute([
            self.current_pr(body, draft=True),
            self.comment(),
            [[self.pending(), self.ledger()]],
        ])
        self.assertEqual(result["action"], "deferred-draft")
        self.assertEqual(result["generation"], 10)
        self.assertEqual(len(calls), 3)
        self.assertFalse(
            any(f"statuses/{self.head}" in token for call in calls for token in call)
        )

    def test_publication_lock_never_completes_generation(self) -> None:
        body = (
            self.body()
            + f"\n<!-- cross-ai-publication-lock:{self.digest}:{'b' * 64} -->\n"
        )
        self.write_event(body)
        retry = {
            "id": 40,
            "state": "pending",
            "context": "cross-ai-audit",
            "description": "Cross-AI audit retry required generation=10",
            "target_url": self.url,
            "creator": {"login": "github-actions[bot]"},
        }
        with (
            mock.patch.object(MODULE.shutil, "which", return_value="/usr/bin/gh"),
            mock.patch.object(
                MODULE.subprocess,
                "run",
                side_effect=[
                    subprocess.CompletedProcess(
                        ["gh"], 0, stdout=json.dumps(self.current_pr(body)), stderr=""
                    ),
                    subprocess.CompletedProcess(
                        ["gh"], 0, stdout=json.dumps(retry), stderr=""
                    ),
                ],
            ),
            self.assertRaises(SystemExit),
        ):
            MODULE.complete_status(self.repo, self.issue, self.event_path)

    def test_stale_event_body_or_force_push_cannot_clear_pending(self) -> None:
        event_body = self.write_event()
        for current in (
            self.current_pr(event_body + "changed\n"),
            self.current_pr(event_body, head="c" * 40),
            self.current_pr(event_body, base="e" * 40),
        ):
            with self.subTest(current=current):
                with (
                    mock.patch.object(MODULE.shutil, "which", return_value="/usr/bin/gh"),
                    mock.patch.object(
                        MODULE.subprocess,
                        "run",
                        return_value=subprocess.CompletedProcess(
                            ["gh"], 0, stdout=json.dumps(current), stderr=""
                        ),
                    ),
                    self.assertRaises(SystemExit),
                ):
                    MODULE.complete_status(self.repo, self.issue, self.event_path)

    def test_force_push_before_validation_marks_live_head_pending(self) -> None:
        event_body = self.write_event()
        live_head = "c" * 40
        retry = {
            "id": 40,
            "state": "pending",
            "context": "cross-ai-audit",
            "description": "Cross-AI audit retry required generation=10",
            "target_url": self.url,
            "creator": {"login": "github-actions[bot]"},
        }
        responses = [self.current_pr(event_body, head=live_head), retry]
        calls: list[list[str]] = []

        def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            return subprocess.CompletedProcess(
                command, 0, stdout=json.dumps(responses.pop(0)), stderr=""
            )

        with (
            mock.patch.object(MODULE.shutil, "which", return_value="/usr/bin/gh"),
            mock.patch.object(MODULE.subprocess, "run", side_effect=runner),
            self.assertRaises(SystemExit),
        ):
            MODULE.complete_status(self.repo, self.issue, self.event_path)
        self.assertEqual(len(calls), 2)
        self.assertIn(f"statuses/{live_head}", calls[-1][2])

    def test_old_body_without_generation_cannot_override_new_pending(self) -> None:
        body = self.write_event("Consultation mode: single\n")
        with (
            mock.patch.object(MODULE.shutil, "which", return_value="/usr/bin/gh"),
            mock.patch.object(
                MODULE.subprocess,
                "run",
                side_effect=[
                    subprocess.CompletedProcess(
                        ["gh"], 0, stdout=json.dumps(self.current_pr(body)), stderr=""
                    ),
                    subprocess.CompletedProcess(
                        ["gh"], 0, stdout=json.dumps([[self.pending()]]), stderr=""
                    ),
                ],
            ),
            self.assertRaises(SystemExit),
        ):
            MODULE.complete_status(self.repo, self.issue, self.event_path)

    def test_initial_marker_cannot_clear_pending_before_ledger_exists(self) -> None:
        body = self.write_event(self.body(10, 0))
        with (
            mock.patch.object(MODULE.shutil, "which", return_value="/usr/bin/gh"),
            mock.patch.object(
                MODULE.subprocess,
                "run",
                side_effect=[
                    subprocess.CompletedProcess(
                        ["gh"], 0, stdout=json.dumps(self.current_pr(body)), stderr=""
                    ),
                    subprocess.CompletedProcess(
                        ["gh"], 0, stdout=json.dumps([[self.pending()]]), stderr=""
                    ),
                ],
            ),
            self.assertRaises(SystemExit),
        ):
            MODULE.complete_status(self.repo, self.issue, self.event_path)

    def test_ledger_must_be_newer_than_pending_generation(self) -> None:
        for ledger_id in (9, 10):
            with self.subTest(ledger_id=ledger_id):
                body = self.write_event(self.body(10, ledger_id))
                with (
                    mock.patch.object(MODULE.shutil, "which", return_value="/usr/bin/gh"),
                    mock.patch.object(
                        MODULE.subprocess,
                        "run",
                        side_effect=[
                            subprocess.CompletedProcess(
                                ["gh"],
                                0,
                                stdout=json.dumps(self.current_pr(body)),
                                stderr="",
                            ),
                            subprocess.CompletedProcess(
                                ["gh"],
                                0,
                                stdout=json.dumps(self.comment()),
                                stderr="",
                            ),
                            subprocess.CompletedProcess(
                                ["gh"],
                                0,
                                stdout=json.dumps([[
                                    self.pending(),
                                    self.ledger(identifier=ledger_id),
                                ]]),
                                stderr="",
                            ),
                        ],
                    ),
                    self.assertRaises(SystemExit),
                ):
                    MODULE.complete_status(self.repo, self.issue, self.event_path)

    def test_exact_generation_success_is_idempotent(self) -> None:
        body = self.write_event()
        current_success = {
            "id": 12,
            "state": "success",
            "context": "cross-ai-audit",
            "description": "Trusted Cross-AI audit passed generation=10",
            "target_url": self.url,
            "creator": {"login": "github-actions[bot]"},
        }
        result, calls = self.execute([
            self.current_pr(body),
            self.comment(),
            [[self.pending(), self.ledger(), current_success]],
        ])
        self.assertEqual(result["action"], "already-current")
        self.assertEqual(len(calls), 3)

    def test_selected_evidence_edit_before_completion_cannot_clear_pending(self) -> None:
        body = self.write_event()
        with (
            mock.patch.object(MODULE.shutil, "which", return_value="/usr/bin/gh"),
            mock.patch.object(
                MODULE.subprocess,
                "run",
                side_effect=[
                    subprocess.CompletedProcess(
                        ["gh"], 0, stdout=json.dumps(self.current_pr(body)), stderr=""
                    ),
                    subprocess.CompletedProcess(
                        ["gh"],
                        0,
                        stdout=json.dumps(
                            self.comment(
                                body=self.evidence_body + "edited",
                                updated_at="2026-07-19T18:01:00Z",
                            )
                        ),
                        stderr="",
                    ),
                ],
            ),
            self.assertRaises(SystemExit),
        ):
            MODULE.complete_status(self.repo, self.issue, self.event_path)

    def test_noncanonical_selected_receipt_cannot_clear_pending(self) -> None:
        body = self.write_event(
            self.body().replace(
                f"; sha256={self.digest}",
                f"; sha256={self.digest}; extra=forbidden",
            )
        )
        with (
            mock.patch.object(MODULE.shutil, "which", return_value="/usr/bin/gh"),
            mock.patch.object(
                MODULE.subprocess,
                "run",
                return_value=subprocess.CompletedProcess(
                    ["gh"], 0, stdout=json.dumps(self.current_pr(body)), stderr=""
                ),
            ),
            self.assertRaises(SystemExit),
        ):
            MODULE.complete_status(self.repo, self.issue, self.event_path)

    def test_selected_evidence_deleted_before_final_success_never_turns_green(self) -> None:
        body = self.write_event()
        retry = {
            "id": 13,
            "state": "pending",
            "context": "cross-ai-audit",
            "description": "Cross-AI audit retry required generation=10",
            "target_url": self.url,
            "creator": {"login": "github-actions[bot]"},
        }
        responses: list[tuple[int, object]] = [
            (0, self.current_pr(body)),
            (0, self.comment()),
            (0, [[self.pending(), self.ledger()]]),
            (0, self.current_pr(body)),
            (0, [[self.pending(), self.ledger()]]),
            (1, {}),
            (0, retry),
        ]
        calls: list[list[str]] = []

        def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            returncode, response = responses.pop(0)
            return subprocess.CompletedProcess(
                command, returncode, stdout=json.dumps(response), stderr=""
            )

        with (
            mock.patch.object(MODULE.shutil, "which", return_value="/usr/bin/gh"),
            mock.patch.object(MODULE.subprocess, "run", side_effect=runner),
            self.assertRaises(SystemExit),
        ):
            MODULE.complete_status(self.repo, self.issue, self.event_path)
        self.assertEqual(len(calls), 7)
        self.assertEqual(
            sum(
                f"statuses/{self.head}" in token
                for call in calls
                for token in call
            ),
            1,
        )
        self.assertIn(f"statuses/{self.head}", calls[-1][2])

    def test_scope_equivalent_new_head_uses_review_head_generation(self) -> None:
        review_head = "c" * 40
        body = self.write_event(self.body(review_head=review_head))
        success = {
            "id": 12,
            "state": "success",
            "context": "cross-ai-audit",
            "description": "Trusted Cross-AI audit passed generation=10",
            "target_url": self.url,
            "creator": {"login": "github-actions[bot]"},
        }
        result, calls = self.execute([
            self.current_pr(body),
            self.comment(),
            [[self.pending(), self.ledger()]],
            [[]],
            self.current_pr(body),
            [[self.pending(), self.ledger()]],
            [[]],
            self.comment(),
            success,
        ])
        self.assertEqual(result["action"], "marked-current")
        self.assertTrue(
            any(f"commits/{review_head}/statuses" in token for token in calls[2])
        )
        self.assertTrue(
            any(f"commits/{self.head}/statuses" in token for token in calls[3])
        )
        self.assertIn(f"statuses/{self.head}", calls[-1][2])

    def test_new_owner_generation_after_validation_restores_pending(self) -> None:
        old_body = self.write_event()
        new_body = self.body(20, 21)
        retry = {
            "id": 31,
            "state": "pending",
            "context": "cross-ai-audit",
            "description": "Cross-AI audit retry required generation=20",
            "target_url": self.url,
            "creator": {"login": "github-actions[bot]"},
        }
        responses = [
            self.current_pr(old_body),
            self.comment(),
            [[self.pending(), self.ledger()]],
            self.current_pr(new_body),
            [[
                self.pending(),
                self.ledger(),
                self.pending(identifier=20),
                self.ledger(identifier=21),
            ]],
            retry,
        ]
        calls: list[list[str]] = []

        def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            return subprocess.CompletedProcess(
                command, 0, stdout=json.dumps(responses.pop(0)), stderr=""
            )

        with (
            mock.patch.object(MODULE.shutil, "which", return_value="/usr/bin/gh"),
            mock.patch.object(MODULE.subprocess, "run", side_effect=runner),
            self.assertRaises(SystemExit),
        ):
            MODULE.complete_status(self.repo, self.issue, self.event_path)
        self.assertEqual(len(calls), 6)
        self.assertIn(f"statuses/{self.head}", calls[-1][2])

    def test_force_push_before_final_success_marks_live_head_pending(self) -> None:
        body = self.write_event()
        live_head = "c" * 40
        retry = {
            "id": 31,
            "state": "pending",
            "context": "cross-ai-audit",
            "description": "Cross-AI audit retry required generation=10",
            "target_url": self.url,
            "creator": {"login": "github-actions[bot]"},
        }
        responses = [
            self.current_pr(body),
            self.comment(),
            [[self.pending(), self.ledger()]],
            self.current_pr(body, head=live_head),
            [[self.pending(), self.ledger()]],
            retry,
        ]
        calls: list[list[str]] = []

        def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            return subprocess.CompletedProcess(
                command, 0, stdout=json.dumps(responses.pop(0)), stderr=""
            )

        with (
            mock.patch.object(MODULE.shutil, "which", return_value="/usr/bin/gh"),
            mock.patch.object(MODULE.subprocess, "run", side_effect=runner),
            self.assertRaises(SystemExit),
        ):
            MODULE.complete_status(self.repo, self.issue, self.event_path)
        self.assertEqual(len(calls), 6)
        self.assertIn(f"statuses/{live_head}", calls[-1][2])

    def test_trusted_retry_pending_can_resume_exact_owner_generation(self) -> None:
        body = self.write_event()
        retry = {
            "id": 12,
            "state": "pending",
            "context": "cross-ai-audit",
            "description": "Cross-AI audit retry required generation=10",
            "target_url": self.url,
            "creator": {"login": "github-actions[bot]"},
        }
        success = {
            "id": 13,
            "state": "success",
            "context": "cross-ai-audit",
            "description": "Trusted Cross-AI audit passed generation=10",
            "target_url": self.url,
            "creator": {"login": "github-actions[bot]"},
        }
        result, _calls = self.execute([
            self.current_pr(body),
            self.comment(),
            [[self.pending(), self.ledger(), retry]],
            self.current_pr(body),
            [[self.pending(), self.ledger(), retry]],
            self.comment(),
            success,
        ])
        self.assertEqual(result["action"], "marked-current")

    def test_stale_success_with_newer_owner_pending_is_reinvalidated(self) -> None:
        body = self.write_event()
        stale_success = {
            "id": 30,
            "state": "success",
            "context": "cross-ai-audit",
            "description": "Trusted Cross-AI audit passed generation=10",
            "target_url": self.url,
            "creator": {"login": "github-actions[bot]"},
        }
        retry = {
            "id": 31,
            "state": "pending",
            "context": "cross-ai-audit",
            "description": "Cross-AI audit retry required generation=20",
            "target_url": self.url,
            "creator": {"login": "github-actions[bot]"},
        }
        responses = [
            self.current_pr(body),
            self.comment(),
            [[
                self.pending(),
                self.ledger(),
                self.pending(identifier=20),
                stale_success,
            ]],
            retry,
        ]

        def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                command, 0, stdout=json.dumps(responses.pop(0)), stderr=""
            )

        with (
            mock.patch.object(MODULE.shutil, "which", return_value="/usr/bin/gh"),
            mock.patch.object(MODULE.subprocess, "run", side_effect=runner),
            self.assertRaises(SystemExit),
        ):
            MODULE.complete_status(self.repo, self.issue, self.event_path)

    def test_non_owner_or_different_pending_generation_cannot_be_cleared(self) -> None:
        body = self.write_event()
        for pending in (
            {**self.pending(), "creator": {"login": "collaborator"}},
            self.pending(identifier=12),
        ):
            with self.subTest(pending=pending):
                with (
                    mock.patch.object(MODULE.shutil, "which", return_value="/usr/bin/gh"),
                    mock.patch.object(
                        MODULE.subprocess,
                        "run",
                        side_effect=[
                            subprocess.CompletedProcess(
                                ["gh"],
                                0,
                                stdout=json.dumps(self.current_pr(body)),
                                stderr="",
                            ),
                            subprocess.CompletedProcess(
                                ["gh"],
                                0,
                                stdout=json.dumps(self.comment()),
                                stderr="",
                            ),
                            subprocess.CompletedProcess(
                                ["gh"],
                                0,
                                stdout=json.dumps([[pending, self.ledger()]]),
                                stderr="",
                            ),
                        ],
                    ),
                    self.assertRaises(SystemExit),
                ):
                    MODULE.complete_status(self.repo, self.issue, self.event_path)

    def test_non_actions_success_attribution_is_rejected(self) -> None:
        body = self.write_event()
        wrong_success = {
            "id": 12,
            "state": "success",
            "context": "cross-ai-audit",
            "description": "Trusted Cross-AI audit passed generation=10",
            "target_url": self.url,
            "creator": {"login": "Halildeu"},
        }
        with (
            mock.patch.object(MODULE.shutil, "which", return_value="/usr/bin/gh"),
            mock.patch.object(
                MODULE.subprocess,
                "run",
                side_effect=[
                    subprocess.CompletedProcess(
                        ["gh"],
                        0,
                        stdout=json.dumps(self.current_pr(body)),
                        stderr="",
                    ),
                    subprocess.CompletedProcess(
                        ["gh"],
                        0,
                        stdout=json.dumps(self.comment()),
                        stderr="",
                    ),
                    subprocess.CompletedProcess(
                        ["gh"],
                        0,
                        stdout=json.dumps(
                            [[self.pending(), self.ledger(), wrong_success]]
                        ),
                        stderr="",
                    ),
                ],
            ),
            self.assertRaises(SystemExit),
        ):
            MODULE.complete_status(self.repo, self.issue, self.event_path)

    def test_post_completion_selected_comment_mutation_restores_pending(self) -> None:
        body = self.body()
        for action in ("edited", "deleted"):
            with self.subTest(action=action):
                self.write_comment_event(action, self.comment_id)
                retry = {
                    "id": 40,
                    "state": "pending",
                    "context": "cross-ai-audit",
                    "description": "Cross-AI audit retry required generation=10",
                    "target_url": self.url,
                    "creator": {"login": "github-actions[bot]"},
                }
                responses = [self.current_pr(body), retry]
                calls: list[list[str]] = []

                def runner(
                    command: list[str], **_kwargs: object
                ) -> subprocess.CompletedProcess[str]:
                    calls.append(command)
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        stdout=json.dumps(responses.pop(0)),
                        stderr="",
                    )

                with (
                    mock.patch.object(
                        MODULE.shutil, "which", return_value="/usr/bin/gh"
                    ),
                    mock.patch.object(MODULE.subprocess, "run", side_effect=runner),
                ):
                    result = MODULE.guard_comment_mutation(
                        self.repo, self.event_path
                    )
                self.assertEqual(
                    result["action"], "selected-evidence-mutation-guarded"
                )
                self.assertEqual(len(calls), 2)
                self.assertIn(f"statuses/{self.head}", calls[-1][2])

    def test_created_owner_v4_evidence_restores_pending(self) -> None:
        self.write_comment_event(
            "created",
            self.comment_id + 1,
            body=(
                '{"schema":"cross-ai-provider-evidence/v4",'
                '"provider":"openai","verdict":"REVISE"}'
            ),
        )
        retry = {
            "id": 40,
            "state": "pending",
            "context": "cross-ai-audit",
            "description": "Cross-AI audit retry required generation=10",
            "target_url": self.url,
            "creator": {"login": "github-actions[bot]"},
        }
        with (
            mock.patch.object(MODULE.shutil, "which", return_value="/usr/bin/gh"),
            mock.patch.object(
                MODULE.subprocess,
                "run",
                side_effect=[
                    subprocess.CompletedProcess(
                        ["gh"], 0, stdout=json.dumps(self.current_pr(self.body())), stderr=""
                    ),
                    subprocess.CompletedProcess(
                        ["gh"], 0, stdout=json.dumps(retry), stderr=""
                    ),
                ],
            ),
        ):
            result = MODULE.guard_comment_mutation(self.repo, self.event_path)
        self.assertEqual(result["action"], "owner-evidence-comment-guarded")

    def test_created_owner_retired_v3_evidence_restores_pending(self) -> None:
        self.write_comment_event(
            "created",
            self.comment_id + 1,
            body=(
                '{"schema":"cross-ai-provider-evidence/v3",'
                '"provider":"openai","verdict":"AGREE"}'
            ),
        )
        retry = {
            "id": 40,
            "state": "pending",
            "context": "cross-ai-audit",
            "description": "Cross-AI audit retry required generation=10",
            "target_url": self.url,
            "creator": {"login": "github-actions[bot]"},
        }
        with (
            mock.patch.object(MODULE.shutil, "which", return_value="/usr/bin/gh"),
            mock.patch.object(
                MODULE.subprocess,
                "run",
                side_effect=[
                    subprocess.CompletedProcess(
                        ["gh"], 0, stdout=json.dumps(self.current_pr(self.body())), stderr=""
                    ),
                    subprocess.CompletedProcess(
                        ["gh"], 0, stdout=json.dumps(retry), stderr=""
                    ),
                ],
            ),
        ):
            result = MODULE.guard_comment_mutation(self.repo, self.event_path)
        self.assertEqual(result["action"], "owner-evidence-comment-guarded")

    def test_delayed_created_event_for_valid_selected_agree_is_idempotent(self) -> None:
        self.write_comment_event(
            "created",
            self.comment_id,
            body=(
                '{"schema":"cross-ai-provider-evidence/v4",'
                '"provider":"openai","verdict":"AGREE"}'
            ),
        )
        with (
            mock.patch.object(MODULE.shutil, "which", return_value="/usr/bin/gh"),
            mock.patch.object(
                MODULE.subprocess,
                "run",
                side_effect=[
                    subprocess.CompletedProcess(
                        ["gh"], 0, stdout=json.dumps(self.current_pr(self.body())), stderr=""
                    ),
                    subprocess.CompletedProcess(
                        ["gh"], 0, stdout=json.dumps(self.comment()), stderr=""
                    ),
                ],
            ),
        ):
            result = MODULE.guard_comment_mutation(self.repo, self.event_path)
        self.assertEqual(result["action"], "ignored-valid-selected-created")

    def test_post_completion_unselected_comment_mutation_is_ignored(self) -> None:
        self.write_comment_event("edited", self.comment_id + 1)
        calls: list[list[str]] = []

        responses = [self.current_pr(self.body()), self.comment()]

        def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(responses.pop(0)),
                stderr="",
            )

        with (
            mock.patch.object(MODULE.shutil, "which", return_value="/usr/bin/gh"),
            mock.patch.object(MODULE.subprocess, "run", side_effect=runner),
        ):
            result = MODULE.guard_comment_mutation(self.repo, self.event_path)
        self.assertEqual(result["action"], "ignored-valid-unselected-comment")
        self.assertEqual(len(calls), 2)

    def test_unselected_owner_evidence_edit_restores_pending(self) -> None:
        retired = (
            '{"schema":"cross-ai-provider-evidence/v3",'
            '"provider":"openai","verdict":"AGREE"}'
        )
        self.write_comment_event(
            "edited",
            self.comment_id + 1,
            body="evidence fields removed",
            previous_body=retired,
        )
        retry = {
            "id": 40,
            "state": "pending",
            "context": "cross-ai-audit",
            "description": "Cross-AI audit retry required generation=10",
            "target_url": self.url,
            "creator": {"login": "github-actions[bot]"},
        }
        calls: list[list[str]] = []
        responses = [self.current_pr(self.body()), retry]

        def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            return subprocess.CompletedProcess(
                command, 0, stdout=json.dumps(responses.pop(0)), stderr=""
            )

        with (
            mock.patch.object(MODULE.shutil, "which", return_value="/usr/bin/gh"),
            mock.patch.object(MODULE.subprocess, "run", side_effect=runner),
        ):
            result = MODULE.guard_comment_mutation(self.repo, self.event_path)
        self.assertEqual(result["action"], "owner-evidence-comment-guarded")
        self.assertEqual(result["comment_action"], "edited")
        self.assertEqual(len(calls), 2)

    def test_unselected_event_still_guards_previously_mutated_selected_comment(self) -> None:
        self.write_comment_event("edited", self.comment_id + 1)
        retry = {
            "id": 40,
            "state": "pending",
            "context": "cross-ai-audit",
            "description": "Cross-AI audit retry required generation=10",
            "target_url": self.url,
            "creator": {"login": "github-actions[bot]"},
        }
        responses: list[tuple[int, object]] = [
            (0, self.current_pr(self.body())),
            (
                0,
                self.comment(
                    body=self.evidence_body + "edited",
                    updated_at="2026-07-19T18:01:00Z",
                ),
            ),
            (0, retry),
        ]

        def runner(
            command: list[str], **_kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            returncode, payload = responses.pop(0)
            return subprocess.CompletedProcess(
                command,
                returncode,
                stdout=json.dumps(payload),
                stderr="",
            )

        with (
            mock.patch.object(MODULE.shutil, "which", return_value="/usr/bin/gh"),
            mock.patch.object(MODULE.subprocess, "run", side_effect=runner),
        ):
            result = MODULE.guard_comment_mutation(self.repo, self.event_path)
        self.assertEqual(result["action"], "selected-evidence-invalid-guarded")

    def test_comment_mutation_without_selected_evidence_is_ignored(self) -> None:
        self.write_comment_event("edited", self.comment_id + 1)
        with (
            mock.patch.object(MODULE.shutil, "which", return_value="/usr/bin/gh"),
            mock.patch.object(
                MODULE.subprocess,
                "run",
                return_value=subprocess.CompletedProcess(
                    ["gh"],
                    0,
                    stdout=json.dumps(
                        self.current_pr(
                            "Consultation mode: none\n"
                            "Consultation reason: routine documentation\n"
                        )
                    ),
                    stderr="",
                ),
            ),
        ):
            result = MODULE.guard_comment_mutation(self.repo, self.event_path)
        self.assertEqual(result["action"], "ignored-no-selected-evidence")


if __name__ == "__main__":
    unittest.main()
