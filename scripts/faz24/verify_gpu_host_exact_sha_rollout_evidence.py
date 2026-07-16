#!/usr/bin/env python3
"""Fail-closed verifier for Faz 24 GPU exact-SHA rollout evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any, Sequence


SCHEMA_VERSION = "faz24.gpu-host-exact-sha-rollout.v1"
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
FORBIDDEN_KEYS = {
    "audio",
    "rawaudio",
    "transcript",
    "transcripttext",
    "token",
    "authorization",
    "password",
    "privatekey",
    "pem",
    "cookie",
}
FORBIDDEN_VALUE_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]+=*"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{8,}\b"),
)


class EvidenceError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceError(message)


def object_field(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    require(isinstance(value, dict), f"{key} must be an object")
    return value


def scan_forbidden(data: Any, path: str = "$") -> None:
    if isinstance(data, dict):
        for key, value in data.items():
            normalized = re.sub(r"[^a-z]", "", key.lower())
            if normalized in FORBIDDEN_KEYS:
                raise EvidenceError(f"forbidden field at {path}.{key}")
            scan_forbidden(value, f"{path}.{key}")
    elif isinstance(data, list):
        for index, value in enumerate(data):
            scan_forbidden(value, f"{path}[{index}]")
    elif isinstance(data, str):
        for pattern in FORBIDDEN_VALUE_PATTERNS:
            if pattern.search(data):
                raise EvidenceError(f"forbidden value pattern at {path}")


def verify(data: dict[str, Any], expected_commit: str) -> None:
    expected_commit = expected_commit.strip()
    require(bool(COMMIT_RE.fullmatch(expected_commit)), "expected commit is invalid")
    scan_forbidden(data)

    require(data.get("schemaVersion") == SCHEMA_VERSION, "schemaVersion mismatch")
    require(data.get("status") == "go", "rollout status is not go")
    require(data.get("targetCommit") == expected_commit, "targetCommit mismatch")
    require(data.get("afterCommit") == expected_commit, "afterCommit mismatch")
    require(
        bool(COMMIT_RE.fullmatch(str(data.get("beforeCommit", "")))),
        "beforeCommit invalid",
    )
    require(
        data.get("sourceCommitVerified") is True, "source commit ancestry not verified"
    )
    require(data.get("whatIfExitCode") == 0, "WhatIf preflight failed")
    require(data.get("deployExitCode") == 0, "deploy updater failed")
    require(data.get("failureClass") == "none", "failureClass is not none")

    task_migration = object_field(data, "taskMigration")
    migration_required = task_migration.get("required")
    require(isinstance(migration_required, bool), "task migration required is invalid")
    tasks_before = object_field(data, "tasksBefore")
    before_actions_canonical: list[bool] = []
    for task_name in ("liveStt", "meetingAi"):
        task = object_field(tasks_before, task_name)
        require(task.get("present") is True, f"{task_name} pre-migration task missing")
        require(task.get("actionCount") == 1, f"{task_name} pre-migration action count")
        require(
            task.get("executeClass") == "windows-powershell",
            f"{task_name} pre-migration executable class",
        )
        require(
            task.get("executeTrusted") is True,
            f"{task_name} pre-migration executable is untrusted",
        )
        require(
            task.get("workingDirectoryClass") == "empty",
            f"{task_name} pre-migration working directory is set",
        )
        require(
            task.get("scriptPathClass") in {"canonical-repo", "legacy-user-repo"},
            f"{task_name} pre-migration script path is unrecognized",
        )
        require(
            task.get("actionMigratable") is True,
            f"{task_name} pre-migration action is not migratable",
        )
        action_canonical = task.get("actionCanonical")
        require(
            isinstance(action_canonical, bool),
            f"{task_name} pre-migration canonical flag is invalid",
        )
        before_actions_canonical.append(action_canonical)
    require(
        migration_required == (not all(before_actions_canonical)),
        "task migration requirement contradicts pre-migration actions",
    )
    if migration_required:
        require(
            task_migration.get("pinWithoutRestartExitCode") == 0,
            "source pin before task migration failed",
        )
        require(
            task_migration.get("whatIfExitCode") == 0,
            "task migration WhatIf failed",
        )
        require(
            task_migration.get("migrationExitCode") == 0,
            "task migration failed",
        )
        require(
            task_migration.get("sourceRollbackExitCode") == -1,
            "source rollback unexpectedly ran",
        )
    else:
        require(
            task_migration.get("pinWithoutRestartExitCode") == -1,
            "unexpected migration source pin",
        )
        require(
            task_migration.get("whatIfExitCode") == -1,
            "unexpected task migration WhatIf",
        )
        require(
            task_migration.get("migrationExitCode") == -1,
            "unexpected task migration",
        )
        require(
            task_migration.get("sourceRollbackExitCode") == -1,
            "unexpected source rollback",
        )

    principal = object_field(data, "principal")
    require(
        principal.get("expectedIdentity") is True,
        "rollout principal identity is not canonical",
    )
    require(
        principal.get("administrator") is True,
        "rollout principal is not an administrator",
    )

    ledger = object_field(data, "ledger")
    require(
        ledger.get("currentCommit") == expected_commit, "ledger currentCommit mismatch"
    )
    require(ledger.get("lastResult") == "tasks-restarted", "ledger lastResult mismatch")

    tasks = object_field(data, "tasks")
    for task_name in ("liveStt", "meetingAi"):
        task = object_field(tasks, task_name)
        require(task.get("present") is True, f"{task_name} task missing")
        require(task.get("state") == 4, f"{task_name} task is not running")
        require(
            task.get("actionCanonical") is True, f"{task_name} action is not canonical"
        )

    health = object_field(data, "health")
    live_health = object_field(health, "liveStt")
    meeting_health = object_field(health, "meetingAi")
    require(live_health.get("reachable") is True, "live STT health is unreachable")
    require(live_health.get("status") == "ok", "live STT health is not ok")
    require(live_health.get("device") == "cuda", "live STT is not on CUDA")
    require(meeting_health.get("reachable") is True, "meeting AI health is unreachable")
    require(meeting_health.get("status") == "ok", "meeting AI health is not ok")
    require(meeting_health.get("backend") == "ollama", "meeting AI is not on Ollama")

    web_socket = object_field(data, "webSocket")
    require(web_socket.get("ready") is True, "WebSocket did not become ready")
    require(web_socket.get("eventType") == "ready", "WebSocket ready event missing")
    require(
        web_socket.get("failureClass") == "none", "WebSocket failureClass is not none"
    )

    privacy = object_field(data, "privacy")
    require(
        privacy.get("rawAudioIncluded") is False, "raw audio inclusion is not false"
    )
    require(
        privacy.get("transcriptTextIncluded") is False,
        "transcript inclusion is not false",
    )
    require(
        privacy.get("secretMaterialIncluded") is False, "secret inclusion is not false"
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--expected-commit", required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        data = json.loads(args.evidence.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise EvidenceError("evidence root must be an object")
        verify(data, args.expected_commit)
    except (OSError, json.JSONDecodeError, EvidenceError) as exc:
        print(f"REJECTED: {exc}", file=sys.stderr)
        return 1
    print("PASS: Faz 24 GPU exact-SHA rollout evidence accepted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
