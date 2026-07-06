#!/usr/bin/env python3
"""Build a metadata-only operator handoff package for Faz 24 I7 app-mTLS.

The package coordinates the remaining platform-ai#198 evidence sequence. It
does not connect to Denetim PC, Vault, Kubernetes, Caddy, firewall/EDR policy,
or production; it does not collect runtime evidence or make an acceptance
claim.
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


SCHEMA_VERSION = "faz24.i7AppMtls.operator-handoff.v1"
MANIFEST_NAME = "faz24-i7-app-mtls-operator-handoff.json"
README_NAME = "README.md"
SHA256SUMS_NAME = "SHA256SUMS"

REPO = "Halildeu/platform-k8s-gitops"
PLATFORM_AI_REPO = "Halildeu/platform-ai"
DEFAULT_BATCH_ID = "faz24-i7-app-mtls-20260628"
DEFAULT_SOURCE_WG_IP = "10.99.0.1"
DEFAULT_DENETIM_WG_IP = "10.99.0.2"
DEFAULT_LIVE_STT_PORT = 8243
DEFAULT_MEETING_AI_PORT = 8343
DEFAULT_LIVE_STT_PREFLIGHT_PATH = "/tmp/faz24-i7-live-stt-preflight.json"
DEFAULT_PROD_GATE_PATH = "/tmp/faz24-i7-prod-gate.json"
INGEST_WORKFLOW = "faz24-i7-app-mtls-evidence-ingest.yml"

SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.:@/-]{1,180}$")
SAFE_PATH_RE = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,220}$")
IPV4_RE = re.compile(r"^(\d{1,3}\.){3}\d{1,3}$")
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


def validate_evidence_path(label: str, value: str) -> None:
    validate_single_line(label, value)
    parts = re.split(r"[\\/]+", value)
    if re.match(r"^[A-Za-z]:", value) or ".." in parts:
        die(f"{label} must not escape the handoff boundary")
    if value.startswith("/") and not value.startswith("/tmp/"):
        die(f"{label} absolute paths are only allowed under /tmp")
    if not SAFE_PATH_RE.match(value):
        die(f"{label} contains unsupported characters")


def validate_ipv4(label: str, value: str) -> None:
    validate_single_line(label, value)
    if not IPV4_RE.match(value):
        die(f"{label} must be an IPv4 address")
    if any(int(part) > 255 for part in value.split(".")):
        die(f"{label} must be an IPv4 address")


def validate_port(label: str, value: int) -> None:
    if not (1 <= value <= 65535):
        die(f"{label} must be 1..65535")


def validate_args(args: argparse.Namespace) -> None:
    validate_safe_token("operator-batch-id", args.operator_batch_id)
    validate_safe_token("gitops-ref", args.gitops_ref)
    validate_ipv4("source-wg-ip", args.source_wg_ip)
    validate_ipv4("denetim-wg-ip", args.denetim_wg_ip)
    validate_port("live-stt-port", args.live_stt_port)
    validate_port("meeting-ai-port", args.meeting_ai_port)
    validate_evidence_path("live-stt-preflight-path", args.live_stt_preflight_path)
    validate_evidence_path("prod-gate-evidence-path", args.prod_gate_evidence_path)


def command_block(lines: list[str]) -> str:
    return "\n".join(lines)


def verify_command(evidence_path: str, summary_path: str, profile: str) -> str:
    return command_block(
        [
            "python3 scripts/faz24/verify-i7-app-mtls-evidence.py \\",
            f"  {evidence_path} \\",
            f"  --summary-json {summary_path}",
            "jq -e '",
            '  .schemaVersion == "faz24.i7.app-mtls.verifier.v1" and',
            '  .status == "pass" and',
            f'  .evidenceProfile == "{profile}" and',
            "  .tokenIncluded == false",
            f"' {summary_path}",
        ]
    )


def ingest_command(evidence_path: str, gitops_ref: str) -> str:
    return command_block(
        [
            f'I7_EVIDENCE_B64="$(base64 < {evidence_path} | tr -d \'\\n\')"',
            f"gh workflow run {INGEST_WORKFLOW} \\",
            f"  --repo {REPO} \\",
            f"  --ref {gitops_ref} \\",
            '  -f evidence_json_base64="${I7_EVIDENCE_B64}"',
        ]
    )


def build_manifest(args: argparse.Namespace) -> dict[str, Any]:
    preflight_summary = "/tmp/faz24-i7-live-stt-preflight.verify.json"
    prod_gate_summary = "/tmp/faz24-i7-prod-gate.verify.json"

    preflight_verify = verify_command(
        args.live_stt_preflight_path,
        preflight_summary,
        "live-stt-preflight",
    )
    prod_gate_verify = verify_command(
        args.prod_gate_evidence_path,
        prod_gate_summary,
        "prod-gate",
    )

    return {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": utc_now(),
        "repo": REPO,
        "platformAiRepo": PLATFORM_AI_REPO,
        "operatorBatchId": args.operator_batch_id,
        "issues": {
            "gitopsRollup": "platform-k8s-gitops#1615",
            "i7ProdGate": "platform-ai#198",
            "computePlaneAudit": "platform-ai#188",
            "directSttE2e": "platform-ai#182",
        },
        "acceptanceBoundary": {
            "issueStatus": "needs-verify",
            "operatorExecutionRequired": True,
            "endpointPolicyEvidenceRequired": True,
            "liveSttPreflightVerifierPassRequired": True,
            "prodGateVerifierPassRequired": True,
            "reviewerAcceptanceRequired": True,
            "liveSttPreflightDoesNotAcceptFullI7": True,
            "prodGateRequiresMeetingAi8343": True,
            "doesNotEnableDirectStt": True,
            "doesNotAcceptComputePlaneAudit": True,
            "doesNotAcceptDirectAudioE2e": True,
            "doesNotAcceptDesktopMicLoopback": True,
            "doesNotAcceptProductionReadiness": True,
            "doesNotAcceptLegalGo": True,
        },
        "mutationBoundary": {
            "packageBuildEvidenceMutation": False,
            "packageBuildClusterMutation": False,
            "packageBuildVaultMutation": False,
            "packageBuildDenetimMutation": False,
            "packageBuildFirewallMutation": False,
            "packageBuildEndpointSecurityMutation": False,
            "packageBuildProductionMutation": False,
            "containsCredentials": False,
            "containsPrivateKeys": False,
            "containsCertificates": False,
            "containsRawAudio": False,
            "containsRawTranscript": False,
            "containsRawHttpBodies": False,
            "containsRawCommandOutput": False,
            "containsPacketCapture": False,
        },
        "target": {
            "gitopsRef": args.gitops_ref,
            "ingestWorkflow": f".github/workflows/{INGEST_WORKFLOW}",
            "sourceWgIp": args.source_wg_ip,
            "denetimWgIp": args.denetim_wg_ip,
            "liveStt": {
                "service": "live-stt",
                "port": args.live_stt_port,
                "profile": "live-stt-preflight",
                "evidencePath": args.live_stt_preflight_path,
                "summaryPath": preflight_summary,
            },
            "meetingAi": {
                "service": "meeting-ai",
                "port": args.meeting_ai_port,
                "profile": "prod-gate",
            },
            "prodGate": {
                "evidencePath": args.prod_gate_evidence_path,
                "summaryPath": prod_gate_summary,
            },
        },
        "requiredChecks": {
            "liveSttPreflight": [
                "wg-route-to-denetim",
                "tcp-8243-reachable",
                "tls-server-identity-verified",
                "mtls-valid-client-accepted",
                "mtls-no-client-rejected",
                "mtls-wrong-client-rejected",
                "redaction-no-audio-transcript",
            ],
            "prodGate": [
                "wg-route-to-denetim",
                "tcp-8243-reachable",
                "tcp-8343-reachable",
                "tls-server-identity-verified",
                "mtls-valid-client-accepted",
                "mtls-no-client-rejected",
                "mtls-wrong-client-rejected",
                "meeting-ai-mtls-valid-client-accepted",
                "request-audit-emitted",
                "plaintext-bypass-closed",
                "cert-rotation-drill",
                "failure-drill-fail-fast",
                "redaction-no-audio-transcript",
            ],
        },
        "orderedGates": [
            {
                "id": "endpoint-policy-evidence",
                "owner": "security/operator",
                "statusBeforeExecution": "pending",
                "requiredTuple": {
                    "source": args.source_wg_ip,
                    "destination": args.denetim_wg_ip,
                    "protocol": "TCP",
                    "liveSttPort": args.live_stt_port,
                    "program": "C:/caddy/caddy.exe",
                    "ttlOrRollbackRequired": True,
                },
                "mustNotBeRecordedInPackage": [
                    "packet payload",
                    "raw firewall dump",
                    "raw EDR log",
                    "credential",
                    "private key",
                    "raw certificate chain",
                    "raw audio",
                    "transcript text",
                ],
                "notes": [
                    "ESET/ERA/central endpoint policy evidence may be referenced by protected path or ticket id only.",
                    "Do not disable endpoint security to force the gate open.",
                ],
            },
            {
                "id": "live-stt-preflight",
                "owner": "operator/reviewer",
                "statusBeforeExecution": "blocked-until-endpoint-policy-evidence",
                "commands": {
                    "verify": preflight_verify,
                    "ingest": ingest_command(args.live_stt_preflight_path, args.gitops_ref),
                },
                "notes": [
                    "This only proves the bounded 8243 live-stt profile.",
                    "It does not close #198 full I7 and does not enable direct-STT.",
                ],
            },
            {
                "id": "prod-gate-evidence",
                "owner": "operator/reviewer",
                "statusBeforeExecution": "blocked-until-8243-preflight-and-8343-ready",
                "commands": {
                    "verify": prod_gate_verify,
                    "ingest": ingest_command(args.prod_gate_evidence_path, args.gitops_ref),
                },
                "notes": [
                    "Requires live-stt and meeting-ai services, request audit, plaintext bypass closure, rotation drill, failure drill, and redaction evidence.",
                    "A PASS ingest still requires reviewer acceptance on platform-ai#198.",
                ],
            },
            {
                "id": "reviewer-acceptance",
                "owner": "reviewer",
                "statusBeforeExecution": "blocked-until-prod-gate-ingest-artifact",
                "notes": [
                    "Attach workflow URL, artifact name, verifier output, and boundary statement to platform-ai#198.",
                    "Do not move #1615 beyond Needs Verify solely because this package exists.",
                    "Do not claim production readiness or legal go from this package.",
                ],
            },
        ],
        "issueCommentTemplates": {
            "package": (
                "I7 app-mTLS operator handoff package attached. Boundary: metadata-only "
                "coordination artifact; no Denetim/Vault/Kubernetes/firewall mutation, no "
                "runtime evidence collection, no direct-STT enablement, and no #198/#1615 "
                "acceptance claimed."
            ),
            "liveSttPreflight": (
                "I7 live-stt preflight evidence ingest attached. Boundary: 8243 preflight "
                "only; meeting-ai 8343, full I7 prod-gate, #188, #182, desktop capture, "
                "production readiness, and legal go remain separate."
            ),
            "prodGate": (
                "I7 prod-gate evidence ingest attached. Boundary: metadata verifier PASS "
                "still requires reviewer acceptance; direct-STT, desktop capture, product "
                "pilot, production readiness, and legal go are not claimed."
            ),
        },
    }


def render_readme(manifest: dict[str, Any]) -> str:
    target = manifest["target"]
    gates = {item["id"]: item for item in manifest["orderedGates"]}
    preflight = gates["live-stt-preflight"]["commands"]
    prod_gate = gates["prod-gate-evidence"]["commands"]
    endpoint_tuple = gates["endpoint-policy-evidence"]["requiredTuple"]

    return f"""# Faz 24 I7 app-mTLS operator handoff

