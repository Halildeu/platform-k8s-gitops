"""policy_dry_run.py — Dev repo policy validation gate.

Validates all policies in policies/ against their corresponding schemas
in schemas/. This is the managed-repo version; the full orchestrator
version also simulates request envelopes and quota/budget checks.

Usage:
    python3 ci/policy_dry_run.py --fixtures fixtures/envelopes --out sim_report.json
"""

import argparse
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def iter_sorted(paths):
    return sorted(paths, key=lambda p: str(p))


def has_existing_targets(*paths: Path) -> bool:
    return any(path.exists() for path in paths)


def schema_path_for_policy(policy_path: Path, *, schemas_dir: Path) -> Path:
    """Map policy_foo.v1.json -> policy-foo.schema.v1.json or policy-foo.schema.json."""
    name = policy_path.name
    base = name.split(".v", 1)[0] if ".v" in name else name.rsplit(".json", 1)[0]
    version = None
    if ".v" in name:
        version_part = name.split(".v", 1)[1].split(".json", 1)[0]
        if version_part.isdigit():
            version = f"v{version_part}"
    if version and version != "v1":
        candidate = schemas_dir / (base.replace("_", "-") + f".schema.{version}.json")
        if candidate.exists():
            return candidate
    schema_name = base.replace("_", "-") + ".schema.json"
    schema_path = schemas_dir / schema_name
    if schema_path.exists():
        return schema_path
    return schemas_dir / (base.replace("_", "-") + ".schema.v1.json")


def validate_policies(repo_root: Path) -> tuple[int, int]:
    """Validate each policy JSON against its matching schema."""
    policies_dir = repo_root / "policies"
    schemas_dir = repo_root / "schemas"
    if not policies_dir.exists():
        return (0, 0)

    policy_paths = iter_sorted([p for p in policies_dir.glob("*.json") if p.is_file()])
    if not policy_paths:
        return (0, 0)

    invalid = 0
    for policy_path in policy_paths:
        sp = schema_path_for_policy(policy_path, schemas_dir=schemas_dir)
        if not sp.exists():
            invalid += 1
            print(f"MISSING_SCHEMA: {policy_path.name} -> expected {sp.name}")
            continue

        schema = load_json(sp)
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)

        instance = load_json(policy_path)
        errors = sorted(validator.iter_errors(instance), key=lambda e: e.json_path)
        if errors:
            invalid += 1
            print(f"INVALID_POLICY: {policy_path.name} (schema={sp.name})")
            for err in errors[:10]:
                where = err.json_path or "$"
                print(f"  - {where}: {err.message}")

    return (len(policy_paths), invalid)


def validate_fixtures(repo_root: Path, fixtures_dir: Path) -> tuple[int, int]:
    """Validate fixture envelopes against request-envelope schema if available."""
    schema_path = repo_root / "schemas" / "request-envelope.schema.json"
    if not schema_path.exists():
        if has_existing_targets(fixtures_dir):
            print("INVALID: schemas/request-envelope.schema.json not found but fixtures exist.")
            return (1, 1)
        return (0, 0)

    if not fixtures_dir.exists():
        return (0, 0)

    fixture_paths = iter_sorted(list(fixtures_dir.glob("*.json")))
    if not fixture_paths:
        return (0, 0)

    validator = Draft202012Validator(load_json(schema_path))

    invalid = 0
    for fp in fixture_paths:
        instance = load_json(fp)
        errors = sorted(validator.iter_errors(instance), key=lambda e: e.json_path)
        if errors and not fp.name.endswith("_invalid.json"):
            invalid += 1
            print(f"INVALID_FIXTURE: {fp.name}")
            for err in errors[:10]:
                where = err.json_path or "$"
                print(f"  - {where}: {err.message}")

    return (len(fixture_paths), invalid)


def main():
    ap = argparse.ArgumentParser(description="Policy dry-run gate for managed repo")
    ap.add_argument("--out", required=True, help="Output report JSON path")
    ap.add_argument("--fixtures", default="fixtures/envelopes", help="Fixtures directory")
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    fixtures_dir = repo_root / args.fixtures

    total_policies, invalid_policies = validate_policies(repo_root)
    total_fixtures, invalid_fixtures = validate_fixtures(repo_root, fixtures_dir)

    report = {
        "status": "FAIL" if (invalid_policies or invalid_fixtures) else "OK",
        "policies": {"total": total_policies, "invalid": invalid_policies},
        "fixtures": {"total": total_fixtures, "invalid": invalid_fixtures},
        "mode": "dry-run",
        "variant": "managed-repo",
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))

    if invalid_policies:
        raise SystemExit(f"Policy dry-run FAIL: {invalid_policies}/{total_policies} invalid policies.")
    if invalid_fixtures:
        raise SystemExit(f"Policy dry-run FAIL: {invalid_fixtures}/{total_fixtures} invalid fixtures.")


if __name__ == "__main__":
    main()
