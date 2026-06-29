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


def redis_records(
    runner: CommandRunner,
    *,
    container: str,
    stream: str,
    count: int,
    timeout: int = 20,
) -> tuple[list[tuple[str, dict[str, str]]], str | None]:
    result = runner(
        [
            "docker",
            "exec",
            container,
            "sh",
            "-c",
            'redis-cli -a "$REDIS_PASSWORD" --json XREVRANGE "$1" + - COUNT "$2"',
            "sh",
            stream,
            str(count),
        ],
        timeout,
    )
    data, error = load_json_result(result, f"redis-xrevrange-{stream}")
    if error:
        return [], error
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
    return records, None


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
    runner: CommandRunner,
    *,
    container: str,
    session_id: str,
    chunk_seq: int,
    correlation_id: str,
    sample_sha256: str,
    count: int,
) -> tuple[str | None, dict[str, str], str | None]:
    errors: list[str] = []
    for idx in range(32):
        stream = f"audio:chunks:p{idx:02d}"
        records, error = redis_records(runner, container=container, stream=stream, count=count)
        if error:
            errors.append(error)
            continue
        match = find_record(
            records,
            session_id=session_id,
            chunk_seq=chunk_seq,
            correlation_id=correlation_id,
        )
        if match and match[1].get("sha256") == sample_sha256:
            return stream, match[1], None
    return None, {}, ";".join(errors[:3]) if errors else None


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
    result_records, err = redis_records(
        runner,
        container=args.redis_container,
        stream=EXPECTED_RESULT_STREAM,
        count=args.redis_count,
    )
    if err:
        failures.append(err)
    else:
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

    audit_records, err = redis_records(
        runner,
        container=args.redis_container,
        stream=EXPECTED_AUDIT_STREAM,
        count=args.redis_count,
    )
    if err:
        failures.append(err)
    else:
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
        runner,
        container=args.redis_container,
        session_id=session_id,
        chunk_seq=chunk_seq,
        correlation_id=correlation_id,
        sample_sha256=sample_sha256,
        count=args.redis_count,
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
