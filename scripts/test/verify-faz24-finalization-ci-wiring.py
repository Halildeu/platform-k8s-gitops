#!/usr/bin/env python3
"""Verify that Faz 24 durable local evidence is an active, exact CI command."""

from __future__ import annotations

import shlex
import sys
from pathlib import Path
from typing import Any

import yaml


EXPECTED_COMMAND = [
    "python3",
    "scripts/test/verify-faz24-finalization-source-evidence.py",
    "docs/faz-24-evidence/2026-07-18-finalization-source-ci.json",
]
REMOTE_VERIFIER = "scripts/test/verify-faz24-finalization-remote-evidence.py"
OPERATOR_ONLY_VERIFIER = "scripts/test/verify-faz24-finalization-build-provenance.py"


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


def load_workflow(path: str) -> dict[str, Any]:
    try:
        with Path(path).open(encoding="utf-8") as stream:
            value = yaml.safe_load(stream)
    except OSError as error:
        fail(f"cannot read CI workflow: {error}")
    except yaml.YAMLError as error:
        fail(f"CI workflow is invalid YAML: {error}")
    if not isinstance(value, dict):
        fail("CI workflow root must be an object")
    return value


def active_steps(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    jobs = workflow.get("jobs", {})
    if not isinstance(jobs, dict):
        fail("CI workflow jobs must be an object")
    steps: list[dict[str, Any]] = []
    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps", []):
            if isinstance(step, dict):
                steps.append(step)
    return steps


def main() -> None:
    if len(sys.argv) != 2:
        fail("usage: verify-faz24-finalization-ci-wiring.py WORKFLOW_YAML")
    matches: list[dict[str, Any]] = []
    for step in active_steps(load_workflow(sys.argv[1])):
        run = step.get("run")
        if not isinstance(run, str):
            continue
        if (
            EXPECTED_COMMAND[1] not in run
            and REMOTE_VERIFIER not in run
            and OPERATOR_ONLY_VERIFIER not in run
        ):
            continue
        try:
            tokens = shlex.split(run)
        except ValueError as error:
            fail(f"cannot parse CI run command: {error}")
        if OPERATOR_ONLY_VERIFIER in tokens:
            fail("operator-only image provenance verifier became an active CI gate")
        if REMOTE_VERIFIER in tokens:
            fail("network/retention-bound remote evidence verifier became an active CI gate")
        if tokens == EXPECTED_COMMAND:
            matches.append(step)

    if len(matches) != 1:
        fail(f"expected one active exact source evidence command, got {len(matches)}")
    print("PASS: Faz 24 durable source evidence CI wiring")


if __name__ == "__main__":
    main()
