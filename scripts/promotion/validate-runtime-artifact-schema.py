#!/usr/bin/env python3
"""
scripts/promotion/validate-runtime-artifact-schema.py

ADR-0023 Guardrail PR-6 — runtime-artifact ledger schema validator.

Mirrors validate-ledger-schema.py (image ledger validator) but operates on the
non-image artifact ledger at runtime-artifacts/<kind>/<digest>.json.

Validates against schema/runtime-artifact-ledger-v1.schema.json with:
  1. JSON Schema conformance (jsonschema Draft 2020-12 + conditional allOf)
  2. File path matches manifest content:
     runtime-artifacts/<artifact_kind>/<digest>.json   where
     <digest> == artifact_content_digest minus the 'sha256:' prefix
  3. Per-kind format hooks:
     - openfga-model: each non-null promotion[*].model_id_env must be a
       Crockford base32 ULID (regex enforced by schema already; cross-check
       belt-and-braces here)

Usage:
  python3 validate-runtime-artifact-schema.py                # all under runtime-artifacts/
  python3 validate-runtime-artifact-schema.py --pr-only      # only files changed vs origin/main
  python3 validate-runtime-artifact-schema.py --single FILE  # single file

Exit codes:
  0 — all valid
  1 — at least 1 schema or cross-check violation
  2 — tool/setup error (schema missing, dependency missing, git diff failure)

Codex 019e44d9 plan-time AGREE chain (iter-1 REVISE → iter-2 REVISE → iter-3
AGREE ready_for_impl:true). 4 P1/P2 findings deferred to post-impl review.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "schema" / "runtime-artifact-ledger-v1.schema.json"
LEDGER_DIR = REPO_ROOT / "runtime-artifacts"

# Crockford base32 ULID — Codex iter-1 #2 / iter-3 final
ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")
DIGEST_RE = re.compile(r"^sha256:[a-f0-9]{64}$")


def load_schema() -> dict[str, Any]:
    if not SCHEMA_PATH.exists():
        print(f"ERR: schema not found: {SCHEMA_PATH}", file=sys.stderr)
        sys.exit(2)
    return json.loads(SCHEMA_PATH.read_text())


def _import_jsonschema():
    try:
        from jsonschema import Draft202012Validator, FormatChecker  # type: ignore
        return Draft202012Validator, FormatChecker
    except ImportError:
        print(
            "ERR: jsonschema not installed. Install with: pip install jsonschema",
            file=sys.stderr,
        )
        sys.exit(2)


def validate_schema(entry: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    """Return a list of jsonschema validation error messages (empty == valid)."""
    Draft202012Validator, FormatChecker = _import_jsonschema()
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(entry), key=lambda e: e.path)
    return [
        f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
        for e in errors
    ]


def validate_path_matches_content(file_path: Path, entry: dict[str, Any]) -> list[str]:
    """
    Cross-check: file_path = runtime-artifacts/<artifact_kind>/<digest>.json
    where <digest> is artifact_content_digest minus the 'sha256:' prefix.

    Fixture mode: files under tests/runtime-artifacts/fixtures/ are exempt from
    the path↔content check (they exist to exercise schema validation in
    isolation; their filenames do not encode digests).
    """
    errors: list[str] = []

    # Fixture mode bypass
    try:
        fixture_dir = REPO_ROOT / "tests" / "runtime-artifacts" / "fixtures"
        file_path.resolve().relative_to(fixture_dir.resolve())
        # File is under fixtures/ — skip path↔content cross-check
        return errors
    except ValueError:
        pass

    try:
        rel = file_path.resolve().relative_to(LEDGER_DIR)
    except ValueError:
        errors.append(
            f"file path not under {LEDGER_DIR} or tests/runtime-artifacts/fixtures/: {file_path}"
        )
        return errors

    parts = rel.parts
    if len(parts) != 2:
        errors.append(
            f"expected runtime-artifacts/<kind>/<digest>.json, got {rel.as_posix()}"
        )
        return errors

    kind_dir, filename = parts
    expected_kind = entry.get("artifact_kind")
    if kind_dir != expected_kind:
        errors.append(
            f"kind directory '{kind_dir}' != artifact_kind '{expected_kind}'"
        )

    if not filename.endswith(".json"):
        errors.append(f"filename must end in .json: {filename}")
    else:
        digest_in_name = filename[:-5]  # strip .json
        digest_field = entry.get("artifact_content_digest", "")
        digest_stripped = digest_field.removeprefix("sha256:")
        if digest_in_name != digest_stripped:
            errors.append(
                f"filename digest '{digest_in_name}' != "
                f"artifact_content_digest stripped '{digest_stripped}'"
            )

    return errors


def validate_kind_format_hooks(entry: dict[str, Any]) -> list[str]:
    """Per-kind extra checks (belt-and-braces on top of schema regex)."""
    errors: list[str] = []
    kind = entry.get("artifact_kind")

    if kind == "openfga-model":
        for env_key in ("test", "prod"):
            block = entry.get("promotion", {}).get(env_key, {})
            mid = block.get("model_id_env")
            if mid is not None and not ULID_RE.match(mid):
                errors.append(
                    f"promotion.{env_key}.model_id_env '{mid}' is not a valid "
                    f"Crockford base32 ULID (26 chars, no I/L/O/U)"
                )

    return errors


def validate_file(file_path: Path, schema: dict[str, Any]) -> list[str]:
    """Run all checks on a single file. Returns combined error list."""
    if not file_path.exists():
        return [f"file not found: {file_path}"]

    try:
        entry = json.loads(file_path.read_text())
    except json.JSONDecodeError as e:
        return [f"invalid JSON: {e}"]

    errors: list[str] = []
    errors.extend(validate_schema(entry, schema))
    errors.extend(validate_path_matches_content(file_path, entry))
    errors.extend(validate_kind_format_hooks(entry))
    return errors


def get_changed_files(base: str = "origin/main", head: str = "HEAD") -> list[Path]:
    """Return changed .json files under runtime-artifacts/ vs base."""
    try:
        out = subprocess.check_output(
            ["git", "diff", "--name-only", f"{base}...{head}"],
            cwd=REPO_ROOT,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"ERR: git diff failed: {e}", file=sys.stderr)
        sys.exit(2)

    return [
        REPO_ROOT / line
        for line in out.splitlines()
        if line.startswith("runtime-artifacts/") and line.endswith(".json")
    ]


def scan_all() -> list[Path]:
    """All ledger JSON files under runtime-artifacts/."""
    if not LEDGER_DIR.exists():
        return []
    return sorted(p for p in LEDGER_DIR.rglob("*.json") if p.is_file())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--pr-only",
        action="store_true",
        help="Validate only files changed vs origin/main (CI PR mode).",
    )
    parser.add_argument(
        "--single",
        type=Path,
        help="Validate a single file (absolute or repo-relative path).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print path+OK lines for every successfully-validated file.",
    )
    args = parser.parse_args()

    schema = load_schema()

    if args.single:
        single = args.single if args.single.is_absolute() else REPO_ROOT / args.single
        targets = [single]
    elif args.pr_only:
        targets = get_changed_files()
        if not targets:
            print("[validate-runtime-artifact] no changed runtime-artifact files in PR diff")
            return 0
    else:
        targets = scan_all()
        if not targets:
            print("[validate-runtime-artifact] no ledger files under runtime-artifacts/")
            return 0

    rc = 0
    for target in targets:
        errs = validate_file(target, schema)
        rel = target.relative_to(REPO_ROOT) if target.is_absolute() else target
        if errs:
            print(f"[FAIL] {rel}")
            for e in errs:
                print(f"  - {e}")
            rc = 1
        elif args.verbose:
            print(f"[OK]   {rel}")

    if rc == 0:
        print(f"[validate-runtime-artifact] all {len(targets)} file(s) valid")
    else:
        print(f"[validate-runtime-artifact] FAIL — at least one file invalid")
    return rc


if __name__ == "__main__":
    sys.exit(main())
