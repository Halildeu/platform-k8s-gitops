#!/usr/bin/env python3
"""Fetch and verify one runner bootstrap response before any side effect."""

from __future__ import annotations

import argparse
import hashlib
import os
import stat
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from scripts.github_apps.cross_ai_deployment_policy.canonical import (
    canonical_bytes,
    sha256_digest,
)
from scripts.github_apps.cross_ai_deployment_policy.contract import EvidenceVerifier
from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError, reject
from scripts.github_apps.cross_ai_deployment_policy.jsonutil import (
    load_json_file,
    loads_json_bytes,
)
from scripts.github_apps.cross_ai_deployment_policy.outcome import verify_stage_outcome
from scripts.github_apps.cross_ai_deployment_policy.oidc import AUDIENCE
from scripts.github_apps.cross_ai_deployment_policy.policy import load_policy
from scripts.github_apps.cross_ai_deployment_policy.timeutil import utc_now


ROOT = Path(__file__).resolve().parents[2]
RESPONSE_SCHEMA = ROOT / "schema/cross-ai-runner-bootstrap-response-v1.schema.json"
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
STAGES = {"apply", "browser-evidence", "compensating-rollback"}
ZERO_TRUST_ROOT_SHA256 = "sha256:" + ("0" * 64)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def _validated_endpoint(value: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError:
        reject("BOOTSTRAP_ENDPOINT_INVALID", "bootstrap endpoint is invalid")
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != "/v1/runner-bootstrap"
        or parsed.query
        or parsed.fragment
        or port not in {None, 443}
    ):
        reject(
            "BOOTSTRAP_ENDPOINT_INVALID",
            "bootstrap endpoint must be exact HTTPS runner-bootstrap URL",
        )
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    return f"{parsed.scheme}://{host}{f':{port}' if port else ''}{parsed.path}"


def _required_env(name: str, *, minimum: int = 1, maximum: int = 512) -> str:
    value = os.environ.get(name)
    if (
        not isinstance(value, str)
        or not minimum <= len(value) <= maximum
        or any(character in value for character in "\r\n\x00")
    ):
        reject("BOOTSTRAP_ENV_INVALID", f"required runtime value {name} is invalid")
    return value


def _positive_env(name: str) -> int:
    value = _required_env(name, maximum=20)
    if not value.isascii() or not value.isdigit() or value.startswith("0"):
        reject("BOOTSTRAP_ENV_INVALID", f"runtime value {name} is not positive")
    number = int(value)
    if number < 1:
        reject("BOOTSTRAP_ENV_INVALID", f"runtime value {name} is not positive")
    return number


def _sha256_text(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _validate_response_schema(response: dict[str, Any]) -> None:
    schema = load_json_file(RESPONSE_SCHEMA)
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(
            response
        ),
        key=lambda item: list(item.path),
    )
    if errors:
        reject(
            "BOOTSTRAP_RESPONSE_SCHEMA_INVALID",
            "bootstrap response does not match the pinned schema",
        )


def _write_exclusive(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError:
        reject("BOOTSTRAP_OUTPUT_INVALID", "bootstrap output must be a new file")
    try:
        os.write(descriptor, canonical_bytes(value))
        os.fsync(descriptor)
        if stat.S_IMODE(os.fstat(descriptor).st_mode) != 0o600:
            reject("BOOTSTRAP_OUTPUT_INVALID", "bootstrap output mode is not private")
    finally:
        os.close(descriptor)


def _github_oidc_token() -> str:
    raw_url = _required_env("ACTIONS_ID_TOKEN_REQUEST_URL", maximum=4096)
    request_token = _required_env(
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN", minimum=20, maximum=4096
    )
    os.environ.pop("ACTIONS_ID_TOKEN_REQUEST_TOKEN", None)
    try:
        parsed = urllib.parse.urlsplit(raw_url)
        query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    except ValueError:
        reject("BOOTSTRAP_OIDC_ENDPOINT_INVALID", "GitHub OIDC request URL is invalid")
    hostname = parsed.hostname or ""
    if (
        parsed.scheme != "https"
        or not hostname.endswith(".actions.githubusercontent.com")
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or not parsed.path.startswith("/")
        or parsed.fragment
        or any(name == "audience" for name, _value in query)
    ):
        reject(
            "BOOTSTRAP_OIDC_ENDPOINT_INVALID",
            "GitHub OIDC request URL is outside the pinned origin profile",
        )
    query.append(("audience", AUDIENCE))
    oidc_url = urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), "")
    )
    request = urllib.request.Request(
        oidc_url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {request_token}",
            "User-Agent": "acik-cross-ai-runner-bootstrap/1",
        },
    )
    request_token = ""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=10) as response:
            if (
                response.status != 200
                or response.headers.get_content_type() != "application/json"
            ):
                reject(
                    "BOOTSTRAP_OIDC_UNAVAILABLE",
                    "GitHub OIDC endpoint response is invalid",
                )
            raw = response.read(64 * 1024 + 1)
    except urllib.error.HTTPError:
        reject("BOOTSTRAP_OIDC_UNAVAILABLE", "GitHub OIDC endpoint rejected request")
    except (urllib.error.URLError, TimeoutError, OSError):
        reject("BOOTSTRAP_OIDC_UNAVAILABLE", "GitHub OIDC endpoint is unavailable")
    if len(raw) > 64 * 1024:
        reject("BOOTSTRAP_OIDC_INVALID", "GitHub OIDC response is oversized")
    value = loads_json_bytes(raw, max_bytes=64 * 1024, label="GitHub OIDC response")
    token = value.get("value")
    if (
        not isinstance(token, str)
        or not 100 <= len(token) <= 32 * 1024
        or token.count(".") != 2
    ):
        reject("BOOTSTRAP_OIDC_INVALID", "GitHub OIDC response has no compact JWT")
    return token


