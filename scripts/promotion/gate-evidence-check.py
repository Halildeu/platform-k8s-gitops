#!/usr/bin/env python3
"""
scripts/promotion/gate-evidence-check.py

Codex Sprint A P0 Item 3 — D29 evidence enforcement gate.
+ Sprint A B0b — Zanzibar AMBER policy tightening per Codex retrospective:
  "D30 prod gate'te Zanzibar-ready iddiası verilecekse core/authz-etkileyen
   servislerde AMBER pass olmamalı."

When a PR touches `kustomize/overlays/prod/**` and changes one or more image
digests, this gate REQUIRES that each new digest has a corresponding
`release-candidates/<repo>/<sha>.json` ledger entry with:

    promotion.test.smoke_evidence.d29_up.status == "GREEN"
    promotion.test.smoke_evidence.d29_functional.status == "GREEN"
    promotion.test.smoke_evidence.d29_zanzibar.status:
      - For services with services.yaml jwt_validates=true (default for
        backend Zanzibar consumers): "GREEN" required
      - For services explicitly marked jwt_validates=false in services.yaml
        (legacy core-data-service: gateway-validated, no own JWT decoder):
        "GREEN" or "AMBER" OK

Without verified test evidence (or with AMBER on a Zanzibar-required service),
the prod promotion PR is BLOCKED at CI.

Usage:
  python3 gate-evidence-check.py
    # Reads PR diff vs origin/main, exits 1 if any prod-overlay digest
    # change lacks ledger evidence.

  python3 gate-evidence-check.py --base main --head HEAD
    # Explicit base/head refs.

Exit codes:
  0 — all prod digest changes have D29 evidence (or no prod digest changes)
  1 — at least one digest change lacks ledger evidence
  2 — tool/setup error
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

# FU-Gate-Refactor (2026-05-21) — Closes DiD-3 (PR #922) TODO: the gate's
# previous inline tier-policy logic now delegates to the shared helper
# `scripts/promotion/d29_evidence_policy.py` so the gate and ledger-mark-
# verified.sh apply the exact same policy semantics. The helper lives in
# the same directory; Python adds the script's directory to sys.path[0]
# when invoked via path, so `import d29_evidence_policy` resolves cleanly
# without sys.path manipulation. CI workflow gate-d29-evidence-required.yml
# invokes this script as `python3 scripts/promotion/gate-evidence-check.py`,
# matching the path-invocation expectation.
import d29_evidence_policy  # type: ignore[import-not-found]

REPO_ROOT = Path(__file__).resolve().parents[2]
LEDGER_DIR = REPO_ROOT / "release-candidates"
PROD_OVERLAY = REPO_ROOT / "kustomize" / "overlays" / "prod"

DIGEST_PATTERN = re.compile(r"@(sha256:[a-f0-9]{64})")

# IMAGE_PATTERN captures the full `image: <ref>@sha256:<digest>` line so
# the gate can distinguish promotion-pipeline images (Halildeu canonical
# repos — `ghcr.io/halildeu/platform-*`) from 3rd-party utility images
# (curl, busybox, alpine, etc.) which are NOT built by this org's
# pipeline and therefore have no release-candidates/ ledger entry.
IMAGE_PATTERN = re.compile(r"image:\s*(\S+)@(sha256:[a-f0-9]{64})")

# Image-ref prefixes that require ledger evidence (canonical pipeline).
# Any digest attached to a ref NOT matching one of these prefixes is a
# 3rd-party utility image (curl, alpine, busybox, runner sidecar) which
# is governed by upstream registry, not this repo's promotion ledger.
LEDGER_REQUIRED_PREFIXES = ("ghcr.io/halildeu/platform-",)


def run(cmd: list[str], cwd: Path | None = None) -> str:
    return subprocess.check_output(cmd, cwd=cwd or REPO_ROOT, text=True)


def get_changed_files(base: str, head: str) -> list[Path]:
    try:
        out = run(["git", "diff", "--name-only", f"{base}...{head}"])
    except subprocess.CalledProcessError as e:
        print(f"ERR: git diff failed: {e}", file=sys.stderr)
        sys.exit(2)
    return [REPO_ROOT / line for line in out.strip().split("\n") if line]


def render_overlay(ref: str | None = None) -> str:
    """Render prod overlay at given ref (or HEAD if None) using git show + kustomize."""
    cmd = ["kubectl", "kustomize", str(PROD_OVERLAY)]
    if ref is None:
        return subprocess.check_output(cmd, cwd=REPO_ROOT, text=True)

    # For comparison: checkout overlay at ref, render, restore
    # Simpler: use git ls-tree to enumerate files at ref, but kustomize needs file system
    # Easiest: tar archive + extract + render
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)
        archive = subprocess.check_output(
            ["git", "archive", "--format=tar", ref],
            cwd=REPO_ROOT,
        )
        # extract via tar
        import tarfile, io

        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(tmppath)
        return subprocess.check_output(
            ["kubectl", "kustomize", str(tmppath / "kustomize" / "overlays" / "prod")],
            text=True,
        )


def extract_digests_from_render(render: str) -> set[str]:
    """Return the set of digests for images that the promotion pipeline
    governs (canonical Halildeu/platform-* repos).  3rd-party utility
    images — curl, alpine, busybox, etc. — are NOT promotion-pipeline
    artifacts and DO NOT need a release-candidates/ ledger entry; their
    digest pins are governed by upstream registry hygiene + Renovate-
    style refresh, not by this gate.
    """
    pipeline_digests: set[str] = set()
    for ref, digest in IMAGE_PATTERN.findall(render):
        if any(ref.startswith(p) for p in LEDGER_REQUIRED_PREFIXES):
            pipeline_digests.add(digest)
    return pipeline_digests


def find_ledger_entries_by_digest(digest: str) -> list[Path]:
    """Search release-candidates/ for entries with matching image.digest."""
    if not LEDGER_DIR.exists():
        return []
    matches = []
    for path in LEDGER_DIR.rglob("*.json"):
        if path.name == "README.md":
            continue
        try:
            entry = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        if entry.get("image", {}).get("digest") == digest:
            matches.append(path)
    return matches


def load_zanzibar_required_services() -> dict[str, bool]:
    """Read services.yaml and return {service_name: jwt_validates}.

    FU-Gate-Refactor (2026-05-21) — Thin wrapper that delegates to
    d29_evidence_policy.load_jwt_validates_map(). Kept as a wrapper rather
    than removed so the existing call sites (and any external callers
    that may import from this module) keep working without API churn.

    Used to determine whether AMBER is acceptable for d29_zanzibar status
    (only for services with jwt_validates=false; backend Zanzibar consumers
    need GREEN).
    """
    return d29_evidence_policy.load_jwt_validates_map(REPO_ROOT)


def check_evidence(entry: dict, jwt_validates_map: dict[str, bool]) -> tuple[bool, str]:
    """Return (verified, reason). verified=True if D29 GREEN per service policy.

    FU-Gate-Refactor (2026-05-21) — Tier-policy semantics delegated to
    `d29_evidence_policy.check_tiers()` (the same helper that ledger-mark-
    verified.sh invokes via its CLI). The gate adds two entry-level checks
    on top of the tier policy:
      1. `promotion.test.smoke_evidence` must be non-null (smoke ran)
      2. `promotion.test.verified_at` must be set (record is complete)
    Both are entry-level concerns (not tier-level), so they stay in the
    gate rather than being pushed into the helper.
    """
    test_block = entry.get("promotion", {}).get("test", {})
    smoke = test_block.get("smoke_evidence")
    service = entry.get("service", "")

    if not smoke:
        return False, "promotion.test.smoke_evidence is null (smoke not run yet)"

    # Delegate tier-policy semantics to the shared helper. The helper applies:
    #   - d29_up GREEN required, every service
    #   - d29_functional GREEN required, every service
    #   - d29_zanzibar: GREEN required for services where jwt_validates=true
    #     (default); GREEN or AMBER acceptable for services explicitly
    #     marked jwt_validates=false (frontend SPA, auth-service, openfga).
    ok, tier_reason = d29_evidence_policy.check_tiers(service, smoke, jwt_validates_map)
    if not ok:
        return False, tier_reason

    verified_at = test_block.get("verified_at")
    if not verified_at:
        return False, "verified_at not set (incomplete promotion record)"

    requires_zanzibar = jwt_validates_map.get(service, True)
    return True, (
        f"verified at {verified_at} (zanzibar policy: "
        f"{'GREEN-only' if requires_zanzibar else 'GREEN-or-AMBER'})"
    )


# Codex `019e443d` REVISE absorb (Fix 2): lag scope must be prod-enabled +
# pipeline-owned. third_party (openfga) and prod-deferred (endpoint-admin)
# services are NOT subject to promotion-lag tracking and would otherwise
# generate false signals on first ledger appearance.
_LAG_PIPELINE_REPOS = {"platform-backend", "platform-web"}


def prod_pipeline_services() -> dict[str, dict]:
    """Return {service_name: yaml_entry} for services subject to promotion-
    lag tracking. Filter rules (all must hold):
      - environments.prod == "enabled"
      - third_party is not truthy
      - repo in _LAG_PIPELINE_REPOS (canonical pipeline-owned)

    Empty dict if services.yaml missing/unparseable/yaml lib absent.
    """
    catalog_path = REPO_ROOT / "docs" / "operations" / "services.yaml"
    if not catalog_path.exists():
        return {}
    try:
        import yaml
    except ImportError:
        return {}
    catalog = yaml.safe_load(catalog_path.read_text()) or {}
    out: dict[str, dict] = {}
    for svc in catalog.get("services", []) or []:
        name = svc.get("name")
        if not name:
            continue
        if svc.get("third_party"):
            continue
        envs = svc.get("environments") or {}
        if envs.get("prod") != "enabled":
            continue
        if svc.get("repo") not in _LAG_PIPELINE_REPOS:
            continue
        out[name] = svc
    return out


# Codex `019e443d` REVISE absorb (Fix 3, non-blocker): map service → digest
# from prod render so the lag check uses per-service identity, not a global
# digest set (digest reuse across services is unlikely but the gate's
# semantics are service-bound; explicit map removes the false-pass surface).
_SERVICE_IMAGE_PATTERN = re.compile(
    r"image:\s*ghcr\.io/halildeu/platform-(?:backend|web)-([a-z0-9-]+)@(sha256:[a-f0-9]{64})"
)


def extract_service_digests_from_render(render: str) -> dict[str, str]:
    """Parse a kustomize render → {service_name: digest}. Service name is
    derived from the image ref suffix after the `platform-(backend|web)-`
    prefix. First occurrence wins on duplicates (multi-container case)."""
    out: dict[str, str] = {}
    for name, digest in _SERVICE_IMAGE_PATTERN.findall(render):
        out.setdefault(name, digest)
    return out


def _parse_iso_utc(ts: str) -> datetime | None:
    """Parse an ISO-8601 timestamp (with Z or offset) → aware datetime, or None."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _digest_short(digest: str) -> str:
    """sha256:<64hex> → first 12 hex chars for human display."""
    if digest.startswith("sha256:") and len(digest) >= 19:
        return digest[7:19]
    return digest[:12]


