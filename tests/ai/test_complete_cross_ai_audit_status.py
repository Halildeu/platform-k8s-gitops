#!/usr/bin/env python3
"""Regression tests for Cross-AI audit generation completion."""

from __future__ import annotations

import importlib.util
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
    digest = "b" * 64
    url = f"https://github.com/{repo}/pull/{issue}"

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.event_path = self.root / "event.json"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def body(self, pending_id: int = 10, ledger_id: int = 11) -> str:
        return (
            "Consultation mode: single\n\n"
            f"<!-- cross-ai-audit-recheck:{pending_id}:{ledger_id}:{self.digest} -->\n"
        )

    def write_event(self, body: str | None = None) -> str:
        value = self.body() if body is None else body
        self.event_path.write_text(
            json.dumps({
                "pull_request": {
                    "number": self.issue,
                    "state": "open",
                    "html_url": self.url,
                    "body": value,
                    "head": {"sha": self.head},
                    "base": {"sha": self.base},
                }
            }),
            encoding="utf-8",
        )
        return value

    def current_pr(
        self,
        body: str,
        head: str | None = None,
        base: str | None = None,
    ) -> dict:
        return {
            "state": "open",
            "html_url": self.url,
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
            [[self.pending(), self.ledger()]],
            success,
            self.current_pr(body),
            [[self.pending(), self.ledger(), success]],
        ])
        self.assertEqual(result["action"], "marked-current")
        self.assertEqual(result["generation"], 10)
        self.assertEqual(len(calls), 5)
        self.assertIn(f"statuses/{self.head}", calls[2][2])

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
            [[self.pending(), self.ledger(), current_success]],
        ])
        self.assertEqual(result["action"], "already-current")
        self.assertEqual(len(calls), 2)

    def test_new_owner_generation_after_validation_restores_pending(self) -> None:
        old_body = self.write_event()
        new_body = self.body(20, 21)
        success = {
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
            self.current_pr(old_body),
            [[self.pending(), self.ledger()]],
            success,
            self.current_pr(new_body),
            [[
                self.pending(),
                self.ledger(),
                self.pending(identifier=20),
                self.ledger(identifier=21),
                success,
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

    def test_force_push_after_success_marks_live_head_pending(self) -> None:
        body = self.write_event()
        live_head = "c" * 40
        success = {
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
            "description": "Cross-AI audit retry required generation=10",
            "target_url": self.url,
            "creator": {"login": "github-actions[bot]"},
        }
        responses = [
            self.current_pr(body),
            [[self.pending(), self.ledger()]],
            success,
            self.current_pr(body, head=live_head),
            [[self.pending(), self.ledger(), success]],
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
            [[self.pending(), self.ledger(), retry]],
            success,
            self.current_pr(body),
            [[self.pending(), self.ledger(), retry, success]],
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


if __name__ == "__main__":
    unittest.main()
