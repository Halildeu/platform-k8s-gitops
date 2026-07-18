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
REVIEW_RESULT_SCHEMA_VERSION = "acik.cross-ai-provider-review-result.v1"
MINIMAX_MODEL = "minimax/MiniMax-M3"
CODEX_MODEL = "gpt-5.6-sol"
ROOT = Path(__file__).resolve().parents[3]


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


class DirectMiniMaxRunner:
    def __init__(
        self,
        wrapper: Path | None = None,
        python_executable: Path | None = None,
    ) -> None:
        selected_wrapper = wrapper or ROOT / "scripts/ai/minimax_m3_review.py"
        self.wrapper = selected_wrapper.expanduser().resolve()
        if not self.wrapper.is_file():
            reject("PROVIDER_EXECUTABLE_INVALID", "MiniMax wrapper is invalid")
        selected_python = python_executable or Path(shutil.which("python3") or "python3")
        self.python_executable = DirectClaudeRunner._validated_executable(
            selected_python, "Python"
        )

    def run(
        self,
        *,
        prompt: str,
        model: str,
        workspace: Path,
        timeout_seconds: int = 600,
    ) -> ProviderExecutionReceipt:
        if model != MINIMAX_MODEL:
            reject("PROVIDER_MODEL_UNAVAILABLE", "MiniMax model is not the pinned route")
        prompt_bytes = prompt.encode("utf-8")
        if not prompt_bytes or len(prompt_bytes) > MAX_PROMPT_BYTES:
            reject("PROVIDER_PROMPT_INVALID", "provider prompt size is invalid")
        result = subprocess.run(
            [
                str(self.python_executable),
                str(self.wrapper),
                "--response-contract",
                "provider-review-json-v1",
                "--timeout",
                str(timeout_seconds),
            ],
            cwd=workspace,
            input=prompt_bytes,
            capture_output=True,
            check=False,
            timeout=timeout_seconds + 30,
        )
        if result.returncode != 0:
            reject("PROVIDER_EXECUTION_FAILED", "direct MiniMax execution failed")
        payload = _provider_json(result.stdout, "MiniMax")
        expected = {
            "ok",
            "provider",
            "provider_claim_source",
            "provider_origin_host",
            "requested_model",
            "actual_model",
            "base_sha",
            "head_sha",
            "scope_sha256",
            "verdict",
            "findings_present",
            "transport",
            "transport_sha256",
            "config_sha256",
            "response_sha256",
            "response",
        }
        if set(payload) != expected:
            reject("PROVIDER_OUTPUT_INVALID", "MiniMax receipt shape is invalid")
        if (
            payload["ok"] is not True
            or payload["provider"] != "minimax"
            or payload["provider_claim_source"] != "trusted-bundled-config"
            or payload["provider_origin_host"] != "agent.minimax.io"
            or payload["requested_model"] != MINIMAX_MODEL
            or payload["actual_model"] != MINIMAX_MODEL
            or payload["base_sha"] is not None
            or payload["head_sha"] is not None
            or payload["transport"] != "mavis-bundled-llm-call"
        ):
            reject("PROVIDER_MODEL_IDENTITY_MISMATCH", "MiniMax route differs")
        response = payload["response"]
        if not isinstance(response, str) or not response:
            reject("PROVIDER_OUTPUT_INVALID", "MiniMax result text is invalid")
        response_bytes = response.encode("utf-8")
        prompt_hex = hashlib.sha256(prompt_bytes).hexdigest()
        response_hex = hashlib.sha256(response_bytes).hexdigest()
        digest_fields = (
            payload["scope_sha256"],
            payload["transport_sha256"],
            payload["config_sha256"],
            payload["response_sha256"],
        )
        if any(
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
            for value in digest_fields
        ):
            reject("PROVIDER_OUTPUT_INVALID", "MiniMax receipt digest is invalid")
        if payload["scope_sha256"] != prompt_hex or payload["response_sha256"] != response_hex:
            reject("PROVIDER_OUTPUT_INVALID", "MiniMax receipt digest differs")
        capability = sha256_digest(
            {
                "channel": "direct-minimax-cli",
                "wrapperRealpath": str(self.wrapper),
                "wrapperSha256": _bytes_digest(self.wrapper.read_bytes()),
                "pythonRealpath": str(self.python_executable),
                "providerOriginHost": payload["provider_origin_host"],
                "transportSha256": f"sha256:{payload['transport_sha256']}",
                "configSha256": f"sha256:{payload['config_sha256']}",
                "requestedModel": MINIMAX_MODEL,
                "reportedModel": payload["actual_model"],
            }
        )
        return ProviderExecutionReceipt(
            provider_family="minimax",
            channel="direct-minimax-cli",
            direct_provider_cli=True,
            model_id=MINIMAX_MODEL,
            model_identity_class="provider-reported",
            capability_snapshot_sha256=capability,
            input_sha256=_bytes_digest(prompt_bytes),
            output_sha256=_bytes_digest(response_bytes),
            result_text=response,
        )


