#!/usr/bin/env python3
"""
ADR-0012-EA DD-EA-5 — ESO Secret Path Allowlist Gate.

Codex 019ded8d AGREE plan-time consensus (Session 37, 2026-05-03):
endpoint-admin-service ExternalSecret manifest'lerinde Vault path scope
enforcement. Sadece ADR-0012-EA §"ESO secret path scope" altında listelenen
keyler kabul edilir; başka path referansı → drift.

Kapsamlı path allowlist (ADR-0012-EA §111-117):
- kv/platform/endpoint-admin/oidc-client-secret
- kv/platform/endpoint-admin/audit-log-dsn
- kv/platform/endpoint-admin/ad-bind-credentials
- kv/platform/endpoint-admin/entra-app-credentials
- kv/platform/endpoint-admin/internal-api-key
- kv/platform/endpoint-admin/agent-enrollment-secret

Note: code signing key (Authenticode trusted signing) bu listenin DIŞINDA —
supply-chain build-time pipeline kapsamı (ESO runtime secret olarak yok).

Scope:
- Sadece endpoint-admin-service ExternalSecret manifest'leri denetlenir.
- Diğer service'ler için ESO scope (auth, user, permission, schema, vb.)
  kendi DD-X gate'leri olabilir (gelecek scope).

Usage:
  python3 scripts/governance/check_eso_secret_allowlist.py [options]

Options:
  --verbose              Detailed per-manifest log
  --json                 Structured JSON output (CI artifact friendly)
  --manifest-glob GLOB   Manifest file glob (default:
                         kustomize/**/endpoint-admin-service/**/*.yaml +
                         kustomize/**/endpoint-admin-service/**/externalsecret*.yaml)
  --fixture PATH         Override fixture path (single file mode for test)

Exit codes:
  0 = all ExternalSecret manifest paths allowlisted
  1 = drift detected (one or more keys outside allowlist)
  2 = invocation error (file missing, parse error)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

# ADR-0012-EA §111-117 ESO secret path allowlist (endpoint-admin-service scope).
# Updates require ADR-0012-EA amendment + Codex consensus (DD-EA-5 boundary).
ALLOWED_KEYS: frozenset[str] = frozenset(
    {
        "kv/platform/endpoint-admin/oidc-client-secret",
        "kv/platform/endpoint-admin/audit-log-dsn",
        "kv/platform/endpoint-admin/ad-bind-credentials",
        "kv/platform/endpoint-admin/entra-app-credentials",
        "kv/platform/endpoint-admin/internal-api-key",
        "kv/platform/endpoint-admin/agent-enrollment-secret",
    }
)

# Strict allowlist enforcement: yeni key eklenmek için ADR-0012-EA §"ESO secret
# path scope" amendment + DD-EA-5 ALLOWED_KEYS güncelleme + Codex consensus.
# Wildcard prefix YASAK — code-signing-key gibi supply-chain pipeline secret'ları
# ESO runtime'da kabul edilmez (build-time CI sign, public key reference only).


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="ADR-0012-EA DD-EA-5 — ESO Secret Path Allowlist Gate",
    )
    parser.add_argument("--verbose", action="store_true", help="Detailed log")
    parser.add_argument("--json", dest="json_output", action="store_true",
                        help="Structured JSON output")
    parser.add_argument(
        "--manifest-glob",
        default=None,
        help="Manifest file glob (default endpoint-admin-service/**/*.yaml)",
    )
    parser.add_argument(
        "--fixture",
        default=None,
        help="Single fixture file (test mode)",
    )
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parent.parent.parent),
        help="Repo root path (default: script grand-parent)",
    )
    return parser.parse_args()


def find_manifests(repo_root: Path, glob_override: str | None) -> list[Path]:
    """Find ExternalSecret manifest candidates for endpoint-admin-service."""
    if glob_override:
        return sorted(repo_root.glob(glob_override))

    candidates: set[Path] = set()
    # Base kustomize endpoint-admin-service
    base = repo_root / "kustomize" / "base" / "apps" / "endpoint-admin-service"
    if base.exists():
        candidates.update(base.rglob("*.yaml"))
    # Overlay endpoint-admin-service (test/prod)
    for overlay in ("test", "prod"):
        overlay_path = (
            repo_root / "kustomize" / "overlays" / overlay / "apps"
            / "endpoint-admin-service"
        )
        if overlay_path.exists():
            candidates.update(overlay_path.rglob("*.yaml"))
        # Overlay-specific ESO directories (e.g. overlays/test/eso/endpoint-admin-*)
        eso_path = repo_root / "kustomize" / "overlays" / overlay / "eso"
        if eso_path.exists():
            for f in eso_path.rglob("*.yaml"):
                if "endpoint-admin" in f.name:
                    candidates.add(f)
    return sorted(candidates)


def extract_remote_keys(doc: dict[str, Any]) -> list[str]:
    """Extract Vault remoteRef.key values from ExternalSecret spec."""
    keys: list[str] = []
    if not isinstance(doc, dict):
        return keys
    if doc.get("kind") != "ExternalSecret":
        return keys
    spec = doc.get("spec", {})
    # data[].remoteRef.key
    for entry in spec.get("data", []) or []:
        if isinstance(entry, dict):
            rref = entry.get("remoteRef", {})
            key = rref.get("key")
            if key:
                keys.append(key)
    # dataFrom[].extract.key
    for entry in spec.get("dataFrom", []) or []:
        if isinstance(entry, dict):
            extract = entry.get("extract", {})
            key = extract.get("key")
            if key:
                keys.append(key)
    return keys


def check_manifest(path: Path) -> tuple[list[str], list[str], list[str]]:
    """Return (allowed_keys, violation_keys, parse_errors) for a manifest."""
    allowed: list[str] = []
    violation: list[str] = []
    errors: list[str] = []
    try:
        with path.open() as f:
            docs = list(yaml.safe_load_all(f))
    except Exception as exc:
        errors.append(f"{path}: parse error — {exc}")
        return allowed, violation, errors

    for doc in docs:
        if not isinstance(doc, dict):
            continue
        if doc.get("kind") != "ExternalSecret":
            continue
        keys = extract_remote_keys(doc)
        for key in keys:
            # Strict allowlist: tam eşleşme. Wildcard prefix yasak (supply-chain
            # secret'ları gibi exception case'leri yakalamak için).
            if key in ALLOWED_KEYS:
                allowed.append(f"{path}: {key}")
            else:
                violation.append(f"{path}: {key}")
    return allowed, violation, errors


def main() -> int:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()

    if args.fixture:
        manifests = [Path(args.fixture).resolve()]
    else:
        manifests = find_manifests(repo_root, args.manifest_glob)

    if args.verbose:
        print(f"[DD-EA-5] repo_root: {repo_root}", file=sys.stderr)
        print(f"[DD-EA-5] manifests scanned: {len(manifests)}", file=sys.stderr)
        for m in manifests:
            print(f"  - {m.relative_to(repo_root) if repo_root in m.parents else m}",
                  file=sys.stderr)

    all_allowed: list[str] = []
    all_violations: list[str] = []
    all_errors: list[str] = []
    for m in manifests:
        allowed, violation, errors = check_manifest(m)
        all_allowed.extend(allowed)
        all_violations.extend(violation)
        all_errors.extend(errors)

    if args.json_output:
        result = {
            "check": "DD-EA-5",
            "scope": "endpoint-admin-service ESO secret path allowlist",
            "manifests_scanned": len(manifests),
            "allowed_keys": all_allowed,
            "violation_keys": all_violations,
            "parse_errors": all_errors,
            "verdict": (
                "pass" if not all_violations and not all_errors else "fail"
            ),
        }
        print(json.dumps(result, indent=2))
    else:
        print(f"DD-EA-5 — ESO secret path allowlist (endpoint-admin-service)")
        print(f"  Manifests scanned: {len(manifests)}")
        print(f"  Allowed keys: {len(all_allowed)}")
        if args.verbose:
            for entry in all_allowed:
                print(f"    ✓ {entry}")
        if all_violations:
            print(f"  ✗ Violations ({len(all_violations)}):")
            for entry in all_violations:
                print(f"    {entry}")
        if all_errors:
            print(f"  ⚠ Parse errors ({len(all_errors)}):")
            for entry in all_errors:
                print(f"    {entry}")
        verdict = "PASS" if not all_violations and not all_errors else "FAIL"
        print(f"  Verdict: {verdict}")

    if all_errors:
        return 2
    if all_violations:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
