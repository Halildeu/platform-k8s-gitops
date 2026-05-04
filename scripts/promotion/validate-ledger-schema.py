#!/usr/bin/env python3
"""
scripts/promotion/validate-ledger-schema.py

Codex P0 #2 — promotion ledger schema validator.

Validates `release-candidates/<repo>/<sha>.json` files against
`schema/promotion-ledger-v1.schema.json`. Run in CI on every PR that
touches release-candidates/**.

Cross-checks:
  1. Schema conformance (jsonschema)
  2. File path matches manifest content (path/<repo>/<sha>.json must
     match repo + git_sha fields)
  3. Service name matches services.yaml catalog (no stale references)
  4. Image digest format consistent with @sha256: pattern

Usage:
  python3 validate-ledger-schema.py                # validate all under release-candidates/
  python3 validate-ledger-schema.py <file>         # single file
  python3 validate-ledger-schema.py --pr-only      # only files changed vs origin/main

Exit codes:
  0 — all valid
  1 — at least 1 schema or cross-check violation
  2 — tool/setup error
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "schema" / "promotion-ledger-v1.schema.json"
LEDGER_DIR = REPO_ROOT / "release-candidates"
CATALOG_PATH = REPO_ROOT / "docs" / "operations" / "services.yaml"


def load_schema() -> dict[str, Any]:
    if not SCHEMA_PATH.exists():
        print(f"ERR: schema not found: {SCHEMA_PATH}", file=sys.stderr)
        sys.exit(2)
    return json.loads(SCHEMA_PATH.read_text())


def load_catalog_services() -> set[str]:
    """Return set of valid service names from services.yaml (any environment status)."""
    try:
        import yaml
    except ImportError:
        print("ERR: PyYAML required (pip install pyyaml)", file=sys.stderr)
        sys.exit(2)

    if not CATALOG_PATH.exists():
        print(f"WARN: catalog not found: {CATALOG_PATH} — skipping service name cross-check")
        return set()

    catalog = yaml.safe_load(CATALOG_PATH.read_text())
    return {svc["name"] for svc in catalog.get("services", []) if "name" in svc}


def validate_one(path: Path, schema: dict[str, Any], catalog_services: set[str]) -> list[str]:
    """Return list of error messages; empty list = OK."""
    errors: list[str] = []

    # Parse JSON
    try:
        entry = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        return [f"{path}: invalid JSON — {e}"]

    # Schema validation
    try:
        from jsonschema import Draft202012Validator
        validator = Draft202012Validator(schema)
        for err in validator.iter_errors(entry):
            loc = ".".join(str(p) for p in err.absolute_path) or "<root>"
            errors.append(f"{path}: schema [{loc}] {err.message}")
    except ImportError:
        print("ERR: jsonschema required (pip install jsonschema)", file=sys.stderr)
        sys.exit(2)

    if errors:
        return errors

    # Cross-check 1: file path matches manifest content (only if under release-candidates/)
    try:
        rel_path = path.relative_to(LEDGER_DIR)
        in_ledger_dir = True
    except ValueError:
        # Test fixtures or other locations — skip path-based cross-check
        in_ledger_dir = False

    if in_ledger_dir:
        if len(rel_path.parts) != 2:
            errors.append(f"{path}: layout violation — expected release-candidates/<repo>/<sha>.json")
        else:
            path_repo, path_filename = rel_path.parts
            path_sha = path_filename.removesuffix(".json")

            if entry.get("repo") != path_repo:
                errors.append(
                    f"{path}: repo field='{entry.get('repo')}' but path implies repo='{path_repo}'"
                )
            if entry.get("git_sha") != path_sha:
                errors.append(
                    f"{path}: git_sha field='{entry.get('git_sha')}' but filename implies sha='{path_sha}'"
                )

    # Cross-check 2: service name in catalog (warn, don't fail — new services may be added)
    service = entry.get("service")
    if catalog_services and service and service not in catalog_services:
        errors.append(
            f"{path}: service='{service}' not in services.yaml catalog "
            f"(known: {sorted(catalog_services)[:5]}...)"
        )

    # Cross-check 3: image digest sanity (must be sha256 + 64 hex)
    image = entry.get("image", {})
    digest = image.get("digest", "")
    if not re.match(r"^sha256:[a-f0-9]{64}$", digest):
        errors.append(f"{path}: image.digest='{digest}' not sha256 64-hex format")

    # Cross-check 4: short-sha consistent with full sha
    short = entry.get("git_short_sha", "")
    full = entry.get("git_sha", "")
    if short and full and not full.startswith(short):
        errors.append(f"{path}: git_short_sha='{short}' is not prefix of git_sha='{full}'")

    # Cross-check 5: image.tag consistency with short-sha
    tag = image.get("tag", "")
    if short and tag and not tag.endswith(short[:7]) and not tag == f"sha-{short[:7]}":
        # tag is "sha-<7-12 hex>"
        m = re.match(r"^sha-([a-f0-9]{7,12})$", tag)
        if m:
            tag_sha = m.group(1)
            if not full.startswith(tag_sha):
                errors.append(
                    f"{path}: image.tag='{tag}' embeds sha that doesn't match git_sha"
                )

    return errors


def files_changed_vs_main() -> list[Path]:
    """Return release-candidates/ files changed vs origin/main."""
    try:
        out = subprocess.check_output(
            ["git", "diff", "--name-only", "origin/main...HEAD", "--", "release-candidates/"],
            cwd=REPO_ROOT,
            text=True,
        )
    except subprocess.CalledProcessError:
        out = ""
    return [REPO_ROOT / line for line in out.strip().split("\n") if line and line.endswith(".json")]


def find_all_ledger_files() -> list[Path]:
    if not LEDGER_DIR.exists():
        return []
    return sorted(p for p in LEDGER_DIR.rglob("*.json") if p.is_file())


def main(argv: list[str]) -> int:
    schema = load_schema()
    catalog = load_catalog_services()

    if len(argv) > 1 and argv[1] == "--pr-only":
        files = files_changed_vs_main()
        print(f"[pr-only] {len(files)} ledger file(s) changed vs origin/main")
    elif len(argv) > 1:
        files = [Path(p).resolve() for p in argv[1:]]
    else:
        files = find_all_ledger_files()
        print(f"[full] validating {len(files)} ledger file(s)")

    if not files:
        print("[OK] no ledger files to validate")
        return 0

    total_errors = 0
    for f in files:
        if not f.exists():
            print(f"[SKIP] {f} not found")
            continue
        if f.name.startswith(".") or f.name == "README.md":
            continue
        errors = validate_one(f, schema, catalog)
        if errors:
            for e in errors:
                print(f"[FAIL] {e}")
            total_errors += len(errors)
        else:
            print(f"[OK]   {f.relative_to(REPO_ROOT)}")

    print()
    if total_errors > 0:
        print(f"=== Total: {total_errors} violation(s) across {len(files)} file(s) ===")
        return 1
    print(f"=== All {len(files)} ledger file(s) valid ===")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