Scope: platform-ai#198 and platform-k8s-gitops#1615.

This package is a coordination artifact only. It does not connect to Denetim
PC, Vault, Kubernetes, Caddy, endpoint security, or production; it does not
collect runtime evidence, change firewall policy, enable direct-STT, send
audio, or advance any issue status.

## Boundary

- Current status remains `Needs Verify`.
- Endpoint/security policy evidence is operator-owned and must be bounded to
  the Denetim WG tuple.
- `live-stt-preflight` proves only the TCP/{target["liveStt"]["port"]} path.
- Full I7 requires `prod-gate` evidence for live-stt and meeting-ai, including
  request audit, plaintext-bypass closure, rotation drill, failure drill, and
  redaction.
- A passing ingest artifact is not reviewer acceptance.
- #188 compute-plane audit, #182 direct-STT e2e, desktop mic/loopback, product
  pilot, production readiness, and legal go remain separate.

## Target

- ingest workflow: `{target["ingestWorkflow"]}`
- source WG IP: `{target["sourceWgIp"]}`
- Denetim WG IP: `{target["denetimWgIp"]}`
- live-stt preflight evidence: `{target["liveStt"]["evidencePath"]}`
- live-stt port: `{target["liveStt"]["port"]}`
- prod-gate evidence: `{target["prodGate"]["evidencePath"]}`
- meeting-ai port: `{target["meetingAi"]["port"]}`