def _request(
    endpoint: str,
    token: str,
    oidc_token: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    request = urllib.request.Request(
        endpoint,
        data=canonical_bytes(body),
        method="POST",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {oidc_token}",
            "Content-Type": "application/json",
            "User-Agent": "acik-cross-ai-runner-bootstrap/1",
            "X-Cross-AI-Bootstrap-Credential": token,
        },
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=15) as response:
            if response.status != 200:
                reject("BOOTSTRAP_HTTP_REJECTED", "bootstrap endpoint rejected request")
            content_type = response.headers.get_content_type()
            if content_type != "application/json":
                reject(
                    "BOOTSTRAP_HTTP_INVALID",
                    "bootstrap response content type is invalid",
                )
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError:
        reject("BOOTSTRAP_HTTP_REJECTED", "bootstrap endpoint rejected request")
    except (urllib.error.URLError, TimeoutError, OSError):
        reject("BOOTSTRAP_HTTP_UNAVAILABLE", "bootstrap endpoint is unavailable")
    if len(raw) > MAX_RESPONSE_BYTES:
        reject("BOOTSTRAP_HTTP_INVALID", "bootstrap response exceeds size limit")
    response = loads_json_bytes(
        raw, max_bytes=MAX_RESPONSE_BYTES, label="bootstrap response"
    )
    if canonical_bytes(response) != raw:
        reject(
            "BOOTSTRAP_RESPONSE_NONCANONICAL",
            "bootstrap response is not canonical JSON",
        )
    return response


