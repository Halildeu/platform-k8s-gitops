#!/usr/bin/env python3
"""Build a metadata-only operator handoff package for Faz 24 external recorder.

The package coordinates the remaining platform-desktop token contract and
external recorder smoke path for platform-k8s-gitops#1615. It does not mint or
read tokens, connect to testai, mutate Keycloak, run the smoke, send audio, or
collect live evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "faz24.externalRecorder.operator-handoff.v1"
MANIFEST_NAME = "faz24-external-recorder-operator-handoff.json"
README_NAME = "README.md"
SHA256SUMS_NAME = "SHA256SUMS"

REPO = "Halildeu/platform-k8s-gitops"
DEFAULT_BATCH_ID = "faz24-external-recorder-20260628"
DEFAULT_BASE_URL = "https://testai.acik.com"
DEFAULT_EXPECTED_ISSUER = "https://testai.acik.com/realms/platform-test"
TOKEN_CONTRACT_REPORT_PATH = "/tmp/faz24-platform-desktop-token-contract.json"
SMOKE_EVIDENCE_PATH = "/tmp/faz24-external-recorder-smoke.json"
SMOKE_VERIFY_PATH = "/tmp/faz24-external-recorder-smoke.verify.json"
GCAP_VERIFY_PATH = "/tmp/faz24-gcap-capture-gate.verify.json"
GCAP_INGEST_INPUT_PATH = "/tmp/faz24-gcap-capture-gate.ingest-input.json"

SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.:@/-]{1,180}$")
HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9.-]{0,120}[a-z0-9])?$")
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


def validate_https_url(label: str, value: str) -> None:
    validate_single_line(label, value)
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        die(f"{label} must be a bounded https URL without credentials")
    if parsed.query or parsed.fragment:
        die(f"{label} must not contain query or fragment")
    host = parsed.hostname or ""
    if not HOST_RE.match(host):
        die(f"{label} host must be a bounded DNS hostname")
    if parsed.port is not None and not (1 <= parsed.port <= 65535):
        die(f"{label} port must be 1..65535")
    if ".." in [part for part in parsed.path.split("/") if part]:
        die(f"{label} path must not escape its boundary")


def validate_args(args: argparse.Namespace) -> None:
    validate_safe_token("operator-batch-id", args.operator_batch_id)
    validate_safe_token("gitops-ref", args.gitops_ref)
    validate_https_url("base-url", args.base_url)
    validate_https_url("expected-issuer", args.expected_issuer)


def command_block(lines: list[str]) -> str:
    return "\n".join(lines)


def build_manifest(args: argparse.Namespace) -> dict[str, Any]:
    token_file_expr = '"${FAZ24_PLATFORM_DESKTOP_TOKEN_FILE:?set operator-only token file}"'
    token_contract = command_block(
        [
            "python3 scripts/keycloak/validate_faz24_platform_desktop_token_contract.py \\",
            f"  --token-file {token_file_expr} \\",
            f'  --expected-issuer "{args.expected_issuer}" \\',
            f"  > {TOKEN_CONTRACT_REPORT_PATH}",
            f"jq -e '.status == \"pass\" and .tokenIncluded == false' {TOKEN_CONTRACT_REPORT_PATH}",
        ]
    )
    smoke_run = command_block(
        [
            "python3 scripts/faz24/run_external_recorder_smoke.py \\",
            f"  --token-file {token_file_expr} \\",
            f'  --base-url "{args.base_url}" \\',
            f'  --expected-issuer "{args.expected_issuer}" \\',
            f"  --output-file {SMOKE_EVIDENCE_PATH}",
            f"jq -e '.status == \"pass\" and .tokenIncluded == false' {SMOKE_EVIDENCE_PATH}",
        ]
    )
    smoke_verify = command_block(
        [
            "python3 scripts/faz24/verify_external_recorder_smoke_evidence.py \\",
            f"  --evidence-file {SMOKE_EVIDENCE_PATH} \\",
            f"  --output-file {SMOKE_VERIFY_PATH}",
            f"jq -e '.status == \"pass\" and .tokenIncluded == false' {SMOKE_VERIFY_PATH}",
        ]
    )
    gcap_aggregate = command_block(
        [
            "python3 scripts/faz24/verify_gcap_capture_gate_evidence.py \\",
            "  --evidence-file /tmp/faz24-external-recorder-smoke-01.verify.json \\",
            "  --evidence-file /tmp/faz24-external-recorder-smoke-02.verify.json \\",
            "  --evidence-file /tmp/faz24-external-recorder-smoke-03.verify.json \\",
            "  --evidence-file /tmp/faz24-desktop-capture-evidence-04.verify.json \\",
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
            "  /tmp/faz24-desktop-capture-evidence.verify.json \\",
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
            "tokenContract": "platform-k8s-gitops#1995",
            "externalRecorderRunner": "platform-k8s-gitops#1996",
            "externalRecorderVerifier": "platform-k8s-gitops#1997",
            "gcapAggregate": "platform-k8s-gitops#2027",
        },
        "acceptanceBoundary": {
            "issueStatus": "needs-verify",
            "operatorExecutionRequired": True,
            "approvedShortLivedTokenRequired": True,
            "tokenContractPassRequired": True,
            "externalSmokePassRequired": True,
            "smokeVerifierPassRequired": True,
            "reviewerAcceptanceRequired": True,
            "gcapRequiresMultipleVerifierSummaries": True,
            "doesNotAcceptDirectStt": True,
            "doesNotAcceptComputePlaneAudit": True,
            "doesNotAcceptDesktopMicLoopback": True,
            "doesNotAcceptProductionReadiness": True,
        },
        "mutationBoundary": {
            "packageBuildHostMutation": False,
            "packageBuildKeycloakMutation": False,
            "packageBuildClusterMutation": False,
            "packageBuildVaultMutation": False,
            "packageBuildProductionMutation": False,
            "containsCredentials": False,
            "containsRawAudio": False,
            "containsRawTranscript": False,
            "containsRawHttpBodies": False,
            "containsRawCommandOutput": False,
        },
        "target": {
            "gitopsRef": args.gitops_ref,
            "baseUrl": args.base_url,
            "expectedIssuer": args.expected_issuer,
            "tokenFileEnv": "FAZ24_PLATFORM_DESKTOP_TOKEN_FILE",
            "tokenContractReportPath": TOKEN_CONTRACT_REPORT_PATH,
            "smokeEvidencePath": SMOKE_EVIDENCE_PATH,
            "smokeVerifierPath": SMOKE_VERIFY_PATH,
            "gcapVerifierPath": GCAP_VERIFY_PATH,
            "gcapIngestInputPath": GCAP_INGEST_INPUT_PATH,
        },
        "orderedGates": [
            {
                "id": "token-file-prep",
                "owner": "operator",
                "statusBeforeExecution": "pending",
                "mustNotBeRecordedInPackage": [
                    "platform-desktop JWT value",
                    "Authorization header",
                    "Keycloak admin response",
                    "admin token",
                    "password",
                    "cookie",
                    "raw shell transcript",
                ],
                "notes": [
                    "Mint a short-lived platform-desktop access token through the approved test-only path.",
                    "Store it in an operator-only 0600 file and export only FAZ24_PLATFORM_DESKTOP_TOKEN_FILE.",
                    "Do not paste token material into issue comments, PRs, Mavis, logs, or artifacts.",
                ],
            },
            {
                "id": "token-contract",
                "owner": "operator",
                "statusBeforeExecution": "pending",
                "commands": {"validate": token_contract},
            },
            {
                "id": "external-recorder-smoke",
                "owner": "operator",
                "statusBeforeExecution": "blocked-until-token-contract-pass",
                "commands": {"run": smoke_run},
            },
            {
                "id": "external-recorder-verifier",
                "owner": "operator",
                "statusBeforeExecution": "blocked-until-smoke-pass",
                "commands": {"verify": smoke_verify},
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
            "tokenContractPass": (
                "Platform-desktop token-contract PASS evidence attached. Boundary: "
                "token value omitted, no live recorder smoke or #1615 acceptance claimed."
            ),
            "smokeVerifierPass": (
                "External recorder smoke verifier PASS evidence attached. Boundary: "
                "direct-STT, compute-plane audit, desktop mic/loopback, G-CAP aggregate, "
                "and production readiness remain separate gates."
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

    return f"""# Faz 24 external recorder operator handoff

