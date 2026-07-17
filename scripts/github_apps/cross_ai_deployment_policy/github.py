"""Least-privilege GitHub App authentication and read-side truth client."""

from __future__ import annotations

import base64
import binascii
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import quote, urlencode, urlsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from .canonical import canonical_bytes
from .errors import PolicyError, reject
from .timeutil import parse_utc


API_VERSION = "2022-11-28"
MAX_GITHUB_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_STAGE_ARTIFACT_BYTES = 16 * 1024 * 1024
REPOSITORY_NAME = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class HTTPResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True)
class GitHubIntentRef:
    ref_object_id: str
    head_sha: str
    annotated: bool


@dataclass(frozen=True)
class CallbackResult:
    accepted: bool
    ambiguous: bool
    status: int | None
    reason_code: str


@dataclass(frozen=True)
class GitHubArtifact:
    artifact_id: int
    name: str
    size_in_bytes: int


class Transport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None = None,
        timeout: float = 10.0,
    ) -> HTTPResponse: ...


class UrllibTransport:
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None = None,
        timeout: float = 10.0,
    ) -> HTTPResponse:
        request = urllib.request.Request(
            url,
            data=body,
            headers=dict(headers),
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = response.read(MAX_GITHUB_RESPONSE_BYTES + 1)
                if len(data) > MAX_GITHUB_RESPONSE_BYTES:
                    reject("GITHUB_RESPONSE_TOO_LARGE", "GitHub response exceeds limit")
                return HTTPResponse(response.status, dict(response.headers.items()), data)
        except urllib.error.HTTPError as exc:
            data = exc.read(MAX_GITHUB_RESPONSE_BYTES + 1)
            return HTTPResponse(exc.code, dict(exc.headers.items()), data)
        except (urllib.error.URLError, TimeoutError, OSError):
            reject("GITHUB_API_UNAVAILABLE", "GitHub API request failed")


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


@dataclass
class _CachedToken:
    token: str
    expires_at: datetime


class GitHubAppTokenProvider:
    def __init__(
        self,
        *,
        app_id: int,
        private_key_file: Path,
        api_origin: str = "https://api.github.com",
        transport: Transport | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if app_id < 1:
            reject("GITHUB_APP_ID_INVALID", "GitHub App ID must be positive")
        parsed = urlsplit(api_origin)
        if parsed.scheme != "https" or parsed.path or parsed.query or parsed.fragment:
            reject("GITHUB_API_ORIGIN_INVALID", "GitHub API origin must be canonical HTTPS")
        self.app_id = app_id
        self.api_origin = api_origin
        self.transport = transport or UrllibTransport()
        self._now = now or (lambda: datetime.now(timezone.utc))
        try:
            pem = private_key_file.read_bytes()
        except OSError as exc:
            reject("GITHUB_APP_KEY_UNAVAILABLE", f"cannot read GitHub App key file: {exc}")
        if len(pem) > 64 * 1024:
            reject("GITHUB_APP_KEY_INVALID", "GitHub App key file exceeds limit")
        try:
            key = serialization.load_pem_private_key(pem, password=None)
        except (TypeError, ValueError):
            reject("GITHUB_APP_KEY_INVALID", "GitHub App private key is invalid")
        if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < 2048:
            reject("GITHUB_APP_KEY_INVALID", "GitHub App key must be RSA 2048 bits or stronger")
        self._key = key
        self._tokens: dict[int, _CachedToken] = {}

    def _jwt(self) -> str:
        now = self._now()
        header = {"alg": "RS256", "typ": "JWT"}
        payload = {
            "iat": int((now - timedelta(seconds=60)).timestamp()),
            "exp": int((now + timedelta(minutes=9)).timestamp()),
            "iss": str(self.app_id),
        }
        signing_input = (
            _b64url(canonical_bytes(header)) + "." + _b64url(canonical_bytes(payload))
        ).encode("ascii")
        signature = self._key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
        return signing_input.decode("ascii") + "." + _b64url(signature)

    def token(self, installation_id: int) -> str:
        if installation_id < 1:
            reject("GITHUB_INSTALLATION_ID_INVALID", "installation ID must be positive")
        now = self._now()
        cached = self._tokens.get(installation_id)
        if cached and cached.expires_at > now + timedelta(minutes=2):
            return cached.token
        response = self.transport.request(
            "POST",
            f"{self.api_origin}/app/installations/{installation_id}/access_tokens",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._jwt()}",
                "X-GitHub-Api-Version": API_VERSION,
                "User-Agent": "acik-cross-ai-deployment-policy/1",
                "Content-Type": "application/json",
            },
            body=b"{}",
        )
        if response.status != 201:
            reject("GITHUB_INSTALLATION_TOKEN_FAILED", "installation token request failed")
        payload = _json_object(response.body, "installation token")
        token = payload.get("token")
        expires_at = parse_utc(payload.get("expires_at"), "installationToken.expires_at")
        if not isinstance(token, str) or len(token) < 20:
            reject("GITHUB_INSTALLATION_TOKEN_INVALID", "installation token response is invalid")
        if expires_at <= now + timedelta(minutes=2):
            reject("GITHUB_INSTALLATION_TOKEN_INVALID", "installation token expires too soon")
        self._tokens[installation_id] = _CachedToken(token=token, expires_at=expires_at)
        return token


