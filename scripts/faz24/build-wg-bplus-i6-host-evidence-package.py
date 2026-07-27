#!/usr/bin/env python3
"""Build an operator package for Faz 24 WG-B+ I6 host evidence collection.

The package is metadata-only orchestration material. It does not collect host
evidence while building, does not connect to aiserver, and does not carry raw
iptables/systemd/WireGuard output or secrets. The generated shell wrapper is
intended to be run by an operator from a clean platform-k8s-gitops checkout on
aiserver.

Schema v2 (2026-07-12): the wrapper now drives the hardened v2 collector arg
surface. The v1 ``--pod-cidr`` default was the I6 false-positive root cause, so
this package requires an explicit ``--cluster-cidr`` and passes the WireGuard
peer + node + docker-network topology the v2 checks need.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = "faz24.i6.host-evidence-package.v2"
SCRIPT_NAME = "collect-staging-i6-host-evidence.sh"
METADATA_NAME = "expected-i6-host-evidence-metadata.json"
README_NAME = "README.md"
SHA256SUMS_NAME = "SHA256SUMS"

NAME_RE = re.compile(r"^[A-Za-z0-9_.:@-]{1,96}$")
CIDR_RE = re.compile(r"^[0-9]{1,3}(\.[0-9]{1,3}){3}/[0-9]{1,2}$")
HOST_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
REF_RE = re.compile(r"^[A-Za-z0-9_.:@/=-]{1,220}$")

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


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sh_single_quoted(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def validate_single_line(label: str, value: str) -> None:
    if "\n" in value or "\r" in value:
        die(f"{label} must be single-line")
    if any(pattern.search(value) for pattern in FORBIDDEN_PATTERNS):
        die(f"{label} must not contain private key or token-like material")


def validate_name(label: str, value: str) -> None:
    validate_single_line(label, value)
    if not NAME_RE.match(value):
        die(f"{label} must use safe name characters")


def validate_cidr(label: str, value: str) -> None:
    validate_single_line(label, value)
    if not CIDR_RE.match(value):
        die(f"{label} must be IPv4 CIDR-shaped")


def validate_host(label: str, value: str) -> None:
    validate_single_line(label, value)
    if not HOST_RE.match(value):
        die(f"{label} must be a bounded host/IP value")


def validate_relative_ref(label: str, value: str) -> None:
    validate_single_line(label, value)
    if not value:
        return
    parts = re.split(r"[\\/]+", value)
    if value.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", value) or ".." in parts:
        die(f"{label} must be relative and stay under protected evidence path")
    if not REF_RE.match(value):
        die(f"{label} contains unsupported characters")


def validate_script_path(label: str, value: str) -> None:
    validate_single_line(label, value)
    if not value:
        return
    if ".." in re.split(r"[\\/]+", value):
        die(f"{label} must not contain parent traversal segments")


def validate_args(args: argparse.Namespace) -> None:
    validate_name("target-host", args.target_host)
    validate_cidr("cluster-cidr", args.cluster_cidr)
    if args.service_cidr:
        validate_cidr("service-cidr", args.service_cidr)
    validate_name("wg-interface", args.wg_interface)
    validate_host("peer-host", args.peer_host)
    if not 1 <= args.peer_port <= 65535:
        die("peer-port must be 1-65535")
    validate_name("wg-node", args.wg_node)
    validate_name("docker-network", args.docker_network)
    if not 1 <= args.probe_attempts <= 10:
        die("probe-attempts must be 1-10")
    if args.installed_host_rule_script:
        validate_script_path("installed-host-rule-script", args.installed_host_rule_script)
    validate_name("kube-context", args.kube_context)
    validate_name("namespace", args.namespace)
    validate_name("systemd-unit", args.systemd_unit)
    validate_name("drift-timer", args.drift_timer)
    if not 1 <= args.drift_interval_minutes <= 1440:
        die("drift-interval-minutes must be 1-1440")
    validate_relative_ref("rollback-tested-ref", args.rollback_tested_ref)


def render_wrapper(args: argparse.Namespace) -> str:
    rollback_arg = ""
    if args.rollback_tested_ref:
        rollback_arg = f"  --rollback-tested-ref {sh_single_quoted(args.rollback_tested_ref)} \\\n"

    service_arg = ""
    if args.service_cidr:
        service_arg = f"  --service-cidr {sh_single_quoted(args.service_cidr)} \\\n"

    installed_arg = ""
    if args.installed_host_rule_script:
        installed_arg = (
            f"  --installed-host-rule-script {sh_single_quoted(args.installed_host_rule_script)} \\\n"
        )

    return f"""#!/usr/bin/env bash
