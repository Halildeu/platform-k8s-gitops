#!/usr/bin/env python3
"""Build a metadata-only operator handoff package for the Faz 24 Meeting-AI
gateway certificate rotation fire drill (platform-k8s-gitops#2321).

The package coordinates the remaining owner-gated live-drill sequence for the
private Meeting-AI result gateway on staging-sw: scoped Vault token seed,
gateway activation, rotation + induced reload-failure drill, evidence verify +
ingest, and reviewer acceptance. It does not connect to staging-sw, Vault,
Kubernetes, Caddy, systemd, or production; it does not seed tokens, trigger
rotation, run the drill, collect runtime evidence, or make an acceptance claim.
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


SCHEMA_VERSION = "faz24.certRotationDrill.operator-handoff.v1"
MANIFEST_NAME = "faz24-cert-rotation-drill-operator-handoff.json"
README_NAME = "README.md"
SHA256SUMS_NAME = "SHA256SUMS"

REPO = "Halildeu/platform-k8s-gitops"
DEFAULT_BATCH_ID = "faz24-cert-rotation-drill-20260713"
DEFAULT_GATEWAY_HOST = "staging-sw"
DEFAULT_GATEWAY_SERVICE = "meeting-ai-private-gateway.service"
DEFAULT_ROTATION_TIMER = "meeting-ai-server-cert-rotation.timer"
DEFAULT_EVIDENCE_PATH = "/tmp/faz24-meeting-ai-cert-rotation-drill.json"
INGEST_WORKFLOW = "faz24-cert-rotation-drill-evidence-ingest.yml"
VERIFIER = "scripts/faz24/verify_meeting_ai_cert_rotation_drill_evidence.py"
ROTATION_SCRIPT = (
    "/usr/local/libexec/platform/meeting-ai-gateway-rotate-server-cert"
)
REQUIRED_FAILURE_ALERT = "MeetingAIGatewayCertificateRotationFailed"

SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.:@/-]{1,180}$")
SAFE_HOST_RE = re.compile(r"^[A-Za-z0-9_.-]{1,180}$")
SAFE_UNIT_RE = re.compile(r"^[A-Za-z0-9_.@-]{1,180}$")
SAFE_PATH_RE = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,220}$")
FORBIDDEN_PATTERNS = (
    re.compile(r"-----BEGIN .*PRIVATE KEY-----"),
    re.compile(r"-----BEGIN CERTIFICATE-----"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bhvs\.[A-Za-z0-9._-]{12,}\b"),
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


def validate_safe_host(label: str, value: str) -> None:
    validate_single_line(label, value)
    if not SAFE_HOST_RE.match(value):
        die(f"{label} contains unsupported characters")


def validate_safe_unit(label: str, value: str) -> None:
    validate_single_line(label, value)
    if not SAFE_UNIT_RE.match(value):
        die(f"{label} contains unsupported characters")


def validate_evidence_path(label: str, value: str) -> None:
    validate_single_line(label, value)
    parts = re.split(r"[\\/]+", value)
    if re.match(r"^[A-Za-z]:", value) or ".." in parts:
        die(f"{label} must not escape the handoff boundary")
    if value.startswith("/") and not value.startswith("/tmp/"):
        die(f"{label} absolute paths are only allowed under /tmp")
    if not SAFE_PATH_RE.match(value):
        die(f"{label} contains unsupported characters")


def validate_args(args: argparse.Namespace) -> None:
    validate_safe_token("operator-batch-id", args.operator_batch_id)
    validate_safe_token("gitops-ref", args.gitops_ref)
    validate_safe_host("gateway-host", args.gateway_host)
    validate_safe_unit("gateway-service", args.gateway_service)
    validate_safe_unit("rotation-timer", args.rotation_timer)
    validate_evidence_path("evidence-path", args.evidence_path)


def command_block(lines: list[str]) -> str:
    return "\n".join(lines)


def verify_command(evidence_path: str, summary_path: str) -> str:
    return command_block(
        [
            f"python3 {VERIFIER} \\",
            f"  {evidence_path} \\",
            f"  --summary-json {summary_path}",
            "jq -e '",
            '  .schemaVersion == "faz24.meetingAiCertRotationDrillVerifier.v1" and',
            '  .status == "pass" and',
            "  .passed == .total",
            f"' {summary_path}",
        ]
    )


def ingest_command(evidence_path: str, gitops_ref: str) -> str:
    return command_block(
        [
            f'DRILL_EVIDENCE_B64="$(base64 < {evidence_path} | tr -d \'\\n\')"',
            f"gh workflow run {INGEST_WORKFLOW} \\",
            f"  --repo {REPO} \\",
            f"  --ref {gitops_ref} \\",
            '  -f evidence_json_base64="${DRILL_EVIDENCE_B64}"',
        ]
    )


def build_manifest(args: argparse.Namespace) -> dict[str, Any]:
    summary_path = "/tmp/faz24-meeting-ai-cert-rotation-drill.verify.json"
    verify = verify_command(args.evidence_path, summary_path)
    ingest = ingest_command(args.evidence_path, args.gitops_ref)

    return {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": utc_now(),
        "repo": REPO,
        "operatorBatchId": args.operator_batch_id,
        "issues": {
            "gitopsRollup": "platform-k8s-gitops#1615",
            "privateDeliveryRuntime": "platform-k8s-gitops#2321",
        },
        "acceptanceBoundary": {
            "issueStatus": "in-progress",
            "operatorExecutionRequired": True,
            "scopedVaultTokenSeedRequired": True,
            "gatewayActivationRequired": True,
            "rotationDrillExecutionRequired": True,
            "inducedReloadFailureRollbackRequired": True,
            "alertFireAndClearRequired": True,
            "drillVerifierPassRequired": True,
            "reviewerAcceptanceRequired": True,
            "doesNotSeedVault": True,
            "doesNotTriggerRotation": True,
            "doesNotRunDrill": True,
            "doesNotActivatePrivateListener": True,
            "doesNotAcceptMtlsNegativeMatrix": True,
            "doesNotAcceptJwtClaimMatrix": True,
            "doesNotAcceptOutboxDrain": True,
            "doesNotAcceptElectronProductPath": True,
            "doesNotAcceptProductionReadiness": True,
            "doesNotAcceptLegalGo": True,
        },
        "mutationBoundary": {
            "packageBuildEvidenceMutation": False,
            "packageBuildClusterMutation": False,
            "packageBuildVaultMutation": False,
            "packageBuildHostMutation": False,
            "packageBuildSystemdMutation": False,
            "packageBuildCaddyMutation": False,
            "packageBuildFirewallMutation": False,
            "packageBuildProductionMutation": False,
            "containsCredentials": False,
            "containsVaultTokens": False,
            "containsPrivateKeys": False,
            "containsCertificates": False,
            "containsIssuingCa": False,
            "containsRawCommandOutput": False,
        },
        "target": {
            "gitopsRef": args.gitops_ref,
            "gatewayHost": args.gateway_host,
            "gatewayService": args.gateway_service,
            "rotationTimer": args.rotation_timer,
            "rotationScript": ROTATION_SCRIPT,
            "rotationScheduleHours": 8,
            "verifier": VERIFIER,
            "ingestWorkflow": f".github/workflows/{INGEST_WORKFLOW}",
            "evidenceSchema": "faz24.meetingAiCertRotationDrillEvidence.v1",
            "evidencePath": args.evidence_path,
            "summaryPath": summary_path,
            "requiredFailureAlert": REQUIRED_FAILURE_ALERT,
        },
        "requiredEvidenceLayers": {
            "up": [
                "textfilePresent",
                "meeting_ai_gateway_rotation_last_attempt_timestamp_seconds",
                "meeting_ai_gateway_rotation_last_success_timestamp_seconds",
                "meeting_ai_gateway_rotation_last_run_success",
                "meeting_ai_gateway_certificate_not_after_timestamp_seconds",
                "lastRunSuccessValue==1",
            ],
            "functional": [
                "fresh-24h-staging-gateway-leaf",
                "leaf-fingerprint-rotated",
                "atomic-tls-current-pointer-swap",
                "gateway-reloaded",
                "uninterrupted-client-auth-healthz-200",
            ],
            "secured": [
                "induced-reload-failure",
                "pointer-rolled-back-no-outage",
                "rotation_last_run_success==0-during-failure",
                "new-version-removed-on-failure",
                f"{REQUIRED_FAILURE_ALERT}-fired",
                "alert-cleared-after-recovery",
            ],
        },
        "orderedGates": [
            {
                "id": "scoped-vault-token-seed",
                "owner": "owner/operator",
                "statusBeforeExecution": "pending",
                "notes": [
                    "Create a scoped, renewable Vault token bound only to the meeting-ai-gateway-server policy.",
                    "Install it root-owned 0600 at /etc/platform/meeting-ai-gateway/vault-token per RB-faz24-meeting-ai-private-gateway.md.",
                    "Do not attach the token value, root token, private key, certificate, or issuing CA to any evidence or issue comment.",
                ],
            },
            {
                "id": "gateway-activation",
                "owner": "operator",
                "statusBeforeExecution": "blocked-until-scoped-vault-token-seed",
                "commands": {
                    "install": "sudo deploy/staging-sw/meeting-ai-private-gateway/install.sh",
                    "enable": command_block(
                        [
                            f"sudo systemctl enable --now {args.gateway_service}",
                            f"sudo systemctl enable --now {args.rotation_timer}",
                        ]
                    ),
                },
                "notes": [
                    "Activation is owner-gated and test-only; production hosts use split-horizon DNS, not the hosts shim.",
                    "The private listener binds 10.99.0.1:9447 only; there must be no 0.0.0.0:9447 listener.",
                ],
            },
            {
                "id": "rotation-drill-execution",
                "owner": "operator",
                "statusBeforeExecution": "blocked-until-gateway-activation",
                "commands": {
                    "rotate": f"sudo {ROTATION_SCRIPT}",
                    "inducedFailureNote": (
                        "Induce a reload failure (e.g. a temporary invalid Caddy adapter config), "
                        "confirm the pointer rolls back to the previous leaf with no outage, then recover."
                    ),
                },
                "notes": [
                    "Capture redacted, metadata-only evidence into the evidence path; never write cert/key/token/issuing-CA values.",
                    f"The failure drill must fire {REQUIRED_FAILURE_ALERT} and it must clear after recovery.",
                    "A single successful rotation is not acceptance; the fail-closed rollback and alert cycle are required.",
                ],
            },
            {
                "id": "evidence-verify-ingest",
                "owner": "operator/reviewer",
                "statusBeforeExecution": "blocked-until-rotation-drill-execution",
                "commands": {
                    "verify": verify,
                    "ingest": ingest,
                },
                "notes": [
                    "The verifier is metadata-only and fail-closed; it does not mutate Vault/Kubernetes/Caddy/systemd/GitHub.",
                    "A passing verifier/ingest artifact is not reviewer acceptance.",
                ],
            },
            {
                "id": "reviewer-acceptance",
                "owner": "reviewer",
                "statusBeforeExecution": "blocked-until-evidence-verify-ingest-artifact",
                "notes": [
                    "Attach workflow URL, artifact name, verifier output, and boundary statement to platform-k8s-gitops#2321.",
                    "The cert-rotation drill is one #2321 residual; private-listener activation, mTLS negative matrix, JWT claim matrix, outbox drain, and Electron product-path remain separate.",
                    "Do not move #2321 or #1615 to accepted solely because this package or a single passing ingest exists.",
                    "Do not claim production readiness or legal go from this package.",
                ],
            },
        ],
        "issueCommentTemplates": {
            "package": (
                "Cert rotation drill operator handoff package attached. Boundary: metadata-only "
                "coordination artifact; no staging-sw/Vault/Kubernetes/Caddy/systemd mutation, no "
                "token seed, no rotation trigger, no runtime evidence collection, and no #2321/#1615 "
                "acceptance claimed."
            ),
            "drill": (
                "Cert rotation drill evidence ingest attached. Boundary: metadata verifier PASS still "
                "requires reviewer acceptance on #2321; private-listener activation, mTLS negative "
                "matrix, JWT claim matrix, outbox drain, Electron product-path, production readiness, "
                "and legal go are not claimed."
            ),
        },
    }


def render_readme(manifest: dict[str, Any]) -> str:
    target = manifest["target"]
    gates = {item["id"]: item for item in manifest["orderedGates"]}
    activation = gates["gateway-activation"]["commands"]
    drill = gates["rotation-drill-execution"]["commands"]
    verify_ingest = gates["evidence-verify-ingest"]["commands"]

    return f"""# Faz 24 Meeting-AI cert rotation drill operator handoff

