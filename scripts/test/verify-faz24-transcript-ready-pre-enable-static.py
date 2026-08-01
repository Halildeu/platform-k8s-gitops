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
TRANSIT_POLICY = (
    ROOT
    / "bootstrap/vault-policies/test/faz24-transcript-ready-permit-signer.hcl"
)
CONTRACT = ROOT / "scripts/faz24/transcript_ready_pre_enable_contract.py"
VERIFIER = ROOT / "scripts/faz24/verify_transcript_ready_pre_enable_evidence.py"
TRUST_BUILDER = ROOT / "scripts/faz24/build_transcript_ready_permit_trust_root.py"
PERMIT_SIGNER = ROOT / "scripts/faz24/sign_transcript_ready_pre_enable_permit.py"
TRANSIT_BOOTSTRAP = (
    ROOT / "scripts/ops/bootstrap_faz24_transcript_ready_permit_transit.py"
)
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
EXPECTED_PRODUCER_CAPABILITIES = [
    {
        "transcriptImageDigest": "sha256:6f930cec0ba1de575c9ce6f9779d4913e50ebe4bc47c1e82eb7fcd42eea53884",
        "backendCommit": "619378ad2c0ec5a11d1efc62a7a1e6465ee220b5",
        "eventContractEvidencePath": "docs/faz-24-evidence/2026-08-01-transcript-ready-event-contract.json",
        "eventContractSha256": "a54c1a165656a13b413bea6d7138881b0520cdce369fad496f65abcb75c85fe9",
        "gateContractSha256": "e4c080a6f080deecebe7d713a8993372e8e6fbf94d0b1fe5d1fe90822fa047f3",
        "backfillEvidencePath": "docs/faz-24-evidence/2026-08-01-transcript-ready-backfill.json",
        "backfillEvidenceSha256": "4b562339f510d689e05f25bb96311125d76ccdcf4d70a08099b0a12d4e256795",
        "outboxRemediationEvidencePath": "docs/faz-24-evidence/2026-08-01-transcript-ready-outbox-remediation.json",
        "outboxRemediationEvidenceSha256": "34d6189757df167041270875557ae8a23eef06b893173e840804883316378f49",
        "redisRemediationEvidencePath": "docs/faz-24-evidence/2026-08-01-transcript-ready-redis-remediation.json",
        "redisRemediationEvidenceSha256": "d059fbe057f758d3dfcfe9e27a7696aa534970b65f95590fb23c78f5a21b7ac1",
        "analysisRunIdEmission": "non-null-v1",
        "finalizationAnalysisRunId": "uuid-not-null-event-bound",
    }
]
EXPECTED_HOST_STARTUP_GUARDS = [
    {
        "platformAiCommit": "4df5fcd5039779c0fd9f57463cdaf54d6e43be74",
        "startupScriptSha256": "97fd2de20d13f4cbf65ceee8dc2921d6a69586bb589000ba768854a2e08144e3",
        "permitRequired": True,
    }
]
EXPECTED_TRANSIT_POLICY = '''# TEST-only Faz 24 transcript-ready pre-enable permit signer.
#
# This token can sign with one dedicated non-exportable Ed25519 Transit key. It
# cannot read/export/delete/rotate keys, mint tokens, access KV, or use the
# cross-ai signing domain.

path "meeting-ai/sign/transcript-ready-permit" {
  capabilities = ["update"]
}

path "auth/token/lookup-self" {
  capabilities = ["read"]
}

path "auth/token/revoke-self" {
  capabilities = ["update"]
}
'''


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
    if policy.get("producerCapabilities") != EXPECTED_PRODUCER_CAPABILITIES:
        fail("producer allowlist must remain pinned to the reviewed exact tuple")
    if policy.get("hostStartupGuards") != EXPECTED_HOST_STARTUP_GUARDS:
        fail("host startup allowlist must remain pinned to the reviewed exact tuple")
    if policy.get("currentBoundary") != {
        "enableAuthorized": True,
        "reason": (
            "exact-test-producer-remediation-receipts-and-permit-enforcing-"
            "host-guard-approved"
        ),
    }:
        fail("current policy must retain the exact reviewed TEST authorization")
    if policy.get("environment", {}).get("redisTls") is not False:
        fail("current Redis evidence target must remain explicit non-TLS test runtime")
    if policy.get("environment", {}).get("appEnv") != "test":
        fail("current permit target must remain explicit appEnv=test")
    if policy.get("environment", {}).get("postgresSchema") != "transcript_service":
        fail("current PostgreSQL evidence target must remain transcript_service")
    if policy.get("environment", {}).get("gpuHostComputerName") != "SRB-AIDENETIMPC":
        fail("current GPU host identity must remain SRB-AIDENETIMPC")
    if policy.get("remediationEvidence") != EXPECTED_REMEDIATIONS:
        fail("policy remediation evidence classes drifted")

    if TRANSIT_POLICY.read_text(encoding="utf-8") != EXPECTED_TRANSIT_POLICY:
        fail("dedicated TEST Transit signer policy drifted")
    source_markers = {
        CONTRACT: (
            'VERDICT_SCHEMA = "faz24.transcriptReadyPreEnableVerdict.v2"',
            'PERMIT_TRUST_ROOT_SCHEMA = "faz24.transcriptReadyPermitTrustRoot.v1"',
            "application/vnd.acik.faz24.transcript-ready-pre-enable-verdict.v2+json",
        ),
        VERIFIER: ("def build_verdict(", '"targetAppEnv"', '"evidenceSha256"'),
        TRUST_BUILDER: (
            'TRANSIT_MOUNT = "meeting-ai"',
            'TRANSIT_KEY_NAME = "transcript-ready-permit"',
            "requiresOutOfBandOwnerPin",
        ),
        PERMIT_SIGNER: (
            'TRANSIT_MOUNT = "meeting-ai"',
            'TRANSIT_KEY_NAME = "transcript-ready-permit"',
            "Ed25519PublicKey.from_public_bytes",
            "VaultTransitSigner",
            "_recompute_canonical_verdict",
            "auth/token/revoke-self",
        ),
        TRANSIT_BOOTSTRAP: (
            'MOUNT = "meeting-ai"',
            'KEY_NAME = "transcript-ready-permit"',
            'POLICY_NAME = "faz24-transcript-ready-permit-signer-test"',
            '"auth/token/lookup-accessor"',
            '"auth/token/revoke-accessor"',
        ),
    }
    for path, markers in source_markers.items():
        content = path.read_text(encoding="utf-8")
        missing_markers = [marker for marker in markers if marker not in content]
        if missing_markers:
            fail(
                f"{path.relative_to(ROOT)} misses permit markers: "
                + ",".join(missing_markers)
            )

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
        "build_transcript_ready_permit_trust_root.py",
        "sign_transcript_ready_pre_enable_permit.py",
        "bootstrap_faz24_transcript_ready_permit_transit.py",
        "tests.faz24.test_transcript_ready_pre_enable_gate",
        "tests.faz24.test_transcript_ready_permit_bootstrap",
        "tests.faz24.test_transcript_ready_permit_signer",
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