def _json_object(body: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        reject("GITHUB_RESPONSE_INVALID", f"{label} response is not JSON")
    if not isinstance(value, dict):
        reject("GITHUB_RESPONSE_INVALID", f"{label} response is not an object")
    return value


class GitHubReader:
    def __init__(
        self,
        *,
        token_provider: GitHubAppTokenProvider,
        api_origin: str = "https://api.github.com",
        transport: Transport | None = None,
    ) -> None:
        self.token_provider = token_provider
        if api_origin != token_provider.api_origin:
            reject(
                "GITHUB_API_ORIGIN_MISMATCH",
                "reader and token provider must use the same API origin",
            )
        self.api_origin = api_origin
        self.transport = transport or token_provider.transport

    def _get(
        self,
        installation_id: int,
        path: str,
        *,
        query: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.api_origin}{path}"
        if query:
            url += "?" + urlencode(query)
        response = self.transport.request(
            "GET",
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token_provider.token(installation_id)}",
                "X-GitHub-Api-Version": API_VERSION,
                "User-Agent": "acik-cross-ai-deployment-policy/1",
            },
        )
        if response.status != 200:
            reject("GITHUB_TRUTH_READ_FAILED", f"GitHub truth read returned {response.status}")
        return _json_object(response.body, "GitHub truth")

    def repository(self, installation_id: int, repository: str) -> dict[str, Any]:
        return self._get(installation_id, f"/repos/{repository}")

    def workflow_run(
        self,
        installation_id: int,
        repository: str,
        run_id: int,
    ) -> dict[str, Any]:
        return self._get(
            installation_id,
            f"/repos/{repository}/actions/runs/{run_id}",
        )

    def intent_ref(
        self,
        installation_id: int,
        repository: str,
        request_id: str,
    ) -> GitHubIntentRef:
        ref = quote(f"tags/cross-ai-intent/{request_id}", safe="/")
        value = self._get(
            installation_id,
            f"/repos/{repository}/git/ref/{ref}",
        )
        target = value.get("object")
        if not isinstance(target, dict):
            reject("GITHUB_REF_INVALID", "intent ref target is missing")
        target_type = target.get("type")
        target_sha = target.get("sha")
        if not isinstance(target_sha, str):
            reject("GITHUB_REF_INVALID", "intent ref SHA is missing")
        if target_type == "commit":
            return GitHubIntentRef(
                ref_object_id=target_sha,
                head_sha=target_sha,
                annotated=False,
            )
        if target_type != "tag":
            reject("GITHUB_REF_INVALID", "intent ref must target a commit or annotated tag")
        tag = self._get(
            installation_id,
            f"/repos/{repository}/git/tags/{quote(target_sha, safe='')}",
        )
        tagged = tag.get("object")
        if (
            not isinstance(tagged, dict)
            or tagged.get("type") != "commit"
            or not isinstance(tagged.get("sha"), str)
        ):
            reject("GITHUB_REF_INVALID", "annotated intent tag must target one commit")
        return GitHubIntentRef(
            ref_object_id=target_sha,
            head_sha=tagged["sha"],
            annotated=True,
        )

    def intent_ref_head(
        self,
        installation_id: int,
        repository: str,
        request_id: str,
    ) -> str:
        return self.intent_ref(installation_id, repository, request_id).head_sha

    def workflow_bytes(
        self,
        installation_id: int,
        repository: str,
        workflow_path: str,
        head_sha: str,
    ) -> bytes:
        path = quote(workflow_path, safe="/")
        value = self._get(
            installation_id,
            f"/repos/{repository}/contents/{path}",
            query={"ref": head_sha},
        )
        if value.get("type") != "file" or value.get("encoding") != "base64":
            reject("GITHUB_WORKFLOW_INVALID", "workflow content response is not a Base64 file")
        content = value.get("content")
        if not isinstance(content, str):
            reject("GITHUB_WORKFLOW_INVALID", "workflow content is missing")
        compact_content = "".join(content.split())
        try:
            raw = base64.b64decode(compact_content, validate=True)
        except (binascii.Error, ValueError):
            reject("GITHUB_WORKFLOW_INVALID", "workflow content Base64 is invalid")
        if len(raw) > 1024 * 1024:
            reject("GITHUB_WORKFLOW_INVALID", "workflow exceeds one MiB")
        return raw

    def environment(
        self,
        installation_id: int,
        repository: str,
        environment: str,
    ) -> dict[str, Any]:
        return self._get(
            installation_id,
            f"/repos/{repository}/environments/{quote(environment, safe='')}",
        )

    def workflow_run_attempt(
        self,
        installation_id: int,
        repository: str,
        run_id: int,
        run_attempt: int,
    ) -> dict[str, Any]:
        if min(run_id, run_attempt) < 1:
            reject("GITHUB_RUN_ATTEMPT_INVALID", "workflow run attempt is invalid")
        return self._get(
            installation_id,
            f"/repos/{repository}/actions/runs/{run_id}/attempts/{run_attempt}",
        )

    def workflow_jobs(
        self,
        installation_id: int,
        repository: str,
        run_id: int,
        run_attempt: int,
    ) -> tuple[dict[str, Any], ...]:
        if min(run_id, run_attempt) < 1:
            reject("GITHUB_RUN_ATTEMPT_INVALID", "workflow run attempt is invalid")
        value = self._get(
            installation_id,
            f"/repos/{repository}/actions/runs/{run_id}/attempts/{run_attempt}/jobs",
            query={"per_page": "100"},
        )
        jobs = value.get("jobs")
        total = value.get("total_count")
        if (
            not isinstance(jobs, list)
            or not isinstance(total, int)
            or isinstance(total, bool)
            or total != len(jobs)
            or not 1 <= total <= 100
            or not all(isinstance(job, dict) for job in jobs)
            or any(job.get("run_attempt") != run_attempt for job in jobs)
        ):
            reject("GITHUB_JOBS_INVALID", "workflow jobs response is incomplete or invalid")
        return tuple(jobs)

    def workflow_artifact(
        self,
        installation_id: int,
        repository: str,
        run_id: int,
        artifact_name: str,
    ) -> GitHubArtifact:
        value = self._get(
            installation_id,
            f"/repos/{repository}/actions/runs/{run_id}/artifacts",
            query={"per_page": "100"},
        )
        artifacts = value.get("artifacts")
        total = value.get("total_count")
        if (
            not isinstance(artifacts, list)
            or not isinstance(total, int)
            or isinstance(total, bool)
            or total != len(artifacts)
            or not 0 <= total <= 100
        ):
            reject("GITHUB_ARTIFACT_LIST_INVALID", "artifact list is incomplete or invalid")
        matches = [
            item for item in artifacts
            if isinstance(item, dict) and item.get("name") == artifact_name
        ]
        if len(matches) != 1:
            reject("GITHUB_ARTIFACT_AMBIGUOUS", "exactly one stage artifact is required")
        artifact = matches[0]
        artifact_id = artifact.get("id")
        size = artifact.get("size_in_bytes")
        if (
            not isinstance(artifact_id, int)
            or isinstance(artifact_id, bool)
            or artifact_id < 1
            or not isinstance(size, int)
            or isinstance(size, bool)
            or not 1 <= size <= MAX_STAGE_ARTIFACT_BYTES
            or artifact.get("expired") is not False
        ):
            reject("GITHUB_ARTIFACT_INVALID", "stage artifact metadata is invalid")
        workflow_run = artifact.get("workflow_run")
        if workflow_run is not None and (
            not isinstance(workflow_run, dict) or workflow_run.get("id") != run_id
        ):
            reject("GITHUB_ARTIFACT_INVALID", "artifact belongs to another workflow run")
        return GitHubArtifact(
            artifact_id=artifact_id,
            name=artifact_name,
            size_in_bytes=size,
        )


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def _validated_artifact_redirect(value: str) -> str:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        reject("GITHUB_ARTIFACT_REDIRECT_INVALID", "artifact redirect is not allowlisted")
    hostname = parsed.hostname or ""
    allowed = hostname == "objects.githubusercontent.com" or hostname.endswith(
        ".blob.core.windows.net"
    )
    if (
        parsed.scheme != "https"
        or not allowed
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or not parsed.path.startswith("/")
        or parsed.fragment
    ):
        reject("GITHUB_ARTIFACT_REDIRECT_INVALID", "artifact redirect is not allowlisted")
    return value