Scope: platform-k8s-gitops#1615 external meeting-admin and recorder lifecycle.

This package is a coordination artifact only. It does not mint or read tokens,
connect to testai, mutate Keycloak, mutate Kubernetes, touch Vault, run the
external recorder smoke, send audio, or collect live evidence.

## Boundary

- Current status remains `Needs Verify`.
- An approved short-lived `platform-desktop` access token is required.
- Gate 1 requires token-contract PASS with `tokenIncluded=false`.
- Gate 2 requires external meeting-admin + recorder smoke PASS.
- Gate 3 requires verifier PASS before attachment.
- G-CAP aggregate acceptance requires multiple verifier summaries and reviewer
  acceptance; a single smoke is not aggregate product evidence.
- Direct-STT, compute-plane audit, desktop mic/loopback, and production
  readiness remain separate gates.

## Target

- base URL: `{target["baseUrl"]}`
- expected issuer: `{target["expectedIssuer"]}`
- token file env var: `{target["tokenFileEnv"]}`
- token-contract report: `{target["tokenContractReportPath"]}`
- smoke evidence: `{target["smokeEvidencePath"]}`
- smoke verifier summary: `{target["smokeVerifierPath"]}`
- G-CAP aggregate summary: `{target["gcapVerifierPath"]}`
- G-CAP ingest input wrapper: `{target["gcapIngestInputPath"]}`

