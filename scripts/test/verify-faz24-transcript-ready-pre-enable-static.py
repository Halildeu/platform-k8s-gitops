#!/usr/bin/env python3
"""Static default-off and policy guard for the transcript-ready pre-enable lane."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Sequence

import yaml


ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "config/faz24-transcript-ready-pre-enable-policy.v1.json"
CI = ROOT / ".github/workflows/ci.yml"
STATIC = ROOT / "scripts/test/faz24-finalization-rollout-static.sh"
READY_FLAG = "MAI_READY_CONSUMER_ENABLED"
TRUE_PATTERN = re.compile(
    rb"MAI_READY_CONSUMER_ENABLED\s*(?::|=)\s*[\"']?\s*(?:true|1|yes|on)\b",
    re.IGNORECASE,
)
KUBERNETES_ENV_PATTERN = re.compile(
    rb"\bname\s*:\s*[\"']?MAI_READY_CONSUMER_ENABLED[\"']?"
    rb"[\s\S]{0,240}?\bvalue\s*:\s*[\"']?\s*(?:true|1|yes|on)\b",
    re.IGNORECASE,
)
EXPECTED_REMEDIATIONS = {
    "nullFinalizations": "BACKFILL",
    "legacyOutbox": "PURGE_OR_REPUBLISH",
    "legacyRedis": "DLQ_ACK_XDEL",
    "consumerDisabled": "KEEP_CONSUMER_DISABLED",
    "metadataOnly": "RECOLLECT_METADATA_ONLY",
    "rerun": "FRESH_ZERO_SCAN",
}


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


def object_findings(value: Any, path: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        if value.get("name") == READY_FLAG:
            if value.get("value") != "false" or "valueFrom" in value:
                findings.append(path)
        for key, child in value.items():
            if key == READY_FLAG and child != "false":
                findings.append(f"{path}.{key}")
            findings.extend(object_findings(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(object_findings(child, f"{path}[{index}]"))
    return findings


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-render", type=Path, required=True)
    parser.add_argument("--test-eso-render", type=Path, required=True)
    parser.add_argument("--prod-render", type=Path, required=True)
    parser.add_argument("--prod-eso-render", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    if policy.get("producerCapabilities") != []:
        fail("producer allowlist changed without replacing the pending policy guard")
    if policy.get("hostStartupGuards") != []:
        fail(
            "host startup allowlist changed without replacing the pending policy guard"
        )
    if policy.get("currentBoundary", {}).get("enableAuthorized") is not False:
        fail("current policy must keep enableAuthorized=false")
    if policy.get("environment", {}).get("redisTls") is not False:
        fail("current Redis evidence target must remain explicit non-TLS test runtime")
    if policy.get("remediationEvidence") != EXPECTED_REMEDIATIONS:
        fail("policy remediation evidence classes drifted")

    operational_roots = (
        ROOT / "kustomize",
        ROOT / "deploy",
        ROOT / ".github/workflows",
    )
    findings: list[str] = []
    for base in operational_roots:
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            content = path.read_bytes()
            if TRUE_PATTERN.search(content) or KUBERNETES_ENV_PATTERN.search(content):
                findings.append(str(path.relative_to(ROOT)))
    renders = (
        args.test_render,
        args.test_eso_render,
        args.prod_render,
        args.prod_eso_render,
    )
    if len({render.resolve() for render in renders}) != 4:
        fail("the four expected render roles must use distinct manifest files")
    for render in renders:
        try:
            documents = yaml.safe_load_all(render.read_text(encoding="utf-8"))
            for index, document in enumerate(documents):
                findings.extend(
                    f"{render}:doc[{index}]{item}" for item in object_findings(document)
                )
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            fail(f"cannot inspect rendered manifest {render}: {type(exc).__name__}")
    if findings:
        fail("ready consumer became operationally enabled: " + ",".join(findings))

    static_text = STATIC.read_text(encoding="utf-8")
    required = (
        "collect_transcript_ready_pre_enable_evidence.py",
        "verify_transcript_ready_pre_enable_evidence.py",
        "tests.faz24.test_transcript_ready_pre_enable_gate",
        "verify-faz24-transcript-ready-pre-enable-static.py",
        "--test-render",
        "--test-eso-render",
        "--prod-render",
        "--prod-eso-render",
    )
    missing = [item for item in required if item not in static_text]
    if missing:
        fail("finalization static lane misses pre-enable guards: " + ",".join(missing))
    if "bash scripts/test/faz24-finalization-rollout-static.sh" not in CI.read_text(
        encoding="utf-8"
    ):
        fail("CI no longer runs the Faz 24 finalization static lane")
    print("PASS: Faz 24 transcript-ready pre-enable static default-off contract")


if __name__ == "__main__":
    main()
