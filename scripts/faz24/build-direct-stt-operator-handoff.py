#!/usr/bin/env python3
"""Build a metadata-only operator handoff package for Faz 24 direct-STT.

The package coordinates the remaining platform-ai#182 / platform-k8s-gitops#1615
runtime evidence sequence. It does not read or write Vault values, connect to a
cluster, enable direct-STT, send audio, or collect live evidence.
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


SCHEMA_VERSION = "faz24.directStt.operator-handoff.v1"
MANIFEST_NAME = "faz24-direct-stt-operator-handoff.json"
README_NAME = "README.md"
SHA256SUMS_NAME = "SHA256SUMS"

REPO = "Halildeu/platform-k8s-gitops"
PLATFORM_AI_REPO = "Halildeu/platform-ai"
DEFAULT_BATCH_ID = "faz24-direct-stt-20260628"
DEFAULT_KUBE_CONTEXT = "k3d-test"
DEFAULT_NAMESPACE = "platform-test"
DEFAULT_DEPLOYMENT = "audio-gateway"
DEFAULT_VAULT_PATH = "kv/platform/audio-gateway-service"
DEFAULT_MTLS_OBJECT_NAME = "audio-gateway-direct-stt-mtls"
DEFAULT_AGGREGATE_OBJECT_NAME = "audio-gateway-secrets"
DEFAULT_TRANSCRIBE_HOST = "live-stt.denetim"
DEFAULT_TRANSCRIBE_IP = "10.99.0.2"
DEFAULT_TRANSCRIBE_PORT = 8243
DEFAULT_SEED_EVIDENCE_PATH = "docs/faz-24-evidence/direct-stt-mtls-seed-evidence.json"
DEFAULT_PREFLIGHT_PATH = "docs/faz-24-evidence/direct-stt-mtls-preflight.json"
DEFAULT_E2E_PATH = "docs/faz-24-evidence/direct-stt-e2e.json"

SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.:@/-]{1,180}$")
SAFE_PATH_RE = re.compile(r"^[A-Za-z0-9_.:@/+~-]{1,220}$")
HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9.-]{0,120}[a-z0-9])?$")
IPV4_RE = re.compile(r"^(\d{1,3}\.){3}\d{1,3}$")
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


def validate_relative_path(label: str, value: str) -> None:
    validate_single_line(label, value)
    parts = re.split(r"[\\/]+", value)
    if value.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", value) or ".." in parts:
        die(f"{label} must be a relative path inside the repo or handoff boundary")
    if not SAFE_PATH_RE.match(value):
        die(f"{label} contains unsupported characters")


def validate_host(label: str, value: str) -> None:
    validate_single_line(label, value)
    if not HOST_RE.match(value):
        die(f"{label} must be a bounded DNS hostname")


def validate_ipv4(label: str, value: str) -> None:
    validate_single_line(label, value)
    if not IPV4_RE.match(value):
        die(f"{label} must be an IPv4 address")
    octets = [int(part) for part in value.split(".")]
    if any(octet > 255 for octet in octets):
        die(f"{label} must be an IPv4 address")


def validate_port(label: str, value: int) -> None:
    if not (1 <= value <= 65535):
        die(f"{label} must be 1..65535")


def validate_args(args: argparse.Namespace) -> None:
    validate_safe_token("operator-batch-id", args.operator_batch_id)
    validate_safe_token("gitops-ref", args.gitops_ref)
    validate_safe_token("kube-context", args.kube_context)
    validate_safe_token("namespace", args.namespace)
    validate_safe_token("deployment", args.deployment)
    validate_safe_token("vault-path", args.vault_path)
    validate_safe_token("mtls-object-name", args.mtls_object_name)
    validate_safe_token("aggregate-object-name", args.aggregate_object_name)
    validate_host("transcribe-host", args.transcribe_host)
    validate_ipv4("transcribe-ip", args.transcribe_ip)
    validate_port("transcribe-port", args.transcribe_port)
    validate_relative_path("seed-evidence-path", args.seed_evidence_path)
    validate_relative_path("preflight-evidence-path", args.preflight_evidence_path)
    validate_relative_path("e2e-evidence-path", args.e2e_evidence_path)


def command_block(lines: list[str]) -> str:
    return "\n".join(lines)


def build_manifest(args: argparse.Namespace) -> dict[str, Any]:
    seed_validate = command_block(
        [
            "python3 scripts/faz24/direct_stt_mtls_seed_operator.py \\",
            f"  --vault-addr https://vault.testai.acik.com \\",
            f"  --vault-path {args.vault_path} \\",
            "  --vault-token-file /secure/operator-vault.token \\",
            "  --ca-crt-file /secure/direct-stt-ca.crt \\",
            "  --client-crt-file /secure/direct-stt-client.crt \\",
            "  --client-key-file /secure/direct-stt-client.key \\",
            f"  --evidence-out {args.seed_evidence_path}",
        ]
    )
    seed_apply = command_block(
        [
            "python3 scripts/faz24/direct_stt_mtls_seed_operator.py \\",
            f"  --vault-addr https://vault.testai.acik.com \\",
            f"  --vault-path {args.vault_path} \\",
            "  --vault-token-file /secure/operator-vault.token \\",
            "  --ca-crt-file /secure/direct-stt-ca.crt \\",
            "  --client-crt-file /secure/direct-stt-client.crt \\",
            "  --client-key-file /secure/direct-stt-client.key \\",
            f"  --evidence-out {args.seed_evidence_path} \\",
            "  --apply",
        ]
    )
    seed_verify = (
        f"python3 scripts/faz24/verify_direct_stt_mtls_seed_operator_evidence.py "
        f"{args.seed_evidence_path} "
        "--summary-json /tmp/faz24-direct-stt-mtls-seed.verify.json"
    )
    seed_ingest = command_block(
        [
            f'DIRECT_STT_MTLS_SEED_B64="$(base64 < {args.seed_evidence_path} | tr -d \'\\n\')"',
            "gh workflow run faz24-direct-stt-mtls-seed-evidence-ingest.yml \\",
            f"  --repo {REPO} \\",
            f"  --ref {args.gitops_ref} \\",
            '  -f evidence_json_base64="${DIRECT_STT_MTLS_SEED_B64}"',
        ]
    )
    preflight_verify = (
        f"python3 scripts/faz24/verify_direct_stt_mtls_enablement_preflight.py "
        f"{args.preflight_evidence_path} "
        "--summary-json /tmp/faz24-direct-stt-mtls-preflight.verify.json"
    )
    e2e_verify = (
        f"python3 scripts/faz24/verify_direct_stt_e2e_evidence.py "
        f"{args.e2e_evidence_path} "
        "--summary-json /tmp/faz24-direct-stt-e2e.verify.json"
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": utc_now(),
        "repo": REPO,
        "platformAiRepo": PLATFORM_AI_REPO,
        "operatorBatchId": args.operator_batch_id,
        "issues": {
            "gitopsRollup": "platform-k8s-gitops#1615",
            "directSttE2e": "platform-ai#182",
            "i7ProdGate": "platform-ai#198",
        },
        "acceptanceBoundary": {
            "issueStatus": "needs-verify",
            "operatorExecutionRequired": True,
            "approvedCredentialSeedRequired": True,
            "seedEvidenceRequired": True,
            "seedEvidenceIngestRequired": True,
            "preflightVerifierPassRequired": True,
            "flagFlipRequiresSeparateReviewedChange": True,
            "e2eVerifierPassRequired": True,
            "reviewerAcceptanceRequired": True,
            "doesNotAcceptI7ProdGate": True,
            "doesNotAcceptDesktopCapture": True,
            "doesNotAcceptProductionReadiness": True,
        },
        "mutationBoundary": {
            "packageBuildHostMutation": False,
            "packageBuildClusterMutation": False,
            "packageBuildVaultMutation": False,
            "packageBuildDenetimMutation": False,
            "packageBuildProductionMutation": False,
            "containsSecrets": False,
            "containsCertificates": False,
            "containsRawAudio": False,
            "containsRawTranscript": False,
            "containsRawCommandOutput": False,
        },
        "target": {
            "gitopsRef": args.gitops_ref,
            "kubeContext": args.kube_context,
            "namespace": args.namespace,
            "deployment": args.deployment,
            "vaultPath": args.vault_path,
            "mtlsObjectName": args.mtls_object_name,
            "aggregateObjectName": args.aggregate_object_name,
            "transcribeHost": args.transcribe_host,
            "transcribeIp": args.transcribe_ip,
            "transcribePort": args.transcribe_port,
            "seedEvidencePath": args.seed_evidence_path,
            "preflightEvidencePath": args.preflight_evidence_path,
            "e2eEvidencePath": args.e2e_evidence_path,
        },
        "orderedGates": [
            {
                "id": "credential-seed",
                "owner": "operator",
                "statusBeforeExecution": "pending",
                "mustNotBeRecordedInPackage": [
                    "direct_stt_ca_crt value",
                    "direct_stt_client_crt value",
                    "direct_stt_client_key value",
                    "Vault token",
                    "kubectl Secret data",
                ],
                "requiredVaultProperties": [
                    "direct_stt_ca_crt",
                    "direct_stt_client_crt",
                    "direct_stt_client_key",
                ],
                "commands": {
                    "validateOnly": seed_validate,
                    "apply": seed_apply,
                    "verifySeedEvidence": seed_verify,
                    "ingestSeedEvidence": seed_ingest,
                    "postSeedReadinessProbe": command_block(
                        [
                            "gh workflow run faz24-direct-stt-mtls-preflight-collect.yml \\",
                            f"  --repo {REPO} \\",
                            f"  --ref {args.gitops_ref} \\",
                            f"  -f kube_context={args.kube_context} \\",
                            f"  -f namespace={args.namespace} \\",
                            f"  -f deployment={args.deployment} \\",
                            "  -f probe_timeout=40",
                        ]
                    ),
                },
                "redactedEvidencePath": args.seed_evidence_path,
            },
            {
                "id": "preflight",
                "owner": "k3d-test executor",
                "statusBeforeExecution": "pending",
                "commands": {
                    "contextCheck": command_block(
                        [
                            f"kubectl config get-contexts {args.kube_context} -o name",
                            f"kubectl --context {args.kube_context} get ns {args.namespace}",
                        ]
                    ),
                    "collect": command_block(
                        [
                            "python3 scripts/faz24/collect_direct_stt_mtls_enablement_preflight.py \\",
                            f"  --context {args.kube_context} \\",
                            f"  --namespace {args.namespace} \\",
                            f"  --deployment {args.deployment} \\",
                            f"  --output {args.preflight_evidence_path}",
                        ]
                    ),
                    "verify": preflight_verify,
                    "ingest": command_block(
                        [
                            f'DIRECT_STT_MTLS_PREFLIGHT_B64="$(base64 < {args.preflight_evidence_path} | tr -d \'\\n\')"',
                            "gh workflow run faz24-direct-stt-mtls-preflight-ingest.yml \\",
                            f"  --repo {REPO} \\",
                            f"  --ref {args.gitops_ref} \\",
                            '  -f evidence_json_base64="${DIRECT_STT_MTLS_PREFLIGHT_B64}"',
                        ]
                    ),
                },
            },
            {
                "id": "flag-flip",
                "owner": "gitops reviewer",
                "statusBeforeExecution": "blocked-until-preflight-pass",
                "notes": [
                    "Change AUDIO_GATEWAY_DIRECT_STT_ENABLED to true in a reviewed GitOps change only after preflight PASS.",
                    "Keep rollback as AUDIO_GATEWAY_DIRECT_STT_ENABLED=false.",
                    "Do not change backend image digest unless intentionally pinned and reviewed.",
                ],
            },
            {
                "id": "e2e",
                "owner": "k3d-test executor",
                "statusBeforeExecution": "blocked-until-flag-flip",
                "commands": {
                    "verify": e2e_verify,
                    "ingest": command_block(
                        [
                            f'DIRECT_STT_EVIDENCE_B64="$(base64 < {args.e2e_evidence_path} | tr -d \'\\n\')"',
                            "gh workflow run faz24-direct-stt-e2e-evidence-ingest.yml \\",
                            f"  --repo {REPO} \\",
                            f"  --ref {args.gitops_ref} \\",
                            '  -f evidence_json_base64="${DIRECT_STT_EVIDENCE_B64}"',
                        ]
                    ),
                },
            },
        ],
        "issueCommentTemplates": {
            "preflightPass": (
                "Direct-STT preflight PASS evidence attached. Boundary: no audio sent, "
                "direct-STT still disabled, no #182 e2e acceptance claimed."
            ),
            "e2ePass": (
                "Direct-STT e2e verifier PASS evidence attached. Boundary: requires "
                "reviewer acceptance before #182/#1615 status advances; #198 full I7 and "
                "production readiness remain separate."
            ),
        },
    }


def render_readme(manifest: dict[str, Any]) -> str:
    target = manifest["target"]
    gates = {item["id"]: item for item in manifest["orderedGates"]}
    preflight_commands = gates["preflight"]["commands"]
    e2e_commands = gates["e2e"]["commands"]

    return f"""# Faz 24 direct-STT operator handoff

