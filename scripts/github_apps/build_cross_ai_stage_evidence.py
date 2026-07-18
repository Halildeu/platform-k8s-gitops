#!/usr/bin/env python3
"""Build the one-file canonical outcome artifact for a protected stage."""

from __future__ import annotations

import argparse
import base64
import binascii
import os
import stat
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from scripts.github_apps.cross_ai_deployment_policy.canonical import (
    canonical_bytes,
    sha256_digest,
)
from scripts.github_apps.cross_ai_deployment_policy.errors import PolicyError, reject
from scripts.github_apps.cross_ai_deployment_policy.jsonutil import (
    load_json_file,
    loads_json_bytes,
)
from scripts.github_apps.cross_ai_deployment_policy.timeutil import (
    parse_utc,
    utc_now,
    utc_seconds,
)


ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "schema/cross-ai-deployment-stage-evidence-v1.schema.json"
STAGE_CONCLUSIONS = {
    "apply": {"success", "failure"},
    "browser-evidence": {"success", "failure"},
    "compensating-rollback": {"rolled-back", "failure"},
}


def _positive_env(name: str) -> int:
    value = os.environ.get(name, "")
    if not value.isascii() or not value.isdigit() or value.startswith("0"):
        reject("STAGE_EVIDENCE_ENV_INVALID", f"{name} is not a positive integer")
    parsed = int(value)
    if parsed > 9_007_199_254_740_991:
        reject("STAGE_EVIDENCE_ENV_INVALID", f"{name} exceeds JSON safe integer")
    return parsed


def _payload(envelope: dict[str, Any]) -> dict[str, Any]:
    encoded = envelope.get("payload")
    if not isinstance(encoded, str):
        reject("STAGE_EVIDENCE_BUNDLE_INVALID", "bundle payload is missing")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        reject("STAGE_EVIDENCE_BUNDLE_INVALID", "bundle payload is not canonical base64")
    payload = loads_json_bytes(raw, max_bytes=4 * 1024 * 1024, label="bundle")
    if canonical_bytes(payload) != raw:
        reject("STAGE_EVIDENCE_BUNDLE_INVALID", "bundle payload is not canonical JSON")
    return payload


def _watchdog(
    path: Path | None,
    stage: str,
    conclusion: str,
    *,
    current,
    grant_end,
) -> str | None:
    if stage != "apply":
        if path is not None:
            reject("STAGE_EVIDENCE_WATCHDOG_INVALID", "non-apply stage has watchdog input")
        return None
    if path is None or not path.is_file() or path.is_symlink():
        if conclusion == "failure":
            return None
        reject(
            "STAGE_EVIDENCE_WATCHDOG_INVALID",
            "successful apply evidence requires the live watchdog expiry receipt",
        )
    value = path.read_text(encoding="ascii").strip()
    parsed = parse_utc(value, "watchdogExpiresAt")
    if parsed <= current or parsed > grant_end:
        reject(
            "STAGE_EVIDENCE_WATCHDOG_INVALID",
            "watchdog is expired or exceeds the signed grant",
        )
    if conclusion not in STAGE_CONCLUSIONS[stage]:
        reject("STAGE_EVIDENCE_CONCLUSION_INVALID", "apply conclusion is invalid")
    return utc_seconds(parsed)


def _write_exclusive(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=False, mode=0o700)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError:
        reject("STAGE_EVIDENCE_OUTPUT_INVALID", "evidence output must be new")
    try:
        os.write(descriptor, canonical_bytes(payload))
        os.fsync(descriptor)
        if stat.S_IMODE(os.fstat(descriptor).st_mode) != 0o600:
            reject("STAGE_EVIDENCE_OUTPUT_INVALID", "evidence output is not private")
    finally:
        os.close(descriptor)


