#!/usr/bin/env python3
"""Build a metadata-only operator handoff package for Faz 24 product gates.

The package coordinates the remaining G-CAP, G-OPS, and G-COMP evidence ingest
sequence for platform-k8s-gitops#1615. It does not collect runtime evidence,
run a pilot, mutate Kubernetes/Vault/firewall/legal state, ingest evidence, or
make an acceptance claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "faz24.productGate.operator-handoff.v1"
MANIFEST_NAME = "faz24-product-gate-operator-handoff.json"
README_NAME = "README.md"
SHA256SUMS_NAME = "SHA256SUMS"

REPO = "Halildeu/platform-k8s-gitops"
DEFAULT_BATCH_ID = "faz24-product-gate-20260628"
INGEST_WORKFLOW = "faz24-product-gate-evidence-ingest.yml"

GCAP_INPUT_PATHS = [
    "/tmp/faz24-external-recorder-smoke-01.verify.json",
    "/tmp/faz24-external-recorder-smoke-02.verify.json",
    "/tmp/faz24-external-recorder-smoke-03.verify.json",
    "/tmp/faz24-desktop-capture-evidence.verify.json",
    "/tmp/faz24-desktop-capture-evidence-05.verify.json",
]
GCAP_VERIFY_PATH = "/tmp/faz24-gcap-capture-gate.verify.json"
GCAP_INGEST_INPUT_PATH = "/tmp/faz24-gcap-capture-gate.ingest-input.json"
GOPS_EVIDENCE_PATH = "/tmp/faz24-gops-operability-evidence.json"
GOPS_VERIFY_PATH = "/tmp/faz24-gops-operability-gate.verify.json"
GOPS_INGEST_INPUT_PATH = "/tmp/faz24-gops-operability-gate.ingest-input.json"
GCOMP_EVIDENCE_PATH = "/tmp/faz24-gcomp-compliance-evidence.json"
GCOMP_VERIFY_PATH = "/tmp/faz24-gcomp-compliance-gate.verify.json"
GCOMP_INGEST_INPUT_PATH = "/tmp/faz24-gcomp-compliance-gate.ingest-input.json"

SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.:@/-]{1,180}$")
FORBIDDEN_PATTERNS = (
    re.compile(r"-----BEGIN .*PRIVATE KEY-----"),
    re.compile(r"-----BEGIN CERTIFICATE-----"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"data:audio/[A-Za-z0-9.+-]+;base64,", re.IGNORECASE),
)


def die(message: str) -> None:
    print(f"ERR {message}", file=sys.stderr)
    raise SystemExit(2)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_single_line(label: str, value: str) -> None:
    if "\n" in value or "\r" in value:
        die(f"{label} must be single-line")
    if any(pattern.search(value) for pattern in FORBIDDEN_PATTERNS):
        die(f"{label} must not contain certificate, private key, token-like, or raw-audio material")


def validate_safe_token(label: str, value: str) -> None:
    validate_single_line(label, value)
    parts = re.split(r"[\\/]+", value)
    if value.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", value) or ".." in parts:
        die(f"{label} must be relative/symbolic and stay inside the handoff boundary")
    if not SAFE_TOKEN_RE.match(value):
        die(f"{label} contains unsupported characters")


def validate_args(args: argparse.Namespace) -> None:
    validate_safe_token("operator-batch-id", args.operator_batch_id)
    validate_safe_token("gitops-ref", args.gitops_ref)


def command_block(lines: list[str]) -> str:
    return "\n".join(lines)


def product_gate_ingest_command(gate: str, evidence_path: str, gitops_ref: str) -> str:
    env_name = f"{gate.upper()}_EVIDENCE_B64"
    return command_block(
        [
            f'{env_name}="$(base64 < {evidence_path} | tr -d \'\\n\')"',
            f"gh workflow run {INGEST_WORKFLOW} \\",
            f"  --repo {REPO} \\",
            f"  --ref {gitops_ref} \\",
            f"  -f gate={gate} \\",
            f'  -f evidence_json_base64="${{{env_name}}}"',
        ]
    )


def build_manifest(args: argparse.Namespace) -> dict[str, Any]:
    gcap_input_args = [
        f"  --evidence-file {path} \\" for path in GCAP_INPUT_PATHS
    ]
    gcap_verify = command_block(
        [
            "python3 scripts/faz24/verify_gcap_capture_gate_evidence.py \\",
            *gcap_input_args,
            "  --min-attempts 5 \\",
            "  --min-distinct-meetings 5 \\",
            "  --min-distinct-sessions 5 \\",
            "  --min-success-rate 0.95 \\",
            "  --max-retry-rate 0.10 \\",
            "  --max-failure-rate 0.05 \\",
            f"  --output-file {GCAP_VERIFY_PATH}",
            "jq -e '",
            '  .schemaVersion == "faz24.gcapCaptureGateVerifier.v1" and',
            '  .status == "pass" and',
            "  .tokenIncluded == false and",
            "  .boundaries.rawAudioIncluded == false and",
            "  .boundaries.rawTranscriptIncluded == false and",
            "  .boundaries.directClientToStt == false and",
            "  .boundaries.directSttTranscriptProven == false and",
            "  .boundaries.computePlaneAuditProven == false and",
            "  .boundaries.productionReady == false",
            f"' {GCAP_VERIFY_PATH}",
        ]
    )
    gcap_ingest_input = command_block(
        [
            f"jq -s '{{\"reports\": .}}' {' '.join(GCAP_INPUT_PATHS)} > {GCAP_INGEST_INPUT_PATH}",
            "jq -e '",
            "  (.reports | length) >= 5 and",
            '  all(.reports[]; .status == "pass" and .tokenIncluded == false)',
            f"' {GCAP_INGEST_INPUT_PATH}",
        ]
    )
    gcap_ingest = product_gate_ingest_command("gcap", GCAP_INGEST_INPUT_PATH, args.gitops_ref)

    gops_verify = command_block(
        [
            "python3 scripts/faz24/verify_gops_operability_gate_evidence.py \\",
            f"  --evidence-file {GOPS_EVIDENCE_PATH} \\",
            f"  --output-file {GOPS_VERIFY_PATH}",
            "jq -e '",
            '  .schemaVersion == "faz24.gopsOperabilityGateVerifier.v1" and',
            '  .status == "pass" and',
            "  .tokenIncluded == false and",
            "  .boundaries.secretsIncluded == false and",
            "  .boundaries.rawAudioIncluded == false and",
            "  .boundaries.rawTranscriptIncluded == false and",
            "  .boundaries.liveProductionMutation == false and",
            "  .boundaries.productionReady == false",
            f"' {GOPS_VERIFY_PATH}",
        ]
    )
    gops_ingest_input = command_block(
        [
            "jq -e '",
            '  .schemaVersion == "faz24.gopsOperabilityEvidence.v1" and',
            '  .status == "pass" and',
            "  .tokenIncluded == false and",
            "  .boundaries.secretsIncluded == false and",
            "  .boundaries.rawAudioIncluded == false and",
            "  .boundaries.rawTranscriptIncluded == false and",
            "  .boundaries.liveProductionMutation == false and",
            "  .boundaries.productionReady == false",
            f"' {GOPS_EVIDENCE_PATH} > {GOPS_INGEST_INPUT_PATH}",
        ]
    )
    gops_ingest = product_gate_ingest_command("gops", GOPS_INGEST_INPUT_PATH, args.gitops_ref)

    gcomp_verify = command_block(
        [
            "python3 scripts/faz24/verify_gcomp_compliance_gate_evidence.py \\",
            f"  --evidence-file {GCOMP_EVIDENCE_PATH} \\",
            f"  --output-file {GCOMP_VERIFY_PATH}",
            "jq -e '",
            '  .schemaVersion == "faz24.gcompComplianceGateVerifier.v1" and',
            '  .status == "pass" and',
            "  .tokenIncluded == false and",
            "  .boundaries.ownerLegalTrackNotificationPresent == true and",
            "  .boundaries.retentionDurationsParametric == true and",
            "  .boundaries.retentionDefaultsFailClosed == true and",
            "  .boundaries.retentionDurationsHardcoded == false and",
            "  .boundaries.legalAdviceClaimed == false and",
            "  .boundaries.legalAcceptanceClaimed == false and",
            "  .boundaries.productionLegalGoClaimed == false and",
            "  .boundaries.liveProductionMutation == false and",
            "  .boundaries.productionReady == false",
            f"' {GCOMP_VERIFY_PATH}",
        ]
    )
    gcomp_ingest_input = command_block(
        [
            "jq -e '",
            '  .schemaVersion == "faz24.gcompComplianceEvidence.v1" and',
            '  .status == "pass" and',
            "  .tokenIncluded == false and",
            "  .boundaries.ownerLegalTrackNotificationPresent == true and",
            "  .boundaries.retentionDurationsParametric == true and",
            "  .boundaries.retentionDefaultsFailClosed == true and",
            "  .boundaries.retentionDurationsHardcoded == false and",
            "  .boundaries.legalAdviceClaimed == false and",
            "  .boundaries.legalAcceptanceClaimed == false and",
            "  .boundaries.productionLegalGoClaimed == false and",
            "  .boundaries.liveProductionMutation == false and",
            "  .boundaries.productionReady == false",
            f"' {GCOMP_EVIDENCE_PATH} > {GCOMP_INGEST_INPUT_PATH}",
        ]
    )
    gcomp_ingest = product_gate_ingest_command("gcomp", GCOMP_INGEST_INPUT_PATH, args.gitops_ref)

    return {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": utc_now(),
        "repo": REPO,
        "operatorBatchId": args.operator_batch_id,
        "issues": {
            "gitopsRollup": "platform-k8s-gitops#1615",
            "gcapAggregate": "platform-k8s-gitops#2027",
            "gopsVerifier": "platform-k8s-gitops#2022",
            "gcompVerifier": "platform-k8s-gitops#2024",
            "productGateIngest": "platform-k8s-gitops#2027",
        },
        "acceptanceBoundary": {
            "issueStatus": "needs-verify",
            "operatorExecutionRequired": True,
            "acceptedRedactedEvidenceRequired": True,
            "gcapVerifierPassRequired": True,
            "gopsVerifierPassRequired": True,
            "gcompVerifierPassRequired": True,
            "productGateIngestRequired": True,
            "reviewerAcceptanceRequired": True,
            "legalTrackParallel": True,
            "kvkkOwnerLegalAcceptanceNotEngineeringBlocker": True,
            "retentionDurationsParametric": True,
            "ownerRetentionValuesApplyWhenProvided": True,
            "doesNotAcceptLegalGo": True,
            "doesNotAcceptDirectStt": True,
            "doesNotAcceptComputePlaneAudit": True,
            "doesNotAcceptDesktopMicLoopback": True,
            "doesNotAcceptI3ManagementAudit": True,
            "doesNotAcceptI7ProdGate": True,
            "doesNotAcceptProductionReadiness": True,
        },
        "mutationBoundary": {
            "packageBuildEvidenceMutation": False,
            "packageBuildClusterMutation": False,
            "packageBuildVaultMutation": False,
            "packageBuildFirewallMutation": False,
            "packageBuildLegalMutation": False,
            "packageBuildProductionMutation": False,
            "containsCredentials": False,
            "containsRawAudio": False,
            "containsRawTranscript": False,
            "containsRawPromptOrResponse": False,
            "containsUnredactedPersonalData": False,
            "containsRawHttpBodies": False,
            "containsRawCommandOutput": False,
        },
        "target": {
            "gitopsRef": args.gitops_ref,
            "ingestWorkflow": f".github/workflows/{INGEST_WORKFLOW}",
            "gcapInputPaths": GCAP_INPUT_PATHS,
            "gcapVerifierPath": GCAP_VERIFY_PATH,
            "gcapIngestInputPath": GCAP_INGEST_INPUT_PATH,
            "gopsEvidencePath": GOPS_EVIDENCE_PATH,
            "gopsVerifierPath": GOPS_VERIFY_PATH,
            "gopsIngestInputPath": GOPS_INGEST_INPUT_PATH,
            "gcompEvidencePath": GCOMP_EVIDENCE_PATH,
            "gcompVerifierPath": GCOMP_VERIFY_PATH,
            "gcompIngestInputPath": GCOMP_INGEST_INPUT_PATH,
        },
        "orderedGates": [
            {
                "id": "redacted-evidence-selection",
                "owner": "operator/reviewer",
                "statusBeforeExecution": "pending",
                "mustNotBeRecordedInPackage": [
                    "credentials",
                    "authorization headers",
                    "private keys",
                    "certificates",
                    "raw audio or base64 audio",
                    "raw transcript text",
                    "raw prompts or responses",
                    "personal data",
                    "legal advice text",
                    "raw shell transcript",
                ],
                "notes": [
                    "Use only already accepted redacted verifier summaries/envelopes.",
                    "G-CAP input must be verifier summaries, not raw recorder or desktop evidence.",
                    "G-OPS/G-COMP input must be metadata-only evidence envelopes.",
                ],
            },
            {
                "id": "gcap-aggregate",
                "owner": "operator/reviewer",
                "statusBeforeExecution": "blocked-until-enough-verifier-summaries",
                "commands": {
                    "verify": gcap_verify,
                    "prepareIngestInput": gcap_ingest_input,
                    "ingest": gcap_ingest,
                },
            },
            {
                "id": "gops-operability",
                "owner": "operator/reviewer",
                "statusBeforeExecution": "blocked-until-redacted-onprem-evidence",
                "commands": {
                    "verify": gops_verify,
                    "prepareIngestInput": gops_ingest_input,
                    "ingest": gops_ingest,
                },
            },
            {
                "id": "gcomp-compliance",
                "owner": "operator/reviewer",
                "statusBeforeExecution": "blocked-until-redacted-engineering-evidence",
                "commands": {
                    "verify": gcomp_verify,
                    "prepareIngestInput": gcomp_ingest_input,
                    "ingest": gcomp_ingest,
                },
            },
            {
                "id": "reviewer-acceptance",
                "owner": "reviewer",
                "statusBeforeExecution": "blocked-until-ingest-artifacts-attached",
                "notes": [
                    "Attach workflow URL, artifact name, verifier status, and reviewer notes.",
                    "Do not move #1615 beyond Needs Verify without accepted live/operator evidence.",
                    "Legal/VERBIS owner acceptance remains parallel and is not claimed here.",
                ],
            },
        ],
        "issueCommentTemplates": {
            "productGatePackage": (
                "Product-gate operator handoff package attached. Boundary: metadata-only "
                "coordination artifact; no G-CAP/G-OPS/G-COMP live acceptance, legal go, "
                "runtime mutation, direct-STT, or #1615 status advance is claimed."
            ),
            "gcapIngest": (
                "G-CAP product-gate ingest artifact attached. Boundary: source-side verifier "
                "summary validation only; direct-STT, compute-plane audit, I7, and production "
                "readiness remain separate."
            ),
            "gopsIngest": (
                "G-OPS product-gate ingest artifact attached. Boundary: redacted on-prem "
                "operability metadata only; no live production mutation or production readiness."
            ),
            "gcompIngest": (
                "G-COMP product-gate ingest artifact attached. Boundary: engineering compliance "
                "evidence only; KVKK/VERBIS legal owner acceptance is parallel and not claimed."
            ),
        },
    }


def render_readme(manifest: dict[str, Any]) -> str:
    target = manifest["target"]
    gates = {item["id"]: item for item in manifest["orderedGates"]}

    return f"""# Faz 24 product-gate operator handoff