def execute(args: argparse.Namespace) -> dict[str, Any]:
    if args.stage not in STAGES:
        reject("BOOTSTRAP_STAGE_INVALID", "bootstrap stage is invalid")
    if args.expected_trust_root_sha256 == ZERO_TRUST_ROOT_SHA256:
        reject(
            "TRUST_ROOT_PIN_SENTINEL",
            "all-zero trust-root pin cannot authorize a protected stage",
        )
    policy = load_policy(args.policy_file)
    stage_policy = policy.stages.get(args.stage)
    if stage_policy is None or stage_policy.workflow_path != args.workflow_path:
        reject("BOOTSTRAP_STAGE_INVALID", "workflow path is not stage-allowlisted")
    endpoint = _validated_endpoint(
        _required_env("CROSS_AI_BOOTSTRAP_URL", maximum=2048)
    )
    if endpoint != policy.runner_bootstrap_url:
        reject(
            "BOOTSTRAP_ENDPOINT_POLICY_MISMATCH",
            "bootstrap endpoint differs from the signed policy",
        )
    token = _required_env("CROSS_AI_BOOTSTRAP_TOKEN", minimum=64)
    os.environ.pop("CROSS_AI_BOOTSTRAP_TOKEN", None)
    ref = _required_env("GITHUB_REF", maximum=200)
    prefix = "refs/tags/cross-ai-intent/"
    if not ref.startswith(prefix):
        reject("BOOTSTRAP_REF_INVALID", "workflow did not start from an intent ref")
    request_id = ref.removeprefix(prefix)
    head_sha = _required_env("GITHUB_SHA", minimum=40, maximum=40)
    run_id = _positive_env("GITHUB_RUN_ID")
    run_attempt = _positive_env("GITHUB_RUN_ATTEMPT")
    runner_name = _required_env("RUNNER_NAME", maximum=200)
    body = {
        "requestId": request_id,
        "stage": args.stage,
        "runId": run_id,
        "runAttempt": run_attempt,
        "intentRef": ref,
        "headSha": head_sha,
        "workflowPath": args.workflow_path,
        "runnerName": runner_name,
    }
    oidc_token = _github_oidc_token()
    response = _request(endpoint, token, oidc_token, body)
    oidc_token = ""
    token_digest = _sha256_text(token)
    token = ""
    _validate_response_schema(response)
    response_digest = response["responseSha256"]
    unsigned_response = dict(response)
    del unsigned_response["responseSha256"]
    if sha256_digest(unsigned_response) != response_digest:
        reject(
            "BOOTSTRAP_RESPONSE_DIGEST_MISMATCH", "bootstrap response digest differs"
        )
    exact = {
        "requestId": request_id,
        "stage": args.stage,
        "runId": run_id,
        "runAttempt": run_attempt,
        "headSha": head_sha,
        "intentRef": ref,
        "workflowPath": args.workflow_path,
    }
    if any(response.get(key) != value for key, value in exact.items()):
        reject(
            "BOOTSTRAP_RESPONSE_BINDING_MISMATCH", "bootstrap response differs from run"
        )

    trust_root = load_json_file(args.trust_root_file)
    verified = EvidenceVerifier(
        trust_root=trust_root,
        revocations_envelope=load_json_file(args.revocations_file),
        now=utc_now(),
        expected_policy_sha256=policy.digest,
        expected_trust_root_sha256=args.expected_trust_root_sha256,
    ).verify_bundle(response["bundleEnvelope"])
    subject = verified.payload["subject"]
    if (
        verified.bundle_digest != response["bundleSha256"]
        or verified.request_id != request_id
        or subject["headSha"] != head_sha
        or subject["intentRef"] != ref
        or subject["repositoryId"] != policy.repository_id
        or subject["repository"] != policy.repository
        or subject["environment"] != policy.environment
        or subject["bootstrapCredentialSha256"] != token_digest
    ):
        reject(
            "BOOTSTRAP_BUNDLE_BINDING_MISMATCH", "signed bundle differs from bootstrap"
        )
    endpoint_id = _required_env("CROSS_AI_ENDPOINT_ID", maximum=512)
    operator_id = _required_env("CROSS_AI_OPERATOR_ID", maximum=512)
    if (
        _sha256_text(endpoint_id) != subject["endpointIdSha256"]
        or _sha256_text(operator_id) != subject["operatorIdSha256"]
        or endpoint_id == operator_id
    ):
        reject(
            "BOOTSTRAP_OPAQUE_BINDING_MISMATCH",
            "Environment endpoint/operator identities differ from the signed subject",
        )

    prior = response["priorStageOutcome"]
    prior_digest = response["priorStageOutcomeSha256"]
    prior_state = response["priorStageState"]
    if args.stage == "apply":
        if any(
            response[field] is not None
            for field in (
                "priorStage",
                "priorStageState",
                "priorStageOutcomeSha256",
                "priorStageOutcome",
            )
        ):
            reject(
                "BOOTSTRAP_PRIOR_OUTCOME_INVALID", "apply must not have a prior outcome"
            )
    elif prior is None:
        if args.stage != "compensating-rollback" or prior_state != "CallbackUnknown":
            reject(
                "BOOTSTRAP_PRIOR_OUTCOME_INVALID", "required prior outcome is absent"
            )
    else:
        if response["priorStage"] != "apply" or sha256_digest(prior) != prior_digest:
            reject("BOOTSTRAP_PRIOR_OUTCOME_INVALID", "prior outcome digest differs")
        verified_outcome = verify_stage_outcome(
            prior,
            bundle=verified,
            expected_stage="apply",
            expected_run_id=prior["runId"],
            expected_run_attempt=prior["runAttempt"],
            expected_run_started_at=prior["runStartedAt"],
            expected_critical_jobs_sha256=prior["criticalJobsSha256"],
            expected_source_artifact_name=prior["sourceArtifactName"],
            expected_source_archive_sha256=prior["sourceArchiveSha256"],
            now=utc_now(),
        )
        required_state = "Succeeded" if args.stage == "browser-evidence" else "Failed"
        if (
            verified_outcome.target_state != required_state
            or prior_state != required_state
        ):
            reject(
                "BOOTSTRAP_PRIOR_OUTCOME_INVALID",
                "prior outcome state is not stage-safe",
            )
    _write_exclusive(args.output, response)
    return response


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify one Cross-AI runner bootstrap")
    parser.add_argument("--stage", choices=sorted(STAGES), required=True)
    parser.add_argument("--workflow-path", required=True)
    parser.add_argument("--policy-file", type=Path, required=True)
    parser.add_argument("--trust-root-file", type=Path, required=True)
    parser.add_argument("--expected-trust-root-sha256", required=True)
    parser.add_argument("--revocations-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        execute(parse_args(argv))
    except PolicyError as exc:
        print(f"FAIL: {exc.code}", file=__import__("sys").stderr)
        return 2
    print("PASS: signed runner bootstrap verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
