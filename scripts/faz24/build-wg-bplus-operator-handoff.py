#!/usr/bin/env python3
"""Build a metadata-only operator handoff package for Faz 24 WG-B+.

This package coordinates the remaining I3 and I6 operator evidence steps. It
does not connect to Denetim PC or aiserver, does not collect live evidence,
and does not mutate host, cluster, WireGuard, platform-ai, or production state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = "faz24.wg-bplus.operator-handoff.v1"
MANIFEST_NAME = "faz24-wg-bplus-operator-handoff.json"
README_NAME = "README.md"
SHA256SUMS_NAME = "SHA256SUMS"

REPO = "Halildeu/platform-k8s-gitops"
DEFAULT_I3_IDENTITY_RUN_ID = "28326845949"
DEFAULT_I3_AUTHORIZE_PACKAGE_RUN_ID = "28326859105"
DEFAULT_I3_PUBLIC_KEY_FINGERPRINT = "SHA256:4hWKcV0D3yrRfW4srj0mQJb+297J+RnS0HuoR0D6t1Y"
DEFAULT_I3_PUBLIC_KEY_LINE_SHA256 = "83f4788c09f9d7e68af113e9680c4a996f95a66c230d6240780ace47734844ff"
DEFAULT_I3_PUBLIC_KEY_BLOB_SHA256 = "e2158a715d03df2ad17d6e2cae3d264096fedbdec9f919d2d07ba84740fab756"
DEFAULT_I6_HOST_PACKAGE_RUN_ID = "28151747361"

RUN_ID_RE = re.compile(r"^[1-9][0-9]{5,32}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
FINGERPRINT_RE = re.compile(r"^SHA256:[A-Za-z0-9+/]+={0,2}$")
SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.:@/-]{1,180}$")
SSH_TARGET_RE = re.compile(r"^[A-Za-z0-9._-]+@[A-Za-z0-9._:-]{1,128}$")

FORBIDDEN_PATTERNS = (
    re.compile(r"-----BEGIN (OPENSSH |RSA |EC |DSA )?PRIVATE KEY-----"),
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
        die(f"{label} must not contain private key or token-like material")


def validate_run_id(label: str, value: str) -> None:
    validate_single_line(label, value)
    if not RUN_ID_RE.match(value):
        die(f"{label} must be a numeric GitHub Actions run id")


def validate_sha256(label: str, value: str) -> None:
    validate_single_line(label, value)
    if not SHA256_RE.match(value):
        die(f"{label} must be a lowercase SHA-256 hex digest")


def validate_fingerprint(label: str, value: str) -> None:
    validate_single_line(label, value)
    if not FINGERPRINT_RE.match(value):
        die(f"{label} must be an OpenSSH SHA256 fingerprint")


def validate_safe_token(label: str, value: str) -> None:
    validate_single_line(label, value)
    parts = re.split(r"[\\/]+", value)
    if value.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", value) or ".." in parts:
        die(f"{label} must be relative/symbolic and stay inside the handoff boundary")
    if not SAFE_TOKEN_RE.match(value):
        die(f"{label} contains unsupported characters")


def validate_ssh_target(label: str, value: str) -> None:
    validate_single_line(label, value)
    if not SSH_TARGET_RE.match(value):
        die(f"{label} must look like user@host")


def validate_args(args: argparse.Namespace) -> None:
    validate_safe_token("operator-batch-id", args.operator_batch_id)
    validate_run_id("i3-identity-run-id", args.i3_identity_run_id)
    validate_run_id("i3-authorize-package-run-id", args.i3_authorize_package_run_id)
    validate_fingerprint("i3-public-key-fingerprint", args.i3_public_key_fingerprint)
    validate_sha256("i3-public-key-line-sha256", args.i3_public_key_line_sha256)
    validate_sha256("i3-public-key-blob-sha256", args.i3_public_key_blob_sha256)
    validate_run_id("i6-host-package-run-id", args.i6_host_package_run_id)
    validate_ssh_target("denetim-ssh-target", args.denetim_ssh_target)
    validate_safe_token("i6-target-host", args.i6_target_host)


def artifact_name(prefix: str, run_id: str) -> str:
    return f"{prefix}-{run_id}"


def run_url(run_id: str) -> str:
    return f"https://github.com/{REPO}/actions/runs/{run_id}"


def command_block(lines: list[str]) -> str:
    return "\n".join(lines)


def build_manifest(args: argparse.Namespace) -> dict[str, object]:
    i3_package = artifact_name(
        "faz24-i3-denetim-ssh-authorize-package",
        args.i3_authorize_package_run_id,
    )
    i6_package = artifact_name(
        "faz24-i6-host-evidence-package",
        args.i6_host_package_run_id,
    )

    i3_ingest_command = command_block(
        [
            'I3_AUTH_EVIDENCE_B64="$(base64 < denetim-i3-ssh-authorize-evidence.json | tr -d \'\\n\')"',
            "gh workflow run faz24-i3-denetim-ssh-authorize-evidence-ingest.yml \\",
            f"  --repo {REPO} \\",
            "  --ref main \\",
            '  -f evidence_json_base64="${I3_AUTH_EVIDENCE_B64}" \\',
            "  -f expected_target_user=svc-denetim-agent \\",
            f"  -f expected_public_key_fingerprint={args.i3_public_key_fingerprint} \\",
            f"  -f expected_public_key_line_sha256={args.i3_public_key_line_sha256} \\",
            f"  -f expected_public_key_blob_sha256={args.i3_public_key_blob_sha256}",
        ]
    )

    i6_ingest_command = command_block(
        [
            'I6_EVIDENCE_B64="$(base64 < "${OUT}" | tr -d \'\\n\')"',
            "gh workflow run faz24-wg-bplus-i6-masq-evidence-ingest.yml \\",
            f"  --repo {REPO} \\",
            "  --ref main \\",
            '  -f evidence_json_base64="${I6_EVIDENCE_B64}"',
        ]
    )

    return {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": utc_now(),
        "repo": REPO,
        "operatorBatchId": args.operator_batch_id,
        "acceptanceBoundary": {
            "i3Status": "needs-verify",
            "i6Status": "needs-verify",
            "operatorExecutionRequired": True,
            "verifierPassRequired": True,
            "reviewerAcceptanceRequired": True,
            "doesNotAcceptDirectStt": True,
            "doesNotAcceptAppMtls": True,
            "doesNotAcceptProductionCutover": True,
        },
        "mutationBoundary": {
            "packageBuildHostMutation": False,
            "packageBuildClusterMutation": False,
            "packageBuildDenetimMutation": False,
            "packageBuildStagingMutation": False,
            "packageBuildProductionMutation": False,
            "containsSecrets": False,
            "containsRawCommandOutput": False,
            "containsRawAudio": False,
            "containsRawTranscript": False,
        },
        "i3": {
            "issue": 1864,
            "boardStatus": "Needs Verify",
            "identityRunId": args.i3_identity_run_id,
            "authorizePackageRunId": args.i3_authorize_package_run_id,
            "authorizePackageRunUrl": run_url(args.i3_authorize_package_run_id),
            "authorizePackageArtifact": i3_package,
            "denetimSshTarget": args.denetim_ssh_target,
            "targetUser": "svc-denetim-agent",
            "expectedPublicKeyFingerprint": args.i3_public_key_fingerprint,
            "expectedPublicKeyLineSha256": args.i3_public_key_line_sha256,
            "expectedPublicKeyBlobSha256": args.i3_public_key_blob_sha256,
            "nextActions": [
                "Download the Denetim SSH authorize package artifact.",
                "Run authorize-denetim-i3-public-key.ps1 in an elevated Denetim PowerShell session.",
                "Ingest denetim-i3-ssh-authorize-evidence.json with faz24-i3-denetim-ssh-authorize-evidence-ingest.yml.",
                "Re-run faz24-wg-bplus-i3-evidence.yml and require verifier PASS.",
            ],
            "commands": {
                "downloadPackage": (
                    f"gh run download {args.i3_authorize_package_run_id} --repo {REPO} "
                    f"--name {i3_package} --dir ./faz24-i3-denetim-package-{args.i3_authorize_package_run_id}"
                ),
                "operatorPowerShell": "powershell -ExecutionPolicy Bypass -File .\\authorize-denetim-i3-public-key.ps1",
                "ingestAuthorizeEvidence": i3_ingest_command,
                "rerunI3Evidence": command_block(
                    [
                        "gh workflow run faz24-wg-bplus-i3-evidence.yml \\",
                        f"  --repo {REPO} \\",
                        "  --ref main \\",
                        f"  -f denetim_ssh_target={args.denetim_ssh_target} \\",
                        "  -f lookback_hours=2 \\",
                        "  -f wg_interface=auto",
                    ]
                ),
            },
        },
        "i6": {
            "issue": 1867,
            "boardStatus": "Needs Verify",
            "hostPackageRunId": args.i6_host_package_run_id,
            "hostPackageRunUrl": run_url(args.i6_host_package_run_id),
            "hostPackageArtifact": i6_package,
            "targetHost": args.i6_target_host,
            "nextActions": [
                "Download the I6 host-evidence package artifact.",
                "Run collect-staging-i6-host-evidence.sh from a clean platform-k8s-gitops checkout on aiserver.",
                "Ingest the resulting protected metadata-only JSON with faz24-wg-bplus-i6-masq-evidence-ingest.yml.",
                "Require GitHub ingest verifier PASS and reviewer acceptance.",
            ],
            "commands": {
                "downloadPackage": (
                    f"gh run download {args.i6_host_package_run_id} --repo {REPO} "
                    f"--name {i6_package} --dir ./faz24-i6-host-package-{args.i6_host_package_run_id}"
                ),
                "operatorShell": "bash /path/to/collect-staging-i6-host-evidence.sh",
                "ingestMasqEvidence": i6_ingest_command,
            },
        },
        "boardSync": {
            "trackedIssues": [1864, 1867, 1874],
            "expectedStatusBeforeOperatorEvidence": "Needs Verify",
            "doNotMoveToDoneWithoutVerifierPassAndReviewerAcceptance": True,
        },
    }


def render_readme(manifest: dict[str, object]) -> str:
    i3 = manifest["i3"]
    i6 = manifest["i6"]
    assert isinstance(i3, dict)
    assert isinstance(i6, dict)
    i3_commands = i3["commands"]
    i6_commands = i6["commands"]
    assert isinstance(i3_commands, dict)
    assert isinstance(i6_commands, dict)

    return f"""# Faz 24 WG-B+ operator handoff

