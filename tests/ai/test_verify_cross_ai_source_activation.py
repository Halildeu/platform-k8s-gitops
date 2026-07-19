#!/usr/bin/env python3
"""Regression tests for the Cross-AI producer trust activation boundary."""

from __future__ import annotations

import importlib.util
import json
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
    CONTEXT = {
        "repository": "Halildeu/platform-k8s-gitops",
        "workflow_ref": (
            "Halildeu/platform-k8s-gitops/.github/workflows/ci.yml"
            "@refs/heads/main"
        ),
        "event_name": "push",
        "git_ref": "refs/heads/main",
        "run_id": "12345",
        "run_attempt": "1",
    }

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
        marker = self.repo / MODULE.ACTIVATION_MARKER_PATH
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_bytes(MODULE.ACTIVATION_MARKER_BYTES)
        self.commit("activate producer stack")

    def assert_activation_error(self, code: str, sha: str) -> None:
        with self.assertRaisesRegex(MODULE.ActivationError, f"^{code}$"):
            MODULE.verify_activation(self.repo, sha, sha, **self.CONTEXT)

    def test_bootstrap_commit_without_producer_stack_cannot_self_attest(self) -> None:
        self.assert_activation_error("activation_marker_unavailable", self.bootstrap_sha)

    def test_activation_commit_binds_checkout_to_all_trusted_sources(self) -> None:
        self.activate_source_stack()
        activation_sha = self.head_sha()
        result = MODULE.verify_activation(
            self.repo, activation_sha, activation_sha, **self.CONTEXT
        )
        self.assertEqual(
            result["schema"], "cross-ai-source-trust-activation/v1"
        )
        self.assertEqual(result["trusted_sha"], activation_sha)
        self.assertEqual(set(result["source_digests"]), set(MODULE.TRUSTED_SOURCE_PATHS))
        self.assertEqual(result["ref"], "refs/heads/main")
        self.assertEqual(result["run_id"], "12345")
        self.assertRegex(
            result["activated_at"],
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
        )

    def test_activation_epoch_remains_stable_on_descendant_main_commits(self) -> None:
        self.activate_source_stack()
        activation_sha = self.head_sha()
        activated = MODULE.verify_activation(
            self.repo, activation_sha, activation_sha, **self.CONTEXT
        )["activated_at"]

        source_path = self.repo / next(iter(MODULE.TRUSTED_SOURCE_PATHS.values()))
        with source_path.open("ab") as handle:
            handle.write(b"\n# trusted producer update\n")
        self.commit("trusted producer update on main")
        descendant_sha = self.head_sha()
        descendant = MODULE.verify_activation(
            self.repo, descendant_sha, descendant_sha, **self.CONTEXT
        )["activated_at"]

        self.assertEqual(descendant, activated)

    def test_marker_before_last_source_activates_at_first_complete_descendant(self) -> None:
        marker = self.repo / MODULE.ACTIVATION_MARKER_PATH
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_bytes(MODULE.ACTIVATION_MARKER_BYTES)
        self.commit("introduce activation marker")

        source_paths = tuple(MODULE.TRUSTED_SOURCE_PATHS.values())
        for index, relative_path in enumerate(source_paths):
            target = self.repo / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / relative_path).read_bytes())
            self.commit(f"add producer source {index}")

        complete_sha = self.head_sha()
        complete = MODULE.verify_activation(
            self.repo, complete_sha, complete_sha, **self.CONTEXT
        )
        self.assertRegex(
            complete["activated_at"],
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
        )

        (self.repo / "README.md").write_text("descendant\n", encoding="utf-8")
        self.commit("mainline descendant")
        descendant_sha = self.head_sha()
        descendant = MODULE.verify_activation(
            self.repo, descendant_sha, descendant_sha, **self.CONTEXT
        )
        self.assertEqual(descendant["activated_at"], complete["activated_at"])

    def test_marker_mutation_cannot_activate_policy(self) -> None:
        self.activate_source_stack()
        activation_sha = self.head_sha()
        marker = self.repo / MODULE.ACTIVATION_MARKER_PATH
        marker.write_text("{}\n", encoding="utf-8")
        with self.assertRaisesRegex(
            MODULE.ActivationError, "^activation_marker_mismatch$"
        ):
            MODULE.verify_activation(
                self.repo, activation_sha, activation_sha, **self.CONTEXT
            )

    def test_non_main_or_non_push_context_cannot_activate_policy(self) -> None:
        self.activate_source_stack()
        activation_sha = self.head_sha()
        for mutation in (
            {"event_name": "pull_request"},
            {"git_ref": "refs/heads/feature"},
            {"workflow_ref": "Halildeu/platform-k8s-gitops/.github/workflows/other.yml@refs/heads/main"},
        ):
            with self.subTest(mutation=mutation):
                context = {**self.CONTEXT, **mutation}
                with self.assertRaisesRegex(
                    MODULE.ActivationError, "^untrusted_activation_context$"
                ):
                    MODULE.verify_activation(
                        self.repo, activation_sha, activation_sha, **context
                    )

    def test_modified_checkout_source_fails_after_activation(self) -> None:
        self.activate_source_stack()
        activation_sha = self.head_sha()
        first_path = next(iter(MODULE.TRUSTED_SOURCE_PATHS.values()))
        with (self.repo / first_path).open("ab") as handle:
            handle.write(b"\n# untrusted mutation\n")
        self.assert_activation_error("trusted_source_checkout_mismatch", activation_sha)

    def test_durable_main_status_recovers_expired_artifact(self) -> None:
        self.activate_source_stack()
        activation_sha = self.head_sha()
        anchor_file = self.repo / "anchor.json"
        anchor_file.write_text(
            json.dumps({
                "anchor_sha": activation_sha,
                "status": {
                    "id": 987,
                    "sha": activation_sha,
                    "state": "success",
                    "context": MODULE.ACTIVATION_STATUS_CONTEXT,
                    "description": MODULE.ACTIVATION_STATUS_DESCRIPTION,
                    "target_url": (
                        "https://github.com/Halildeu/platform-k8s-gitops/"
                        "actions/runs/7654"
                    ),
                    "created_at": "2099-01-01T00:00:00Z",
                    "creator": {"login": "github-actions[bot]"},
                },
                "run": {
                    "id": 7654,
                    "head_sha": activation_sha,
                    "event": "push",
                    "head_branch": "main",
                    "status": "completed",
                    "conclusion": "success",
                    "path": ".github/workflows/ci.yml",
                    "html_url": (
                        "https://github.com/Halildeu/platform-k8s-gitops/"
                        "actions/runs/7654"
                    ),
                    "repository": {"full_name": "Halildeu/platform-k8s-gitops"},
                },
            }),
            encoding="utf-8",
        )
        result = MODULE.verify_activation(
            self.repo,
            activation_sha,
            activation_sha,
            repository="Halildeu/platform-k8s-gitops",
            workflow_ref=(
                "Halildeu/platform-k8s-gitops/"
                ".github/workflows/gate-cross-ai-audit.yml@refs/heads/main"
            ),
            event_name="pull_request_target",
            git_ref="refs/heads/main",
            run_id="9999",
            run_attempt="2",
            recovery_anchor_file=anchor_file,
        )
        self.assertEqual(result["schema"], "cross-ai-source-trust-activation/v2")
        self.assertEqual(result["activation_mode"], "durable-main-status-recovery")
        self.assertEqual(result["anchor_sha"], activation_sha)
        self.assertEqual(result["anchor_status_id"], 987)
        self.assertEqual(result["anchor_run_id"], "7654")

    def test_recovery_rejects_non_actions_activation_status(self) -> None:
        self.activate_source_stack()
        activation_sha = self.head_sha()
        anchor_file = self.repo / "anchor.json"
        anchor_file.write_text(
            json.dumps({
                "anchor_sha": activation_sha,
                "status": {
                    "id": 987,
                    "sha": activation_sha,
                    "state": "success",
                    "context": MODULE.ACTIVATION_STATUS_CONTEXT,
                    "description": MODULE.ACTIVATION_STATUS_DESCRIPTION,
                    "target_url": (
                        "https://github.com/Halildeu/platform-k8s-gitops/"
                        "actions/runs/7654"
                    ),
                    "created_at": "2099-01-01T00:00:00Z",
                    "creator": {"login": "collaborator"},
                },
                "run": {
                    "id": 7654,
                    "head_sha": activation_sha,
                    "event": "push",
                    "head_branch": "main",
                    "status": "completed",
                    "conclusion": "success",
                    "path": ".github/workflows/ci.yml",
                    "html_url": (
                        "https://github.com/Halildeu/platform-k8s-gitops/"
                        "actions/runs/7654"
                    ),
                    "repository": {"full_name": "Halildeu/platform-k8s-gitops"},
                },
            }),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            MODULE.ActivationError, "^recovery_anchor_invalid$"
        ):
            MODULE.verify_activation(
                self.repo,
                activation_sha,
                activation_sha,
                repository="Halildeu/platform-k8s-gitops",
                workflow_ref=(
                    "Halildeu/platform-k8s-gitops/"
                    ".github/workflows/gate-cross-ai-audit.yml@refs/heads/main"
                ),
                event_name="pull_request_target",
                git_ref="refs/heads/main",
                run_id="9999",
                run_attempt="2",
                recovery_anchor_file=anchor_file,
            )

    def test_recovery_rejects_success_from_an_older_main_commit(self) -> None:
        self.activate_source_stack()
        activation_sha = self.head_sha()
        (self.repo / "README.md").write_text("new base\n", encoding="utf-8")
        self.commit("new exact base without a successful activation status")
        exact_base_sha = self.head_sha()
        anchor_file = self.repo / "anchor.json"
        anchor_file.write_text(
            json.dumps({
                "anchor_sha": activation_sha,
                "status": {
                    "id": 987,
                    "sha": activation_sha,
                    "state": "success",
                    "context": MODULE.ACTIVATION_STATUS_CONTEXT,
                    "description": MODULE.ACTIVATION_STATUS_DESCRIPTION,
                    "target_url": (
                        "https://github.com/Halildeu/platform-k8s-gitops/"
                        "actions/runs/7654"
                    ),
                    "created_at": "2099-01-01T00:00:00Z",
                    "creator": {"login": "github-actions[bot]"},
                },
                "run": {
                    "id": 7654,
                    "head_sha": activation_sha,
                    "event": "push",
                    "head_branch": "main",
                    "status": "completed",
                    "conclusion": "success",
                    "path": ".github/workflows/ci.yml",
                    "html_url": (
                        "https://github.com/Halildeu/platform-k8s-gitops/"
                        "actions/runs/7654"
                    ),
                    "repository": {"full_name": "Halildeu/platform-k8s-gitops"},
                },
            }),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            MODULE.ActivationError, "^recovery_anchor_not_exact_base$"
        ):
            MODULE.verify_activation(
                self.repo,
                exact_base_sha,
                exact_base_sha,
                repository="Halildeu/platform-k8s-gitops",
                workflow_ref=(
                    "Halildeu/platform-k8s-gitops/"
                    ".github/workflows/gate-cross-ai-audit.yml@refs/heads/main"
                ),
                event_name="pull_request_target",
                git_ref="refs/heads/main",
                run_id="9999",
                run_attempt="2",
                recovery_anchor_file=anchor_file,
            )


if __name__ == "__main__":
    unittest.main()