class GitHubArtifactDownloader:
    """Download one bounded Actions artifact without forwarding App auth on redirect."""

    def __init__(
        self,
        *,
        token_provider: GitHubAppTokenProvider,
        api_origin: str = "https://api.github.com",
    ) -> None:
        if api_origin != token_provider.api_origin:
            reject("GITHUB_API_ORIGIN_MISMATCH", "artifact downloader origin differs")
        self.token_provider = token_provider
        self.api_origin = api_origin
        self._opener = urllib.request.build_opener(_NoRedirectHandler())

    def _open(self, request: urllib.request.Request) -> HTTPResponse:
        try:
            with self._opener.open(request, timeout=15.0) as response:
                data = response.read(MAX_STAGE_ARTIFACT_BYTES + 1)
                if len(data) > MAX_STAGE_ARTIFACT_BYTES:
                    reject("GITHUB_ARTIFACT_TOO_LARGE", "artifact archive exceeds limit")
                return HTTPResponse(response.status, dict(response.headers.items()), data)
        except urllib.error.HTTPError as exc:
            return HTTPResponse(exc.code, dict(exc.headers.items()), b"")
        except (urllib.error.URLError, TimeoutError, OSError):
            reject("GITHUB_API_UNAVAILABLE", "artifact download request failed")

    def download(
        self,
        *,
        installation_id: int,
        repository: str,
        artifact: GitHubArtifact,
    ) -> bytes:
        if REPOSITORY_NAME.fullmatch(repository) is None:
            reject("GITHUB_ARTIFACT_INVALID", "repository is invalid")
        api_url = (
            f"{self.api_origin}/repos/{repository}/actions/artifacts/"
            f"{artifact.artifact_id}/zip"
        )
        first = self._open(
            urllib.request.Request(
                api_url,
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {self.token_provider.token(installation_id)}",
                    "X-GitHub-Api-Version": API_VERSION,
                    "User-Agent": "acik-cross-ai-deployment-policy/1",
                },
                method="GET",
            )
        )
        location = first.headers.get("Location") or first.headers.get("location")
        if first.status != 302 or not isinstance(location, str):
            reject("GITHUB_ARTIFACT_DOWNLOAD_FAILED", "artifact API did not return a redirect")
        redirect = _validated_artifact_redirect(location)
        second = self._open(
            urllib.request.Request(
                redirect,
                headers={"User-Agent": "acik-cross-ai-deployment-policy/1"},
                method="GET",
            )
        )
        if second.status != 200 or len(second.body) != artifact.size_in_bytes:
            reject("GITHUB_ARTIFACT_DOWNLOAD_FAILED", "artifact bytes differ from metadata")
        return second.body


