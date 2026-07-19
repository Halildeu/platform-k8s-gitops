"""Provider-specific execution receipts and signed review issuance."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

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
CODEX_ROUTINE_MODEL = "gpt-5.3-codex-spark"
CODEX_HIGH_IMPACT_MODEL = "gpt-5.6-sol"
CODEX_MODELS = frozenset({CODEX_ROUTINE_MODEL, CODEX_HIGH_IMPACT_MODEL})
# Compatibility name for existing high-impact/Faz 22 consumers. It must never
# be interpreted as a wildcard or a routine-route alias.
CODEX_MODEL = CODEX_HIGH_IMPACT_MODEL
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
    provider_session_id: str | None
    provider_transcript_sha256: str | None
    capability_snapshot: dict[str, Any] | None
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
        # Historical implementation remains below only for forensic source
        # archaeology and is unreachable by construction.
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
            reasoning_effort="xhigh",
            sandbox="read-only",
            ephemeral=True,
            provider_session_id=None,
            provider_transcript_sha256=None,
            capability_snapshot=None,
            capability_snapshot_sha256=capability,
            input_sha256=_bytes_digest(prompt_bytes),
            output_sha256=_bytes_digest(text.encode("utf-8")),
            result_text=text,
        )


class DirectCodexRunner:
    def __init__(self, executable: Path | None = None) -> None:
        selected = executable or Path(shutil.which("codex") or "codex")
        self.executable = self._validated_native_executable(selected)

    @staticmethod
    def _validated_native_executable(path: Path) -> Path:
        """Resolve only a native Codex binary or the official npm wrapper.

        A PATH-injected shell/Python shim must never receive the provider-review
        signing route.  The official npm entrypoint is resolved to its bundled
        platform-native binary before the private execution copy is made.
        """

        resolved = DirectClaudeRunner._validated_executable(path, "Codex")
        try:
            with resolved.open("rb") as handle:
                header = handle.read(4)
            mode = resolved.stat().st_mode
        except OSError:
            reject("PROVIDER_EXECUTABLE_INVALID", "Codex executable cannot be inspected")
        native_magic = (
            header == b"\x7fELF"
            or header[:2] == b"MZ"
            or header
            in {
                b"\xfe\xed\xfa\xce",
                b"\xce\xfa\xed\xfe",
                b"\xfe\xed\xfa\xcf",
                b"\xcf\xfa\xed\xfe",
                b"\xca\xfe\xba\xbe",
                b"\xbe\xba\xfe\xca",
            }
        )
        if native_magic:
            if mode & 0o022:
                reject(
                    "PROVIDER_EXECUTABLE_INVALID",
                    "Codex native executable is group/world writable",
                )
            return resolved
        if resolved.name != "codex.js" or resolved.parent.name != "bin":
            reject(
                "PROVIDER_EXECUTABLE_INVALID",
                "Codex executable is neither native nor the official npm wrapper",
            )
        package_root = resolved.parent.parent
        if package_root.name != "codex" or package_root.parent.name != "@openai":
            reject(
                "PROVIDER_EXECUTABLE_INVALID",
                "Codex npm wrapper is outside the official package layout",
            )
        candidates = [
            candidate.resolve()
            for candidate in package_root.glob(
                "node_modules/@openai/codex-*/vendor/*/bin/codex"
            )
            if candidate.is_file() and os.access(candidate, os.X_OK)
        ]
        if len(candidates) != 1:
            reject(
                "PROVIDER_EXECUTABLE_INVALID",
                "Codex npm wrapper does not resolve to one native platform binary",
            )
        native = candidates[0]
        try:
            with native.open("rb") as handle:
                native_header = handle.read(4)
            native_mode = native.stat().st_mode
        except OSError:
            reject("PROVIDER_EXECUTABLE_INVALID", "Codex native binary is unavailable")
        if (
            native_header == b"\x7fELF"
            or native_header[:2] == b"MZ"
            or native_header
            in {
                b"\xfe\xed\xfa\xce",
                b"\xce\xfa\xed\xfe",
                b"\xfe\xed\xfa\xcf",
                b"\xcf\xfa\xed\xfe",
                b"\xca\xfe\xba\xbe",
                b"\xbe\xba\xfe\xca",
            }
        ) and not (native_mode & 0o022):
            return native
        reject(
            "PROVIDER_EXECUTABLE_INVALID",
            "Codex package native binary is mutable or invalid",
        )

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
    def _terminal_result(raw: bytes) -> tuple[str, str]:
        if not raw or len(raw) > MAX_PROVIDER_OUTPUT_BYTES:
            reject("PROVIDER_OUTPUT_INVALID", "Codex output size is invalid")
        try:
            lines = raw.decode("utf-8").splitlines()
        except UnicodeDecodeError:
            reject("PROVIDER_OUTPUT_INVALID", "Codex output is not UTF-8")
        events = [_provider_json(line.encode("utf-8"), "Codex event") for line in lines if line]
        if not events or events[0].get("type") != "thread.started":
            reject("PROVIDER_OUTPUT_INVALID", "Codex thread start is missing")
        thread_events = [event for event in events if event.get("type") == "thread.started"]
        if len(thread_events) != 1:
            reject("PROVIDER_OUTPUT_INVALID", "Codex thread identity is ambiguous")
        thread_id = thread_events[0].get("thread_id")
        try:
            canonical_thread_id = str(UUID(str(thread_id)))
        except (ValueError, AttributeError):
            reject("PROVIDER_SESSION_ID_INVALID", "Codex thread identity is invalid")
        if canonical_thread_id != thread_id:
            reject("PROVIDER_SESSION_ID_INVALID", "Codex thread identity is not canonical")
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
        return messages[0], canonical_thread_id

    def run(
        self,
        *,
        prompt: str,
        model: str,
        workspace: Path,
        timeout_seconds: int = 600,
    ) -> ProviderExecutionReceipt:
        if model not in CODEX_MODELS:
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
        text, thread_id = self._terminal_result(result.stdout)
        public_execution_arguments = list(execution_command[1:])
        workspace_index = public_execution_arguments.index("-C") + 1
        public_execution_arguments[workspace_index] = "<BOUND_WORKSPACE>"
        capability_snapshot = {
            "schemaVersion": "acik.direct-codex-launch-attestation.v1",
            "channel": "openai-codex",
            "cliRealpathSha256": _bytes_digest(str(self.executable).encode("utf-8")),
            "cliSha256": pinned_digest,
            "executableIdentityClass": "private-content-copy",
            "cliVersionSha256": _bytes_digest(version.stdout.strip()),
            "liveModelCatalogSha256": _bytes_digest(catalog.stdout),
            "requestedModel": model,
            "providerReportedModel": None,
            "reasoningEffort": "xhigh",
            "sandbox": "read-only",
            "ephemeral": True,
            "launchConfiguration": {
                "catalogArguments": catalog_command[1:],
                "executionArguments": public_execution_arguments,
            },
        }
        capability = sha256_digest(capability_snapshot)
        return ProviderExecutionReceipt(
            provider_family="openai",
            channel="openai-codex",
            direct_provider_cli=True,
            model_id=model,
            model_identity_class="trusted-launch-attested",
            reasoning_effort="xhigh",
            sandbox="read-only",
            ephemeral=True,
            provider_session_id=thread_id,
            provider_transcript_sha256=_bytes_digest(result.stdout),
            capability_snapshot=capability_snapshot,
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
        # Historical implementation remains below only for forensic source
        # archaeology and is unreachable by construction.
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
            reasoning_effort="xhigh",
            sandbox="read-only",
            ephemeral=True,
            provider_session_id=None,
            provider_transcript_sha256=None,
            capability_snapshot=None,
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
                parsed = UUID(value)
            except (AttributeError, ValueError):
                reject("PROVIDER_REVIEW_COORDINATES_INVALID", f"{label} is not a UUID")
            if str(parsed) != value:
                reject(
                    "PROVIDER_REVIEW_COORDINATES_INVALID",
                    f"{label} is not a canonical UUID",
                )
        for label, value in (
            ("subjectSha256", coordinates.subject_sha256),
            ("closureRootSha256", coordinates.closure_root_sha256),
        ):
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
        if coordinates.round > 1 and (
            not isinstance(previous, str)
            or len(previous) != 71
            or not previous.startswith("sha256:")
            or any(character not in "0123456789abcdef" for character in previous[7:])
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
                    or any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for character in value)
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
            or execution.provider_session_id is None
            or execution.provider_transcript_sha256 is None
            or execution.capability_snapshot is None
            or sha256_digest(execution.capability_snapshot)
            != execution.capability_snapshot_sha256
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
            "providerSessionId": execution.provider_session_id,
            "providerTranscriptSha256": execution.provider_transcript_sha256,
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
    "CODEX_HIGH_IMPACT_MODEL",
    "CODEX_MODEL",
    "CODEX_MODELS",
    "CODEX_ROUTINE_MODEL",
    "DirectCodexRunner",
    "ProviderExecutionReceipt",
    "ProviderReviewIssuer",
    "REVIEW_RESULT_SCHEMA_VERSION",
    "ReviewCoordinates",
]
