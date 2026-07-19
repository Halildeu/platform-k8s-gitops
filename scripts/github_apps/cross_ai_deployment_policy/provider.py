"""Provider-specific execution receipts and signed review issuance."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Protocol

from jsonschema import Draft202012Validator, FormatChecker

from .canonical import sha256_digest
from .contract import (
    REVIEW_PAYLOAD_TYPE_V2,
    REVIEW_SCHEMA_V2,
)
from .errors import reject
from .jsonutil import load_json_file
from .timeutil import parse_utc


MAX_PROVIDER_OUTPUT_BYTES = 2 * 1024 * 1024
MAX_PROMPT_BYTES = 512 * 1024
REVIEW_RESULT_SCHEMA_VERSION = "acik.cross-ai-provider-review-result.v1"
CLAUDE_MODEL = "claude-opus-4-8"
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
    reasoning_effort: str
    sandbox: str
    ephemeral: bool
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
        del prompt, model, workspace, timeout_seconds
        reject(
            "PROVIDER_ROUTE_RETIRED",
            "Claude execution is retired; active review accepts direct Codex only",
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
        catalog_command = [str(self.executable), "debug", "models"]
        execution_command = [
            str(self.executable),
            "exec",
            "--ignore-user-config",
            "--ignore-rules",
            "-c",
            'model_reasoning_effort="xhigh"',
            "--model",
            model,
            "--sandbox",
            "read-only",
            "--ephemeral",
            "--json",
            "-C",
            str(workspace.resolve()),
            "-",
        ]
        try:
            with tempfile.TemporaryDirectory(
                prefix="cross-ai-codex-", dir=workspace.resolve()
            ) as directory:
                pinned_executable = Path(directory) / "codex"
                shutil.copyfile(self.executable, pinned_executable)
                pinned_executable.chmod(0o500)
                pinned_digest = _bytes_digest(pinned_executable.read_bytes())
                dispatch = {"executable": str(pinned_executable)}
                version = subprocess.run(
                    [str(self.executable), "--version"],
                    cwd=workspace,
                    capture_output=True,
                    check=False,
                    timeout=30,
                    **dispatch,
                )
                catalog = subprocess.run(
                    catalog_command,
                    cwd=workspace,
                    capture_output=True,
                    check=False,
                    timeout=60,
                    **dispatch,
                )
                if (
                    version.returncode != 0
                    or not version.stdout
                    or catalog.returncode != 0
                ):
                    reject(
                        "PROVIDER_CAPABILITY_UNAVAILABLE",
                        "Codex capability is unavailable",
                    )
                self._catalog_model(catalog.stdout, model)
                result = subprocess.run(
                    execution_command,
                    cwd=workspace,
                    input=prompt_bytes,
                    capture_output=True,
                    check=False,
                    timeout=timeout_seconds,
                    **dispatch,
                )
                if _bytes_digest(pinned_executable.read_bytes()) != pinned_digest:
                    reject(
                        "PROVIDER_EXECUTABLE_CHANGED",
                        "Codex executable changed during execution",
                    )
        except OSError:
            reject(
                "PROVIDER_EXECUTABLE_PIN_FAILED",
                "Codex executable could not be pinned for execution",
            )
        if result.returncode != 0:
            reject("PROVIDER_EXECUTION_FAILED", "direct Codex execution failed")
        text = self._terminal_result(result.stdout)
        capability = sha256_digest(
            {
                "channel": "openai-codex",
                "cliRealpath": str(self.executable),
                "cliSha256": pinned_digest,
                "executableIdentityClass": "private-content-copy",
                "cliVersionSha256": _bytes_digest(version.stdout.strip()),
                "liveModelCatalogSha256": _bytes_digest(catalog.stdout),
                "requestedModel": CODEX_MODEL,
                "providerReportedModel": None,
                "launchConfiguration": {
                    "catalogArguments": catalog_command[1:],
                    "executionArguments": execution_command[1:],
                },
            }
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
        del prompt, model, workspace, provider_family, timeout_seconds
        reject(
            "PROVIDER_ROUTE_RETIRED",
            "Cursor execution is retired; active review accepts direct Codex only",
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
        contract_version: str = "v2",
    ) -> None:
        self.signer = signer
        self.provider_family = provider_family
        self.channel = channel
        self.direct_provider_cli = direct_provider_cli
        self.model_identity_class = model_identity_class
        self.allowed_models = allowed_models
        self.issuer = issuer
        if contract_version == "v1":
            reject(
                "LEGACY_CONTRACT_READ_ONLY",
                "v1 evidence may be verified for history but cannot be issued",
            )
        if contract_version == "v2":
            self.review_schema_version = "acik.cross-ai-deployment-review.v2"
            self.review_schema = REVIEW_SCHEMA_V2
            self.review_payload_type = REVIEW_PAYLOAD_TYPE_V2
        else:
            reject(
                "PROVIDER_CONTRACT_VERSION_INVALID",
                "provider issuer contract version is unsupported",
            )

    @staticmethod
    def validate_coordinates(coordinates: ReviewCoordinates) -> None:
        for label, value in (
            ("reviewId", coordinates.review_id),
            ("reviewChainId", coordinates.review_chain_id),
        ):
            try:
                parsed = uuid.UUID(value)
            except (AttributeError, ValueError):
                reject("PROVIDER_REVIEW_COORDINATES_INVALID", f"{label} is not a UUID")
            if str(parsed) != value:
                reject(
                    "PROVIDER_REVIEW_COORDINATES_INVALID",
                    f"{label} is not a canonical UUID",
                )
        digest_fields = (
            ("subjectSha256", coordinates.subject_sha256),
            ("closureRootSha256", coordinates.closure_root_sha256),
        )
        for label, value in digest_fields:
            if (
                not isinstance(value, str)
                or len(value) != 71
                or not value.startswith("sha256:")
                or any(character not in "0123456789abcdef" for character in value[7:])
            ):
                reject(
                    "PROVIDER_REVIEW_COORDINATES_INVALID",
                    f"{label} is not a canonical SHA-256 digest",
                )
        if not isinstance(coordinates.round, int) or not 1 <= coordinates.round <= 100:
            reject("PROVIDER_REVIEW_COORDINATES_INVALID", "round is invalid")
        previous = coordinates.previous_round_sha256
        if coordinates.round == 1 and previous is not None:
            reject(
                "PROVIDER_REVIEW_COORDINATES_INVALID",
                "round one cannot reference a previous review",
            )
        if coordinates.round > 1:
            if (
                not isinstance(previous, str)
                or len(previous) != 71
                or not previous.startswith("sha256:")
                or any(
                    character not in "0123456789abcdef"
                    for character in previous[7:]
                )
            ):
                reject(
                    "PROVIDER_REVIEW_COORDINATES_INVALID",
                    "later rounds require a canonical previous-review digest",
                )
        issued_at = parse_utc(coordinates.issued_at, "review.issuedAt")
        expires_at = parse_utc(coordinates.expires_at, "review.expiresAt")
        if expires_at <= issued_at or expires_at - issued_at > timedelta(minutes=120):
            reject("REVIEW_LIFETIME_INVALID", "review lifetime must be within 120 minutes")

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
            or execution.reasoning_effort != "xhigh"
            or execution.sandbox != "read-only"
            or execution.ephemeral is not True
        ):
            reject("PROVIDER_ISSUER_POLICY_MISMATCH", "execution receipt differs from issuer policy")
        self.validate_coordinates(coordinates)
        result = self._review_result(execution.result_text)
        findings_projection = {
            "verdict": result["verdict"],
            "findingIds": result["findingIds"],
            "resolvedFindingIds": result["resolvedFindingIds"],
            "acknowledgedFindingIds": result["acknowledgedFindingIds"],
        }
        payload = {
            "schemaVersion": self.review_schema_version,
            "reviewId": coordinates.review_id,
            "reviewChainId": coordinates.review_chain_id,
            "providerFamily": self.provider_family,
            "channel": self.channel,
            "directProviderCli": self.direct_provider_cli,
            "modelId": execution.model_id,
            "modelIdentityClass": execution.model_identity_class,
            "reasoningEffort": execution.reasoning_effort,
            "sandbox": execution.sandbox,
            "ephemeral": execution.ephemeral,
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
        schema = load_json_file(self.review_schema)
        errors = sorted(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(payload),
            key=lambda item: list(item.path),
        )
        if errors:
            reject("PROVIDER_REVIEW_RESULT_INVALID", "issued review does not satisfy schema")
        return self.signer.sign_json_envelope(
            payload_type=self.review_payload_type,
            payload=payload,
        )


__all__ = [
    "CLAUDE_MODEL",
    "CODEX_MODEL",
    "DirectCodexRunner",
    "ProviderExecutionReceipt",
    "ProviderReviewIssuer",
    "REVIEW_RESULT_SCHEMA_VERSION",
    "ReviewCoordinates",
]