def latest_verified_per_service(jwt_validates_map: dict[str, bool]) -> dict[str, dict]:
    """For each service with a release-candidates/ ledger entry, return the
    LATEST D29-verified record (max verified_at). 'Verified' = check_evidence()
    returns True under the current Zanzibar policy.

    Returns {service: {"path": Path, "entry": dict, "verified_at_dt": datetime,
                       "digest": str}}.
    """
    latest: dict[str, dict] = {}
    if not LEDGER_DIR.exists():
        return latest
    for path in LEDGER_DIR.rglob("*.json"):
        if path.name == "README.md":
            continue
        try:
            entry = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        svc = entry.get("service", "")
        if not svc:
            continue
        verified_at = entry.get("promotion", {}).get("test", {}).get("verified_at")
        v_dt = _parse_iso_utc(verified_at)
        if not v_dt:
            continue
        ok, _ = check_evidence(entry, jwt_validates_map)
        if not ok:
            continue
        digest = entry.get("image", {}).get("digest", "")
        if not digest:
            continue
        current = latest.get(svc)
        if current is None or v_dt > current["verified_at_dt"]:
            latest[svc] = {
                "path": path,
                "entry": entry,
                "verified_at_dt": v_dt,
                "digest": digest,
            }
    return latest


def check_promotion_lag(lag_days: int) -> int:
    """ADR-0023 D5 Guardrail PR-5 — fail-closed gate that detects when a
    test-validated (D29-GREEN) digest has not been promoted to prod for
    longer than ``lag_days``. Prevents prod from silently lagging a
    test-validated generation.

    Logic:
      - Render current prod overlay → set of pipeline digests in prod.
      - For each service tracked in services.yaml, find LATEST D29-verified
        ledger entry (by verified_at).
      - If that digest is NOT in prod overlay AND verified_at older than
        ``lag_days`` ago, flag as lag.

    Exit codes: 0 OK, 1 lag detected, 2 setup error.
    """
    try:
        render = render_overlay()
    except subprocess.CalledProcessError as e:
        print(f"ERR: cannot render prod overlay: {e}", file=sys.stderr)
        return 2

    # Codex `019e443d` Fix 3: per-service digest identity, not global set.
    prod_service_digests = extract_service_digests_from_render(render)

    jwt_validates_map = load_zanzibar_required_services()
    if not jwt_validates_map:
        print(
            "ERR: services.yaml empty or unreadable — lag check cannot identify "
            "tracked services; aborting setup-error",
            file=sys.stderr,
        )
        return 2

    # Codex `019e443d` Fix 2: lag scope is prod-enabled, pipeline-owned,
    # non-third-party. Zanzibar policy map (jwt_validates_map) stays the
    # full catalog so check_evidence() applies the correct Zanzibar rule
    # when filtering verified entries below.
    pipeline_scope = prod_pipeline_services()
    if not pipeline_scope:
        print(
            "ERR: prod_pipeline_services() empty — services.yaml lacks any "
            "prod-enabled pipeline-owned service; cannot run lag check",
            file=sys.stderr,
        )
        return 2

    services = sorted(pipeline_scope.keys())
    latest = latest_verified_per_service(jwt_validates_map)

    cutoff = datetime.now(timezone.utc) - timedelta(days=lag_days)
    now = datetime.now(timezone.utc)

    print(
        f"[INFO] promotion-lag check: lag_days={lag_days}, "
        f"cutoff={cutoff.isoformat()}"
    )
    print(
        f"[INFO] services in lag scope (prod-enabled, pipeline-owned, "
        f"non-third-party): {len(services)}"
    )
    print(
        f"[INFO] prod overlay pipeline service-digests parsed: "
        f"{len(prod_service_digests)}"
    )

    lags: list[tuple[str, str, int, Path]] = []
    no_ledger: list[str] = []

    for svc in services:
        info = latest.get(svc)
        if not info:
            no_ledger.append(svc)
            continue

        digest = info["digest"]
        v_dt = info["verified_at_dt"]
        age = (now - v_dt).days
        rel = info["path"].relative_to(REPO_ROOT)

        prod_digest = prod_service_digests.get(svc)
        if prod_digest == digest:
            print(
                f"[OK]   {svc}: latest verified digest "
                f"{_digest_short(digest)} already in prod (verified {age}d ago)"
            )
            continue

        if v_dt < cutoff:
            print(
                f"[LAG]  {svc}: digest {_digest_short(digest)} verified "
                f"{age}d ago (>{lag_days}d), NOT in prod "
                f"(prod has {_digest_short(prod_digest) if prod_digest else '<none>'}; "
                f"ledger {rel})"
            )
            lags.append((svc, digest, age, info["path"]))
        else:
            print(
                f"[INFO] {svc}: digest {_digest_short(digest)} verified "
                f"{age}d ago, not yet in prod (within {lag_days}d window)"
            )

    if no_ledger:
        # Pipeline-scoped services without ANY D29-verified ledger.
        # Treated as INFO (not failure): new services may not have any
        # ledger yet; D29 evidence gate covers their first prod promotion.
        print(
            f"[INFO] {len(no_ledger)} pipeline service(s) without any "
            f"D29-verified ledger entry (likely never promoted yet): "
            f"{', '.join(no_ledger[:8])}"
            f"{' …' if len(no_ledger) > 8 else ''}"
        )

    print()
    if lags:
        print(
            f"=== {len(lags)} service(s) with promotion lag > {lag_days}d "
            f"— gate FAIL ==="
        )
        for svc, digest, age, rel_path in lags:
            print(
                f"  {svc}: digest={digest} verified={age}d ago "
                f"ledger={rel_path.relative_to(REPO_ROOT)}"
            )
        print()
        print(
            "To unblock: open prod overlay PR bumping these services to the "
            "test-validated digest."
        )
        # Codex `019e443d` Fix 1 absorb: deferral escape hatch removed —
        # there is no implemented parser for "promotion-deferred:" in the
        # ledger schema yet, so the unblock advice promises only the
        # behaviour the gate actually supports. Formal deferral mechanism
        # is a follow-up (Guardrail PR-6 ledger-format work).
        return 1

    print(
        f"=== No promotion lag detected — all D29-verified digests either "
        f"already promoted to prod or within {lag_days}d window ==="
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="D29 evidence gate for prod promotions")
    parser.add_argument("--base", default="origin/main", help="Base ref")
    parser.add_argument("--head", default="HEAD", help="Head ref")
    parser.add_argument(
        "--check-promotion-lag",
        action="store_true",
        help="Run ADR-0023 PR-5 lag check instead of PR digest evidence check "
        "(see check_promotion_lag for semantics).",
    )
    parser.add_argument(
        "--lag-days",
        type=int,
        default=7,
        help="Threshold (days) — D29-verified digest not promoted to prod for "
        "longer than this is flagged as lag (default: 7).",
    )
    args = parser.parse_args()

    if args.check_promotion_lag:
        return check_promotion_lag(args.lag_days)

    # Step 1: Was prod overlay touched in this PR?
    changed = get_changed_files(args.base, args.head)
    prod_overlay_changed = any("kustomize/overlays/prod/" in str(p) for p in changed)

    if not prod_overlay_changed:
        print("[OK] no kustomize/overlays/prod/ changes — gate not applicable")
        return 0

    print(f"[INFO] prod overlay touched; checking digest evidence")

    # Step 2: Compute digest delta (new digests in head not in base)
    try:
        render_head = render_overlay()
    except subprocess.CalledProcessError as e:
        print(f"ERR: cannot render HEAD prod overlay: {e}", file=sys.stderr)
        return 2

    try:
        render_base = render_overlay(args.base)
    except subprocess.CalledProcessError as e:
        print(f"WARN: cannot render base ref ({args.base}) — falling back to HEAD-only check")
        render_base = ""

    head_digests = extract_digests_from_render(render_head)
    base_digests = extract_digests_from_render(render_base)
    new_digests = head_digests - base_digests

    if not new_digests:
        print("[OK] no new image digests in prod overlay vs base — gate satisfied")
        return 0

    print(f"[INFO] {len(new_digests)} new digest(s) in prod overlay:")
    for d in sorted(new_digests):
        print(f"  - {d}")

    # Step 3: For each new digest, require D29-GREEN ledger entry per service policy
    jwt_validates_map = load_zanzibar_required_services()
    if jwt_validates_map:
        zanzibar_required = sorted(s for s, v in jwt_validates_map.items() if v)
        zanzibar_optional = sorted(s for s, v in jwt_validates_map.items() if not v)
        print(f"[POLICY] Zanzibar GREEN required for: {zanzibar_required}")
        if zanzibar_optional:
            print(f"[POLICY] Zanzibar AMBER acceptable for: {zanzibar_optional}")

    fails = 0
    for digest in sorted(new_digests):
        entries = find_ledger_entries_by_digest(digest)
        if not entries:
            print(
                f"[FAIL] {digest}: no release-candidates/ ledger entry found "
                f"(test promotion + D29 smoke must precede prod promotion)"
            )
            fails += 1
            continue

        # Use first match (digest is unique per build)
        entry_path = entries[0]
        entry = json.loads(entry_path.read_text())
        verified, reason = check_evidence(entry, jwt_validates_map)

        if not verified:
            print(f"[FAIL] {digest}: ledger {entry_path.relative_to(REPO_ROOT)} — {reason}")
            fails += 1
        else:
            print(f"[OK]   {digest}: ledger {entry_path.relative_to(REPO_ROOT)} — {reason}")

    print()
    if fails > 0:
        print(f"=== Total: {fails} digest(s) without D29 evidence — prod promotion BLOCKED ===")
        print()
        print("To unblock:")
        print("  1. Promote digest to test cluster first (auto-promotion bot)")
        print("  2. Wait for D29 smoke gate (test-smoke-after-deploy)")
        print("  3. Verify ledger entry's promotion.test.smoke_evidence is GREEN")
        print("  4. Re-run this PR's CI (push empty commit or re-request)")
        return 1

    print(f"=== All {len(new_digests)} prod digest(s) have D29 evidence — gate satisfied ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
