#!/usr/bin/env python3
"""
scripts/promotion/gate-evidence-check.py

Codex Sprint A P0 Item 3 — D29 evidence enforcement gate.

When a PR touches `kustomize/overlays/prod/**` and changes one or more image
digests, this gate REQUIRES that each new digest has a corresponding
`release-candidates/<repo>/<sha>.json` ledger entry with:

    promotion.test.smoke_evidence.d29_up.status == "GREEN"
    promotion.test.smoke_evidence.d29_functional.status == "GREEN"
    promotion.test.smoke_evidence.d29_zanzibar.status in ("GREEN", "AMBER")

Without verified test evidence, the prod promotion PR is BLOCKED at CI.

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
from pathlib import Path
from typing import Iterator

REPO_ROOT = Path(__file__).resolve().parents[2]
LEDGER_DIR = REPO_ROOT / "release-candidates"
PROD_OVERLAY = REPO_ROOT / "kustomize" / "overlays" / "prod"

DIGEST_PATTERN = re.compile(r"@(sha256:[a-f0-9]{64})")


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
    return set(DIGEST_PATTERN.findall(render))


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


def check_evidence(entry: dict) -> tuple[bool, str]:
    """Return (verified, reason). verified=True if D29 GREEN."""
    test_block = entry.get("promotion", {}).get("test", {})
    smoke = test_block.get("smoke_evidence")

    if not smoke:
        return False, "promotion.test.smoke_evidence is null (smoke not run yet)"

    up = smoke.get("d29_up", {}).get("status")
    fn = smoke.get("d29_functional", {}).get("status")
    zb = smoke.get("d29_zanzibar", {}).get("status")

    if up != "GREEN":
        return False, f"d29_up status={up} (need GREEN)"
    if fn != "GREEN":
        return False, f"d29_functional status={fn} (need GREEN)"
    if zb not in ("GREEN", "AMBER"):
        return False, f"d29_zanzibar status={zb} (need GREEN or AMBER)"

    verified_at = test_block.get("verified_at")
    if not verified_at:
        return False, "verified_at not set (incomplete promotion record)"

    return True, f"verified at {verified_at}"


def main() -> int:
    parser = argparse.ArgumentParser(description="D29 evidence gate for prod promotions")
    parser.add_argument("--base", default="origin/main", help="Base ref")
    parser.add_argument("--head", default="HEAD", help="Head ref")
    args = parser.parse_args()

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

    # Step 3: For each new digest, require D29-GREEN ledger entry
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
        verified, reason = check_evidence(entry)

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