set -euo pipefail

if [ ! -f scripts/faz24/collect-wg-bplus-i6-masq-evidence.py ] || \\
   [ ! -f scripts/faz24/verify-wg-bplus-i6-masq-evidence.py ]; then
  echo "ERR run this script from the platform-k8s-gitops repository root on aiserver" >&2
  exit 2
fi

OUT="${{OUT:-/tmp/wg-bplus-i6-masq-evidence.json}}"
PROTECTED_EVIDENCE_PATH="${{PROTECTED_EVIDENCE_PATH:-operator://{args.target_host}/protected/faz24/i6/$(date -u +%Y%m%dT%H%M%SZ)}}"

case "${{OUT}}" in
  *$'\\n'*|*$'\\r'*)
    echo "ERR OUT must be single-line" >&2
    exit 2
    ;;
esac
case "${{PROTECTED_EVIDENCE_PATH}}" in
  *$'\\n'*|*$'\\r'*)
    echo "ERR PROTECTED_EVIDENCE_PATH must be single-line" >&2
    exit 2
    ;;
esac

sudo -E python3 scripts/faz24/collect-wg-bplus-i6-masq-evidence.py \\
  --output "${{OUT}}" \\
  --cluster-cidr {sh_single_quoted(args.cluster_cidr)} \\
{service_arg}  --wg-interface {sh_single_quoted(args.wg_interface)} \\
  --peer-host {sh_single_quoted(args.peer_host)} \\
  --peer-port {args.peer_port} \\
  --wg-node {sh_single_quoted(args.wg_node)} \\
  --docker-network {sh_single_quoted(args.docker_network)} \\
  --probe-attempts {args.probe_attempts} \\
  --kube-context {sh_single_quoted(args.kube_context)} \\
  --namespace {sh_single_quoted(args.namespace)} \\
  --systemd-unit {sh_single_quoted(args.systemd_unit)} \\
  --drift-timer {sh_single_quoted(args.drift_timer)} \\
  --drift-interval-minutes {args.drift_interval_minutes} \\
{installed_arg}{rollback_arg}  --protected-evidence-path "${{PROTECTED_EVIDENCE_PATH}}"

python3 scripts/faz24/verify-wg-bplus-i6-masq-evidence.py "${{OUT}}"

echo
echo "Evidence JSON: ${{OUT}}"
echo "Protected evidence path: ${{PROTECTED_EVIDENCE_PATH}}"
echo
echo "If the verifier above prints PASS, ingest the exact JSON from a trusted workstation:"
echo "I6_EVIDENCE_B64=\\\"\\$(base64 < '${{OUT}}' | tr -d '\\\\n')\\\""
echo "gh workflow run faz24-wg-bplus-i6-masq-evidence-ingest.yml --repo Halildeu/platform-k8s-gitops --ref main -f evidence_json_base64=\\\"\\${{I6_EVIDENCE_B64}}\\\""
"""


def metadata(args: argparse.Namespace) -> dict[str, object]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": utc_now(),
        "targetHost": args.target_host,
        "collector": "scripts/faz24/collect-wg-bplus-i6-masq-evidence.py",
        "verifier": "scripts/faz24/verify-wg-bplus-i6-masq-evidence.py",
        "defaults": {
            "clusterCIDR": args.cluster_cidr,
            "serviceCIDR": args.service_cidr,
            "wgInterface": args.wg_interface,
            "peerHost": args.peer_host,
            "peerPort": args.peer_port,
            "wgNode": args.wg_node,
            "dockerNetwork": args.docker_network,
            "probeAttempts": args.probe_attempts,
            "installedHostRuleScript": args.installed_host_rule_script,
            "kubeContext": args.kube_context,
            "namespace": args.namespace,
            "systemdUnit": args.systemd_unit,
            "driftTimer": args.drift_timer,
            "driftIntervalMinutes": args.drift_interval_minutes,
            "rollbackTestedRef": args.rollback_tested_ref,
        },
        "protectedEvidencePathTemplate": f"operator://{args.target_host}/protected/faz24/i6/<utc-run-id>",
        "redaction": {
            "secretMaterialIncluded": False,
            "rawCommandOutputIncluded": False,
            "rawPacketCaptureIncluded": False,
            "rawAudioIncluded": False,
            "rawTranscriptIncluded": False,
        },
        "boundary": {
            "hostMutationByPackageBuild": False,
            "hostMutationByWrapper": False,
            "clusterObjectMutation": False,
            "wireGuardMutation": False,
            "platformAiMutation": False,
            "productionMutation": False,
        },
    }


def render_readme(args: argparse.Namespace) -> str:
    return f"""# Faz 24 WG-B+ I6 host evidence package

