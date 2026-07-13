#!/usr/bin/env python3
"""Build a metadata-only operator handoff package for the Faz 24 authenticated
Meeting AI analyze smoke (platform-k8s-gitops#2186 / #1615).

The package coordinates the remaining owner-gated live analyze-smoke sequence
through the public testai edge: restore staging-sw / WireGuard reachability,
seed a scoped platform-desktop test token, run the redacted analyze smoke
(`testai -> api-gateway -> meeting-service -> meeting-ai`), verify the redacted
evidence, and obtain reviewer acceptance. It does not connect to staging-sw,
WireGuard, Keycloak, Kubernetes, the api-gateway, or production; it does not
seed a token, run the smoke, collect runtime evidence, or make an acceptance
claim.

The run + verify tooling referenced here is delivered by
platform-k8s-gitops#2263 (`run_meeting_ai_analyze_smoke.py` +
`verify_meeting_ai_analyze_smoke_evidence.py`); this builder only emits the
coordination artifact and never imports or executes that tooling.
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


SCHEMA_VERSION = "faz24.meetingAiAnalyzeSmoke.operator-handoff.v1"
MANIFEST_NAME = "faz24-meeting-ai-analyze-smoke-operator-handoff.json"
README_NAME = "README.md"
SHA256SUMS_NAME = "SHA256SUMS"

REPO = "Halildeu/platform-k8s-gitops"
DEFAULT_BATCH_ID = "faz24-analyze-smoke-20260713"
DEFAULT_STAGING_HOST = "staging-sw"
DEFAULT_BASE_URL = "https://testai.acik.com"
DEFAULT_EXPECTED_ISSUER = "https://testai.acik.com/realms/platform-test"
DEFAULT_TOKEN_FILE = "/tmp/faz24-analyze-smoke-token"
DEFAULT_EVIDENCE_PATH = "/tmp/faz24-meeting-ai-analyze-smoke.json"

RUN_SCRIPT = "scripts/faz24/run_meeting_ai_analyze_smoke.py"
VERIFIER = "scripts/faz24/verify_meeting_ai_analyze_smoke_evidence.py"
TOOLING_SOURCE = "platform-k8s-gitops#2263"
EVIDENCE_SCHEMA = "faz24.meetingAiAnalyzeSmoke.v1"
VERIFIER_SCHEMA = "faz24.meetingAiAnalyzeSmokeVerifier.v1"
EXTERNAL_MEETINGS_PATH = "/api/v1/admin/meetings"
ANALYZE_PATH_SUFFIX = "/intelligence/analyze"
REQUIRED_STEPS = ["token_contract", "create_meeting", "meeting_ai_analyze"]

SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.:@/-]{1,180}$")
SAFE_HOST_RE = re.compile(r"^[A-Za-z0-9_.-]{1,180}$")
SAFE_URL_RE = re.compile(r"^https://[A-Za-z0-9_.:/-]{1,200}$")
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


def validate_safe_url(label: str, value: str) -> None:
    validate_single_line(label, value)
    if not value.startswith("https://"):
        die(f"{label} must be an https:// URL")
    if not SAFE_URL_RE.match(value):
        die(f"{label} contains unsupported characters")


def validate_boundary_path(label: str, value: str) -> None:
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
    validate_safe_host("staging-host", args.staging_host)
    validate_safe_url("base-url", args.base_url)
    validate_safe_url("expected-issuer", args.expected_issuer)
    validate_boundary_path("token-file", args.token_file)
    validate_boundary_path("evidence-path", args.evidence_path)


def command_block(lines: list[str]) -> str:
    return "\n".join(lines)


def run_command(base_url: str, expected_issuer: str, token_file: str, evidence_path: str) -> str:
    return command_block(
        [
            f"python3 {RUN_SCRIPT} \\",
            f"  --token-file {token_file} \\",
            f"  --base-url {base_url} \\",
            f"  --expected-issuer {expected_issuer} \\",
            f"  --output-file {evidence_path}",
        ]
    )


def verify_command(evidence_path: str, summary_path: str) -> str:
    return command_block(
        [
            f"python3 {VERIFIER} \\",
            f"  --evidence-file {evidence_path} \\",
            f"  --output-file {summary_path}",
            "jq -e '",
            f'  .schemaVersion == "{VERIFIER_SCHEMA}" and',
            '  .status == "pass" and',
            "  (.failedChecks | length) == 0",
            f"' {summary_path}",
        ]
    )


def build_manifest(args: argparse.Namespace) -> dict[str, Any]:
    summary_path = "/tmp/faz24-meeting-ai-analyze-smoke.verify.json"
    run = run_command(args.base_url, args.expected_issuer, args.token_file, args.evidence_path)
    verify = verify_command(args.evidence_path, summary_path)

    return {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": utc_now(),
        "repo": REPO,
        "operatorBatchId": args.operator_batch_id,
        "issues": {
            "gitopsRollup": "platform-k8s-gitops#1615",
            "transcriptDeliveryRollout": "platform-k8s-gitops#2186",
            "analyzeSmokeTooling": TOOLING_SOURCE,
        },
        "acceptanceBoundary": {
            "issueStatus": "needs-runtime-smoke",
            "operatorExecutionRequired": True,
            "stagingReachabilityRestoreRequired": True,
            "scopedTestTokenSeedRequired": True,
            "analyzeSmokeExecutionRequired": True,
            "analyzeVerifierPassRequired": True,
            "reviewerAcceptanceRequired": True,
            "doesNotSeedToken": True,
            "doesNotRunSmoke": True,
            "doesNotConnectStaging": True,
            "doesNotConnectTestaiEdge": True,
            "doesNotAcceptDesktopLiveSmoke": True,
            "doesNotAcceptGpuHostStt": True,
            "doesNotAcceptProductionReadiness": True,
            "doesNotAcceptLegalGo": True,
        },
        "mutationBoundary": {
            "packageBuildEvidenceMutation": False,
            "packageBuildClusterMutation": False,
            "packageBuildTokenMutation": False,
            "packageBuildKeycloakMutation": False,
            "packageBuildHostMutation": False,
            "packageBuildNetworkMutation": False,
            "packageBuildProductionMutation": False,
            "containsCredentials": False,
            "containsTokens": False,
            "containsSourceText": False,
            "containsAnalyzeOutput": False,
            "containsPii": False,
            "containsRawCommandOutput": False,
        },
        "target": {
            "gitopsRef": args.gitops_ref,
            "stagingHost": args.staging_host,
            "baseUrl": args.base_url,
            "expectedIssuer": args.expected_issuer,
            "externalMeetingsPath": EXTERNAL_MEETINGS_PATH,
            "analyzePathSuffix": ANALYZE_PATH_SUFFIX,
            "runScript": RUN_SCRIPT,
            "verifier": VERIFIER,
            "toolingSource": TOOLING_SOURCE,
            "evidenceSchema": EVIDENCE_SCHEMA,
            "verifierSchema": VERIFIER_SCHEMA,
            "tokenFile": args.token_file,
            "evidencePath": args.evidence_path,
            "summaryPath": summary_path,
            "requiredSteps": REQUIRED_STEPS,
        },
        "requiredEvidenceLayers": {
            "up": [
                "staging-sw-wireguard-reachable",
                "testai-base-url-reachable",
                "api-gateway-meeting-service-meeting-ai-pods-running",
            ],
            "functional": [
                "token_contract-ok",
                f"create_meeting-POST-{EXTERNAL_MEETINGS_PATH}-201",
                f"meeting_ai_analyze-POST-*{ANALYZE_PATH_SUFFIX}-200",
                "structured-analyze-envelope",
                "responseMeta-schemaVersion-and-backend-present",
            ],
            "secured": [
                "tokenIncluded==false",
                "rawSourceTextIncluded==false",
                "rawAnalyzeResponseIncluded==false",
                "piiEvidenceIncluded==false",
                "erpSpecificContract==false",
                "sourceTextSha256-present",
            ],
        },
        "orderedGates": [
            {
                "id": "staging-reachability-restore",
                "owner": "owner/operator",
                "statusBeforeExecution": "pending",
                "notes": [
                    "Restore staging-sw / WireGuard reachability so the public testai edge routes to the cluster.",
                    "Confirm reachability out-of-band; do not attach WireGuard keys, SSH keys, or raw network output to evidence.",
                ],
            },
            {
                "id": "scoped-test-token-seed",
                "owner": "owner/operator",
                "statusBeforeExecution": "blocked-until-staging-reachability-restore",
                "notes": [
                    "Obtain a scoped platform-desktop test token from the testai Keycloak realm for the analyze-smoke run.",
                    f"Install it single-line at {args.token_file}; never attach the token value to any evidence or issue comment.",
                    "The token contract is validated in-run by scripts/keycloak/validate_faz24_platform_desktop_token_contract.py.",
                ],
            },
            {
                "id": "analyze-smoke-execution",
                "owner": "operator",
                "statusBeforeExecution": "blocked-until-scoped-test-token-seed",
                "commands": {
                    "run": run,
                },
                "notes": [
                    f"The smoke exercises {EXTERNAL_MEETINGS_PATH} (create) and *{ANALYZE_PATH_SUFFIX} (analyze) through {args.base_url}.",
                    "Redacted evidence only: no token, no source text, no Meeting AI natural-language output, no PII.",
                    "A single 200 is not acceptance; the redacted envelope + boundary layers are required.",
                ],
            },
            {
                "id": "evidence-verify",
                "owner": "operator/reviewer",
                "statusBeforeExecution": "blocked-until-analyze-smoke-execution",
                "commands": {
                    "verify": verify,
                },
                "notes": [
                    "The verifier is metadata-only and fail-closed; it does not mutate the cluster, Keycloak, the edge, or GitHub.",
                    f"Attach the passing verifier summary + redacted evidence artifact to {REPO}#2186.",
                    "A passing verifier is not reviewer acceptance.",
                ],
            },
            {
                "id": "reviewer-acceptance",
                "owner": "reviewer",
                "statusBeforeExecution": "blocked-until-evidence-verify-artifact",
                "notes": [
                    "Attach verifier output, redacted evidence artifact name, and a boundary statement to platform-k8s-gitops#2186.",
                    "The authenticated analyze smoke is one #2186 residual; desktop live Turkish smoke and GPU-host live STT remain separate owner-gated gates.",
                    "Do not move #2186 or #1615 to accepted solely because this package or a single passing verifier exists.",
                    "Do not claim production readiness, D30 prod cutover, or legal go from this package.",
                ],
            },
        ],
        "issueCommentTemplates": {
            "package": (
                "Meeting AI analyze smoke operator handoff package attached. Boundary: metadata-only "
                "coordination artifact; no staging-sw/WireGuard/Keycloak/cluster/edge mutation, no token "
                "seed, no smoke run, no runtime evidence collection, and no #2186/#1615 acceptance claimed."
            ),
            "smoke": (
                "Meeting AI analyze smoke evidence attached. Boundary: redacted metadata verifier PASS still "
                "requires reviewer acceptance on #2186; desktop live Turkish smoke, GPU-host live STT, "
                "production readiness, and legal go are not claimed."
            ),
        },
    }


def render_readme(manifest: dict[str, Any]) -> str:
    target = manifest["target"]
    gates = {item["id"]: item for item in manifest["orderedGates"]}
    run = gates["analyze-smoke-execution"]["commands"]["run"]
    verify = gates["evidence-verify"]["commands"]["verify"]

    return f"""# Faz 24 Meeting AI analyze smoke operator handoff

