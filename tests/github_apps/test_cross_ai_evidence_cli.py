from __future__ import annotations

import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from scripts.github_apps.cross_ai_deployment_policy.canonical import sha256_digest
from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError
from scripts.github_apps.cross_ai_deployment_policy.provider import (
    CODEX_MODEL,
    ProviderExecutionReceipt,
    REVIEW_RESULT_SCHEMA_VERSION,
)
from scripts.github_apps.cross_ai_deployment_policy.secureio import load_private_json
from scripts.github_apps.run_cross_ai_evidence_coordinator import coordinate_bundle
from scripts.github_apps.run_cross_ai_review_issuer import issue_review
from tests.github_apps.cross_ai_policy_fixtures import FixtureFactory, digest
from tests.github_apps.test_cross_ai_deployment_provider import StaticSigner


class StaticRunner:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, *, prompt, model, workspace, timeout_seconds=600):
        self.calls += 1
        self.prompt = prompt
        self.model = model
        self.workspace = workspace
        self.timeout_seconds = timeout_seconds
        result = json.dumps(
            {
                "schemaVersion": REVIEW_RESULT_SCHEMA_VERSION,
                "verdict": "AGREE",
                "findingIds": [],
                "resolvedFindingIds": [],
                "acknowledgedFindingIds": [],
            },
            separators=(",", ":"),
        )
        return ProviderExecutionReceipt(
            provider_family="openai",
            channel="openai-codex",
            direct_provider_cli=True,
            model_id=CODEX_MODEL,
            model_identity_class="trusted-launch-attested",
            reasoning_effort="xhigh",
            sandbox="read-only",
            ephemeral=True,
            capability_snapshot_sha256=digest("capability"),
            input_sha256=digest("input"),
            output_sha256=digest("output"),
            result_text=result,
        )