Scope: platform-ai#182 and platform-k8s-gitops#1615.

This package is a coordination artifact only. It does not connect to Vault,
Kubernetes, Denetim PC, or production; it does not read or write credentials;
it does not enable direct-STT; it does not send audio; and it does not collect
live evidence.

## Boundary

- Current status remains `Needs Verify`.
- Operator credential seed is required before Gate 1.
- Gate 0 seed evidence verifier/ingest proves only redacted helper execution.
- Gate 1 requires metadata-only preflight PASS while direct-STT is still false.
- The direct-STT flag flip is a separate reviewed GitOps change after Gate 1.
- Gate 2 requires metadata-only e2e PASS after the flag flip.
- Reviewer acceptance is required before #182/#1615 status advances.
- #198 full I7, desktop capture, and production readiness remain separate.

## Target

- kube context: `{target["kubeContext"]}`
- namespace: `{target["namespace"]}`
- deployment: `{target["deployment"]}`
- mTLS Kubernetes object: `{target["mtlsObjectName"]}`
- aggregate Kubernetes object: `{target["aggregateObjectName"]}`
- transcribe endpoint identity: `{target["transcribeHost"]}:{target["transcribePort"]}`
- redacted seed evidence path: `{target["seedEvidencePath"]}`

## Gate 0 — credential seed

