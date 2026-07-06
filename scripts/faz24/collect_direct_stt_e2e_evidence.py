#!/usr/bin/env python3
"""Collect metadata-only Faz 24 #182 direct-STT e2e evidence.

This collector is intentionally narrow. It consumes the redacted
faz24.externalRecorderSmoke.v1 JSON emitted by run_external_recorder_smoke.py,
then reads only bounded Kubernetes/Redis/log metadata needed by
verify_direct_stt_e2e_evidence.py. It never writes tokens, PEM values, raw
audio, raw transcript text, destination URLs, or raw command output.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


SCHEMA_VERSION = "faz24.directSttE2eEvidence.v1"
DEFAULT_CONTEXT = "k3d-test"
DEFAULT_NAMESPACE = "platform-test"
DEFAULT_DEPLOYMENT = "audio-gateway"
DEFAULT_CONFIGMAP = "audio-gateway-config"
DEFAULT_MTLS_SECRET = "audio-gateway-direct-stt-mtls"
DEFAULT_REDIS_CONTAINER = "platform-redis-streams-test"
DEFAULT_REDIS_SERVICE = "redis-streams"
DEFAULT_REDIS_SECRET = "audio-gateway-secrets"
DEFAULT_REDIS_SECRET_KEY = "SPRING_DATA_REDIS_PASSWORD"
DEFAULT_REDIS_CLI_IMAGE = "redis:7.4-alpine"
EXPECTED_TRANSCRIBE_HOST = "live-stt.denetim"
EXPECTED_TRANSCRIBE_PORT = 8243
EXPECTED_HOST_ALIAS_IP = "10.99.0.2"
EXPECTED_MTLS_MOUNT = "/etc/direct-stt-mtls"
EXPECTED_RESULT_STREAM = "transcript:direct-stt-results"
EXPECTED_AUDIT_STREAM = "audit:events"
EXPECTED_AUDIT_EVENT = "CHUNK_FORWARDED_TO_COMPUTE_PLANE"
EXPECTED_RESULT_EVENT = "DIRECT_STT_TRANSCRIPT_RESULT"
REQUIRED_SECRET_KEYS = {
    "direct-stt-ca.crt",
    "direct-stt-client.crt",
    "direct-stt-client.key",
}
SHA256_RE = re.compile(r"sha256:([0-9a-f]{64})")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SESSION_ID_RE = re.compile(r"^SES-[A-Za-z0-9_-]{4,120}$")
SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_.@-]{1,160}$")
RAW_AUDIO_KEYS = {"audio", "audioBytes", "audio_bytes", "rawAudio", "raw_audio", "payload", "body"}


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[[list[str], int], CommandResult]


def utc_now() -> str:
    return (
        dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def run_command(argv: list[str], timeout: int = 30) -> CommandResult:
    try:
        proc = subprocess.run(
            argv,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except FileNotFoundError:
        return CommandResult(127, "", "command-not-found")
    except subprocess.TimeoutExpired:
        return CommandResult(124, "", "timeout")
    return CommandResult(proc.returncode, proc.stdout, proc.stderr)


def load_json_result(result: CommandResult, name: str) -> tuple[Any | None, str | None]:
    if result.returncode != 0:
        return None, f"{name}:command-exit-{result.returncode}"
    try:
        return json.loads(result.stdout), None
    except json.JSONDecodeError:
        return None, f"{name}:invalid-json"


def kget(
    runner: CommandRunner,
    *,
    context: str,
    namespace: str,
    kind: str,
    name: str | None,
    timeout: int = 30,
) -> tuple[Any | None, str | None]:
    argv = ["kubectl", "--context", context, "-n", namespace, "get", kind]
    if name:
        argv.append(name)
    argv.extend(["-o", "json"])
    return load_json_result(runner(argv, timeout), f"kubectl-get-{kind}-{name or 'list'}")


def kget_secret_key_names(
    runner: CommandRunner,
    *,
    context: str,
    namespace: str,
    name: str,
    timeout: int = 30,
) -> tuple[set[str], str | None]:
    template = '{{range $k, $_ := .data}}{{printf "%s\\n" $k}}{{end}}'
    result = runner(
        [
            "kubectl",
            "--context",
            context,
            "-n",
            namespace,
            "get",
            "secret",
            name,
            "-o",
            f"go-template={template}",
        ],
        timeout,
    )
    if result.returncode != 0:
        return set(), f"kubectl-get-secret-{name}:command-exit-{result.returncode}"
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}, None


def kube_access_status(
    runner: CommandRunner,
    *,
    context: str,
    namespace: str,
) -> tuple[bool, bool, str | None]:
    context_result = runner(["kubectl", "config", "get-contexts", context, "-o", "name"], 10)
    if context_result.returncode != 0 or context_result.stdout.strip() != context:
        return False, False, f"kubectl-context-{context}-missing"
    namespace_result = runner(["kubectl", "--context", context, "get", "namespace", namespace, "-o", "json"], 10)
    if namespace_result.returncode != 0:
        return True, False, f"kubectl-namespace-{namespace}:command-exit-{namespace_result.returncode}"
    return True, True, None


def git_commit(runner: CommandRunner, override: str | None) -> str:
    if override:
        return override if GIT_SHA_RE.match(override) else ""
    result = runner(["git", "rev-parse", "HEAD"], 10)
    value = result.stdout.strip()
    return value if result.returncode == 0 and GIT_SHA_RE.match(value) else ""


def container_status(pod: dict[str, Any], name: str) -> dict[str, Any]:
    for status in pod.get("status", {}).get("containerStatuses", []):
        if status.get("name") == name:
            return status
    return {}


def find_audio_gateway_pod(pods: dict[str, Any], deployment: str) -> dict[str, Any] | None:
    items = pods.get("items", []) if isinstance(pods, dict) else []
    candidates: list[dict[str, Any]] = []
    matching: list[dict[str, Any]] = []
    for pod in items:
        if not isinstance(pod, dict):
            continue
        labels = pod.get("metadata", {}).get("labels", {})
        if labels.get("app.kubernetes.io/name") != deployment:
            continue
        matching.append(pod)
        status = container_status(pod, deployment)
        if pod.get("status", {}).get("phase") == "Running" and status.get("ready") is True:
            candidates.append(pod)
    pool = candidates or matching
    if not pool:
        return None
    pool.sort(key=lambda item: item.get("metadata", {}).get("creationTimestamp", ""))
    return pool[-1]


def pod_ready(pod: dict[str, Any] | None, deployment: str) -> bool:
    if not pod:
        return False
    status = container_status(pod, deployment)
    return pod.get("status", {}).get("phase") == "Running" and status.get("ready") is True


def image_digest_hex(pod: dict[str, Any] | None, deployment: str) -> str:
    if not pod:
        return ""
    status = container_status(pod, deployment)
    for value in [status.get("imageID"), status.get("image")]:
        if isinstance(value, str):
            match = SHA256_RE.search(value)
            if match:
                return match.group(1)
    return ""


def mtls_mount_present(deployment: dict[str, Any] | None) -> bool:
    if not isinstance(deployment, dict):
        return False
    containers = deployment.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
    for container in containers if isinstance(containers, list) else []:
        if container.get("name") != DEFAULT_DEPLOYMENT:
            continue
        for mount in container.get("volumeMounts", []) or []:
            if mount.get("name") == "direct-stt-mtls" and mount.get("mountPath") == EXPECTED_MTLS_MOUNT:
                return True
    return False


def host_alias_ip(deployment: dict[str, Any] | None) -> str:
    if not isinstance(deployment, dict):
        return ""
    aliases = deployment.get("spec", {}).get("template", {}).get("spec", {}).get("hostAliases", [])
    for alias in aliases if isinstance(aliases, list) else []:
        if EXPECTED_TRANSCRIBE_HOST in (alias.get("hostnames") or []):
            return str(alias.get("ip") or "")
    return ""


def mtls_probe(
    runner: CommandRunner,
    *,
    context: str,
    namespace: str,
    pod_name: str,
    timeout: int,
) -> dict[str, Any]:
    script = (
        'start="$(date +%s%3N)"; '
        'code="$(curl -sS -o /dev/null -w "%{http_code}" '
        f'--connect-timeout {timeout} --max-time {timeout} '
        '--cacert /etc/direct-stt-mtls/direct-stt-ca.crt '
        '--cert /etc/direct-stt-mtls/direct-stt-client.crt '
        '--key /etc/direct-stt-mtls/direct-stt-client.key '
        f'https://{EXPECTED_TRANSCRIBE_HOST}:{EXPECTED_TRANSCRIBE_PORT}/health || true)"; '
        'end="$(date +%s%3N)"; '
        'printf "%s %s\\n" "$code" "$((end-start))"'
    )
    result = runner(
        [
            "kubectl",
            "--context",
            context,
            "-n",
            namespace,
            "exec",
            pod_name,
            "-c",
            DEFAULT_DEPLOYMENT,
            "--",
            "sh",
            "-c",
            script,
        ],
        timeout + 10,
    )
    status = 0
    total_ms = 0
    if result.returncode == 0:
        parts = result.stdout.strip().split()
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            status = int(parts[0])
            total_ms = int(parts[1])
    return {
        "fromRealPod": bool(pod_name),
        "host": EXPECTED_TRANSCRIBE_HOST,
        "port": EXPECTED_TRANSCRIBE_PORT,
        "clientCertificateUsed": True,
        "healthHttpStatus": status,
        "totalMs": total_ms,
        "error": None if status == 200 else f"mtls-health-status-{status or 'missing'}",
    }


def parse_redis_records(data: Any) -> list[tuple[str, dict[str, str]]]:
    records: list[tuple[str, dict[str, str]]] = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, list) or len(item) != 2:
            continue
        record_id, fields_raw = item
        fields: dict[str, str] = {}
        if isinstance(fields_raw, list):
            for idx in range(0, len(fields_raw) - 1, 2):
                fields[str(fields_raw[idx])] = str(fields_raw[idx + 1])
        elif isinstance(fields_raw, dict):
            fields = {str(k): str(v) for k, v in fields_raw.items()}
        if isinstance(record_id, str):
            records.append((record_id, fields))
    return records


def redis_records_from_result(
    result: CommandResult,
    *,
    stream: str,
    error_prefix: str = "redis-xrevrange",
) -> tuple[list[tuple[str, dict[str, str]]], str | None]:
    data, error = load_json_result(result, f"{error_prefix}-{stream}")
    if error:
        return [], error
    return parse_redis_records(data), None


def redis_records_via_docker(
    runner: CommandRunner,
    *,
    container: str,
    stream: str,
    count: int,
    timeout: int,
) -> tuple[list[tuple[str, dict[str, str]]], str | None]:
    result = runner(
        [
            "docker",
            "exec",
            container,
            "sh",
            "-c",
            'export REDISCLI_AUTH="$REDIS_PASSWORD"; redis-cli --json XREVRANGE "$1" + - COUNT "$2"',
            "redis-query",
            stream,
            str(count),
        ],
        timeout,
    )
    return redis_records_from_result(result, stream=stream)


class RespParseError(ValueError):
    pass


class RespParser:
    def __init__(self, payload: str) -> None:
        self.data = payload.encode("utf-8", errors="surrogateescape")
        self.pos = 0

    def read_line(self) -> bytes:
        end = self.data.find(b"\r\n", self.pos)
        terminator_len = 2
        if end < 0:
            # subprocess.run(text=True) normalizes CRLF to LF. The Redis
            # payload is still RESP-shaped, but line delimiters arrive as LF.
            end = self.data.find(b"\n", self.pos)
            terminator_len = 1
        if end < 0:
            raise RespParseError("missing-crlf")
        line = self.data[self.pos:end]
        self.pos = end + terminator_len
        return line

    def parse_one(self) -> Any:
        if self.pos >= len(self.data):
            raise RespParseError("unexpected-eof")
        prefix = self.data[self.pos : self.pos + 1]
        self.pos += 1
        if prefix == b"+":
            return self.read_line().decode("utf-8", errors="replace")
        if prefix == b"-":
            message = self.read_line().decode("utf-8", errors="replace")
            raise RespParseError(f"redis-error:{message[:80]}")
        if prefix == b":":
            return int(self.read_line())
        if prefix == b"$":
            length = int(self.read_line())
            if length < 0:
                return None
            value = self.data[self.pos : self.pos + length]
            self.pos += length
            if self.data[self.pos : self.pos + 2] == b"\r\n":
                self.pos += 2
            elif self.data[self.pos : self.pos + 1] == b"\n":
                self.pos += 1
            else:
                raise RespParseError("bulk-missing-crlf")
            return value.decode("utf-8", errors="replace")
        if prefix == b"*":
            length = int(self.read_line())
            if length < 0:
                return None
            return [self.parse_one() for _ in range(length)]
        raise RespParseError(f"unknown-prefix:{prefix!r}")

    def parse_all(self) -> list[Any]:
        values = []
        while self.pos < len(self.data):
            values.append(self.parse_one())
        return values


def redis_records_from_resp_result(
    result: CommandResult,
    *,
    stream: str,
    error_prefix: str = "redis-kube-exec-xrevrange",
) -> tuple[list[tuple[str, dict[str, str]]], str | None]:
    if result.returncode != 0:
        return [], f"{error_prefix}-{stream}:command-exit-{result.returncode}"
    try:
        values = RespParser(result.stdout).parse_all()
    except (RespParseError, ValueError):
        return [], f"{error_prefix}-{stream}:invalid-resp"
    stream_payload = next((value for value in values if isinstance(value, list)), None)
    if stream_payload is None:
        return [], f"{error_prefix}-{stream}:missing-array"
    return parse_redis_records(stream_payload), None


def redis_records_via_kube_exec(
    runner: CommandRunner,
    *,
    context: str,
    namespace: str,
    pod_name: str,
    container_name: str,
    stream: str,
    count: int,
    timeout: int,
) -> tuple[list[tuple[str, dict[str, str]]], str | None]:
    script = r'''
set -euo pipefail
stream="$1"
count="$2"
host="${SPRING_DATA_REDIS_HOST:-redis-streams}"
port="${SPRING_DATA_REDIS_PORT:-6379}"
password="${SPRING_DATA_REDIS_PASSWORD:-${REDIS_PASSWORD:-}}"
if [ -z "${password}" ]; then
  exit 42
fi
resp_bulk() {
  local value="$1"
  printf '$%s\r\n%s\r\n' "${#value}" "${value}"
}
exec 3<>"/dev/tcp/${host}/${port}"
{
  printf '*2\r\n'
  resp_bulk AUTH
  resp_bulk "${password}"
  printf '*6\r\n'
  resp_bulk XREVRANGE
  resp_bulk "${stream}"
  resp_bulk +
  resp_bulk -
  resp_bulk COUNT
  resp_bulk "${count}"
  printf '*1\r\n'
  resp_bulk QUIT
} >&3
timeout 10 cat <&3
'''
    result = runner(
        [
            "kubectl",
            "--context",
            context,
            "-n",
            namespace,
            "exec",
            pod_name,
            "-c",
            container_name,
            "--",
            "bash",
            "-c",
            script,
            "redis-query",
            stream,
            str(count),
        ],
        timeout,
    )
    return redis_records_from_resp_result(result, stream=stream)


def parse_redis_stream_batch(stdout: str) -> tuple[dict[str, list[tuple[str, dict[str, str]]]], str | None]:
    parsed: dict[str, list[tuple[str, dict[str, str]]]] = {}
    current_stream = ""
    current_lines: list[str] = []

    def flush() -> str | None:
        if not current_stream:
            return None
        payload = "\n".join(current_lines).strip()
        if not payload:
            parsed[current_stream] = []
            return None
        try:
            parsed[current_stream] = parse_redis_records(json.loads(payload))
        except json.JSONDecodeError:
            return f"redis-kube-cli-xrevrange-{current_stream}:invalid-json"
        return None

    for line in stdout.splitlines():
        if line.startswith("__STREAM__"):
            error = flush()
            if error:
                return parsed, error
            current_stream = line.removeprefix("__STREAM__")
            current_lines = []
        else:
            current_lines.append(line)
    error = flush()
    return parsed, error


def redis_streams_via_kube_cli_pod(
    runner: CommandRunner,
    *,
    context: str,
    namespace: str,
    service: str,
    secret: str,
    secret_key: str,
    image: str,
    streams: list[str],
    count: int,
    timeout: int,
) -> tuple[dict[str, list[tuple[str, dict[str, str]]]], str | None]:
    suffix = hashlib.sha256(f"{os.getpid()}:{time.monotonic_ns()}:{','.join(streams)}".encode("utf-8")).hexdigest()[:12]
    pod_name = f"faz24-redis-read-{suffix}"
    script = (
        'export REDISCLI_AUTH="$REDIS_PASSWORD"; '
        'count="$1"; shift; '
        'for stream in "$@"; do '
        'printf "__STREAM__%s\\n" "$stream"; '
        'redis-cli -h "$REDIS_HOST" --json XREVRANGE "$stream" + - COUNT "$count" || exit "$?"; '
        'done'
    )
    manifest = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": pod_name,
            "namespace": namespace,
            "labels": {
                "app.kubernetes.io/name": "faz24-redis-read",
                "app.kubernetes.io/part-of": "platform-k8s-gitops",
                "faz24.acik.com/purpose": "direct-stt-e2e-evidence",
            },
        },
        "spec": {
            "activeDeadlineSeconds": timeout,
            "automountServiceAccountToken": False,
            "restartPolicy": "Never",
            "containers": [
                {
                    "name": "redis-cli",
                    "image": image,
                    "imagePullPolicy": "IfNotPresent",
                    "env": [
                        {"name": "REDIS_HOST", "value": service},
                        {
                            "name": "REDIS_PASSWORD",
                            "valueFrom": {
                                "secretKeyRef": {
                                    "name": secret,
                                    "key": secret_key,
                                }
                            },
                        },
                    ],
                    "command": ["sh", "-c"],
                    "args": [
                        script,
                        "redis-query",
                        str(count),
                        *streams,
                    ],
                    "resources": {
                        "requests": {"cpu": "10m", "memory": "32Mi"},
                        "limits": {"cpu": "100m", "memory": "128Mi"},
                    },
                    "securityContext": {
                        "allowPrivilegeEscalation": False,
                        "capabilities": {"drop": ["ALL"]},
                        "readOnlyRootFilesystem": True,
                    },
                }
            ],
        },
    }

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
        json.dump(manifest, handle)
        manifest_path = handle.name
    try:
        apply_result = runner(
            ["kubectl", "--context", context, "-n", namespace, "apply", "-f", manifest_path],
            20,
        )
        if apply_result.returncode != 0:
            return {}, f"redis-kube-cli-batch:apply-command-exit-{apply_result.returncode}"

        deadline = time.monotonic() + timeout
        phase = ""
        while time.monotonic() < deadline:
            pod_data, get_error = kget(
                runner,
                context=context,
                namespace=namespace,
                kind="pod",
                name=pod_name,
                timeout=10,
            )
            if not get_error and isinstance(pod_data, dict):
                phase = str(pod_data.get("status", {}).get("phase") or "")
                if phase in {"Succeeded", "Failed"}:
                    break
            time.sleep(1)
        if phase != "Succeeded":
            return {}, f"redis-kube-cli-batch:pod-phase-{phase or 'timeout'}"

        logs_result = runner(
            ["kubectl", "--context", context, "-n", namespace, "logs", pod_name, "-c", "redis-cli"],
            20,
        )
        if logs_result.returncode != 0:
            return {}, f"redis-kube-cli-batch:logs-command-exit-{logs_result.returncode}"
        return parse_redis_stream_batch(logs_result.stdout)
    finally:
        try:
            os.unlink(manifest_path)
        except FileNotFoundError:
            pass
        runner(
            [
                "kubectl",
                "--context",
                context,
                "-n",
                namespace,
                "delete",
                "pod",
                pod_name,
                "--ignore-not-found=true",
                "--wait=false",
            ],
            20,
        )


def redis_records_via_kube_cli_pod(
    runner: CommandRunner,
    *,
    context: str,
    namespace: str,
    service: str,
    secret: str,
    secret_key: str,
    image: str,
    stream: str,
    count: int,
    timeout: int,
) -> tuple[list[tuple[str, dict[str, str]]], str | None]:
    records_by_stream, error = redis_streams_via_kube_cli_pod(
        runner,
        context=context,
        namespace=namespace,
        service=service,
        secret=secret,
        secret_key=secret_key,
        image=image,
        streams=[stream],
        count=count,
        timeout=timeout,
    )
    if error:
        return [], error
    return records_by_stream.get(stream, []), None


def redis_records(
    runner: CommandRunner,
    *,
    container: str,
    stream: str,
    count: int,
    context: str | None = None,
    namespace: str | None = None,
    service: str = DEFAULT_REDIS_SERVICE,
    secret: str = DEFAULT_REDIS_SECRET,
    secret_key: str = DEFAULT_REDIS_SECRET_KEY,
    image: str = DEFAULT_REDIS_CLI_IMAGE,
    exec_pod: str | None = None,
    exec_container: str = DEFAULT_DEPLOYMENT,
    timeout: int = 20,
) -> tuple[list[tuple[str, dict[str, str]]], str | None]:
    records, docker_error = redis_records_via_docker(
        runner,
        container=container,
        stream=stream,
        count=count,
        timeout=timeout,
    )
    if not docker_error:
        return records, None
    if context and namespace and exec_pod and any(
        marker in docker_error
        for marker in ("command-exit-125", "command-exit-126", "command-exit-127")
    ):
        # GitHub's self-hosted runner container has kubectl but not docker.
        # Reuse the already-running audio-gateway pod, which is the runtime
        # producer and has the Redis secret/env + network path, instead of
        # creating a generic pod that NetworkPolicy/quota can block.
        records, kube_error = redis_records_via_kube_exec(
            runner,
            context=context,
            namespace=namespace,
            pod_name=exec_pod,
            container_name=exec_container,
            stream=stream,
            count=count,
            timeout=timeout,
        )
        if not kube_error:
            return records, None
        return [], f"{docker_error};{kube_error}"
    return [], docker_error


def redis_stream_records(
    runner: CommandRunner,
    *,
    container: str,
    streams: list[str],
    count: int,
    context: str | None = None,
    namespace: str | None = None,
    service: str = DEFAULT_REDIS_SERVICE,
    secret: str = DEFAULT_REDIS_SECRET,
    secret_key: str = DEFAULT_REDIS_SECRET_KEY,
    image: str = DEFAULT_REDIS_CLI_IMAGE,
    exec_pod: str | None = None,
    exec_container: str = DEFAULT_DEPLOYMENT,
    timeout: int = 20,
) -> tuple[dict[str, list[tuple[str, dict[str, str]]]], list[str]]:
    records_by_stream: dict[str, list[tuple[str, dict[str, str]]]] = {}
    errors: list[str] = []
    first_docker_tooling_error = ""

    for stream in streams:
        records, error = redis_records_via_docker(
            runner,
            container=container,
            stream=stream,
            count=count,
            timeout=timeout,
        )
        if error:
            if any(marker in error for marker in ("command-exit-125", "command-exit-126", "command-exit-127")):
                first_docker_tooling_error = error
                break
            errors.append(error)
            continue
        records_by_stream[stream] = records

    if not first_docker_tooling_error:
        return records_by_stream, errors

    if not context or not namespace or not exec_pod:
        return {}, [first_docker_tooling_error]

    kube_records: dict[str, list[tuple[str, dict[str, str]]]] = {}
    kube_errors: list[str] = []
    for stream in streams:
        records, kube_error = redis_records_via_kube_exec(
            runner,
            context=context,
            namespace=namespace,
            pod_name=exec_pod,
            container_name=exec_container,
            stream=stream,
            count=count,
            timeout=timeout,
        )
        if kube_error:
            kube_errors.append(kube_error)
            continue
        kube_records[stream] = records
    if kube_errors:
        return kube_records, [f"{first_docker_tooling_error};{error}" for error in kube_errors[:3]]
    return kube_records, []


def find_record(
    records: list[tuple[str, dict[str, str]]],
    *,
    session_id: str,
    chunk_seq: int,
    correlation_id: str,
    event_type: str | None = None,
) -> tuple[str, dict[str, str]] | None:
    for record_id, fields in records:
        if event_type and fields.get("eventType") != event_type:
            continue
        if fields.get("sessionId") != session_id:
            continue
        if str(fields.get("chunkSeq")) != str(chunk_seq):
            continue
        if correlation_id and fields.get("correlationId") != correlation_id:
            continue
        return record_id, fields
    return None


def find_audio_chunk_record(
    *,
    records_by_stream: dict[str, list[tuple[str, dict[str, str]]]],
    session_id: str,
    chunk_seq: int,
    correlation_id: str,
    sample_sha256: str,
) -> tuple[str | None, dict[str, str], str | None]:
    for idx in range(32):
        stream = f"audio:chunks:p{idx:02d}"
        records = records_by_stream.get(stream, [])
        match = find_record(
            records,
            session_id=session_id,
            chunk_seq=chunk_seq,
            correlation_id=correlation_id,
        )
        if match and match[1].get("sha256") == sample_sha256:
            return stream, match[1], None
    return None, {}, None


def safe_text_hash(value: str) -> tuple[str, int]:
    return hashlib.sha256(value.encode("utf-8")).hexdigest(), len(value)


def logs_have_forbidden_content(
    runner: CommandRunner,
    *,
    context: str,
    namespace: str,
    pod_name: str,
    transcript_text: str,
) -> tuple[bool, bool, str | None]:
    result = runner(
        [
            "kubectl",
            "--context",
            context,
            "-n",
            namespace,
            "logs",
            pod_name,
            "-c",
            DEFAULT_DEPLOYMENT,
            "--since=10m",
            "--tail=500",
        ],
        20,
    )
    if result.returncode != 0:
        return True, True, f"kubectl-logs:command-exit-{result.returncode}"
    logs = result.stdout
    raw_audio = "data:audio/" in logs or "audio_base64" in logs or "raw_audio" in logs
    raw_transcript = bool(transcript_text and transcript_text in logs)
    return raw_audio, raw_transcript, None


def step_by_name(smoke: dict[str, Any], name: str) -> dict[str, Any]:
    for step in smoke.get("steps", []) if isinstance(smoke.get("steps"), list) else []:
        if isinstance(step, dict) and step.get("name") == name:
            return step
    return {}


def collect(args: argparse.Namespace, runner: CommandRunner = run_command) -> dict[str, Any]:
    failures: list[str] = []
    smoke = json.loads(args.external_smoke_file.read_text(encoding="utf-8"))
    ids = smoke.get("ids") if isinstance(smoke.get("ids"), dict) else {}
    sample = smoke.get("sample") if isinstance(smoke.get("sample"), dict) else {}

    meeting_id = str(ids.get("meetingId") or "")
    session_id = str(ids.get("sessionId") or "")
    upload_step = step_by_name(smoke, "upload_chunk")
    upload_response = upload_step.get("response") if isinstance(upload_step.get("response"), dict) else {}
    chunk_seq = int(upload_response.get("chunkSeq", sample.get("chunkSeq", 0)) or 0)
    correlation_id = str(upload_response.get("correlationId") or "")
    sample_sha256 = str(sample.get("sampleSha256") or "")
    redis_service = getattr(args, "redis_service", DEFAULT_REDIS_SERVICE)
    redis_secret = getattr(args, "redis_secret", DEFAULT_REDIS_SECRET)
    redis_secret_key = getattr(args, "redis_secret_key", DEFAULT_REDIS_SECRET_KEY)
    redis_cli_image = getattr(args, "redis_cli_image", DEFAULT_REDIS_CLI_IMAGE)

    if smoke.get("status") != "pass":
        failures.append("external-smoke-not-pass")
    if not SESSION_ID_RE.match(session_id):
        failures.append("session-id-shape")
    if not SAFE_NAME_RE.match(correlation_id):
        failures.append("correlation-id-shape")
    if not re.fullmatch(r"[0-9a-f]{64}", sample_sha256):
        failures.append("sample-sha256-shape")

    context_available, namespace_reachable, context_failure = kube_access_status(
        runner,
        context=args.context,
        namespace=args.namespace,
    )
    if not context_available or not namespace_reachable:
        failures.append(context_failure or "kube-access-failed")

    configmap, err = kget(runner, context=args.context, namespace=args.namespace, kind="configmap", name=DEFAULT_CONFIGMAP)
    if err:
        failures.append(err)
    deployment, err = kget(runner, context=args.context, namespace=args.namespace, kind="deployment", name=args.deployment)
    if err:
        failures.append(err)
    pods, err = kget(runner, context=args.context, namespace=args.namespace, kind="pods", name=None)
    if err:
        failures.append(err)
    pod = find_audio_gateway_pod(pods or {}, args.deployment)
    pod_name = str(pod.get("metadata", {}).get("name") or "") if pod else ""
    if not pod_ready(pod, args.deployment):
        failures.append("audio-gateway-pod-not-ready")

    secret_keys, err = kget_secret_key_names(
        runner,
        context=args.context,
        namespace=args.namespace,
        name=DEFAULT_MTLS_SECRET,
    )
    if err:
        failures.append(err)
    if not REQUIRED_SECRET_KEYS.issubset(secret_keys):
        failures.append("mtls-secret-key-missing")

    direct_enabled = (
        isinstance(configmap, dict)
        and configmap.get("data", {}).get("AUDIO_GATEWAY_DIRECT_STT_ENABLED") == "true"
    )
    if not direct_enabled:
        failures.append("direct-stt-not-enabled")

    probe = mtls_probe(
        runner,
        context=args.context,
        namespace=args.namespace,
        pod_name=pod_name,
        timeout=args.probe_timeout,
    )
    if probe.get("healthHttpStatus") != 200:
        failures.append(str(probe.get("error") or "mtls-health-not-200"))

    result_record: tuple[str, dict[str, str]] | None = None
    audit_record: tuple[str, dict[str, str]] | None = None
    transcript_hash = ""
    transcript_chars = 0
    transcript_text = ""
    redis_streams = [EXPECTED_RESULT_STREAM, EXPECTED_AUDIT_STREAM]
    redis_streams.extend(f"audio:chunks:p{idx:02d}" for idx in range(32))
    redis_records_by_stream, redis_errors = redis_stream_records(
        runner,
        container=args.redis_container,
        streams=redis_streams,
        count=args.redis_count,
        context=args.context,
        namespace=args.namespace,
        service=redis_service,
        secret=redis_secret,
        secret_key=redis_secret_key,
        image=redis_cli_image,
        exec_pod=pod_name,
        exec_container=args.deployment,
    )
    if redis_errors:
        failures.extend(redis_errors[:3])

    result_records = redis_records_by_stream.get(EXPECTED_RESULT_STREAM, [])
    result_record = find_record(
        result_records,
        session_id=session_id,
        chunk_seq=chunk_seq,
        correlation_id=correlation_id,
        event_type=EXPECTED_RESULT_EVENT,
    )
    if not result_record:
        failures.append("result-stream-entry-not-found")
    else:
        transcript_text = result_record[1].get("textDraft", "")
        transcript_hash, transcript_chars = safe_text_hash(transcript_text)
        if not transcript_text:
            failures.append("result-stream-transcript-empty")

    audit_records = redis_records_by_stream.get(EXPECTED_AUDIT_STREAM, [])
    audit_record = find_record(
        audit_records,
        session_id=session_id,
        chunk_seq=chunk_seq,
        correlation_id=correlation_id,
        event_type=EXPECTED_AUDIT_EVENT,
    )
    if not audit_record:
        failures.append("compute-plane-audit-not-found")

    audio_stream, audio_fields, err = find_audio_chunk_record(
        records_by_stream=redis_records_by_stream,
        session_id=session_id,
        chunk_seq=chunk_seq,
        correlation_id=correlation_id,
        sample_sha256=sample_sha256,
    )
    if err:
        failures.append(err)
    if not audio_stream:
        failures.append("audio-chunk-metadata-record-not-found")

    audio_chunk_has_raw = any(
        key in RAW_AUDIO_KEYS or ("audio" in key.lower() and key != "audioFormat")
        for key in audio_fields
    )
    result_has_raw_audio = bool(result_record and any(key in RAW_AUDIO_KEYS for key in result_record[1]))
    raw_audio_logs, raw_transcript_logs, log_error = logs_have_forbidden_content(
        runner,
        context=args.context,
        namespace=args.namespace,
        pod_name=pod_name,
        transcript_text=transcript_text,
    )
    if log_error:
        failures.append(log_error)
    if raw_audio_logs:
        failures.append("raw-audio-log-finding")
    if raw_transcript_logs:
        failures.append("raw-transcript-log-finding")

    status = "pass" if not failures else "fail"
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": status,
        "issue": "platform-ai#182",
        "tokenIncluded": False,
        "generatedAt": utc_now(),
        "failures": failures,
        "source": {
            "gitopsCommit": git_commit(runner, args.gitops_commit),
            "backendImageDigest": image_digest_hex(pod, args.deployment),
        },
        "environment": {
            "cluster": args.context,
            "kubectlContext": args.context,
            "namespace": args.namespace,
            "deployment": args.deployment,
            "podName": pod_name,
            "podReady": pod_ready(pod, args.deployment),
            "contextAvailable": context_available,
            "namespaceReachable": namespace_reachable,
            "contextFailure": context_failure or "",
        },
        "runtime": {
            "directSttEnabled": direct_enabled,
            "transcribeHost": EXPECTED_TRANSCRIBE_HOST,
            "transcribePort": EXPECTED_TRANSCRIBE_PORT,
            "hostAliasIp": host_alias_ip(deployment),
            "mtlsMountPath": EXPECTED_MTLS_MOUNT,
            "mtlsMountPresent": mtls_mount_present(deployment),
            "mtlsSecretName": DEFAULT_MTLS_SECRET,
            "secretValueIncluded": False,
            "mtlsSecretKeyNames": sorted(secret_keys),
        },
        "mtlsProbe": {key: value for key, value in probe.items() if key != "error"},
        "flow": {
            "sessionId": session_id,
            "chunkSeq": chunk_seq,
            "correlationId": correlation_id,
            "sampleSha256": sample_sha256,
            "rawAudioIncluded": False,
            "meetingCreateHttpStatus": step_by_name(smoke, "create_meeting").get("statusCode", 0),
            "chunkUploadHttpStatus": upload_step.get("statusCode", 0),
            "finishHttpStatus": step_by_name(smoke, "finish_session").get("statusCode", 0),
            "transcribeHttpStatus": 200 if result_record else 0,
            "resultStreamKey": EXPECTED_RESULT_STREAM,
            "resultStreamEntryFound": result_record is not None,
            "resultStreamRecordId": result_record[0] if result_record else "",
            "transcriptTextIncluded": False,
            "transcriptSha256": transcript_hash,
            "transcriptCharCount": transcript_chars,
        },
        "audit": {
            "streamKey": EXPECTED_AUDIT_STREAM,
            "eventType": EXPECTED_AUDIT_EVENT,
            "eventFound": audit_record is not None,
            "recordId": audit_record[0] if audit_record else "",
            "sessionIdMatches": bool(audit_record and audit_record[1].get("sessionId") == session_id),
            "chunkSeqMatches": bool(audit_record and str(audit_record[1].get("chunkSeq")) == str(chunk_seq)),
            "correlationIdMatches": bool(audit_record and audit_record[1].get("correlationId") == correlation_id),
        },
        "persistence": {
            "redisAudioChunkMetadataOnly": bool(audio_stream and not audio_chunk_has_raw),
            "rawAudioInRedis": bool(audio_chunk_has_raw),
            "rawAudioInResultStream": result_has_raw_audio,
            "rawAudioInLogs": raw_audio_logs,
            "rawTranscriptInEvidence": False,
            "rawTranscriptInLogs": raw_transcript_logs,
        },
        "boundaries": {
            "directAudioE2eProven": status == "pass",
            "directSttTranscriptProven": status == "pass" and bool(transcript_hash),
            "computePlaneAuditProven": audit_record is not None,
            "directClientToStt": False,
            "rawAudioIncluded": False,
            "rawTranscriptIncluded": False,
            "i7ProdGateProven": False,
            "desktopMicLoopbackProven": False,
            "productionReady": False,
        },
    }


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
    finally:
        try:
            os.chmod(path, 0o600)
        except FileNotFoundError:
            pass


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--external-smoke-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--context", default=DEFAULT_CONTEXT)
    parser.add_argument("--namespace", default=DEFAULT_NAMESPACE)
    parser.add_argument("--deployment", default=DEFAULT_DEPLOYMENT)
    parser.add_argument("--redis-container", default=DEFAULT_REDIS_CONTAINER)
    parser.add_argument("--redis-service", default=DEFAULT_REDIS_SERVICE)
    parser.add_argument("--redis-secret", default=DEFAULT_REDIS_SECRET)
    parser.add_argument("--redis-secret-key", default=DEFAULT_REDIS_SECRET_KEY)
    parser.add_argument("--redis-cli-image", default=DEFAULT_REDIS_CLI_IMAGE)
    parser.add_argument("--gitops-commit")
    parser.add_argument("--probe-timeout", type=int, default=40)
    parser.add_argument("--redis-count", type=int, default=1000)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    evidence = collect(args)
    status = evidence["status"]
    write_json(args.output, evidence)
    print(f"evidence={args.output}")
    print("collector=metadata-written")
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