Scope: platform-k8s-gitops#2321 and platform-k8s-gitops#1615.

This package is a coordination artifact only. It does not connect to staging-sw,
Vault, Kubernetes, Caddy, systemd, or production; it does not seed tokens,
trigger rotation, run the drill, collect runtime evidence, or advance any issue
status.

## Boundary

- Current #2321 status remains In Progress.
- The scoped Vault token seed is owner-owned; never attach its value, a root
  token, a private key, a certificate, or an issuing CA to evidence or comments.
- A single successful rotation is not acceptance. The fail-closed rollback and
  the `{target["requiredFailureAlert"]}` fire/clear cycle are required.
- A passing verifier/ingest artifact is not reviewer acceptance.
- Private-listener activation, mTLS negative matrix, JWT claim matrix, outbox
  drain, Electron product-path, production readiness, and legal go remain
  separate.

## Target

- gateway host: `{target["gatewayHost"]}`
- gateway service: `{target["gatewayService"]}`
- rotation timer: `{target["rotationTimer"]}` (every {target["rotationScheduleHours"]}h)
- rotation script: `{target["rotationScript"]}`
- verifier: `{target["verifier"]}`
- ingest workflow: `{target["ingestWorkflow"]}`
- evidence schema: `{target["evidenceSchema"]}`
- evidence path: `{target["evidencePath"]}`