class DirectCodexRunner:
    def __init__(self, executable: Path | None = None) -> None:
        selected = executable or Path(shutil.which("codex") or "codex")
        self.executable = DirectClaudeRunner._validated_executable(selected, "Codex")

    @staticmethod
    def _catalog_model(raw: bytes, model: str) -> dict[str, Any]:
        payload = _provider_json(raw, "Codex model catalog")
        models = payload.get("models")
        if not isinstance(models, list):
            reject("PROVIDER_CAPABILITY_UNAVAILABLE", "Codex model list is invalid")
        matches = [entry for entry in models if isinstance(entry, dict) and entry.get("slug") == model]
        if len(matches) != 1:
            reject("PROVIDER_MODEL_UNAVAILABLE", "Codex model is not live-listed")
        selected = matches[0]
        if selected.get("visibility") != "list" or selected.get("supported_in_api") is not True:
            reject("PROVIDER_MODEL_UNAVAILABLE", "Codex model is not supported")
        return selected

    @staticmethod
    def _terminal_result(raw: bytes) -> str:
        if not raw or len(raw) > MAX_PROVIDER_OUTPUT_BYTES:
            reject("PROVIDER_OUTPUT_INVALID", "Codex output size is invalid")
        try:
            lines = raw.decode("utf-8").splitlines()
        except UnicodeDecodeError:
            reject("PROVIDER_OUTPUT_INVALID", "Codex output is not UTF-8")
        events = [_provider_json(line.encode("utf-8"), "Codex event") for line in lines if line]
        if not events or events[0].get("type") != "thread.started":
            reject("PROVIDER_OUTPUT_INVALID", "Codex thread start is missing")
        if len([event for event in events if event.get("type") == "turn.started"]) != 1:
            reject("PROVIDER_OUTPUT_INVALID", "Codex turn start is ambiguous")
        completed = [event for event in events if event.get("type") == "turn.completed"]
        if len(completed) != 1 or events[-1] is not completed[0]:
            reject("PROVIDER_OUTPUT_INVALID", "Codex completed turn is not terminal")
        messages: list[str] = []
        for event in events:
            event_type = event.get("type")
            if event_type in {"thread.started", "turn.started", "turn.completed"}:
                continue
            if event_type != "item.completed":
                reject("PROVIDER_TOOL_EVENT_REJECTED", "Codex emitted a non-terminal event")
            item = event.get("item")
            if not isinstance(item, dict):
                reject("PROVIDER_OUTPUT_INVALID", "Codex item is invalid")
            item_type = item.get("type")
            if item_type == "reasoning":
                continue
            if item_type != "agent_message":
                reject("PROVIDER_TOOL_EVENT_REJECTED", "Codex used or exposed a tool")
            text = item.get("text")
            if not isinstance(text, str) or not text:
                reject("PROVIDER_OUTPUT_INVALID", "Codex message is invalid")
            messages.append(text)
        if len(messages) != 1:
            reject("PROVIDER_OUTPUT_INVALID", "Codex terminal message is not singular")
        return messages[0]

    def run(
        self,
        *,
        prompt: str,
        model: str,
        workspace: Path,
        timeout_seconds: int = 600,
    ) -> ProviderExecutionReceipt:
        if model != CODEX_MODEL:
            reject("PROVIDER_MODEL_UNAVAILABLE", "Codex model is not the pinned route")
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
        catalog = subprocess.run(
            [str(self.executable), "--ignore-user-config", "debug", "models"],
            cwd=workspace,
            capture_output=True,
            check=False,
            timeout=60,
        )
        if version.returncode != 0 or not version.stdout or catalog.returncode != 0:
            reject("PROVIDER_CAPABILITY_UNAVAILABLE", "Codex capability is unavailable")
        self._catalog_model(catalog.stdout, model)
        launch = {
            "ignoreUserConfig": True,
            "sandbox": "read-only",
            "ephemeral": True,
            "json": True,
            "mcp": False,
            "plugins": False,
            "search": False,
            "write": False,
        }
        result = subprocess.run(
            [
                str(self.executable),
                "exec",
                "--ignore-user-config",
                "--model",
                model,
                "--sandbox",
                "read-only",
                "--ephemeral",
                "--json",
                "-C",
                str(workspace.resolve()),
                "-",
            ],
            cwd=workspace,
            input=prompt_bytes,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
        if result.returncode != 0:
            reject("PROVIDER_EXECUTION_FAILED", "direct Codex execution failed")
        text = self._terminal_result(result.stdout)
        capability = sha256_digest(
            {
                "channel": "openai-codex",
                "cliRealpath": str(self.executable),
                "cliSha256": _bytes_digest(self.executable.read_bytes()),
                "cliVersionSha256": _bytes_digest(version.stdout.strip()),
                "liveModelCatalogSha256": _bytes_digest(catalog.stdout),
                "requestedModel": CODEX_MODEL,
                "providerReportedModel": None,
                "launchConfiguration": launch,
            }
        )
        return ProviderExecutionReceipt(
            provider_family="openai",
            channel="openai-codex",
            direct_provider_cli=True,
            model_id=CODEX_MODEL,
            model_identity_class="trusted-launch-attested",
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
            "schemaVersion",
            "verdict",
            "findingIds",
            "resolvedFindingIds",
            "acknowledgedFindingIds",
        }
        if (
            set(payload) != expected
            or payload.get("schemaVersion") != REVIEW_RESULT_SCHEMA_VERSION
            or payload.get("verdict") not in {"AGREE", "REVISE", "RED", "PARTIAL"}
        ):
            reject("PROVIDER_REVIEW_RESULT_INVALID", "provider review result shape is invalid")
        for field in expected - {"schemaVersion", "verdict"}:
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
    "CODEX_MODEL",
    "CursorRunner",
    "DirectClaudeRunner",
    "DirectCodexRunner",
    "DirectMiniMaxRunner",
    "MINIMAX_MODEL",
    "ProviderExecutionReceipt",
    "ProviderReviewIssuer",
    "REVIEW_RESULT_SCHEMA_VERSION",
    "ReviewCoordinates",
]
