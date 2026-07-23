from __future__ import annotations

import argparse
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from scripts.github_apps.cross_ai_deployment_policy.canonical import sha256_digest
from scripts.github_apps.cross_ai_deployment_policy.contract import EvidenceVerifier
from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError
from scripts.github_apps.cross_ai_deployment_policy.policy import load_policy
from scripts.github_apps import run_cross_ai_runner_bootstrap as client
from tests.github_apps.cross_ai_policy_fixtures import FixtureFactory
from tests.github_apps.test_cross_ai_runner_bootstrap import (
    CREDENTIAL,
    HEAD,
    REQUEST_ID,
    WORKFLOW,
    policy_payload,
)


class RunnerBootstrapClientTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.policy_file = self.root / "policy.json"
        self.policy_file.write_text(json.dumps(policy_payload()), encoding="utf-8")
        self.policy = load_policy(self.policy_file)
        self.factory = FixtureFactory()
        self.fixture = self.factory.build(
            policy_digest=self.policy.digest,
            bootstrap_credential=CREDENTIAL,
            stage_overrides={
                "apply": {
                    "workflowPath": WORKFLOW,
                    "runsOnLabels": ["self-hosted", "aiserver", "testai-deploy"],
                    "runnerAttestationClass": "acik-testai-deploy-v1",
                }
            },
        )
        self.verified = EvidenceVerifier(
            trust_root=self.fixture.trust_root,
            revocations_envelope=self.fixture.revocations_envelope,
            now=self.fixture.now,
            expected_policy_sha256=self.policy.digest,
        ).verify_bundle(self.fixture.bundle_envelope)
        self.trust_root_file = self.root / "trust-root.json"
        self.revocations_file = self.root / "revocations.json"
        self.trust_root_file.write_text(
            json.dumps(self.fixture.trust_root), encoding="utf-8"
        )
        self.revocations_file.write_text(
            json.dumps(self.fixture.revocations_envelope), encoding="utf-8"
        )
        self.output = self.root / "bootstrap.json"
        self.response = {
            "schemaVersion": "acik.cross-ai-runner-bootstrap-response.v1",
            "requestId": REQUEST_ID,
            "stage": "apply",
            "runId": 999001,
            "runAttempt": 1,
            "runnerId": 98765,
            "headSha": HEAD,
            "intentRef": f"refs/tags/cross-ai-intent/{REQUEST_ID}",
            "workflowPath": WORKFLOW,
            "bundleSha256": self.verified.bundle_digest,
            "bundleEnvelope": self.fixture.bundle_envelope,
            "priorStage": None,
            "priorStageState": None,
            "priorStageOutcomeSha256": None,
            "priorStageOutcome": None,
            "issuedAt": "2026-07-16T20:30:30Z",
            "expiresAt": "2026-07-16T21:00:00Z",
        }
        self.response["responseSha256"] = sha256_digest(self.response)
        self.environment = {
            "CROSS_AI_BOOTSTRAP_URL": ("https://testai.acik.com/v1/runner-bootstrap"),
            "CROSS_AI_BOOTSTRAP_TOKEN": CREDENTIAL.decode("ascii"),
            "CROSS_AI_ENDPOINT_ID": "endpoint",
            "CROSS_AI_OPERATOR_ID": "operator",
            "GITHUB_REF": f"refs/tags/cross-ai-intent/{REQUEST_ID}",
            "GITHUB_SHA": HEAD,
            "GITHUB_RUN_ID": "999001",
            "GITHUB_RUN_ATTEMPT": "1",
            "RUNNER_NAME": "testai-deploy-runner",
        }

    def tearDown(self) -> None:
        self.directory.cleanup()

    def args(self) -> argparse.Namespace:
        return argparse.Namespace(
            stage="apply",
            workflow_path=WORKFLOW,
            policy_file=self.policy_file,
            trust_root_file=self.trust_root_file,
            expected_trust_root_sha256=sha256_digest(self.fixture.trust_root),
            revocations_file=self.revocations_file,
            output=self.output,
        )

    def test_verifies_every_binding_and_writes_private_canonical_response(self) -> None:
        with (
            patch.dict(os.environ, self.environment, clear=True),
            patch.object(client, "_github_oidc_token", return_value="x.y.z"),
            patch.object(client, "_request", return_value=self.response),
            patch.object(client, "utc_now", return_value=self.fixture.now),
        ):
            result = client.execute(self.args())
            self.assertNotIn("CROSS_AI_BOOTSTRAP_TOKEN", os.environ)
        self.assertEqual(result["bundleSha256"], self.verified.bundle_digest)
        self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o600)
        self.assertEqual(json.loads(self.output.read_bytes()), self.response)

    def test_rejects_all_zero_trust_root_pin_before_network_or_secret_use(self) -> None:
        args = self.args()
        args.expected_trust_root_sha256 = "sha256:" + ("0" * 64)
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(PolicyError, "TRUST_ROOT_PIN_SENTINEL"):
                client.execute(args)

    def test_rejects_response_tamper_and_opaque_identity_mismatch(self) -> None:
        tampered = dict(self.response)
        tampered["runnerId"] = 12345
        with (
            patch.dict(os.environ, self.environment, clear=True),
            patch.object(client, "_github_oidc_token", return_value="x.y.z"),
            patch.object(client, "_request", return_value=tampered),
            patch.object(client, "utc_now", return_value=self.fixture.now),
        ):
            with self.assertRaisesRegex(
                PolicyError, "BOOTSTRAP_RESPONSE_DIGEST_MISMATCH"
            ):
                client.execute(self.args())
        wrong_identity = dict(self.environment)
        wrong_identity["CROSS_AI_ENDPOINT_ID"] = "another-endpoint"
        with (
            patch.dict(os.environ, wrong_identity, clear=True),
            patch.object(client, "_github_oidc_token", return_value="x.y.z"),
            patch.object(client, "_request", return_value=self.response),
            patch.object(client, "utc_now", return_value=self.fixture.now),
        ):
            with self.assertRaisesRegex(
                PolicyError, "BOOTSTRAP_OPAQUE_BINDING_MISMATCH"
            ):
                client.execute(self.args())

    def test_rejects_non_https_non_loopback_endpoint(self) -> None:
        environment = dict(self.environment)
        environment["CROSS_AI_BOOTSTRAP_URL"] = (
            "http://testai.acik.com/v1/runner-bootstrap"
        )
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(PolicyError, "BOOTSTRAP_ENDPOINT_INVALID"):
                client.execute(self.args())

    def test_rejects_https_bootstrap_endpoint_outside_signed_policy(self) -> None:
        environment = dict(self.environment)
        environment["CROSS_AI_BOOTSTRAP_URL"] = (
            "https://attacker.invalid/v1/runner-bootstrap"
        )
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(
                PolicyError, "BOOTSTRAP_ENDPOINT_POLICY_MISMATCH"
            ):
                client.execute(self.args())

    def test_rejects_loopback_http_and_nonstandard_https_port(self) -> None:
        for endpoint in (
            "http://127.0.0.1:8080/v1/runner-bootstrap",
            "https://testai.acik.com:8443/v1/runner-bootstrap",
        ):
            with self.subTest(endpoint=endpoint):
                with self.assertRaisesRegex(PolicyError, "BOOTSTRAP_ENDPOINT_INVALID"):
                    client._validated_endpoint(endpoint)

    def test_requests_exact_github_oidc_audience_and_clears_request_token(self) -> None:
        compact_jwt = f"{'a' * 100}.b.c"

        class Headers:
            @staticmethod
            def get_content_type() -> str:
                return "application/json"

        class Response:
            status = 200
            headers = Headers()

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            @staticmethod
            def read(_limit: int) -> bytes:
                return json.dumps({"value": compact_jwt}).encode()

        class Opener:
            request = None

            def open(self, request, timeout: int):
                self.request = request
                self.timeout = timeout
                return Response()

        opener = Opener()
        environment = {
            "ACTIONS_ID_TOKEN_REQUEST_URL": (
                "https://pipelines.actions.githubusercontent.com/oidc/token?job=123"
            ),
            "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "request-token-material-0001",
        }
        with (
            patch.dict(os.environ, environment, clear=True),
            patch.object(client.urllib.request, "build_opener", return_value=opener),
        ):
            self.assertEqual(client._github_oidc_token(), compact_jwt)
            self.assertNotIn("ACTIONS_ID_TOKEN_REQUEST_TOKEN", os.environ)
        self.assertIsNotNone(opener.request)
        parsed = urlsplit(opener.request.full_url)
        self.assertEqual(
            parse_qs(parsed.query),
            {"job": ["123"], "audience": [client.AUDIENCE]},
        )
        self.assertEqual(
            opener.request.get_header("Authorization"),
            "Bearer request-token-material-0001",
        )
        self.assertEqual(opener.timeout, 10)

    def test_rejects_untrusted_github_oidc_request_origin(self) -> None:
        environment = {
            "ACTIONS_ID_TOKEN_REQUEST_URL": (
                "https://actions.githubusercontent.com.attacker.invalid/oidc/token"
            ),
            "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "request-token-material-0001",
        }
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(PolicyError, "BOOTSTRAP_OIDC_ENDPOINT_INVALID"):
                client._github_oidc_token()


if __name__ == "__main__":
    unittest.main()
