#!/usr/bin/env python3
"""Build a metadata-only operator handoff package for Faz 24 desktop capture.

The package coordinates the remaining platform-desktop microphone + loopback
capture evidence path for platform-k8s-gitops#1615. It does not run the desktop
app, read tokens, send audio, connect to testai, or collect live evidence.
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


SCHEMA_VERSION = "faz24.desktopCapture.operator-handoff.v1"
MANIFEST_NAME = "faz24-desktop-capture-operator-handoff.json"
README_NAME = "README.md"
SHA256SUMS_NAME = "SHA256SUMS"

REPO = "Halildeu/platform-k8s-gitops"
DEFAULT_BATCH_ID = "faz24-desktop-capture-20260628"
EVIDENCE_PATH = "/tmp/faz24-desktop-capture-evidence.json"
VERIFY_PATH = "/tmp/faz24-desktop-capture-evidence.verify.json"
GCAP_VERIFY_PATH = "/tmp/faz24-gcap-capture-gate.verify.json"
GCAP_INGEST_INPUT_PATH = "/tmp/faz24-gcap-capture-gate.ingest-input.json"

SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.:@/-]{1,180}$")
FORBIDDEN_PATTERNS = (
    re.compile(r"-----BEGIN .*PRIVATE KEY-----"),
    re.compile(r"-----BEGIN CERTIFICATE-----"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
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
        die(f"{label} must not contain certificate, private key, or token-like material")


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


def build_manifest(args: argparse.Namespace) -> dict[str, Any]:
    redacted_review = command_block(
        [
            f"test -s {EVIDENCE_PATH}",
            "jq -e '",
            '  .schemaVersion == "faz24.desktopCaptureEvidence.v1" and',
            '  .status == "pass" and',
            "  .tokenIncluded == false and",
            "  .boundaries.rawAudioIncluded == false and",
            "  .boundaries.rawTranscriptIncluded == false and",
            "  .boundaries.directClientToStt == false",
            f"' {EVIDENCE_PATH}",
        ]
    )
    verify = command_block(
        [
            "python3 scripts/faz24/verify_desktop_capture_evidence.py \\",
            f"  {EVIDENCE_PATH} \\",
            f"  --summary-json {VERIFY_PATH}",
            "jq -e '",
            '  .schemaVersion == "faz24.desktopCaptureEvidenceVerifier.v1" and',
            '  .status == "pass" and',
            "  .tokenIncluded == false and",
            "  .boundaries.desktopMicLoopbackProven == true and",
            "  .boundaries.directClientToStt == false",
            f"' {VERIFY_PATH}",
        ]
    )
    gcap_aggregate = command_block(
        [
            "python3 scripts/faz24/verify_gcap_capture_gate_evidence.py \\",
            "  --evidence-file /tmp/faz24-external-recorder-smoke-01.verify.json \\",
            "  --evidence-file /tmp/faz24-external-recorder-smoke-02.verify.json \\",
            "  --evidence-file /tmp/faz24-external-recorder-smoke-03.verify.json \\",
            f"  --evidence-file {VERIFY_PATH} \\",
            "  --evidence-file /tmp/faz24-desktop-capture-evidence-05.verify.json \\",
            "  --min-attempts 5 \\",
            "  --min-distinct-meetings 5 \\",
            "  --min-distinct-sessions 5 \\",
            "  --min-success-rate 0.95 \\",
            "  --max-retry-rate 0.10 \\",
            "  --max-failure-rate 0.05 \\",
            f"  --output-file {GCAP_VERIFY_PATH}",
            f"jq -e '.tokenIncluded == false' {GCAP_VERIFY_PATH}",
        ]
    )
    gcap_ingest_input = command_block(
        [
            "jq -s '{\"reports\": .}' \\",
            "  /tmp/faz24-external-recorder-smoke-01.verify.json \\",
            "  /tmp/faz24-external-recorder-smoke-02.verify.json \\",
            "  /tmp/faz24-external-recorder-smoke-03.verify.json \\",
            f"  {VERIFY_PATH} \\",
            f"  /tmp/faz24-desktop-capture-evidence-05.verify.json > {GCAP_INGEST_INPUT_PATH}",
            "jq -e '",
            "  (.reports | length) >= 5 and",
            '  all(.reports[]; .status == "pass" and .tokenIncluded == false)',
            f"' {GCAP_INGEST_INPUT_PATH}",
        ]
    )
    gcap_ingest = command_block(
        [
            f'GCAP_EVIDENCE_B64="$(base64 < {GCAP_INGEST_INPUT_PATH} | tr -d \'\\n\')"',
            "gh workflow run faz24-product-gate-evidence-ingest.yml \\",
            f"  --repo {REPO} \\",
            f"  --ref {args.gitops_ref} \\",
            "  -f gate=gcap \\",
            '  -f evidence_json_base64="${GCAP_EVIDENCE_B64}"',
        ]
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": utc_now(),
        "repo": REPO,
        "operatorBatchId": args.operator_batch_id,
        "issues": {
            "gitopsRollup": "platform-k8s-gitops#1615",
            "gcapAggregate": "platform-k8s-gitops#2027",
        },
        "acceptanceBoundary": {
            "issueStatus": "needs-verify",
            "operatorExecutionRequired": True,
            "realDesktopRunRequired": True,
            "microphoneRealDeviceRequired": True,
            "loopbackRealDeviceRequired": True,
            "activeIndicatorRequired": True,
            "consentCaptureRequired": True,
            "verifierPassRequired": True,
            "reviewerAcceptanceRequired": True,
            "gcapRequiresMultipleVerifierSummaries": True,
            "doesNotAcceptDirectStt": True,
            "doesNotAcceptComputePlaneAudit": True,
            "doesNotAcceptI7ProdGate": True,
            "doesNotAcceptProductionReadiness": True,
        },
        "mutationBoundary": {
            "packageBuildHostMutation": False,
            "packageBuildDesktopMutation": False,
            "packageBuildClusterMutation": False,
            "packageBuildVaultMutation": False,
            "packageBuildProductionMutation": False,
            "containsCredentials": False,
            "containsRawAudio": False,
            "containsRawTranscript": False,
            "containsDeviceLabels": False,
            "containsRawCommandOutput": False,
        },
        "target": {
            "gitopsRef": args.gitops_ref,
            "desktopEvidencePath": EVIDENCE_PATH,
            "desktopVerifierPath": VERIFY_PATH,
            "gcapVerifierPath": GCAP_VERIFY_PATH,
            "gcapIngestInputPath": GCAP_INGEST_INPUT_PATH,
        },
        "orderedGates": [
            {
                "id": "desktop-run-prep",
                "owner": "operator",
                "statusBeforeExecution": "pending",
                "mustNotBeRecordedInPackage": [
                    "raw microphone audio",
                    "raw loopback audio",
                    "device labels",
                    "JWT or Authorization header",
                    "desktop logs",
                    "shell transcript",
                    "network trace or pcap",
                ],
                "notes": [
                    "Run the real platform-desktop app with microphone and loopback sources.",
                    "Confirm visible active recording indicator and recording consent capture.",
                    "Export only the redacted metadata envelope to the expected evidence path.",
                ],
            },
            {
                "id": "redacted-evidence-review",
                "owner": "operator",
                "statusBeforeExecution": "blocked-until-real-desktop-run",
                "commands": {"review": redacted_review},
            },
            {
                "id": "desktop-verifier",
                "owner": "operator/reviewer",
                "statusBeforeExecution": "blocked-until-redacted-evidence-present",
                "commands": {"verify": verify},
            },
            {
                "id": "gcap-aggregate",
                "owner": "reviewer/operator",
                "statusBeforeExecution": "blocked-until-enough-verifier-summaries",
                "commands": {
                    "verify": gcap_aggregate,
                    "prepareIngestInput": gcap_ingest_input,
                    "ingest": gcap_ingest,
                },
            },
        ],
        "issueCommentTemplates": {
            "desktopVerifierPass": (
                "Desktop capture verifier PASS evidence attached. Boundary: proves one "
                "real platform-desktop mic+loopback attempt only; direct-STT, "
                "compute-plane audit, G-CAP aggregate, I7, and production readiness "
                "remain separate gates."
            ),
            "gcapAggregate": (
                "G-CAP aggregate verifier evidence attached. Boundary: only accepted if "
                "status=pass and reviewer accepts the threshold set; direct-STT and "
                "production readiness remain separate."
            ),
        },
    }


def render_readme(manifest: dict[str, Any]) -> str:
    target = manifest["target"]
    gates = {item["id"]: item for item in manifest["orderedGates"]}

    return f"""# Faz 24 desktop capture operator handoff