class EvidenceCLITest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.factory = FixtureFactory("v3")
        self.fixture = self.factory.build()
        self.payload = self.factory.decode_payload(self.fixture.bundle_envelope)
        self.trust_root = self.root / "trust-root.json"
        self.revocations = self.root / "revocations.json"
        self.trust_root.write_text(json.dumps(self.fixture.trust_root), encoding="utf-8")
        self.revocations.write_text(
            json.dumps(self.fixture.revocations_envelope),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.directory.cleanup()

    def private_json(self, name: str, value: dict) -> Path:
        path = self.root / name
        path.write_text(json.dumps(value), encoding="utf-8")
        path.chmod(0o600)
        return path

    def issuer_args(self, request: Path, prompt: Path, output: Path) -> Namespace:
        return Namespace(
            provider="openai",
            workspace=self.root,
            prompt_file=prompt,
            request_file=request,
            trust_root_file=self.trust_root,
            expected_trust_root_sha256=sha256_digest(self.fixture.trust_root),
            revocations_file=self.revocations,
            vault_origin="https://vault.example.test",
            vault_token_file=self.root / "unused-token",
            vault_mount="cross-ai",
            vault_key_name="openai-codex",
            vault_key_version=1,
            provider_executable=None,
            timeout_seconds=600,
            output=output,
        )

    def test_review_issuer_runs_fixed_route_and_writes_only_signed_leaf(self) -> None:
        request = self.private_json(
            "review-request.json",
            {
                "schemaVersion": "acik.cross-ai-review-issuance-request.v1",
                "reviewId": "50000000-0000-4000-8000-000000000010",
                "reviewChainId": "40000000-0000-4000-8000-000000000010",
                "subjectSha256": digest("subject"),
                "round": 1,
                "previousRoundSha256": None,
                "closureRootSha256": digest("closure"),
                "issuedAt": "2026-07-18T20:10:00Z",
                "expiresAt": "2026-07-18T21:30:00Z",
            },
        )
        prompt = self.root / "prompt.txt"
        prompt.write_text("Review exact canonical scope.", encoding="utf-8")
        prompt.chmod(0o600)
        output = self.root / "review.dsse.json"
        runner = StaticRunner()
        summary = issue_review(
            self.issuer_args(request, prompt, output),
            runner=runner,
            signer=StaticSigner(self.factory, self.factory.OPENAI_KEY_ID),
            observed_at=self.fixture.now,
        )
        self.assertEqual(runner.calls, 1)
        self.assertEqual(runner.model, CODEX_MODEL)
        self.assertEqual(summary["verdict"], "AGREE")
        self.assertFalse(summary["outputPathDisclosed"])
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        envelope = load_private_json(output, label="review output")
        self.assertEqual(summary["reviewEnvelopeSha256"], sha256_digest(envelope))
        self.assertNotIn("Review exact canonical scope.", output.read_text())

    def test_retired_provider_fails_before_provider_execution(self) -> None:
        request = self.private_json(
            "review-request.json",
            {
                "schemaVersion": "acik.cross-ai-review-issuance-request.v1",
                "reviewId": "50000000-0000-4000-8000-000000000011",
                "reviewChainId": "40000000-0000-4000-8000-000000000011",
                "subjectSha256": digest("subject"),
                "round": 1,
                "previousRoundSha256": None,
                "closureRootSha256": digest("closure"),
                "issuedAt": "2026-07-18T20:10:00Z",
                "expiresAt": "2026-07-18T21:30:00Z",
            },
        )
        prompt = self.root / "prompt.txt"
        prompt.write_text("Review exact canonical scope.", encoding="utf-8")
        prompt.chmod(0o600)
        runner = StaticRunner()
        args = self.issuer_args(request, prompt, self.root / "review.dsse.json")
        args.provider = "anthropic"
        with self.assertRaisesRegex(PolicyError, "PROVIDER_ROUTE_RETIRED"):
            issue_review(
                args,
                runner=runner,
                signer=StaticSigner(self.factory, self.factory.OPENAI_KEY_ID),
                observed_at=self.fixture.now,
            )
        self.assertEqual(runner.calls, 0)

    def test_v3_coordinator_cli_verifies_then_writes_bundle(self) -> None:
        request = self.private_json(
            "coordination-request.json",
            {
                "schemaVersion": "acik.cross-ai-evidence-coordination-request.v1",
                "bundleId": "70000000-0000-4000-8000-000000000010",
                "subject": self.payload["subject"],
                "workflowStages": self.payload["workflowStages"],
                "runnerAdmissionLeaseEnvelope": self.payload[
                    "runnerAdmissionLeaseEnvelope"
                ],
                "grant": self.payload["grant"],
                "reviewEnvelopes": self.payload["reviewEnvelopes"],
                "closureEntries": self.payload["closure"]["entries"],
                "finalAgreeReviewSha256": self.payload["consensus"][
                    "finalAgreeReviewSha256"
                ],
                "providerFamilies": self.payload["consensus"]["providerFamilies"],
            },
        )
        output = self.root / "bundle.dsse.json"
        args = Namespace(
            request_file=request,
            trust_root_file=self.trust_root,
            expected_trust_root_sha256=sha256_digest(self.fixture.trust_root),
            revocations_file=self.revocations,
            expected_policy_sha256=self.payload["subject"]["policySha256"],
            vault_origin="https://vault.example.test",
            vault_token_file=self.root / "unused-token",
            vault_mount="cross-ai",
            vault_key_name="coordinator",
            vault_key_version=1,
            output=output,
        )
        summary = coordinate_bundle(
            args,
            signer=StaticSigner(self.factory, self.factory.COORDINATOR_KEY_ID),
            observed_at=self.fixture.now,
        )
        self.assertEqual(summary["providerFamilies"], ["openai"])
        self.assertFalse(summary["outputPathDisclosed"])
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        envelope = load_private_json(output, label="bundle output")
        self.assertEqual(summary["bundleEnvelopeSha256"], sha256_digest(envelope))


if __name__ == "__main__":
    unittest.main()