## Gate 0 — operator token file

Mint a short-lived `platform-desktop` token through the approved test-only
operator path. Store it in an operator-only file and export only the file path:

```bash
umask 077
export FAZ24_PLATFORM_DESKTOP_TOKEN_FILE=/tmp/faz24-platform-desktop-token.jwt
# Write the token value into the file without echoing it to logs.
```

Do not paste the token, authorization header, Keycloak admin response, admin
credential, password, cookie, or raw shell transcript into GitHub, Mavis, PRs,
or artifacts.

## Gate 1 — token-contract validation

```bash
{gates["token-contract"]["commands"]["validate"]}
```

Attach only `{target["tokenContractReportPath"]}` after confirming
`status=pass` and `tokenIncluded=false`.

## Gate 2 — external recorder smoke

```bash
{gates["external-recorder-smoke"]["commands"]["run"]}
```

This exercises the public `POST /api/v1/admin/meetings` path and the
`audio-gateway` consent/session/chunk/finish/status lifecycle. The output must
remain metadata-only.

## Gate 3 — verifier

```bash
{gates["external-recorder-verifier"]["commands"]["verify"]}
```

Attach `{target["smokeEvidencePath"]}` and `{target["smokeVerifierPath"]}` only
after checking both have `tokenIncluded=false`.

## Gate 4 — G-CAP aggregate

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

Token-contract PASS comment template:

```text
{manifest["issueCommentTemplates"]["tokenContractPass"]}
```

External smoke verifier PASS comment template:

```text
{manifest["issueCommentTemplates"]["smokeVerifierPass"]}
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
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--expected-issuer", default=DEFAULT_EXPECTED_ISSUER)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    build_package(args)
    print(f"status=pass packageDir={Path(args.output_dir)}")
    print("schema=faz24-external-recorder-operator-handoff-v1")
    print("acceptance=needs-operator-runtime-evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