Scope: platform-k8s-gitops#1615 G-CAP, G-OPS, and G-COMP product-gate evidence sequence.

This package is a coordination artifact only. It does not collect runtime
evidence, run a pilot, mutate Kubernetes, touch Vault, change firewall or legal
state, ingest evidence, store raw meeting data, or advance #1615.

## Boundary

- Current status remains `Needs Verify`.
- Use only accepted redacted metadata evidence.
- G-CAP requires multiple accepted external-recorder and/or desktop verifier
  summaries. Raw recorder or raw desktop envelopes are not aggregate input.
- G-OPS requires redacted install, upgrade, backup, restore, rollback, secret
  delivery, observability, and runbook evidence.
- G-COMP requires engineering evidence for consent, parametric retention,
  legal-hold, access-audit, deletion/export, owner legal-track notification,
  redaction, and runbook controls.
- KVKK/VERBIS owner legal acceptance is a parallel legal track after owner
  notification; it is not an engineering completion blocker and is not claimed
  by this package.
- Retention duration values are parametric. If owner values are supplied, they
  must be applied as config with owner provenance; otherwise durable storage
  must remain fail-closed/unset.
- Direct-STT, compute-plane audit, desktop mic/loopback, I3, I7, legal go, and
  production readiness remain separate gates.