Seed these Vault properties through an approved operator path. Do not print,
paste, log, or attach values:

- `direct_stt_ca_crt`
- `direct_stt_client_crt`
- `direct_stt_client_key`

Do not put these values into `{target["aggregateObjectName"]}`. They belong only
in `{target["mtlsObjectName"]}`.

Use the repo helper from an operator shell that has the approved PEM files and
a Vault token file. Keep all input files `chmod 600`; replace only the
`/secure/...` placeholders. First run validate-only; it writes redacted
evidence but does not mutate Vault:

```bash
{gates["credential-seed"]["commands"]["validateOnly"]}
```

Then apply the Vault KV v2 merge patch:

```bash
{gates["credential-seed"]["commands"]["apply"]}
```

Verify the applied seed evidence:

```bash
{gates["credential-seed"]["commands"]["verifySeedEvidence"]}
```

Archive the redacted seed evidence through CI:

```bash
{gates["credential-seed"]["commands"]["ingestSeedEvidence"]}
```

The helper writes only redacted evidence to `{target["seedEvidencePath"]}`:
property names, file-format booleans, permission booleans, HTTP status, and
boundary flags. It must not contain PEM values, Vault token, local file paths,
raw command output, audio, transcript text, or Kubernetes Secret data.

Seed evidence PASS is not Direct-STT acceptance. It proves only that the
operator helper applied the bounded Vault merge patch and wrote safe redacted
evidence. After the apply step, force or wait for ESO reconciliation and use
the canonical preflight collector as the readiness proof:

```bash
{gates["credential-seed"]["commands"]["postSeedReadinessProbe"]}
```

## Gate 1 — pre-flag mTLS preflight

Check context:

```bash
{preflight_commands["contextCheck"]}
```

Collect metadata-only evidence:

```bash
{preflight_commands["collect"]}
```

Verify it:

```bash
{preflight_commands["verify"]}
```

Ingest it after confirming no secret values, raw command output, raw audio, or
transcript text are present:

```bash
{preflight_commands["ingest"]}
```

## Gate 2 — reviewed flag flip

Do not flip direct-STT from a failing preflight. After Gate 1 PASS, use a
reviewed GitOps change to set `AUDIO_GATEWAY_DIRECT_STT_ENABLED=true`. Rollback
is `AUDIO_GATEWAY_DIRECT_STT_ENABLED=false`.

## Gate 3 — direct-STT e2e

After the flag flip, collect the metadata-only e2e envelope per
`docs/runbooks/RB-faz24-direct-stt-mtls-enable.md`, then verify it:

```bash
{e2e_commands["verify"]}
```

Ingest it:

```bash
{e2e_commands["ingest"]}
```

## Follow-up comments

Preflight PASS comment template:

```text
{manifest["issueCommentTemplates"]["preflightPass"]}
```

E2E PASS comment template:

```text
{manifest["issueCommentTemplates"]["e2ePass"]}
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
    parser.add_argument("--kube-context", default=DEFAULT_KUBE_CONTEXT)
    parser.add_argument("--namespace", default=DEFAULT_NAMESPACE)
    parser.add_argument("--deployment", default=DEFAULT_DEPLOYMENT)
    parser.add_argument("--vault-path", default=DEFAULT_VAULT_PATH)
    parser.add_argument("--mtls-object-name", default=DEFAULT_MTLS_OBJECT_NAME)
    parser.add_argument("--aggregate-object-name", default=DEFAULT_AGGREGATE_OBJECT_NAME)
    parser.add_argument("--transcribe-host", default=DEFAULT_TRANSCRIBE_HOST)
    parser.add_argument("--transcribe-ip", default=DEFAULT_TRANSCRIBE_IP)
    parser.add_argument("--transcribe-port", type=int, default=DEFAULT_TRANSCRIBE_PORT)
    parser.add_argument("--seed-evidence-path", default=DEFAULT_SEED_EVIDENCE_PATH)
    parser.add_argument("--preflight-evidence-path", default=DEFAULT_PREFLIGHT_PATH)
    parser.add_argument("--e2e-evidence-path", default=DEFAULT_E2E_PATH)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    build_package(args)
    print(f"status=pass packageDir={Path(args.output_dir)}")
    print("schema=faz24-direct-stt-operator-handoff-v1")
    print("acceptance=needs-operator-runtime-evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