Scope: platform-k8s-gitops#2186 and platform-k8s-gitops#1615.

This package is a coordination artifact only. It does not connect to staging-sw,
WireGuard, Keycloak, Kubernetes, the api-gateway, the testai edge, or
production; it does not seed a token, run the smoke, collect runtime evidence, or
advance any issue status.

## Boundary

- Current #2186 status remains needs-runtime-smoke.
- The scoped test token is owner-owned; never attach its value to evidence or
  comments.
- Redacted evidence only: no token, no source text, no Meeting AI
  natural-language output, no PII.
- A single analyze 200 is not acceptance; the redacted envelope and boundary
  layers are required.
- A passing verifier is not reviewer acceptance.
- Desktop live Turkish smoke, GPU-host live STT, production readiness, and legal
  go remain separate.
- The run + verify tooling is delivered by {target["toolingSource"]}.

## Target

- staging host: `{target["stagingHost"]}`
- base URL: `{target["baseUrl"]}`
- expected issuer: `{target["expectedIssuer"]}`
- create path: `{target["externalMeetingsPath"]}`
- analyze path suffix: `{target["analyzePathSuffix"]}`
- run script: `{target["runScript"]}`
- verifier: `{target["verifier"]}`
- evidence schema: `{target["evidenceSchema"]}`
- verifier schema: `{target["verifierSchema"]}`
- evidence path: `{target["evidencePath"]}`