## Target

- ingest workflow: `{target["ingestWorkflow"]}`
- G-CAP verifier summary: `{target["gcapVerifierPath"]}`
- G-CAP ingest input wrapper: `{target["gcapIngestInputPath"]}`
- G-OPS evidence: `{target["gopsEvidencePath"]}`
- G-OPS verifier summary: `{target["gopsVerifierPath"]}`
- G-OPS ingest input: `{target["gopsIngestInputPath"]}`
- G-COMP evidence: `{target["gcompEvidencePath"]}`
- G-COMP verifier summary: `{target["gcompVerifierPath"]}`
- G-COMP ingest input: `{target["gcompIngestInputPath"]}`

## Gate 0 - evidence selection

Use only already accepted redacted metadata inputs. Do not attach credentials,
authorization headers, private keys, certificates, raw audio, transcript text,
prompts, responses, personal data, legal advice text, or raw shell transcripts.

## Gate 1 - G-CAP aggregate

Run this only after enough accepted verifier summaries exist:

```bash
{gates["gcap-aggregate"]["commands"]["verify"]}
```

Prepare the workflow input from the verifier summaries, not from the aggregate
verifier output:

```bash
{gates["gcap-aggregate"]["commands"]["prepareIngestInput"]}
```

Ingest the wrapper through the no-mutation workflow:

```bash
{gates["gcap-aggregate"]["commands"]["ingest"]}
```

## Gate 2 - G-OPS operability

```bash
{gates["gops-operability"]["commands"]["verify"]}
```

Prepare a schema-checked redacted input for the workflow:

```bash
{gates["gops-operability"]["commands"]["prepareIngestInput"]}
```

```bash
{gates["gops-operability"]["commands"]["ingest"]}
```

## Gate 3 - G-COMP compliance engineering

```bash
{gates["gcomp-compliance"]["commands"]["verify"]}
```

Prepare a schema-checked redacted input for the workflow:

```bash
{gates["gcomp-compliance"]["commands"]["prepareIngestInput"]}
```

```bash
{gates["gcomp-compliance"]["commands"]["ingest"]}
```

## Gate 4 - reviewer acceptance

Attach each workflow URL, artifact name, verifier status, and reviewer note to
the relevant gate issue before moving any gate beyond `Needs Verify`.

## Follow-up comments

Package comment template:

```text
{manifest["issueCommentTemplates"]["productGatePackage"]}
```

G-CAP ingest comment template:

```text
{manifest["issueCommentTemplates"]["gcapIngest"]}
```

G-OPS ingest comment template:

```text
{manifest["issueCommentTemplates"]["gopsIngest"]}
```

G-COMP ingest comment template:

```text
{manifest["issueCommentTemplates"]["gcompIngest"]}
```
"""


def write_text(path: Path, metadata_content: str) -> None:
    path.write_text(metadata_content, encoding="utf-8")


def write_sha256sums(output_dir: Path) -> None:
    lines = []
    for path in sorted(output_dir.iterdir(), key=lambda item: item.name):
        if path.name == SHA256SUMS_NAME or not path.is_file():
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.name}")
    write_text(output_dir / SHA256SUMS_NAME, "\n".join(lines) + "\n")


def build_package(args: argparse.Namespace) -> dict[str, Any]:
    validate_args(args)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = build_manifest(args)
    write_text(output_dir / MANIFEST_NAME, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    write_text(output_dir / README_NAME, render_readme(manifest))
    write_sha256sums(output_dir)
    return manifest


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, help="directory for the handoff files")
    parser.add_argument("--operator-batch-id", default=DEFAULT_BATCH_ID)
    parser.add_argument("--gitops-ref", default="main")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    build_package(args)
    print(f"status=pass packageDir={Path(args.output_dir)}")
    print("schema=faz24-product-gate-operator-handoff-v1")
    print("acceptance=needs-operator-runtime-evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