def build(args: argparse.Namespace) -> tuple[dict[str, Any], str]:
    if args.conclusion not in STAGE_CONCLUSIONS[args.stage]:
        reject("STAGE_EVIDENCE_CONCLUSION_INVALID", "stage conclusion is invalid")
    response = load_json_file(args.bootstrap_file)
    if response.get("stage") != args.stage:
        reject("STAGE_EVIDENCE_BINDING_INVALID", "bootstrap stage differs")
    payload = _payload(response.get("bundleEnvelope", {}))
    if sha256_digest(response["bundleEnvelope"]) != response.get("bundleSha256"):
        reject("STAGE_EVIDENCE_BINDING_INVALID", "bootstrap bundle digest differs")
    subject = payload.get("subject")
    stages = payload.get("workflowStages")
    if not isinstance(subject, dict) or not isinstance(stages, list):
        reject("STAGE_EVIDENCE_BUNDLE_INVALID", "signed subject or stages are missing")
    matches = [item for item in stages if item.get("stage") == args.stage]
    if len(matches) != 1:
        reject("STAGE_EVIDENCE_BINDING_INVALID", "signed stage is ambiguous")
    signed_stage = matches[0]
    grant = payload.get("grant")
    if not isinstance(grant, dict):
        reject("STAGE_EVIDENCE_BUNDLE_INVALID", "signed grant is missing")
    current = utc_now()
    grant_start = parse_utc(grant.get("notBefore"), "grant.notBefore")
    grant_end = parse_utc(grant.get("expiresAt"), "grant.expiresAt")
    if current < grant_start or current >= grant_end:
        reject("STAGE_EVIDENCE_GRANT_INVALID", "signed grant is not currently active")
    request_id = response.get("requestId")
    run_id = _positive_env("GITHUB_RUN_ID")
    run_attempt = _positive_env("GITHUB_RUN_ATTEMPT")
    if (
        response.get("runId") != run_id
        or response.get("runAttempt") != run_attempt
        or response.get("headSha") != os.environ.get("GITHUB_SHA")
        or response.get("intentRef") != os.environ.get("GITHUB_REF")
        or subject.get("repository") != os.environ.get("GITHUB_REPOSITORY")
        or str(subject.get("repositoryId")) != os.environ.get("GITHUB_REPOSITORY_ID")
        or response.get("workflowPath") != signed_stage.get("workflowPath")
    ):
        reject("STAGE_EVIDENCE_BINDING_INVALID", "runtime differs from signed bootstrap")
    watchdog = _watchdog(
        args.watchdog_expires_file,
        args.stage,
        args.conclusion,
        current=current,
        grant_end=grant_end,
    )
    evidence = {
        "schemaVersion": "acik.cross-ai-deployment-stage-evidence.v1",
        "requestId": request_id,
        "stage": args.stage,
        "runId": run_id,
        "runAttempt": run_attempt,
        "repositoryId": subject["repositoryId"],
        "repository": subject["repository"],
        "environment": subject["environment"],
        "headSha": subject["headSha"],
        "intentRef": subject["intentRef"],
        "sessionSha256": subject["sessionSha256"],
        "workflowBlobSha256": signed_stage["workflowBlobSha256"],
        "artifactSetSha256": subject["artifactSetSha256"],
        "rollbackPlanSha256": subject["rollbackPlanSha256"],
        "postDeployVerifierSha256": subject["postDeployVerifierSha256"],
        "watchdogExpiresAt": watchdog,
        "conclusion": args.conclusion,
        "createdAt": utc_seconds(current),
    }
    schema = load_json_file(SCHEMA)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(
            evidence
        ),
        key=lambda item: list(item.path),
    )
    if errors:
        reject("STAGE_EVIDENCE_SCHEMA_INVALID", "generated evidence is invalid")
    output = args.output_dir / "cross-ai-stage-evidence.json"
    _write_exclusive(output, evidence)
    artifact_name = (
        f"cross-ai-stage-outcome-{request_id}-{args.stage}-{run_id}-{run_attempt}"
    )
    with args.github_output.open("a", encoding="utf-8") as handle:
        handle.write(f"artifact-name={artifact_name}\n")
        handle.write(f"evidence-file={output}\n")
    return evidence, artifact_name


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bootstrap-file", type=Path, required=True)
    parser.add_argument("--stage", choices=sorted(STAGE_CONCLUSIONS), required=True)
    parser.add_argument("--conclusion", required=True)
    parser.add_argument("--watchdog-expires-file", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--github-output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        _evidence, artifact = build(parse_args(argv))
    except (PolicyError, OSError, UnicodeError) as exc:
        code = exc.code if isinstance(exc, PolicyError) else "STAGE_EVIDENCE_IO_INVALID"
        print(f"FAIL: {code}", file=__import__("sys").stderr)
        return 2
    print(f"PASS: canonical stage evidence prepared as {artifact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
