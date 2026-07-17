from __future__ import annotations

import base64
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError
from scripts.github_apps.cross_ai_deployment_policy.github import (
    GitHubArtifact,
    GitHubAppTokenProvider,
    GitHubArtifactDownloader,
    GitHubDecisionClient,
    GitHubDispatcherClient,
    GitHubReader,
    HTTPResponse,
    _validated_artifact_redirect,
)


NOW = datetime(2026, 7, 16, 21, 0, tzinfo=timezone.utc)


class FakeTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, str], bytes | None]] = []
        self.routes: dict[tuple[str, str], HTTPResponse] = {}

    def add(self, method: str, url: str, status: int, payload: object) -> None:
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.routes[(method, url)] = HTTPResponse(status, {}, body)

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        body: bytes | None = None,
        timeout: float = 10.0,
    ) -> HTTPResponse:
        self.calls.append((method, url, dict(headers), body))
        return self.routes.get((method, url), HTTPResponse(404, {}, b"{}"))


class StubArtifactDownloader(GitHubArtifactDownloader):
    def __init__(self, *, responses, **kwargs) -> None:
        super().__init__(**kwargs)
        self.responses = list(responses)
        self.requests = []

    def _open(self, request):
        self.requests.append(request)
        return self.responses.pop(0)


class GitHubReaderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        key_path = Path(self.directory.name) / "app.pem"
        key_path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        self.transport = FakeTransport()
        self.token_url = "https://api.github.com/app/installations/2222/access_tokens"
        self.transport.add(
            "POST",
            self.token_url,
            201,
            {
                "token": "ghs_" + ("a" * 40),
                "expires_at": "2026-07-16T22:00:00Z",
            },
        )
        self.provider = GitHubAppTokenProvider(
            app_id=999,
            private_key_file=key_path,
            transport=self.transport,
            now=lambda: NOW,
        )
        self.reader = GitHubReader(
            token_provider=self.provider,
            transport=self.transport,
        )

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_caches_installation_token_and_emits_bounded_jwt(self) -> None:
        first = self.provider.token(2222)
        second = self.provider.token(2222)
        self.assertEqual(first, second)
        token_calls = [call for call in self.transport.calls if call[1] == self.token_url]
        self.assertEqual(len(token_calls), 1)
        authorization = token_calls[0][2]["Authorization"]
        self.assertTrue(authorization.startswith("Bearer "))
        jwt = authorization.removeprefix("Bearer ")
        self.assertEqual(len(jwt.split(".")), 3)

    def test_reads_run_ref_annotated_tag_workflow_and_environment(self) -> None:
        repository = "Halildeu/platform-k8s-gitops"
        run_url = f"https://api.github.com/repos/{repository}/actions/runs/7"
        ref_url = (
            f"https://api.github.com/repos/{repository}/git/ref/"
            "tags/cross-ai-intent/30000000-0000-4000-8000-000000000001"
        )
        tag_url = f"https://api.github.com/repos/{repository}/git/tags/{'a' * 40}"
        workflow_url = (
            f"https://api.github.com/repos/{repository}/contents/"
            ".github/workflows/apply.yml?ref=" + ("b" * 40)
        )
        environment_url = (
            f"https://api.github.com/repos/{repository}/environments/faz22-view-only-pilot"
        )
        self.transport.add("GET", run_url, 200, {"id": 7})
        self.transport.add(
            "GET", ref_url, 200, {"object": {"type": "tag", "sha": "a" * 40}}
        )
        self.transport.add(
            "GET", tag_url, 200, {"object": {"type": "commit", "sha": "b" * 40}}
        )
        encoded = base64.b64encode(b"on: workflow_dispatch\n").decode()
        wrapped = encoded[:8] + "\n" + encoded[8:]
        self.transport.add(
            "GET",
            workflow_url,
            200,
            {"type": "file", "encoding": "base64", "content": wrapped},
        )
        self.transport.add(
            "GET", environment_url, 200, {"name": "faz22-view-only-pilot"}
        )
        self.assertEqual(self.reader.workflow_run(2222, repository, 7), {"id": 7})
        intent_ref = self.reader.intent_ref(
            2222, repository, "30000000-0000-4000-8000-000000000001"
        )
        self.assertEqual(intent_ref.head_sha, "b" * 40)
        self.assertEqual(intent_ref.ref_object_id, "a" * 40)
        self.assertTrue(intent_ref.annotated)
        self.assertEqual(
            self.reader.workflow_bytes(
                2222, repository, ".github/workflows/apply.yml", "b" * 40
            ),
            b"on: workflow_dispatch\n",
        )
        self.assertEqual(
            self.reader.environment(2222, repository, "faz22-view-only-pilot")["name"],
            "faz22-view-only-pilot",
        )
        for call in self.transport.calls:
            if call[0] == "GET":
                self.assertEqual(call[2]["Authorization"], "Bearer ghs_" + ("a" * 40))

    def test_rejects_token_failure_invalid_key_and_origin_confusion(self) -> None:
        self.transport.add("POST", self.token_url, 403, {})
        with self.assertRaisesRegex(PolicyError, "GITHUB_INSTALLATION_TOKEN_FAILED"):
            self.provider.token(2222)
        with self.assertRaisesRegex(PolicyError, "GITHUB_API_ORIGIN_MISMATCH"):
            GitHubReader(
                token_provider=self.provider,
                api_origin="https://github.example.test",
            )

    def test_rejects_failed_truth_read_and_invalid_workflow_content(self) -> None:
        repository = "Halildeu/platform-k8s-gitops"
        run_url = f"https://api.github.com/repos/{repository}/actions/runs/9"
        self.transport.add("GET", run_url, 500, {})
        with self.assertRaisesRegex(PolicyError, "GITHUB_TRUTH_READ_FAILED"):
            self.reader.workflow_run(2222, repository, 9)

        workflow_url = (
            f"https://api.github.com/repos/{repository}/contents/"
            ".github/workflows/apply.yml?ref=" + ("b" * 40)
        )
        self.transport.add(
            "GET",
            workflow_url,
            200,
            {"type": "file", "encoding": "base64", "content": "!!!!"},
        )
        with self.assertRaisesRegex(PolicyError, "GITHUB_WORKFLOW_INVALID"):
            self.reader.workflow_bytes(
                2222, repository, ".github/workflows/apply.yml", "b" * 40
            )

    def test_reads_complete_jobs_and_one_exact_bounded_artifact(self) -> None:
        repository = "Halildeu/platform-k8s-gitops"
        attempt_url = (
            f"https://api.github.com/repos/{repository}/actions/runs/7/attempts/1"
        )
        jobs_url = attempt_url + "/jobs?per_page=100"
        artifacts_url = (
            f"https://api.github.com/repos/{repository}/actions/runs/7/artifacts"
            "?per_page=100"
        )
        jobs = [
            {"id": 1, "name": "apply", "status": "completed", "run_attempt": 1}
        ]
        artifact_name = "cross-ai-stage-outcome-request-apply-7-1"
        self.transport.add("GET", jobs_url, 200, {"total_count": 1, "jobs": jobs})
        self.transport.add(
            "GET",
            artifacts_url,
            200,
            {
                "total_count": 1,
                "artifacts": [
                    {
                        "id": 88,
                        "name": artifact_name,
                        "size_in_bytes": 1234,
                        "expired": False,
                        "workflow_run": {"id": 7},
                    }
                ],
            },
        )
        self.transport.add("GET", attempt_url, 200, {"id": 7, "run_attempt": 1})
        self.assertEqual(
            self.reader.workflow_run_attempt(2222, repository, 7, 1),
            {"id": 7, "run_attempt": 1},
        )
        self.assertEqual(
            self.reader.workflow_jobs(2222, repository, 7, 1), tuple(jobs)
        )
        artifact = self.reader.workflow_artifact(
            2222, repository, 7, artifact_name
        )
        self.assertEqual(artifact.artifact_id, 88)
        self.assertEqual(artifact.size_in_bytes, 1234)

    def test_rejects_truncated_job_pages_artifact_confusion_and_bad_redirects(self) -> None:
        repository = "Halildeu/platform-k8s-gitops"
        jobs_url = (
            f"https://api.github.com/repos/{repository}/actions/runs/7/attempts/1/jobs"
            "?per_page=100"
        )
        artifacts_url = (
            f"https://api.github.com/repos/{repository}/actions/runs/7/artifacts"
            "?per_page=100"
        )
        self.transport.add("GET", jobs_url, 200, {"total_count": 2, "jobs": [{}]})
        with self.assertRaisesRegex(PolicyError, "GITHUB_JOBS_INVALID"):
            self.reader.workflow_jobs(2222, repository, 7, 1)
        self.transport.add(
            "GET",
            artifacts_url,
            200,
            {
                "total_count": 2,
                "artifacts": [
                    {"id": 1, "name": "same", "size_in_bytes": 1, "expired": False},
                    {"id": 2, "name": "same", "size_in_bytes": 1, "expired": False},
                ],
            },
        )
        with self.assertRaisesRegex(PolicyError, "GITHUB_ARTIFACT_AMBIGUOUS"):
            self.reader.workflow_artifact(2222, repository, 7, "same")
        self.assertEqual(
            _validated_artifact_redirect(
                "https://objects.githubusercontent.com/path/archive.zip?sig=opaque"
            ),
            "https://objects.githubusercontent.com/path/archive.zip?sig=opaque",
        )
        for value in (
            "http://objects.githubusercontent.com/archive.zip",
            "https://objects.githubusercontent.com.evil.test/archive.zip",
            "https://127.0.0.1/archive.zip",
            "https://production.blob.core.windows.net.evil.test/archive.zip",
            "https://objects.githubusercontent.com:invalid/archive.zip",
        ):
            with self.subTest(value=value), self.assertRaisesRegex(
                PolicyError, "GITHUB_ARTIFACT_REDIRECT_INVALID"
            ):
                _validated_artifact_redirect(value)

        with self.assertRaisesRegex(PolicyError, "GITHUB_API_ORIGIN_MISMATCH"):
            GitHubArtifactDownloader(
                token_provider=self.provider,
                api_origin="https://github.example.test",
            )

    def test_artifact_download_does_not_forward_app_token_to_blob_host(self) -> None:
        archive = b"PK-safe-stage-archive"
        location = "https://objects.githubusercontent.com/path/archive.zip?sig=opaque"
        downloader = StubArtifactDownloader(
            token_provider=self.provider,
            responses=[
                HTTPResponse(302, {"Location": location}, b""),
                HTTPResponse(200, {}, archive),
            ],
        )
        result = downloader.download(
            installation_id=2222,
            repository="Halildeu/platform-k8s-gitops",
            artifact=GitHubArtifact(7, "stage", len(archive)),
        )
        self.assertEqual(result, archive)
        self.assertTrue(
            downloader.requests[0].get_header("Authorization").startswith("Bearer ghs_")
        )
        self.assertIsNone(downloader.requests[1].get_header("Authorization"))
        self.assertEqual(downloader.requests[1].full_url, location)

    def test_decision_client_uses_only_reconstructed_route_and_classifies_result(self) -> None:
        repository = "Halildeu/platform-k8s-gitops"
        url = (
            f"https://api.github.com/repos/{repository}/actions/runs/7/"
            "deployment_protection_rule"
        )
        self.transport.add("POST", url, 204, b"")
        client = GitHubDecisionClient(
            token_provider=self.provider, transport=self.transport
        )
        result = client.post_decision(
            installation_id=2222,
            repository=repository,
            run_id=7,
            environment="faz22-view-only-pilot",
            state="approved",
            comment="APPROVED evidence=sha256:abc stage=apply",
        )
        self.assertTrue(result.accepted)
        callback = [call for call in self.transport.calls if call[1] == url][-1]
        self.assertEqual(
            json.loads(callback[3]),
            {
                "comment": "APPROVED evidence=sha256:abc stage=apply",
                "environment_name": "faz22-view-only-pilot",
                "state": "approved",
            },
        )
        self.transport.add("POST", url, 503, {})
        self.assertTrue(
            client.post_decision(
                installation_id=2222,
                repository=repository,
                run_id=7,
                environment="faz22-view-only-pilot",
                state="rejected",
                comment="REJECTED code=POLICY_INVALID",
            ).ambiguous
        )
        self.transport.add("POST", url, 400, {})
        definitive = client.post_decision(
            installation_id=2222,
            repository=repository,
            run_id=7,
            environment="faz22-view-only-pilot",
            state="rejected",
            comment="REJECTED code=POLICY_INVALID",
        )
        self.assertFalse(definitive.ambiguous)
        self.assertFalse(definitive.accepted)

    def test_dispatcher_creates_only_intent_ref_and_no_input_dispatch(self) -> None:
        repository = "Halildeu/platform-k8s-gitops"
        request_id = "30000000-0000-4000-8000-000000000001"
        head = "b" * 40
        create_url = f"https://api.github.com/repos/{repository}/git/refs"
        ref_url = (
            f"https://api.github.com/repos/{repository}/git/ref/"
            f"tags/cross-ai-intent/{request_id}"
        )
        dispatch_url = (
            f"https://api.github.com/repos/{repository}/actions/workflows/"
            ".github%2Fworkflows%2Fapply.yml/dispatches"
        )
        self.transport.add("POST", create_url, 201, {"ref": "created"})
        self.transport.add(
            "GET", ref_url, 200, {"object": {"type": "commit", "sha": head}}
        )
        self.transport.add("POST", dispatch_url, 204, b"")
        dispatcher = GitHubDispatcherClient(
            token_provider=self.provider,
            reader=self.reader,
            transport=self.transport,
        )
        live_ref = dispatcher.create_intent_ref(
            installation_id=2222,
            repository=repository,
            request_id=request_id,
            head_sha=head,
        )
        self.assertEqual(live_ref.head_sha, head)
        dispatcher.dispatch_workflow(
            installation_id=2222,
            repository=repository,
            workflow_path=".github/workflows/apply.yml",
            request_id=request_id,
        )
        create = [call for call in self.transport.calls if call[1] == create_url][-1]
        self.assertEqual(
            json.loads(create[3]),
            {"ref": f"refs/tags/cross-ai-intent/{request_id}", "sha": head},
        )
        dispatch = [call for call in self.transport.calls if call[1] == dispatch_url][-1]
        self.assertEqual(
            json.loads(dispatch[3]),
            {"ref": f"cross-ai-intent/{request_id}"},
        )


if __name__ == "__main__":
    unittest.main()