class GitHubDecisionClient:
    """Narrow client for the one documented deployment-rule decision route."""

    def __init__(
        self,
        *,
        token_provider: GitHubAppTokenProvider,
        api_origin: str = "https://api.github.com",
        transport: Transport | None = None,
    ) -> None:
        if api_origin != token_provider.api_origin:
            reject(
                "GITHUB_API_ORIGIN_MISMATCH",
                "decision client and token provider must use the same API origin",
            )
        self.token_provider = token_provider
        self.api_origin = api_origin
        self.transport = transport or token_provider.transport

    def post_decision(
        self,
        *,
        installation_id: int,
        repository: str,
        run_id: int,
        environment: str,
        state: str,
        comment: str,
    ) -> CallbackResult:
        if REPOSITORY_NAME.fullmatch(repository) is None or run_id < 1:
            reject("GITHUB_CALLBACK_TARGET_INVALID", "callback target is invalid")
        if state not in {"approved", "rejected"}:
            reject("GITHUB_CALLBACK_STATE_INVALID", "callback state is invalid")
        if (
            not isinstance(environment, str)
            or not 1 <= len(environment) <= 120
            or not isinstance(comment, str)
            or not 1 <= len(comment) <= 1024
            or any(ord(character) < 0x20 or ord(character) > 0x7E for character in comment)
        ):
            reject("GITHUB_CALLBACK_BODY_INVALID", "callback body is invalid")
        body = canonical_bytes(
            {
                "comment": comment,
                "environment_name": environment,
                "state": state,
            }
        )
        url = (
            f"{self.api_origin}/repos/{repository}/actions/runs/{run_id}/"
            "deployment_protection_rule"
        )
        try:
            response = self.transport.request(
                "POST",
                url,
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {self.token_provider.token(installation_id)}",
                    "X-GitHub-Api-Version": API_VERSION,
                    "User-Agent": "acik-cross-ai-deployment-policy/1",
                    "Content-Type": "application/json",
                },
                body=body,
            )
        except PolicyError as exc:
            if exc.code == "GITHUB_API_UNAVAILABLE":
                return CallbackResult(False, True, None, "CALLBACK_TRANSPORT_AMBIGUOUS")
            raise
        if response.status == 204:
            if response.body:
                return CallbackResult(False, True, 204, "CALLBACK_RESPONSE_AMBIGUOUS")
            return CallbackResult(True, False, 204, "CALLBACK_ACCEPTED_204")
        if response.status in {408, 409, 422, 425, 429} or 500 <= response.status <= 599:
            return CallbackResult(False, True, response.status, "CALLBACK_HTTP_AMBIGUOUS")
        return CallbackResult(False, False, response.status, "CALLBACK_HTTP_REJECTED")


