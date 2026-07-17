#!/usr/bin/env python3
"""Unit tests for deterministic scope safety predicates."""

from __future__ import annotations

import importlib.util
import contextlib
import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/ai/prepare_cross_ai_scope.py"
WORKFLOW_PATH = ROOT / ".github/workflows/gate-cross-ai-audit.yml"
SPEC = importlib.util.spec_from_file_location("prepare_cross_ai_scope", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class BinaryScopeTests(unittest.TestCase):
    def test_rejects_standard_binary_diff_marker(self) -> None:
        patch = b"diff --git a/a.png b/a.png\nBinary files a/a.png and b/a.png differ\n"
        self.assertIsNotNone(MODULE.BINARY_DIFF_RE.search(patch))

    def test_rejects_git_binary_patch_marker(self) -> None:
        patch = b"diff --git a/a.bin b/a.bin\nGIT binary patch\nliteral 3\nabc\n"
        self.assertIsNotNone(MODULE.BINARY_DIFF_RE.search(patch))

    def test_text_diff_does_not_match_binary_marker(self) -> None:
        patch = b"diff --git a/a.txt b/a.txt\n+Binary files are discussed here\n"
        self.assertIsNone(MODULE.BINARY_DIFF_RE.search(patch))


class RedactionTests(unittest.TestCase):
    def test_email_and_turkish_mobile_are_redacted(self) -> None:
        text = "Aday person@example.com ve +90 532 123 45 67"
        redacted = MODULE.EMAIL_RE.sub("<redacted-email>", text)
        redacted = MODULE.TURKISH_PHONE_RE.sub("<redacted-phone>", redacted)
        self.assertEqual(redacted, "Aday <redacted-email> ve <redacted-phone>")


class OutputSafetyTests(unittest.TestCase):
    def test_exclusive_output_rejects_preexisting_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target.patch"
            link = root / "scope.patch"
            link.symlink_to(target)
            with contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit):
                    MODULE.write_exclusive_output(link, b"scope")
            self.assertFalse(target.exists())


class DeterministicDiffTests(unittest.TestCase):
    def test_scope_is_independent_of_caller_columns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.name", "Test"], cwd=repo, check=True
            )
            subprocess.run(
                ["git", "config", "user.email", "test@example.invalid"],
                cwd=repo,
                check=True,
            )
            source = repo / "scope.txt"
            source.write_text("first\n", encoding="utf-8")
            subprocess.run(["git", "add", "scope.txt"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
            base = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            source.write_text("first\nsecond\n", encoding="utf-8")
            subprocess.run(["git", "commit", "-qam", "head"], cwd=repo, check=True)
            head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            previous = os.environ.get("COLUMNS")
            try:
                subprocess.run(
                    ["git", "config", "diff.algorithm", "patience"],
                    cwd=repo,
                    check=True,
                )
                subprocess.run(
                    ["git", "config", "diff.indentHeuristic", "true"],
                    cwd=repo,
                    check=True,
                )
                os.environ["COLUMNS"] = "20"
                narrow = MODULE.run_git_diff(repo, base, head, 100_000)
                subprocess.run(
                    ["git", "config", "diff.algorithm", "histogram"],
                    cwd=repo,
                    check=True,
                )
                subprocess.run(
                    ["git", "config", "diff.indentHeuristic", "false"],
                    cwd=repo,
                    check=True,
                )
                os.environ["COLUMNS"] = "200"
                wide = MODULE.run_git_diff(repo, base, head, 100_000)
            finally:
                if previous is None:
                    os.environ.pop("COLUMNS", None)
                else:
                    os.environ["COLUMNS"] = previous
            self.assertEqual(narrow, wide)


class WorkflowBindingTests(unittest.TestCase):
    def test_changed_files_come_from_git_with_rename_detection_disabled(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        self.assertIn("diff --name-only --no-renames", workflow)
        self.assertNotIn("--jq '.[].filename'", workflow)

    def test_workflow_fetches_complete_history_for_real_merge_base(self) -> None:
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        self.assertIn("fetch-depth: 0", workflow)
        self.assertNotIn("--depth=1000", workflow)


if __name__ == "__main__":
    unittest.main()
