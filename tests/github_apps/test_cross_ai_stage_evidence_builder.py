from __future__ import annotations

import argparse
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.github_apps import build_cross_ai_stage_evidence as builder
from scripts.github_apps.cross_ai_deployment_policy.canonical import (
    canonical_bytes,
    sha256_digest,
)
from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError
from tests.github_apps.cross_ai_policy_fixtures import FixtureFactory


class StageEvidenceBuilderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.factory = FixtureFactory()
        self.fixture = self.factory.build()
        bundle = self.factory.decode_payload(self.fixture.bundle_envelope)
        self.response = {
            "requestId": bundle["grant"]["requestId"],
            "stage": "browser-evidence",
            "runId": 101,
            "runAttempt": 1,
            "headSha": bundle["subject"]["headSha"],
            "intentRef": bundle["subject"]["intentRef"],
            "workflowPath": bundle["workflowStages"][1]["workflowPath"],
            "bundleSha256": sha256_digest(self.fixture.bundle_envelope),
            "bundleEnvelope": self.fixture.bundle_envelope,
        }
        self.bootstrap = self.root / "bootstrap.json"
        self.bootstrap.write_bytes(canonical_bytes(self.response))
        self.github_output = self.root / "github-output"
        self.github_output.touch(mode=0o600)
        self.environment = {
            "GITHUB_RUN_ID": "101",
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_SHA": bundle["subject"]["headSha"],
            "GITHUB_REF": bundle["subject"]["intentRef"],
            "GITHUB_REPOSITORY": bundle["subject"]["repository"],
            "GITHUB_REPOSITORY_ID": str(bundle["subject"]["repositoryId"]),
        }

    def tearDown(self) -> None:
        self.directory.cleanup()

    def args(self, **overrides) -> argparse.Namespace:
        values = {
            "bootstrap_file": self.bootstrap,
            "stage": "browser-evidence",
            "conclusion": "success",
            "watchdog_expires_file": None,
            "output_dir": self.root / "outcome",
            "github_output": self.github_output,
        }
        values.update(overrides)
        return argparse.Namespace(**values)

    def test_builds_one_private_canonical_stage_evidence_file(self) -> None:
        with patch.dict(os.environ, self.environment, clear=True), patch.object(
            builder, "utc_now", return_value=self.fixture.now
        ):
            evidence, artifact = builder.build(self.args())
        output = self.root / "outcome/cross-ai-stage-evidence.json"
        self.assertEqual(output.read_bytes(), canonical_bytes(evidence))
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
        self.assertEqual(evidence["watchdogExpiresAt"], None)
        self.assertEqual(
            artifact,
            "cross-ai-stage-outcome-30000000-0000-4000-8000-000000000001-"
            "browser-evidence-101-1",
        )
        outputs = self.github_output.read_text(encoding="utf-8")
        self.assertIn(f"artifact-name={artifact}\n", outputs)
        self.assertIn(f"evidence-file={output}\n", outputs)

    def test_rejects_bundle_digest_drift_and_apply_without_watchdog(self) -> None:
        changed = json.loads(self.bootstrap.read_text(encoding="utf-8"))
        changed["bundleSha256"] = "sha256:" + ("0" * 64)
        self.bootstrap.write_bytes(canonical_bytes(changed))
        with patch.dict(os.environ, self.environment, clear=True), patch.object(
            builder, "utc_now", return_value=self.fixture.now
        ), self.assertRaisesRegex(PolicyError, "STAGE_EVIDENCE_BINDING_INVALID"):
            builder.build(self.args())

        self.response["stage"] = "apply"
        self.response["workflowPath"] = self.factory.decode_payload(
            self.fixture.bundle_envelope
        )["workflowStages"][0]["workflowPath"]
        self.response["bundleSha256"] = sha256_digest(self.fixture.bundle_envelope)
        self.bootstrap.write_bytes(canonical_bytes(self.response))
        with patch.dict(os.environ, self.environment, clear=True), patch.object(
            builder, "utc_now", return_value=self.fixture.now
        ), self.assertRaisesRegex(PolicyError, "STAGE_EVIDENCE_WATCHDOG_INVALID"):
            builder.build(self.args(stage="apply"))


if __name__ == "__main__":
    unittest.main()