class GitHubDispatcherClient:
    """Dedicated App surface: create immutable intent refs and dispatch no-input workflows."""

    def __init__(
        self,
        *,
        token_provider: GitHubAppTokenProvider,
        reader: GitHubReader,
        api_origin: str = "https://api.github.com",
        transport: Transport | None = None,
    ) -> None:
        if api_origin != token_provider.api_origin or reader.api_origin != api_origin:
            reject("GITHUB_API_ORIGIN_MISMATCH", "dispatcher GitHub origins differ")
        self.token_provider = token_provider
        self.reader = reader
        self.api_origin = api_origin
        self.transport = transport or token_provider.transport

    def _post(
        self,
        *,
        installation_id: int,
        path: str,
        payload: dict[str, Any],
    ) -> HTTPResponse:
        return self.transport.request(
            "POST",
            f"{self.api_origin}{path}",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token_provider.token(installation_id)}",
                "X-GitHub-Api-Version": API_VERSION,
                "User-Agent": "acik-cross-ai-intent-dispatcher/1",
                "Content-Type": "application/json",
            },
            body=canonical_bytes(payload),
        )

    def create_intent_ref(
        self,
        *,
        installation_id: int,
        repository: str,
        request_id: str,
        head_sha: str,
    ) -> GitHubIntentRef:
        if REPOSITORY_NAME.fullmatch(repository) is None or not re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
            request_id,
        ) or not re.fullmatch(r"[a-f0-9]{40}", head_sha):
            reject("GITHUB_INTENT_REF_INVALID", "intent ref request is invalid")
        response = self._post(
            installation_id=installation_id,
            path=f"/repos/{repository}/git/refs",
            payload={
                "ref": f"refs/tags/cross-ai-intent/{request_id}",
                "sha": head_sha,
            },
        )
        if response.status not in {201, 422}:
            reject("GITHUB_INTENT_REF_CREATE_FAILED", "intent ref creation failed")
        live_ref = self.reader.intent_ref(installation_id, repository, request_id)
        if live_ref.head_sha != head_sha:
            reject("GITHUB_INTENT_REF_COLLISION", "existing intent ref points elsewhere")
        return live_ref

    def dispatch_workflow(
        self,
        *,
        installation_id: int,
        repository: str,
        workflow_path: str,
        request_id: str,
    ) -> None:
        if REPOSITORY_NAME.fullmatch(repository) is None or not workflow_path.startswith(
            ".github/workflows/"
        ) or not re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
            request_id,
        ):
            reject("GITHUB_WORKFLOW_DISPATCH_INVALID", "workflow dispatch target is invalid")
        workflow = quote(workflow_path, safe="")
        response = self._post(
            installation_id=installation_id,
            path=f"/repos/{repository}/actions/workflows/{workflow}/dispatches",
            payload={"ref": f"cross-ai-intent/{request_id}"},
        )
        if response.status != 204 or response.body:
            reject("GITHUB_WORKFLOW_DISPATCH_FAILED", "workflow dispatch was not accepted")

__all__ = [
    "GitHubArtifact",
    "GitHubArtifactDownloader",
    "GitHubAppTokenProvider",
    "GitHubDecisionClient",
    "GitHubDispatcherClient",
    "GitHubIntentRef",
    "CallbackResult",
    "GitHubReader",
    "HTTPResponse",
    "Transport",
    "UrllibTransport",
]