## Gate 0 - scoped Vault token seed (owner)

Create a scoped, renewable Vault token bound only to the
`meeting-ai-gateway-server` policy and install it root-owned `0600` at
`/etc/platform/meeting-ai-gateway/vault-token` per
`docs/runbooks/RB-faz24-meeting-ai-private-gateway.md`. Do not attach the token
value, root token, private key, certificate, or issuing CA anywhere.

## Gate 1 - gateway activation (operator)

```bash
{activation["install"]}
{activation["enable"]}
```

## Gate 2 - rotation + induced reload-failure drill (operator)

Trigger a rotation:

```bash
{drill["rotate"]}
```

{drill["inducedFailureNote"]}

Capture redacted, metadata-only evidence into `{target["evidencePath"]}`. Never
write cert/key/token/issuing-CA values or raw command output.

## Gate 3 - verify + ingest (operator)

Validate the metadata-only drill evidence:

```bash
{verify_ingest["verify"]}
```

Ingest it:

```bash
{verify_ingest["ingest"]}
```

## Gate 4 - reviewer acceptance (reviewer)

Attach workflow URL, artifact name, verifier output, and boundary statement to
platform-k8s-gitops#2321. Keep #2321 and #1615 unaccepted unless the relevant
rollup gate has accepted runtime evidence.

## Follow-up comments

Package comment template:

```text
{manifest["issueCommentTemplates"]["package"]}
```

Drill evidence comment template:

```text
{manifest["issueCommentTemplates"]["drill"]}
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
    parser.add_argument("--gateway-host", default=DEFAULT_GATEWAY_HOST)
    parser.add_argument("--gateway-service", default=DEFAULT_GATEWAY_SERVICE)
    parser.add_argument("--rotation-timer", default=DEFAULT_ROTATION_TIMER)
    parser.add_argument("--evidence-path", default=DEFAULT_EVIDENCE_PATH)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    build_package(args)
    print(f"status=pass packageDir={Path(args.output_dir)}")
    print("schema=faz24-cert-rotation-drill-operator-handoff-v1")
    print("acceptance=needs-operator-runtime-evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
