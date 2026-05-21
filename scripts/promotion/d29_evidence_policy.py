#!/usr/bin/env python3
"""
scripts/promotion/d29_evidence_policy.py

Shared D29 evidence policy helper — invoked by both:
  - gate-evidence-check.py (PR gate that BLOCKS prod promotion)
  - ledger-mark-verified.sh (post-smoke marker that updates promotion.<env>.verified_at)

PROBLEM (live incident, 2026-05-21):
  ledger-mark-verified.sh enforced a blanket strict NON_GREEN tier check that
  pre-rejected every (service, digest) pair when ANY tier in the smoke report
  was non-GREEN. Frontend prod-variant smoke (ADR-0022) intrinsically emits
  d29_zanzibar=AMBER because the SPA has no own JWT decoder / OpenFGA plane.
  The blanket rejection forced operators to hand-author the ledger entry
  (see PR #919) on every frontend prod promotion.

  Meanwhile gate-evidence-check.py — the AUTHORITATIVE policy that blocks PR
  merge — already implements the correct nuance: services.yaml entries with
  jwt_validates=false (frontend, auth-service, openfga) accept GREEN OR AMBER
  for the zanzibar tier; jwt_validates=true services (default) require GREEN.

FIX (this helper):
  Extract that nuanced policy into a shared module so the marker applies
  the same rule the gate applies. AMBER on d29_zanzibar is OK iff the
  service is jwt_validates=false in docs/operations/services.yaml.
  d29_up and d29_functional remain strict GREEN-required for every service.

USAGE:
  # As a library (preferred for in-process callers like gate-evidence-check.py
  # in a future refactor):
  from d29_evidence_policy import load_jwt_validates_map, check_tiers
  m = load_jwt_validates_map(repo_root)
  ok, reason = check_tiers("frontend", report["tiers"], m)

  # As a CLI (invoked by bash, e.g. ledger-mark-verified.sh):
  python3 scripts/promotion/d29_evidence_policy.py check-tiers \
    --service frontend --report /tmp/smoke-report.json
  # exit 0 = pass policy (mark verified)
  # exit 1 = fail policy (skip with reason on stderr)
  # exit 2 = setup error (services.yaml missing, malformed report, etc.)

DESIGN NOTES:
  - check_tiers() returns (bool, str). bool True = pass, False = fail.
    The string is a human-readable reason for logging/audit.
  - require_verified_at is INTENTIONALLY NOT a parameter on check_tiers().
    The tiers object does not carry verified_at — that field lives on the
    ledger entry's promotion.<env> block. gate-evidence-check.py's
    check_evidence() applies the verified_at check as an ENTRY-level
    layer on top of check_tiers() (see PR #936 — FU-Gate-Refactor).
  - Default policy on missing service: jwt_validates=True (strict). Safer
    to fail-closed than silently accept AMBER on an unknown service.

HISTORY:
  - 2026-05-21 PR #922 (DiD-3) — initial extraction; ledger-mark-verified.sh
    invokes via CLI (`check-tiers` subcommand). gate-evidence-check.py kept
    its own inline copy to limit blast radius.
  - 2026-05-21 PR #936 (FU-Gate-Refactor) — gate-evidence-check.py now also
    imports and delegates to this helper. Single source of truth for D29
    tier policy semantics; both the PR-blocking gate and the post-smoke
    marker apply identical rules.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


# Anchor: this file lives at scripts/promotion/<file>; repo root is two levels up.
_DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[2]


def _resolve_repo_root(explicit: str | None = None) -> Path:
    """Resolve the gitops repo root from (priority order):
      1. explicit argument (CLI --repo-root)
      2. PLATFORM_GITOPS_REPO env var
      3. derived from this file's location

    Returns Path. Does NOT verify it exists — caller checks services.yaml.
    """
    import os

    if explicit:
        return Path(explicit).resolve()
    env = os.environ.get("PLATFORM_GITOPS_REPO")
    if env:
        return Path(env).resolve()
    return _DEFAULT_REPO_ROOT


def load_jwt_validates_map(repo_root: Path | None = None) -> dict[str, bool]:
    """Read docs/operations/services.yaml and return {service: jwt_validates}.

    Returns empty dict if catalog is missing/unparseable/PyYAML absent.
    Empty dict means callers MUST default to strict (jwt_validates=True)
    for every service — never silently relax policy.
    """
    root = repo_root or _DEFAULT_REPO_ROOT
    catalog_path = root / "docs" / "operations" / "services.yaml"
    if not catalog_path.exists():
        return {}

    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        return {}

    try:
        catalog = yaml.safe_load(catalog_path.read_text()) or {}
    except yaml.YAMLError:
        return {}

    out: dict[str, bool] = {}
    for svc in catalog.get("services", []) or []:
        name = svc.get("name")
        if not name:
            continue
        # Default jwt_validates=True if the field is absent — same as
        # gate-evidence-check.py's load_zanzibar_required_services().
        out[name] = bool(svc.get("jwt_validates", True))
    return out


def check_tiers(
    service: str,
    tiers: dict,
    jwt_validates_map: dict[str, bool],
) -> tuple[bool, str]:
    """Apply D29 tier policy for a single (service, tiers) pair.

    Rules:
      - d29_up MUST be GREEN for every service.
      - d29_functional MUST be GREEN for every service.
      - d29_zanzibar: GREEN required if service.jwt_validates=True (default);
        GREEN or AMBER acceptable if service.jwt_validates=False.

    Args:
      service: service name (matches services.yaml entry).
      tiers: dict-shaped tiers block from smoke report (.tiers in the JSON).
              Each tier key (d29_up, d29_functional, d29_zanzibar) must have
              a sub-dict with .status field.
      jwt_validates_map: result of load_jwt_validates_map().

    Returns:
      (ok, reason) tuple.
      ok=True means the entry MAY be marked verified per policy.
      ok=False means skip; reason is a human-readable explanation.
    """
    if not isinstance(tiers, dict):
        return False, "report.tiers is not a dict (malformed report)"

    def _status(tier_key: str) -> str:
        block = tiers.get(tier_key)
        if not isinstance(block, dict):
            return "MISSING"
        return block.get("status", "MISSING") or "MISSING"

    up_status = _status("d29_up")
    fn_status = _status("d29_functional")
    zb_status = _status("d29_zanzibar")

    if up_status != "GREEN":
        return False, f"d29_up status={up_status} (need GREEN, strict for every service)"
    if fn_status != "GREEN":
        return False, (
            f"d29_functional status={fn_status} (need GREEN, strict for every service)"
        )

    # Default jwt_validates=True (strict) if service is missing from catalog.
    # This is the safer fail-closed direction — unknown services don't get
    # auto-relaxed policy.
    requires_zanzibar = jwt_validates_map.get(service, True)

    if requires_zanzibar:
        if zb_status != "GREEN":
            return False, (
                f"d29_zanzibar status={zb_status} "
                f"(service '{service}' is Zanzibar-required per services.yaml, need GREEN)"
            )
        return True, (
            f"all tiers GREEN (service '{service}' zanzibar policy: GREEN-required)"
        )
    else:
        if zb_status not in ("GREEN", "AMBER"):
            return False, (
                f"d29_zanzibar status={zb_status} "
                f"(service '{service}' jwt_validates=false, accept GREEN or AMBER)"
            )
        return True, (
            f"d29_up=GREEN d29_functional=GREEN d29_zanzibar={zb_status} "
            f"(service '{service}' zanzibar policy: GREEN-or-AMBER)"
        )


def _cmd_check_tiers(args: argparse.Namespace) -> int:
    """CLI entry: check tiers from a smoke-report JSON file.

    Exit codes:
      0 = policy pass (mark verified)
      1 = policy fail (skip with reason on stderr)
      2 = setup error (missing files, malformed JSON, no catalog)
    """
    report_path = Path(args.report)
    if not report_path.exists():
        print(f"ERR: smoke report not found: {report_path}", file=sys.stderr)
        return 2

    try:
        report = json.loads(report_path.read_text())
    except json.JSONDecodeError as e:
        print(f"ERR: smoke report is not valid JSON: {e}", file=sys.stderr)
        return 2

    tiers = report.get("tiers")
    if tiers is None:
        print("ERR: smoke report has no .tiers field", file=sys.stderr)
        return 2

    repo_root = _resolve_repo_root(args.repo_root)
    jwt_map = load_jwt_validates_map(repo_root)
    # Empty map (catalog missing / PyYAML absent) → strict-everywhere default.
    # That is the existing gate-evidence-check.py behavior.

    ok, reason = check_tiers(args.service, tiers, jwt_map)
    # Print reason to stderr so callers can capture it without polluting
    # stdout (which CI / shell pipelines may consume as data).
    print(f"[d29-policy] service={args.service} ok={ok}: {reason}", file=sys.stderr)
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Shared D29 evidence policy (gate + marker)."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_check = sub.add_parser(
        "check-tiers",
        help="Check tier policy for a (service, smoke report) pair. "
        "Exit 0=pass, 1=fail (skip), 2=setup error.",
    )
    p_check.add_argument("--service", required=True, help="Service name (per services.yaml).")
    p_check.add_argument(
        "--report",
        required=True,
        help="Path to smoke-report JSON (with .tiers d29_up/d29_functional/d29_zanzibar).",
    )
    p_check.add_argument(
        "--repo-root",
        default=None,
        help="Explicit gitops repo root (overrides PLATFORM_GITOPS_REPO env / file-relative default).",
    )
    p_check.set_defaults(func=_cmd_check_tiers)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