## Gate 0 - staging reachability restore (owner)

Restore staging-sw / WireGuard reachability so the public testai edge routes to
the cluster. Confirm reachability out-of-band; do not attach WireGuard keys, SSH
keys, or raw network output to evidence.

## Gate 1 - scoped test token seed (owner)

Obtain a scoped platform-desktop test token from the testai Keycloak realm and
install it single-line at `{target["tokenFile"]}`. Do not attach the token value
anywhere.

## Gate 2 - analyze smoke execution (operator)

```bash
{run}
```

Redacted evidence only: no token, no source text, no Meeting AI natural-language
output, and no PII.

## Gate 3 - verify (operator/reviewer)

Validate the redacted analyze-smoke evidence:

```bash
{verify}
```

Attach the passing verifier summary and the redacted evidence artifact to
platform-k8s-gitops#2186.

## Gate 4 - reviewer acceptance (reviewer)

Attach verifier output, redacted evidence artifact name, and a boundary
statement to platform-k8s-gitops#2186. Keep #2186 and #1615 unaccepted unless the
relevant rollup gate has accepted runtime evidence.

## Follow-up comments

Package comment template:

```text
{manifest["issueCommentTemplates"]["package"]}
```

Analyze smoke evidence comment template:

```text
{manifest["issueCommentTemplates"]["smoke"]}
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
    parser.add_argument("--staging-host", default=DEFAULT_STAGING_HOST)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--expected-issuer", default=DEFAULT_EXPECTED_ISSUER)
    parser.add_argument("--token-file", default=DEFAULT_TOKEN_FILE)
    parser.add_argument("--evidence-path", default=DEFAULT_EVIDENCE_PATH)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    build_package(args)
    print(f"status=pass packageDir={Path(args.output_dir)}")
    print("schema=faz24-meeting-ai-analyze-smoke-operator-handoff-v1")
    print("acceptance=needs-operator-runtime-evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