Scope: platform-k8s-gitops#1864, #1867, and #1874.

This package is a coordination artifact only. It does not connect to Denetim
PC or aiserver, does not collect live evidence, and does not change host,
cluster, WireGuard, platform-ai, secret, or production state.

## Current boundary

- I3 board status: `Needs Verify`
- I6 board status: `Needs Verify`
- I3 requires Denetim operator execution, Denetim authorize evidence ingest,
  and then I3 evidence verifier PASS.
- I6 requires aiserver operator execution, MASQ evidence ingest, and verifier
  PASS.
- This package does not prove direct-STT Functional, app-mTLS, compute-plane
  audit smoke, direct audio e2e, or production cutover.

## I3 Denetim public-key authorization

Download the package:

```bash
{i3_commands["downloadPackage"]}
```

Run on Denetim PC from the extracted package directory in an elevated
PowerShell session:

```powershell
{i3_commands["operatorPowerShell"]}
```

From a trusted workstation, ingest `denetim-i3-ssh-authorize-evidence.json`:

```bash
{i3_commands["ingestAuthorizeEvidence"]}
```

If the ingest verifier returns PASS, re-run the I3 evidence workflow:

```bash
{i3_commands["rerunI3Evidence"]}
```

## I6 aiserver host evidence

Download the package:

```bash
{i6_commands["downloadPackage"]}
```

Run on `aiserver` from a clean `platform-k8s-gitops` checkout:

```bash
{i6_commands["operatorShell"]}
```

If the local verifier returns PASS, ingest the exact JSON:

```bash
{i6_commands["ingestMasqEvidence"]}
```

## Follow-up

After each ingest run, add evidence comments to the linked issue with workflow
URL, artifact name, verifier output, and no-leak boundary. Keep #1864 and
#1867 in `Needs Verify` until verifier PASS and reviewer acceptance are both
present.
"""


def write_text(path: Path, value: str) -> None:
    path.write_text(value, encoding="utf-8")


def write_sha256sums(output_dir: Path) -> None:
    lines = []
    for path in sorted(output_dir.iterdir(), key=lambda item: item.name):
        if path.name == SHA256SUMS_NAME or not path.is_file():
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.name}")
    write_text(output_dir / SHA256SUMS_NAME, "\n".join(lines) + "\n")


def build_package(args: argparse.Namespace) -> dict[str, object]:
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
    parser.add_argument("--operator-batch-id", default="faz24-wg-bplus-20260628")
    parser.add_argument("--i3-identity-run-id", default=DEFAULT_I3_IDENTITY_RUN_ID)
    parser.add_argument("--i3-authorize-package-run-id", default=DEFAULT_I3_AUTHORIZE_PACKAGE_RUN_ID)
    parser.add_argument("--i3-public-key-fingerprint", default=DEFAULT_I3_PUBLIC_KEY_FINGERPRINT)
    parser.add_argument("--i3-public-key-line-sha256", default=DEFAULT_I3_PUBLIC_KEY_LINE_SHA256)
    parser.add_argument("--i3-public-key-blob-sha256", default=DEFAULT_I3_PUBLIC_KEY_BLOB_SHA256)
    parser.add_argument("--i6-host-package-run-id", default=DEFAULT_I6_HOST_PACKAGE_RUN_ID)
    parser.add_argument("--denetim-ssh-target", default="svc-denetim-agent@10.99.0.2")
    parser.add_argument("--i6-target-host", default="aiserver")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    manifest = build_package(args)
    print(f"status=pass packageDir={Path(args.output_dir)}")
    print(f"schemaVersion={manifest['schemaVersion']}")
    print("acceptance=needs-operator-evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
