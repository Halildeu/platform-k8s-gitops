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
        self._write_response()
        self.github_output = self.root / "github-output"
        self.github_output.touch(mode=0o600)
        self.environment = {
            "GITHUB_RUN_ID": "101",
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_SHA": bundle["subject"]["headSha"],
            "GITHUB_REF": bundle["subject"]["intentRef"],
            "GITHUB_REPOSITORY": bundle["subject"]["repository"],
            "GITHUB_REPOSITORY_ID": str(bundle["subject"]["repositoryId"]),
            "GITHUB_WORKFLOW_REF": (
                f'{bundle["subject"]["repository"]}/'
                f'{bundle["workflowStages"][1]["workflowPath"]}'
                f'@{bundle["subject"]["intentRef"]}'
            ),
        }

    def _write_response(self) -> None:
        response = dict(self.response)
        response.pop("responseSha256", None)
        response["responseSha256"] = sha256_digest(response)
        self.response = response
        self.bootstrap.write_bytes(canonical_bytes(response))
        self.bootstrap.chmod(0o600)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def args(self, **overrides) -> argparse.Namespace:
        stage = overrides.get("stage", "browser-evidence")
        conclusion = overrides.get("conclusion", "success")
        values = {
            "bootstrap_file": self.bootstrap,
            "stage": "browser-evidence",
            "conclusion": "success",
            "watchdog_expires_file": None,
            "output_dir": self.root / "outcome",
            "github_output": self.github_output,
            "product_artifact_id": (
                "707"
                if stage == "browser-evidence" and conclusion == "success"
                else None
            ),
            "product_artifact_digest": (
                "sha256:" + ("7" * 64)
                if stage == "browser-evidence" and conclusion == "success"
                else None
            ),
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
        self.assertEqual(evidence["productArtifactId"], 707)
        self.assertEqual(
            evidence["productArtifactName"],
            "faz22-6-view-only-viewer-browser-evidence-101",
        )
        self.assertEqual(evidence["productArtifactDigest"], "sha256:" + ("7" * 64))
        self.assertEqual(
            artifact,
            "cross-ai-stage-outcome-30000000-0000-4000-8000-000000000001-"
            "browser-evidence-101-1",
        )
        outputs = self.github_output.read_text(encoding="utf-8")
        self.assertIn(f"artifact-name={artifact}\n", outputs)
        self.assertIn(f"evidence-file={output}\n", outputs)

    def test_rejects_bundle_digest_drift_and_successful_apply_without_watchdog(
        self,
    ) -> None:
        changed = json.loads(self.bootstrap.read_text(encoding="utf-8"))
        changed["bundleSha256"] = "sha256:" + ("0" * 64)
        self.bootstrap.write_bytes(canonical_bytes(changed))
        self.bootstrap.chmod(0o600)
        with patch.dict(os.environ, self.environment, clear=True), patch.object(
            builder, "utc_now", return_value=self.fixture.now
        ), self.assertRaisesRegex(PolicyError, "STAGE_EVIDENCE_BINDING_INVALID"):
            builder.build(self.args())

        self.response["stage"] = "apply"
        self.response["workflowPath"] = self.factory.decode_payload(
            self.fixture.bundle_envelope
        )["workflowStages"][0]["workflowPath"]
        self.environment["GITHUB_WORKFLOW_REF"] = (
            f'{self.environment["GITHUB_REPOSITORY"]}/'
            f'{self.response["workflowPath"]}@{self.environment["GITHUB_REF"]}'
        )
        self.response["bundleSha256"] = sha256_digest(self.fixture.bundle_envelope)
        self._write_response()
        with patch.dict(os.environ, self.environment, clear=True), patch.object(
            builder, "utc_now", return_value=self.fixture.now
        ), self.assertRaisesRegex(PolicyError, "STAGE_EVIDENCE_WATCHDOG_INVALID"):
            builder.build(self.args(stage="apply"))

    def test_rejects_workflow_ref_or_product_artifact_drift(self) -> None:
        changed_environment = dict(self.environment)
        changed_environment["GITHUB_WORKFLOW_REF"] = (
            "Halildeu/platform-k8s-gitops/.github/workflows/other.yml@"
            + self.environment["GITHUB_REF"]
        )
        with patch.dict(os.environ, changed_environment, clear=True), patch.object(
            builder, "utc_now", return_value=self.fixture.now
        ), self.assertRaisesRegex(PolicyError, "STAGE_EVIDENCE_BINDING_INVALID"):
            builder.build(self.args())

        with patch.dict(os.environ, self.environment, clear=True), patch.object(
            builder, "utc_now", return_value=self.fixture.now
        ), self.assertRaisesRegex(
            PolicyError, "STAGE_EVIDENCE_PRODUCT_ARTIFACT_INVALID"
        ):
            builder.build(self.args(product_artifact_digest="sha256:" + ("0" * 63)))

    def test_records_apply_failure_before_watchdog_creation(self) -> None:
        self.response["stage"] = "apply"
        self.response["workflowPath"] = self.factory.decode_payload(
            self.fixture.bundle_envelope
        )["workflowStages"][0]["workflowPath"]
        self.environment["GITHUB_WORKFLOW_REF"] = (
            f'{self.environment["GITHUB_REPOSITORY"]}/'
            f'{self.response["workflowPath"]}@{self.environment["GITHUB_REF"]}'
        )
        self._write_response()
        with patch.dict(os.environ, self.environment, clear=True), patch.object(
            builder, "utc_now", return_value=self.fixture.now
        ):
            evidence, _artifact = builder.build(
                self.args(stage="apply", conclusion="failure")
            )
        self.assertEqual(evidence["conclusion"], "failure")
        self.assertIsNone(evidence["watchdogExpiresAt"])

    def test_apply_success_requires_private_owned_watchdog_receipt(self) -> None:
        self.response["stage"] = "apply"
        self.response["workflowPath"] = self.factory.decode_payload(
            self.fixture.bundle_envelope
        )["workflowStages"][0]["workflowPath"]
        self.environment["GITHUB_WORKFLOW_REF"] = (
            f'{self.environment["GITHUB_REPOSITORY"]}/'
            f'{self.response["workflowPath"]}@{self.environment["GITHUB_REF"]}'
        )
        self._write_response()
        receipt = self.root / "watchdog-expires-at"
        receipt.write_text("2026-07-16T21:00:00Z\n", encoding="ascii")
        receipt.chmod(0o600)
        with patch.dict(os.environ, self.environment, clear=True), patch.object(
            builder, "utc_now", return_value=self.fixture.now
        ):
            evidence, _artifact = builder.build(
                self.args(stage="apply", watchdog_expires_file=receipt)
            )
        self.assertEqual(evidence["watchdogExpiresAt"], "2026-07-16T21:00:00Z")

        receipt.chmod(0o644)
        with patch.dict(os.environ, self.environment, clear=True), patch.object(
            builder, "utc_now", return_value=self.fixture.now
        ), self.assertRaisesRegex(PolicyError, "STAGE_EVIDENCE_WATCHDOG_INVALID"):
            builder.build(
                self.args(
                    stage="apply",
                    watchdog_expires_file=receipt,
                    output_dir=self.root / "rejected-outcome",
                )
            )


if __name__ == "__main__":
    unittest.main()
