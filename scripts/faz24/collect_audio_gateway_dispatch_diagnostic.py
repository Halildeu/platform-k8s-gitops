#!/usr/bin/env python3
"""Collect a redacted audio-gateway dispatch classification from test logs.

The collector keeps raw Kubernetes logs in memory and writes only a bounded,
allow-listed classification. It never persists log lines, payloads, tokens,
transcript text, or Redis credentials.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
from typing import Callable, Sequence


MAX_SMOKE_BYTES = 2 * 1024 * 1024
ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")
EXCEPTION_RE = re.compile(r"\berr=([A-Za-z0-9_$.-]{1,160})\b")

CLASSIFIERS = (
    ("redis-auth-acl", "ALERT Redis AUTH/ACL failure on dispatch"),
    ("redis-tls", "ALERT mTLS/SSL handshake failure on dispatch"),
    ("redis-failover", "Redis transient cluster failover; short retry"),
    ("redis-dispatch-unavailable", "Redis dispatch failed; marking Unavailable"),
    ("redis-stream-capacity", "Redis stream at capacity; rejecting chunk QueueFull"),
    ("redis-consumer-lag", "Consumer group lag beyond threshold; rejecting chunk QueueFull"),
    ("redis-consumer-idle", "Consumer not draining (oldest pending idle beyond threshold); QueueFull"),
    ("direct-stt-saturated", "Direct-STT forward dropped (in-flight saturated"),
    ("direct-stt-copy", "Direct-STT byte copy failed"),
    ("direct-stt-schedule", "Direct-STT schedule rejected"),
    ("direct-stt-setup", "Direct-STT forward setup failed"),
    ("direct-stt-timeout", "Direct-STT forward timeout"),
    ("direct-stt-http", "Direct-STT forward HTTP error"),
    ("direct-stt-connection", "Direct-STT forward connection error"),
    ("direct-stt-failed", "Direct-STT forward failed"),
)


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[[Sequence[str], int], CommandResult]


def run_command(argv: Sequence[str], timeout: int) -> CommandResult:
    try:
        completed = subprocess.run(
            list(argv),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return CommandResult(124, "", "")
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _load_smoke(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError("external smoke evidence is missing or unsafe")
    if path.stat().st_size > MAX_SMOKE_BYTES:
        raise ValueError("external smoke evidence exceeds size bound")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("external smoke evidence must be an object")
    return value


def _step(smoke: dict, name: str) -> dict:
    for item in smoke.get("steps", []):
        if isinstance(item, dict) and item.get("name") == name:
            return item
    raise ValueError(f"external smoke step missing: {name}")


def _bounded_id(value: object, field: str) -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise ValueError(f"external smoke {field} is missing or invalid")
    return value


def extract_request_ids(smoke: dict) -> tuple[str, str]:
    start = _step(smoke, "start_session").get("response", {})
    upload = _step(smoke, "upload_chunk").get("response", {})
    if not isinstance(start, dict) or not isinstance(upload, dict):
        raise ValueError("external smoke response metadata is invalid")
    return (
        _bounded_id(start.get("sessionId"), "sessionId"),
        _bounded_id(upload.get("correlationId"), "correlationId"),
    )


def classify_logs(
    raw_logs: str, session_id: str, correlation_id: str
) -> tuple[str, str | None, int, bool]:
    matches: list[tuple[str, str | None, bool]] = []
    for line in raw_logs.splitlines():
        if f"sessionId={session_id}" not in line:
            continue
        correlation_matched = f"correlationId={correlation_id}" in line
        for classification, marker in CLASSIFIERS:
            if marker not in line:
                continue
            exception = EXCEPTION_RE.search(line)
            matches.append(
                (
                    classification,
                    exception.group(1) if exception else None,
                    correlation_matched,
                )
            )
            break

    if not matches:
        return "no-allowlisted-match", None, 0, False
    unique = {(classification, exception) for classification, exception, _ in matches}
    if len(unique) != 1:
        return "multiple-allowlisted-matches", None, len(matches), any(item[2] for item in matches)
    classification, exception = next(iter(unique))
    return classification, exception, len(matches), any(item[2] for item in matches)


def collect(
    smoke_path: Path,
    output: Path,
    *,
    context: str,
    namespace: str,
    deployment: str,
    since: str,
    command_runner: CommandRunner = run_command,
) -> dict:
    if context != "k3d-test" or namespace != "platform-test" or deployment != "audio-gateway":
        raise ValueError("collector is restricted to platform-test audio-gateway")
    if not re.fullmatch(r"[1-9][0-9]?[smh]", since):
        raise ValueError("since must be a bounded Kubernetes duration")

    session_id, correlation_id = extract_request_ids(_load_smoke(smoke_path))
    result = command_runner(
        [
            "kubectl",
            "--context",
            context,
            "-n",
            namespace,
            "logs",
            "-l",
            f"app.kubernetes.io/name={deployment}",
            "-c",
            deployment,
            f"--since={since}",
            "--tail=5000",
            "--max-log-requests=10",
        ],
        30,
    )
    if result.returncode == 0:
        classification, exception_class, matched_count, correlation_matched = classify_logs(
            result.stdout, session_id, correlation_id
        )
        status = "classified" if classification not in {
            "no-allowlisted-match",
            "multiple-allowlisted-matches",
        } else "inconclusive"
        log_query = "success"
    else:
        classification = "log-query-failed"
        exception_class = None
        matched_count = 0
        correlation_matched = False
        status = "inconclusive"
        log_query = f"exit-{result.returncode}"

    evidence = {
        "schemaVersion": "faz24.audioGatewayDispatchDiagnostic.v1",
        "status": status,
        "environment": {"cluster": context, "namespace": namespace},
        "request": {"sessionId": session_id, "correlationId": correlation_id},
        "diagnostic": {
            "classification": classification,
            "exceptionClass": exception_class,
            "matchedCount": matched_count,
            "matchBasis": "sessionId",
            "correlationMatched": correlation_matched,
            "logQuery": log_query,
        },
        "boundaries": {
            "platformTestOnly": True,
            "rawLogsIncluded": False,
            "secretValuesIncluded": False,
            "audioIncluded": False,
            "transcriptIncluded": False,
            "productionMutated": False,
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output.chmod(0o600)
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--external-smoke-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--context", default="k3d-test")
    parser.add_argument("--namespace", default="platform-test")
    parser.add_argument("--deployment", default="audio-gateway")
    parser.add_argument("--since", default="10m")
    args = parser.parse_args()

    try:
        evidence = collect(
            args.external_smoke_file,
            args.output,
            context=args.context,
            namespace=args.namespace,
            deployment=args.deployment,
            since=args.since,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"collector_error={exc}")
        return 1

    print(f"dispatch_diagnostic={args.output}")
    print(f"dispatch_classification={evidence['diagnostic']['classification']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