## Gate 0 - endpoint policy evidence

Capture or reference protected operator evidence for this exact tuple:

```text
source={endpoint_tuple["source"]}
destination={endpoint_tuple["destination"]}
protocol={endpoint_tuple["protocol"]}
port={endpoint_tuple["liveSttPort"]}
program={endpoint_tuple["program"]}
ttl_or_rollback_required=true
```

Do not attach packet payloads, raw firewall dumps, raw EDR logs, credentials,
private keys, raw certificate chains, raw audio, or transcript text. Do not
disable endpoint security to force the gate open.

## Gate 1 - live-stt preflight

Validate the metadata-only preflight JSON:

```bash
{preflight["verify"]}
```

Ingest it:

```bash
{preflight["ingest"]}
```

## Gate 2 - prod-gate evidence

Validate the full I7 metadata-only JSON:

```bash
{prod_gate["verify"]}
```

Ingest it:

```bash
{prod_gate["ingest"]}
```

## Gate 3 - reviewer acceptance

Attach workflow URL, artifact name, verifier output, and boundary statement to
platform-ai#198. Keep #1615 in `Needs Verify` unless the relevant rollup gate
has accepted runtime evidence.

## Follow-up comments

Package comment template:

```text
{manifest["issueCommentTemplates"]["package"]}
```

Live-stt preflight comment template:

```text
{manifest["issueCommentTemplates"]["liveSttPreflight"]}
```

Prod-gate comment template:

```text
{manifest["issueCommentTemplates"]["prodGate"]}
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
    parser.add_argument("--source-wg-ip", default=DEFAULT_SOURCE_WG_IP)
    parser.add_argument("--denetim-wg-ip", default=DEFAULT_DENETIM_WG_IP)
    parser.add_argument("--live-stt-port", type=int, default=DEFAULT_LIVE_STT_PORT)
    parser.add_argument("--meeting-ai-port", type=int, default=DEFAULT_MEETING_AI_PORT)
    parser.add_argument("--live-stt-preflight-path", default=DEFAULT_LIVE_STT_PREFLIGHT_PATH)
    parser.add_argument("--prod-gate-evidence-path", default=DEFAULT_PROD_GATE_PATH)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    build_package(args)
    print(f"status=pass packageDir={Path(args.output_dir)}")
    print("schema=faz24-i7-app-mtls-operator-handoff-v1")
    print("acceptance=needs-operator-runtime-evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
