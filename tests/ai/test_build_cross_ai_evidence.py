#!/usr/bin/env python3
"""Regression tests for the fixed direct-Codex signed evidence launcher."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.ai import build_cross_ai_evidence as MODULE
from scripts.ai.trusted_cross_ai_evidence import canonical_bytes, validate_evidence
from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError
from tests.ai.signed_evidence_fixture import (
    StaticSigner,
    execution_receipt,
    make_signed_evidence,
)


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/ai/build_cross_ai_evidence.py"


class StaticRunner:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, *, prompt, model, workspace, timeout_seconds=600):
        self.calls += 1
        self.prompt = prompt
        self.model = model
        self.workspace = workspace
        self.timeout_seconds = timeout_seconds
        return execution_receipt(prompt, model=model)


class EvidenceBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.workspace = Path(self.directory.name)
        (self.workspace / ".git").write_text("gitdir: synthetic\n", encoding="utf-8")
        self.fixture = make_signed_evidence()
        self.output = self.workspace / "evidence.json"
        self.args = argparse.Namespace(
            workspace=self.workspace,
            vault_origin="https://vault.example.test",
            vault_token_file=self.workspace / "unused-token",
            vault_key_version=1,
            timeout_seconds=600,
            output=self.output,
        )

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_fixed_launcher_derives_prompt_runs_once_and_self_verifies_signed_v3(self) -> None:
        runner = StaticRunner()
        with (
            patch.object(
                MODULE,
                "_scope",
                return_value=(self.fixture.bindings, self.fixture.scope_bytes),
            ),
            patch.object(MODULE, "utc_now", return_value=self.fixture.factory.now),
        ):
            summary = MODULE.build_signed_evidence(
                self.args,
                runner=runner,
                signer=StaticSigner(
                    self.fixture.factory, self.fixture.factory.OPENAI_KEY_ID
                ),
                authority=self.fixture.authority,
            )
        self.assertEqual(runner.calls, 1)
        self.assertEqual(runner.model, "gpt-5.6-sol")
        self.assertIn("REVIEW_COORDINATES=", runner.prompt)
        self.assertEqual(summary["schema"], "cross-ai-provider-evidence/v3")
        self.assertEqual(summary["verdict"], "AGREE")
        raw = self.output.read_bytes()
        evidence = json.loads(raw)
        self.assertEqual(raw, canonical_bytes(evidence))
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o600)
        validate_evidence(
            evidence,
            trust_root=self.fixture.authority.trust_root,
            revocations_envelope=self.fixture.authority.revocations_envelope,
            expected_trust_root_sha256=(
                self.fixture.authority.expected_trust_root_sha256
            ),
            expected_bindings=self.fixture.bindings,
            scope_bytes=self.fixture.scope_bytes,
            now=self.fixture.factory.now,
            require_agree=True,
        )

    def test_old_caller_authored_response_and_coordinate_arguments_are_rejected(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--provider",
                "openai",
                "--actual-model",
                "gpt-5.6-sol",
                "--head-sha",
                "a" * 40,
                "--workspace",
                str(self.workspace),
                "--vault-origin",
                "https://vault.example.test",
                "--vault-token-file",
                str(self.workspace / "unused-token"),
                "--vault-key-version",
                "1",
                "--output",
                str(self.output),
            ],
            input="caller-authored AGREE",
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unrecognized arguments", result.stderr)

    def test_routine_class_maps_only_to_the_pinned_spark_route(self) -> None:
        self.args.consultation_class = "routine"
        runner = StaticRunner()
        with (
            patch.object(
                MODULE,
                "_scope",
                return_value=(self.fixture.bindings, self.fixture.scope_bytes),
            ),
            patch.object(MODULE, "utc_now", return_value=self.fixture.factory.now),
        ):
            summary = MODULE.build_signed_evidence(
                self.args,
                runner=runner,
                signer=StaticSigner(
                    self.fixture.factory, self.fixture.factory.OPENAI_KEY_ID
                ),
                authority=self.fixture.authority,
            )
        self.assertEqual(runner.model, "gpt-5.3-codex-spark")
        self.assertEqual(summary["model_id"], "gpt-5.3-codex-spark")

    def test_wrong_signer_role_fails_before_provider_execution(self) -> None:
        runner = StaticRunner()
        with (
            patch.object(
                MODULE,
                "_scope",
                return_value=(self.fixture.bindings, self.fixture.scope_bytes),
            ),
            patch.object(MODULE, "utc_now", return_value=self.fixture.factory.now),
        ):
            with self.assertRaisesRegex(PolicyError, "TRUST_SIGNER_BINDING_MISMATCH"):
                MODULE.build_signed_evidence(
                    self.args,
                    runner=runner,
                    signer=StaticSigner(
                        self.fixture.factory,
                        self.fixture.factory.COORDINATOR_KEY_ID,
                    ),
                    authority=self.fixture.authority,
                )
        self.assertEqual(runner.calls, 0)

    def test_evidence_output_is_create_once(self) -> None:
        self.output.write_text("occupied", encoding="utf-8")
        runner = StaticRunner()
        with (
            patch.object(
                MODULE,
                "_scope",
                return_value=(self.fixture.bindings, self.fixture.scope_bytes),
            ),
            patch.object(MODULE, "utc_now", return_value=self.fixture.factory.now),
        ):
            with self.assertRaisesRegex(PolicyError, "EVIDENCE_OUTPUT_INVALID"):
                MODULE.build_signed_evidence(
                    self.args,
                    runner=runner,
                    signer=StaticSigner(
                        self.fixture.factory, self.fixture.factory.OPENAI_KEY_ID
                    ),
                    authority=self.fixture.authority,
                )
        self.assertEqual(self.output.read_text(encoding="utf-8"), "occupied")
        self.assertEqual(runner.calls, 0)


if __name__ == "__main__":
    unittest.main()