Scope: platform-k8s-gitops#1615 desktop mic + loopback capture evidence.

This package is a coordination artifact only. It does not run the desktop app,
read tokens, connect to testai, mutate Kubernetes, touch Vault, send audio, or
collect live evidence.

## Boundary

- Current status remains `Needs Verify`.
- A real `platform-desktop` run is required.
- Both microphone and loopback sources must be real-device, not synthetic.
- A visible active recording indicator and consent capture are required.
- The redacted evidence envelope and verifier summary must have
  `tokenIncluded=false`.
- A single desktop verifier PASS is one capture attempt only; G-CAP aggregate
  still requires enough accepted verifier summaries and reviewer acceptance.
- Direct-STT, compute-plane audit, I7, and production readiness remain separate
  gates.

## Target

- desktop evidence: `{target["desktopEvidencePath"]}`
- desktop verifier summary: `{target["desktopVerifierPath"]}`
- G-CAP aggregate summary: `{target["gcapVerifierPath"]}`
- G-CAP ingest input wrapper: `{target["gcapIngestInputPath"]}`

## Gate 0 — real desktop run

Run the actual `platform-desktop` app with microphone and system-loopback
capture enabled. Confirm the active recording indicator is visible and consent
is captured. Export only the redacted metadata envelope:

```text
{target["desktopEvidencePath"]}
```

Do not attach raw audio, base64 audio, transcript text, device labels, JWTs,
Authorization headers, desktop logs, shell transcripts, or packet captures.

## Gate 1 — redacted evidence review

```bash
{gates["redacted-evidence-review"]["commands"]["review"]}
```

## Gate 2 — verifier

```bash
{gates["desktop-verifier"]["commands"]["verify"]}
```

Attach `{target["desktopEvidencePath"]}` and `{target["desktopVerifierPath"]}`
only after confirming both are metadata-only and the verifier summary has
`status=pass`.

## Gate 3 — G-CAP aggregate

Run this only after enough accepted external-recorder and/or desktop verifier
summaries exist:

```bash
{gates["gcap-aggregate"]["commands"]["verify"]}
```

Prepare the ingest wrapper from verifier summaries, then run the no-mutation
ingest workflow:

```bash
{gates["gcap-aggregate"]["commands"]["prepareIngestInput"]}

{gates["gcap-aggregate"]["commands"]["ingest"]}
```

## Follow-up comments

Desktop verifier PASS comment template:

```text
{manifest["issueCommentTemplates"]["desktopVerifierPass"]}
```

G-CAP aggregate comment template:

```text
{manifest["issueCommentTemplates"]["gcapAggregate"]}
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
    print("schema=faz24-desktop-capture-operator-handoff-v1")
    print("acceptance=needs-operator-runtime-evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
