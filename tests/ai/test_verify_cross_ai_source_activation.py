#!/usr/bin/env python3
"""Regression tests for the Cross-AI producer trust activation boundary."""

from __future__ import annotations

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/ai/verify_cross_ai_source_activation.py"
SPEC = importlib.util.spec_from_file_location(
    "verify_cross_ai_source_activation", MODULE_PATH
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SourceActivationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(
            [
                "git", "-C", str(self.repo), "config",
                "user.email", "test@example.invalid",
            ],
            check=True,
        )
        subprocess.run(
            [
                "git", "-C", str(self.repo), "config",
                "user.name", "Cross-AI Test",
            ],
            check=True,
        )
        (self.repo / "README.md").write_text("bootstrap\n", encoding="utf-8")
        self.commit("bootstrap without producer stack")
        self.bootstrap_sha = self.head_sha()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def commit(self, message: str) -> None:
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-q", "-m", message],
            check=True,
        )

    def head_sha(self) -> str:
        return subprocess.check_output(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"], text=True
        ).strip()

    def activate_source_stack(self) -> None:
        for relative_path in MODULE.TRUSTED_SOURCE_PATHS.values():
            target = self.repo / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / relative_path).read_bytes())
        self.commit("activate producer stack")

    def assert_activation_error(self, code: str, sha: str) -> None:
        with self.assertRaisesRegex(MODULE.ActivationError, f"^{code}$"):
            MODULE.verify_activation(self.repo, sha, sha)

    def test_bootstrap_commit_without_producer_stack_cannot_self_attest(self) -> None:
        self.assert_activation_error("trusted_source_unavailable", self.bootstrap_sha)

    def test_activation_commit_binds_checkout_to_all_trusted_sources(self) -> None:
        self.activate_source_stack()
        activation_sha = self.head_sha()
        result = MODULE.verify_activation(self.repo, activation_sha, activation_sha)
        self.assertEqual(
            result["schema"], "cross-ai-source-trust-activation/v1"
        )
        self.assertEqual(result["trusted_sha"], activation_sha)
        self.assertEqual(set(result["source_digests"]), set(MODULE.TRUSTED_SOURCE_PATHS))

    def test_modified_checkout_source_fails_after_activation(self) -> None:
        self.activate_source_stack()
        activation_sha = self.head_sha()
        first_path = next(iter(MODULE.TRUSTED_SOURCE_PATHS.values()))
        with (self.repo / first_path).open("ab") as handle:
            handle.write(b"\n# untrusted mutation\n")
        self.assert_activation_error("trusted_source_checkout_mismatch", activation_sha)


if __name__ == "__main__":
    unittest.main()
