"""Provider-specific execution receipts and signed review issuance."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Protocol

from jsonschema import Draft202012Validator, FormatChecker

from .canonical import sha256_digest
from .contract import REVIEW_PAYLOAD_TYPE, REVIEW_SCHEMA
from .errors import reject
from .jsonutil import load_json_file
from .timeutil import parse_utc


MAX_PROVIDER_OUTPUT_BYTES = 2 * 1024 * 1024
MAX_PROMPT_BYTES = 512 * 1024


def _bytes_digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _no_duplicate_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            reject("PROVIDER_OUTPUT_DUPLICATE_KEY", f"duplicate provider JSON key {key}")
        result[key] = value
    return result


def _provider_json(raw: bytes, label: str) -> dict[str, Any]:
    if not raw or len(raw) > MAX_PROVIDER_OUTPUT_BYTES:
        reject("PROVIDER_OUTPUT_INVALID", f"{label} output size is invalid")
    try:
        value = json.loads(raw, object_pairs_hook=_no_duplicate_object)
    except (UnicodeDecodeError, json.JSONDecodeError):
        reject("PROVIDER_OUTPUT_INVALID", f"{label} output is not JSON")
    if not isinstance(value, dict):
        reject("PROVIDER_OUTPUT_INVALID", f"{label} output is not an object")
    return value


@dataclass(frozen=True)
class ProviderExecutionReceipt:
    provider_family: str
    channel: str
    direct_provider_cli: bool
    model_id: str
    model_identity_class: str
    capability_snapshot_sha256: str
    input_sha256: str
    output_sha256: str
    result_text: str


class EnvelopeSigner(Protocol):
    @property
    def key_id(self) -> str: ...

    def sign_json_envelope(
        self, *, payload_type: str, payload: dict[str, Any]
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ReviewCoordinates:
    review_id: str
    review_chain_id: str
    subject_sha256: str
    round: int
    previous_round_sha256: str | None
    closure_root_sha256: str
    issued_at: str
    expires_at: str


class DirectClaudeRunner:
    def __init__(self, executable: Path | None = None) -> None:
        selected = executable or Path(shutil.which("claude") or "claude")
        self.executable = self._validated_executable(selected, "Claude")

    @staticmethod
    def _validated_executable(path: Path, label: str) -> Path:
        resolved = path.expanduser().resolve()
        if not resolved.is_file() or not os.access(resolved, os.X_OK):
            reject("PROVIDER_EXECUTABLE_INVALID", f"{label} executable is invalid")
        return resolved

    def run(
        self,
        *,
        prompt: str,
        model: str,
        workspace: Path,
        timeout_seconds: int = 600,
    ) -> ProviderExecutionReceipt:
        prompt_bytes = prompt.encode("utf-8")
        if not prompt_bytes or len(prompt_bytes) > MAX_PROMPT_BYTES:
            reject("PROVIDER_PROMPT_INVALID", "provider prompt size is invalid")
        version = subprocess.run(
            [str(self.executable), "--version"],
            cwd=workspace,
            capture_output=True,
            check=False,
            timeout=30,
        )
        if version.returncode != 0 or not version.stdout:
            reject("PROVIDER_CAPABILITY_UNAVAILABLE", "Claude CLI version is unavailable")
        result = subprocess.run(
            [
                str(self.executable),
                "-p",
                "--output-format",
                "json",
                "--model",
                model,
                "--permission-mode",
                "plan",
                "--tools",
                "",
                "--no-session-persistence",
            ],
            cwd=workspace,
            input=prompt_bytes,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
        if result.returncode != 0:
            reject("PROVIDER_EXECUTION_FAILED", "direct Claude execution failed")
        payload = _provider_json(result.stdout, "Claude")
        if payload.get("type") != "result" or payload.get("subtype") != "success" or payload.get("is_error") is not False:
            reject("PROVIDER_EXECUTION_FAILED", "direct Claude did not return success")
        model_usage = payload.get("modelUsage")
        if not isinstance(model_usage, dict) or len(model_usage) != 1:
            reject("PROVIDER_MODEL_IDENTITY_MISSING", "Claude modelUsage is not singular")
        reported_model = next(iter(model_usage))
        if reported_model != model:
            reject("PROVIDER_MODEL_IDENTITY_MISMATCH", "Claude reported a different model")
        text = payload.get("result")
        if not isinstance(text, str) or not text or len(text.encode("utf-8")) > MAX_PROVIDER_OUTPUT_BYTES:
            reject("PROVIDER_OUTPUT_INVALID", "Claude result text is invalid")
        capability = sha256_digest(
            {
                "channel": "direct-anthropic-cli",
                "cliVersionSha256": _bytes_digest(version.stdout.strip()),
                "requestedModel": model,
                "reportedModels": sorted(model_usage),
            }
        )
        return ProviderExecutionReceipt(
            provider_family="anthropic",
            channel="direct-anthropic-cli",
            direct_provider_cli=True,
            model_id=reported_model,
            model_identity_class="provider-reported",
            capability_snapshot_sha256=capability,
            input_sha256=_bytes_digest(prompt_bytes),
            output_sha256=_bytes_digest(text.encode("utf-8")),
            result_text=text,
        )


class CursorRunner:
    def __init__(
        self,
        executable: Path | None = None,
    ) -> None:
        selected = executable or Path(shutil.which("agent") or "agent")
        self.executable = DirectClaudeRunner._validated_executable(selected, "Cursor")

    def run(
        self,
        *,
        prompt: str,
        model: str,
        workspace: Path,
        provider_family: str,
        timeout_seconds: int = 600,
    ) -> ProviderExecutionReceipt:
        prompt_bytes = prompt.encode("utf-8")
        if not prompt_bytes or len(prompt_bytes) > MAX_PROMPT_BYTES:
            reject("PROVIDER_PROMPT_INVALID", "provider prompt size is invalid")
        version = subprocess.run(
            [str(self.executable), "--version"],
            cwd=workspace,
            capture_output=True,
            check=False,
            timeout=30,
        )
        models = subprocess.run(
            [str(self.executable), "--list-models"],
            cwd=workspace,
            capture_output=True,
            check=False,
            timeout=60,
        )
        if version.returncode != 0 or models.returncode != 0:
            reject("PROVIDER_CAPABILITY_UNAVAILABLE", "Cursor capability list is unavailable")
        try:
            model_lines = models.stdout.decode("utf-8").splitlines()
        except UnicodeDecodeError:
            reject("PROVIDER_CAPABILITY_UNAVAILABLE", "Cursor model list is not UTF-8")
        model_ids = {
            line.split(" - ", 1)[0].strip()
            for line in model_lines
            if " - " in line
        }
        if model not in model_ids:
            reject("PROVIDER_MODEL_UNAVAILABLE", "requested Cursor model is not live-listed")
        result = subprocess.run(
            [
                str(self.executable),
                "-p",
                "--output-format",
                "json",
                "--mode",
                "ask",
                "--trust",
                "--sandbox",
                "enabled",
                "--workspace",
                str(workspace),
                "--model",
                model,
            ],
            cwd=workspace,
            input=prompt_bytes,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
        if result.returncode != 0:
            reject("PROVIDER_EXECUTION_FAILED", "Cursor execution failed")
        payload = _provider_json(result.stdout, "Cursor")
        if payload.get("type") != "result" or payload.get("subtype") != "success" or payload.get("is_error") is not False:
            reject("PROVIDER_EXECUTION_FAILED", "Cursor did not return success")
        text = payload.get("result")
        if not isinstance(text, str) or not text or len(text.encode("utf-8")) > MAX_PROVIDER_OUTPUT_BYTES:
            reject("PROVIDER_OUTPUT_INVALID", "Cursor result text is invalid")
        capability = sha256_digest(
            {
                "channel": "cursor-cli",
                "cliVersionSha256": _bytes_digest(version.stdout.strip()),
                "liveModelListSha256": _bytes_digest(models.stdout),
                "launchedModel": model,
            }
        )
        return ProviderExecutionReceipt(
            provider_family=provider_family,
            channel="cursor-cli",
            direct_provider_cli=False,
            model_id=model,
            model_identity_class="trusted-launch-attested",
            capability_snapshot_sha256=capability,
            input_sha256=_bytes_digest(prompt_bytes),
            output_sha256=_bytes_digest(text.encode("utf-8")),
            result_text=text,
        )


class ProviderReviewIssuer:
    def __init__(
        self,
        *,
        signer: EnvelopeSigner,
        provider_family: str,
        channel: str,
        direct_provider_cli: bool,
        model_identity_class: str,
        allowed_models: frozenset[str],
        issuer: str,
    ) -> None:
        self.signer = signer
        self.provider_family = provider_family
        self.channel = channel
        self.direct_provider_cli = direct_provider_cli
        self.model_identity_class = model_identity_class
        self.allowed_models = allowed_models
        self.issuer = issuer

    @staticmethod
    def _review_result(text: str) -> dict[str, Any]:
        payload = _provider_json(text.encode("utf-8"), "review result")
        expected = {
            "verdict",
            "findingIds",
            "resolvedFindingIds",
            "acknowledgedFindingIds",
        }
        if set(payload) != expected or payload.get("verdict") not in {"AGREE", "REVISE", "RED", "PARTIAL"}:
            reject("PROVIDER_REVIEW_RESULT_INVALID", "provider review result shape is invalid")
        for field in expected - {"verdict"}:
            values = payload[field]
            if (
                not isinstance(values, list)
                or len(values) != len(set(values))
                or any(
                    not isinstance(value, str)
                    or not 2 <= len(value) <= 64
                    or value.upper() != value
                    for value in values
                )
            ):
                reject("PROVIDER_REVIEW_RESULT_INVALID", f"{field} is invalid")
        return payload

    def issue(
        self,
        *,
        execution: ProviderExecutionReceipt,
        coordinates: ReviewCoordinates,
    ) -> dict[str, Any]:
        if (
            execution.provider_family != self.provider_family
            or execution.channel != self.channel
            or execution.direct_provider_cli is not self.direct_provider_cli
            or execution.model_identity_class != self.model_identity_class
            or execution.model_id not in self.allowed_models
        ):
            reject("PROVIDER_ISSUER_POLICY_MISMATCH", "execution receipt differs from issuer policy")
        issued_at = parse_utc(coordinates.issued_at, "review.issuedAt")
        expires_at = parse_utc(coordinates.expires_at, "review.expiresAt")
        if expires_at <= issued_at or expires_at - issued_at > timedelta(minutes=120):
            reject("REVIEW_LIFETIME_INVALID", "review lifetime must be within 120 minutes")
        result = self._review_result(execution.result_text)
        findings_projection = {
            "verdict": result["verdict"],
            "findingIds": result["findingIds"],
            "resolvedFindingIds": result["resolvedFindingIds"],
            "acknowledgedFindingIds": result["acknowledgedFindingIds"],
        }
        payload = {
            "schemaVersion": "acik.cross-ai-deployment-review.v1",
            "reviewId": coordinates.review_id,
            "reviewChainId": coordinates.review_chain_id,
            "providerFamily": self.provider_family,
            "channel": self.channel,
            "directProviderCli": self.direct_provider_cli,
            "modelId": execution.model_id,
            "modelIdentityClass": execution.model_identity_class,
            "capabilitySnapshotSha256": execution.capability_snapshot_sha256,
            "subjectSha256": coordinates.subject_sha256,
            "round": coordinates.round,
            "verdict": result["verdict"],
            "inputSha256": execution.input_sha256,
            "outputSha256": execution.output_sha256,
            "findingsSha256": sha256_digest(findings_projection),
            "previousRoundSha256": coordinates.previous_round_sha256,
            "findingIds": result["findingIds"],
            "resolvedFindingIds": result["resolvedFindingIds"],
            "acknowledgedFindingIds": result["acknowledgedFindingIds"],
            "closureRootSha256": coordinates.closure_root_sha256,
            "issuedAt": coordinates.issued_at,
            "expiresAt": coordinates.expires_at,
            "issuer": self.issuer,
            "keyId": self.signer.key_id,
        }
        schema = load_json_file(REVIEW_SCHEMA)
        errors = sorted(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(payload),
            key=lambda item: list(item.path),
        )
        if errors:
            reject("PROVIDER_REVIEW_RESULT_INVALID", "issued review does not satisfy schema")
        return self.signer.sign_json_envelope(
            payload_type=REVIEW_PAYLOAD_TYPE,
            payload=payload,
        )


__all__ = [
    "CursorRunner",
    "DirectClaudeRunner",
    "ProviderExecutionReceipt",
    "ProviderReviewIssuer",
    "ReviewCoordinates",
]
