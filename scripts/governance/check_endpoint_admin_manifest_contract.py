#!/usr/bin/env python3
"""
ADR-0012-EA DD-EA-1 — Manifest Contract Drift Gate.

Codex 019ded8d AGREE plan-time consensus (Session 37, 2026-05-03):
endpoint-admin-service kustomize render bytes baseline + sha256 hash compare.
PR sonrası base/overlay manifest değişikliği render hash'i invalidate eder;
yeni baseline + Codex consensus gerek.

Scope:
- kustomize/base/apps/endpoint-admin-service (lab tier base render)
- kustomize/overlays/test/apps/endpoint-admin-service (test reconcile sonrası)
- kustomize/overlays/prod/apps/endpoint-admin-service (prod reconcile sonrası, 22.2+)

Şu an 22.1.3 lab reconcile öncesi — sadece base render baseline. Overlay scope
test+prod reconcile'da ayrı PR olarak eklenir.

Usage:
  python3 scripts/governance/check_endpoint_admin_manifest_contract.py [options]

Options:
  --verbose                Detailed log
  --json                   Structured JSON output
  --update-baseline        Compute current hash + write baseline file (drift fix)
  --baseline-path PATH     Override baseline file (default:
                           tests/governance/fixtures/dd-ea-1-endpoint-admin-base.sha256)
  --kustomize-path PATH    Override kustomize source (default:
                           kustomize/base/apps/endpoint-admin-service)
  --kubectl-bin BIN        Override kubectl binary (default: kubectl)
  --repo-root PATH         Repo root (default: script grand-parent)

Exit codes:
  0 = render bytes match baseline
  1 = drift detected
  2 = invocation error (kubectl missing, kustomize parse error)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="ADR-0012-EA DD-EA-1 — Manifest Contract Drift Gate",
    )
    parser.add_argument("--verbose", action="store_true", help="Detailed log")
    parser.add_argument("--json", dest="json_output", action="store_true",
                        help="Structured JSON output")
    parser.add_argument("--update-baseline", action="store_true",
                        help="Write current hash as new baseline")
    parser.add_argument(
        "--baseline-path",
        default="tests/governance/fixtures/dd-ea-1-endpoint-admin-base.sha256",
    )
    parser.add_argument(
        "--kustomize-path",
        default="kustomize/base/apps/endpoint-admin-service",
    )
    parser.add_argument("--kubectl-bin", default="kubectl")
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parent.parent.parent),
    )
    return parser.parse_args()


def render_kustomize(
    repo_root: Path, kustomize_path: str, kubectl_bin: str
) -> tuple[bytes | None, str | None]:
    """Run kubectl kustomize, return (render_bytes, error_msg)."""
    if not shutil.which(kubectl_bin):
        return None, f"kubectl binary not found: {kubectl_bin}"
    target = repo_root / kustomize_path
    if not target.exists():
        return None, f"kustomize source not found: {target}"
    try:
        result = subprocess.run(
            [kubectl_bin, "kustomize", str(target)],
            capture_output=True,
            text=False,  # bytes mode for hash stability
            check=True,
        )
        return result.stdout, None
    except subprocess.CalledProcessError as exc:
        return None, f"kustomize failed: {exc.stderr.decode(errors='replace')[:300]}"


def compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_baseline(path: Path) -> str | None:
    if not path.exists():
        return None
    return path.read_text().strip()


def write_baseline(path: Path, hash_value: str, kustomize_path: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (
        "# DD-EA-1 baseline (kustomize render bytes sha256)\n"
        f"# Source: {kustomize_path}\n"
        "# Update: python3 scripts/governance/check_endpoint_admin_manifest_contract.py --update-baseline\n"
        f"{hash_value}\n"
    )
    path.write_text(content)


def main() -> int:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    baseline_path = repo_root / args.baseline_path

    render_bytes, render_err = render_kustomize(
        repo_root, args.kustomize_path, args.kubectl_bin
    )
    if render_err is not None:
        if args.json_output:
            print(json.dumps({
                "check": "DD-EA-1",
                "verdict": "error",
                "error": render_err,
            }, indent=2))
        else:
            print(f"DD-EA-1 — invocation error: {render_err}")
        return 2

    assert render_bytes is not None  # type guard
    actual_hash = compute_sha256(render_bytes)

    if args.update_baseline:
        write_baseline(baseline_path, actual_hash, args.kustomize_path)
        msg = f"DD-EA-1 baseline updated: {baseline_path} → {actual_hash[:16]}..."
        if args.verbose:
            print(msg)
        return 0

    expected_hash = read_baseline(baseline_path)
    expected_clean = (
        expected_hash.split("\n")[-1].strip()
        if expected_hash else None
    )

    drift = expected_clean is not None and actual_hash != expected_clean
    missing_baseline = expected_clean is None

    if args.json_output:
        print(json.dumps({
            "check": "DD-EA-1",
            "scope": "endpoint-admin-service kustomize render bytes",
            "kustomize_path": args.kustomize_path,
            "actual_hash": actual_hash,
            "expected_hash": expected_clean,
            "verdict": (
                "missing-baseline" if missing_baseline
                else "drift" if drift
                else "pass"
            ),
        }, indent=2))
    else:
        print(f"DD-EA-1 — Manifest contract drift gate (endpoint-admin-service)")
        print(f"  Source: {args.kustomize_path}")
        print(f"  Actual hash:   {actual_hash}")
        print(f"  Expected hash: {expected_clean or '(missing baseline)'}")
        if missing_baseline:
            print(
                "  ⚠ Baseline missing. Run with --update-baseline to "
                "establish initial hash."
            )
            return 2
        if drift:
            print("  ✗ DRIFT DETECTED — render bytes diverge from baseline")
            print("    Update baseline if intentional:")
            print(
                "    python3 scripts/governance/check_endpoint_admin_manifest_contract.py "
                "--update-baseline"
            )
        else:
            print("  ✓ Render bytes match baseline")

    if missing_baseline:
        return 2
    if drift:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