Scope: platform-k8s-gitops#1867. This package helps an operator collect the
metadata-only I6 pod-CIDR to WireGuard MASQ evidence from `{args.target_host}`
using the hardened v2 collector.

## Files

- `{SCRIPT_NAME}`: wrapper that runs the repository collector and verifier.
- `{METADATA_NAME}`: expected defaults and no-leak boundary metadata.
- `{SHA256SUMS_NAME}`: package file hashes.

## Boundary

The package build does not connect to `{args.target_host}`. The wrapper is
read-only evidence collection: it does not change host iptables/nftables,
WireGuard, Kubernetes objects, platform-ai, secrets, or production state. Raw
host command output must remain outside the JSON evidence contract.

## Operator flow

1. Copy or download this package onto `{args.target_host}`.
2. From a clean `platform-k8s-gitops` checkout on `{args.target_host}`, run:

```bash
bash /path/to/{SCRIPT_NAME}
```

Optional overrides:

```bash
OUT=/tmp/wg-bplus-i6-masq-evidence.json \\
PROTECTED_EVIDENCE_PATH=operator://{args.target_host}/protected/faz24/i6/20260712T060000Z \\
bash /path/to/{SCRIPT_NAME}
```

3. If the verifier prints `PASS`, ingest the exact JSON with
   `faz24-wg-bplus-i6-masq-evidence-ingest.yml`.

Acceptance remains pending until the GitHub ingest workflow returns PASS and
#1867 receives reviewed evidence. This package does not prove direct-STT
Functional, I3 management audit, app-mTLS, or production cutover.
"""


def write_sha256sums(output_dir: Path) -> None:
    lines = []
    for path in sorted(output_dir.iterdir(), key=lambda item: item.name):
        if path.name == SHA256SUMS_NAME or not path.is_file():
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.name}")
    (output_dir / SHA256SUMS_NAME).write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_package(args: argparse.Namespace) -> None:
    validate_args(args)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    wrapper = output_dir / SCRIPT_NAME
    wrapper.write_text(render_wrapper(args), encoding="utf-8")
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    (output_dir / METADATA_NAME).write_text(
        json.dumps(metadata(args), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / README_NAME).write_text(render_readme(args), encoding="utf-8")
    write_sha256sums(output_dir)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--target-host", default="aiserver")
    parser.add_argument("--cluster-cidr", required=True)
    parser.add_argument("--service-cidr", default="")
    parser.add_argument("--wg-interface", default="auto")
    parser.add_argument("--peer-host", default="10.99.0.2")
    parser.add_argument("--peer-port", type=int, default=8243)
    parser.add_argument("--wg-node", default="k3d-test-server-0")
    parser.add_argument("--docker-network", default="platform-test-net")
    parser.add_argument("--probe-attempts", type=int, default=3)
    parser.add_argument("--installed-host-rule-script", default="")
    parser.add_argument("--kube-context", default="k3d-test")
    parser.add_argument("--namespace", default="platform-test")
    parser.add_argument("--systemd-unit", default="k3d-wg-masq.service")
    parser.add_argument("--drift-timer", default="k3d-wg-masq.timer")
    parser.add_argument("--drift-interval-minutes", type=int, default=5)
    parser.add_argument("--rollback-tested-ref", default="rollback/k3d-wg-masq-dry-run.json")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    build_package(args)
    print(f"status=pass packageDir={args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
