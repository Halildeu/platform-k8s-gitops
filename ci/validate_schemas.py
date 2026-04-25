import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def iter_sorted(paths):
    return sorted(paths, key=lambda p: str(p))


def has_existing_targets(*paths: Path) -> bool:
    return any(path.exists() for path in paths)


def fail_if_forbidden_terms_present(repo_root: Path) -> None:
    # SSOT terminology lock: "skill" is forbidden in docs/specs; use CAPABILITY/KABİLİYET instead.
    forbidden = re.compile(r"\bskills?\b", re.IGNORECASE)
    scan_roots = [
        repo_root / "docs",
        repo_root / "schemas",
        repo_root / "roadmaps",
        repo_root / "capabilities",
    ]

    hits: list[tuple[str, int, str]] = []
    for scan_root in scan_roots:
        if not scan_root.exists():
            continue

        scan_paths = iter_sorted(
            [
                p
                for p in scan_root.rglob("*")
                if p.is_file() and p.suffix in {".md", ".json"}
            ]
        )
        for path in scan_paths:
            rel = path.relative_to(repo_root).as_posix()
            try:
                text = path.read_text(encoding="utf-8")
            except Exception:
                continue

            for lineno, line in enumerate(text.splitlines(), start=1):
                if forbidden.search(line):
                    hits.append((rel, lineno, line.strip()[:200]))
                    if len(hits) >= 20:
                        break
            if len(hits) >= 20:
                break

        if len(hits) >= 20:
            break

    if hits:
        print("FORBIDDEN_TERM: 'skill' is not allowed in SSOT docs/specs. Use CAPABILITY/KABİLİYET instead.")
        for rel, lineno, snippet in hits:
            print(f"  - {rel}:{lineno}: {snippet}")
        raise SystemExit("Forbidden term 'skill' found in SSOT docs/specs. Use CAPABILITY/KABİLİYET instead.")


def validate_schema_files(repo_root: Path) -> list[Path]:
    schemas_dir = repo_root / "schemas"
    schema_paths = iter_sorted(
        list(schemas_dir.glob("*.schema.json")) + list(schemas_dir.glob("*.schema.v1.json"))
    )
    if not schema_paths:
        raise SystemExit("No schemas found in schemas/*.schema.json or schemas/*.schema.v1.json")

    for schema_path in schema_paths:
        Draft202012Validator.check_schema(load_json(schema_path))

    return schema_paths


def validate_request_envelope_fixtures(repo_root: Path) -> tuple[int, int]:
    schema_path = repo_root / "schemas" / "request-envelope.schema.json"
    fixtures_root = repo_root / "fixtures" / "envelopes"
    if not schema_path.exists():
        if has_existing_targets(fixtures_root):
            print("INVALID: schemas/request-envelope.schema.json not found but fixtures/envelopes exists.")
            return (1, 1)
        return (0, 0)

    validator = Draft202012Validator(load_json(schema_path))
    fixture_paths = iter_sorted(fixtures_root.glob("*.json")) if fixtures_root.exists() else []
    if not fixture_paths:
        return (0, 0)

    negative_fixture_paths = [p for p in fixture_paths if p.name.endswith("_invalid.json")]
    positive_fixture_paths = [p for p in fixture_paths if not p.name.endswith("_invalid.json")]

    invalid = 0
    for fixture_path in positive_fixture_paths:
        instance = load_json(fixture_path)
        errors = sorted(validator.iter_errors(instance), key=lambda e: e.json_path)
        if errors:
            invalid += 1
            print(f"INVALID: {fixture_path}")
            for err in errors[:10]:
                where = err.json_path or "$"
                print(f"  - {where}: {err.message}")

    unexpected_valid_negatives = 0
    for fixture_path in negative_fixture_paths:
        instance = load_json(fixture_path)
        errors = sorted(validator.iter_errors(instance), key=lambda e: e.json_path)
        if not errors:
            unexpected_valid_negatives += 1
            print(f"UNEXPECTED_VALID_NEGATIVE: {fixture_path}")

    total_checked = len(positive_fixture_paths) + len(negative_fixture_paths)
    if total_checked != len(fixture_paths):
        raise SystemExit("Internal error: fixture classification mismatch.")

    if unexpected_valid_negatives:
        invalid += unexpected_valid_negatives

    return (len(positive_fixture_paths), invalid)


def schema_path_for_policy(policy_path: Path, *, schemas_dir: Path) -> Path:
    # policy_security.v1.json -> policy-security.schema.json
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
    policies_dir = repo_root / "policies"
    schemas_dir = repo_root / "schemas"
    if not policies_dir.exists():
        print("WARN: policies/ not found; skipping policy validation.")
        return (0, 0)

    policy_paths = iter_sorted([p for p in policies_dir.glob("*.json") if p.is_file()])
    if not policy_paths:
        print("WARN: No policy files found in policies/*.json; skipping policy validation.")
        return (0, 0)

    invalid = 0
    for policy_path in policy_paths:
        schema_path = schema_path_for_policy(policy_path, schemas_dir=schemas_dir)
        if not schema_path.exists():
            invalid += 1
            print(f"MISSING_SCHEMA: {policy_path} -> expected {schema_path}")
            continue

        schema = load_json(schema_path)
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)

        instance = load_json(policy_path)
        errors = sorted(validator.iter_errors(instance), key=lambda e: e.json_path)
        if errors:
            invalid += 1
            print(f"INVALID_POLICY: {policy_path} (schema={schema_path.name})")
            for err in errors[:10]:
                where = err.json_path or "$"
                print(f"  - {where}: {err.message}")

    return (len(policy_paths), invalid)


def validate_roadmaps(repo_root: Path) -> tuple[int, int]:
    schema_path = repo_root / "schemas" / "roadmap.schema.json"
    roadmaps_dir = repo_root / "roadmaps"
    if not schema_path.exists():
        if has_existing_targets(roadmaps_dir):
            print("INVALID: schemas/roadmap.schema.json not found but roadmaps/ exists.")
            return (1, 1)
        return (0, 0)

    if not roadmaps_dir.exists():
        return (0, 0)

    validator = Draft202012Validator(load_json(schema_path))
    roadmap_paths = iter_sorted([p for p in roadmaps_dir.rglob("roadmap.v*.json") if p.is_file()])
    if not roadmap_paths:
        return (0, 0)

    invalid = 0
    for rp in roadmap_paths:
        instance = load_json(rp)
        errors = sorted(validator.iter_errors(instance), key=lambda e: e.json_path)
        if errors:
            invalid += 1
            print(f"INVALID_ROADMAP: {rp}")
            for err in errors[:10]:
                where = err.json_path or "$"
                print(f"  - {where}: {err.message}")

    return (len(roadmap_paths), invalid)


def validate_roadmap_changes(repo_root: Path) -> tuple[int, int]:
    schema_path = repo_root / "schemas" / "roadmap-change.schema.json"
    changes_dir = repo_root / "roadmaps" / "SSOT" / "changes"
    if not schema_path.exists():
        if has_existing_targets(changes_dir):
            print("INVALID: schemas/roadmap-change.schema.json not found but roadmaps/SSOT/changes exists.")
            return (1, 1)
        return (0, 0)

    if not changes_dir.exists():
        return (0, 0)

    validator = Draft202012Validator(load_json(schema_path))
    change_paths = iter_sorted([p for p in changes_dir.glob("*.json") if p.is_file()])
    if not change_paths:
        return (0, 0)

    invalid = 0
    for cp in change_paths:
        instance = load_json(cp)
        errors = sorted(validator.iter_errors(instance), key=lambda e: e.json_path)
        if errors:
            invalid += 1
            print(f"INVALID_ROADMAP_CHANGE: {cp}")
            for err in errors[:10]:
                where = err.json_path or "$"
                print(f"  - {where}: {err.message}")

    return (len(change_paths), invalid)


def validate_debt_changes(repo_root: Path) -> tuple[int, int]:
    schema_path = repo_root / "schemas" / "chg-debt.schema.json"
    changes_dir = repo_root / "roadmaps" / "SSOT" / "changes" / "debt"
    if not schema_path.exists():
        if has_existing_targets(changes_dir):
            print("INVALID: schemas/chg-debt.schema.json not found but roadmaps/SSOT/changes/debt exists.")
            return (1, 1)
        return (0, 0)
    if not changes_dir.exists():
        return (0, 0)

    validator = Draft202012Validator(load_json(schema_path))
    change_paths = iter_sorted([p for p in changes_dir.glob("CHG-*.json") if p.is_file()])
    if not change_paths:
        return (0, 0)

    invalid = 0
    for cp in change_paths:
        instance = load_json(cp)
        errors = sorted(validator.iter_errors(instance), key=lambda e: e.json_path)
        if errors:
            invalid += 1
            print(f"INVALID_DEBT_CHG: {cp}")
            for err in errors[:10]:
                where = err.json_path or "$"
                print(f"  - {where}: {err.message}")

    return (len(change_paths), invalid)


def validate_script_budget(repo_root: Path) -> tuple[int, int]:
    schema_path = repo_root / "schemas" / "script-budget.schema.json"
    if not schema_path.exists():
        print("WARN: schemas/script-budget.schema.json not found; skipping script budget validation.")
        return (0, 0)

    config_path = repo_root / "ci" / "script_budget.v1.json"
    if not config_path.exists():
        print("INVALID: ci/script_budget.v1.json not found.")
        return (1, 1)

    schema = load_json(schema_path)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)

    instance = load_json(config_path)
    errors = sorted(validator.iter_errors(instance), key=lambda e: e.json_path)
    if errors:
        print(f"INVALID_SCRIPT_BUDGET: {config_path} (schema={schema_path.name})")
        for err in errors[:10]:
            where = err.json_path or "$"
            print(f"  - {where}: {err.message}")
        return (1, 1)

    return (1, 0)

def validate_formats(repo_root: Path) -> tuple[int, int]:
    schema_path = repo_root / "schemas" / "format-autopilot-chat.schema.json"
    formats_dir = repo_root / "formats"
    if not schema_path.exists():
        if has_existing_targets(formats_dir):
            print("INVALID: schemas/format-autopilot-chat.schema.json not found but formats/ exists.")
            return (1, 1)
        return (0, 0)

    if not formats_dir.exists():
        return (0, 0)

    format_paths = iter_sorted([p for p in formats_dir.glob("format-autopilot-chat.v*.json") if p.is_file()])
    if not format_paths:
        return (0, 0)

    schema = load_json(schema_path)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)

    invalid = 0
    for fp in format_paths:
        instance = load_json(fp)
        errors = sorted(validator.iter_errors(instance), key=lambda e: e.json_path)
        if errors:
            invalid += 1
            print(f"INVALID_FORMAT: {fp} (schema={schema_path.name})")
            for err in errors[:10]:
                where = err.json_path or "$"
                print(f"  - {where}: {err.message}")

    return (len(format_paths), invalid)

def validate_packs(repo_root: Path) -> tuple[int, int]:
    schema_path = repo_root / "schemas" / "pack-manifest.schema.v1.json"
    packs_dir = repo_root / "packs"
    if not schema_path.exists():
        if has_existing_targets(packs_dir):
            print("INVALID: schemas/pack-manifest.schema.v1.json not found but packs/ exists.")
            return (1, 1)
        return (0, 0)

    if not packs_dir.exists():
        return (0, 0)

    pack_paths = iter_sorted([p for p in packs_dir.rglob("pack.manifest.v1.json") if p.is_file()])
    if not pack_paths:
        return (0, 0)

    schema = load_json(schema_path)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)

    invalid = 0
    for pp in pack_paths:
        instance = load_json(pp)
        errors = sorted(validator.iter_errors(instance), key=lambda e: e.json_path)
        if errors:
            invalid += 1
            print(f"INVALID_PACK_MANIFEST: {pp} (schema={schema_path.name})")
            for err in errors[:10]:
                where = err.json_path or "$"
                print(f"  - {where}: {err.message}")

    return (len(pack_paths), invalid)

def validate_project_manifests(repo_root: Path) -> tuple[int, int]:
    schema_path = repo_root / "schemas" / "project-manifest.schema.json"
    projects_dir = repo_root / "roadmaps" / "PROJECTS"
    if not schema_path.exists():
        if has_existing_targets(projects_dir):
            print("INVALID: schemas/project-manifest.schema.json not found but roadmaps/PROJECTS exists.")
            return (1, 1)
        return (0, 0)

    if not projects_dir.exists():
        return (0, 0)

    manifest_paths = iter_sorted([p for p in projects_dir.rglob("project.manifest.v1.json") if p.is_file()])
    if not manifest_paths:
        return (0, 0)

    schema = load_json(schema_path)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)

    invalid = 0
    for mp in manifest_paths:
        instance = load_json(mp)
        errors = sorted(validator.iter_errors(instance), key=lambda e: e.json_path)
        if errors:
            invalid += 1
            print(f"INVALID_PROJECT_MANIFEST: {mp} (schema={schema_path.name})")
            for err in errors[:10]:
                where = err.json_path or "$"
                print(f"  - {where}: {err.message}")

    return (len(manifest_paths), invalid)

def validate_capabilities(repo_root: Path) -> tuple[int, int]:
    schema_path = repo_root / "schemas" / "spec-capability.schema.json"
    caps_dir = repo_root / "capabilities"
    if not schema_path.exists():
        if has_existing_targets(caps_dir):
            print("INVALID: schemas/spec-capability.schema.json not found but capabilities/ exists.")
            return (1, 1)
        return (0, 0)

    if not caps_dir.exists():
        return (0, 0)

    cap_paths = iter_sorted([p for p in caps_dir.glob("*.v*.json") if p.is_file()])
    if not cap_paths:
        return (0, 0)

    schema = load_json(schema_path)
    Draft202012Validator.check_schema(schema)

    spec_core_path = repo_root / "schemas" / "spec-core.schema.json"
    registry = None
    if spec_core_path.exists():
        try:
            from referencing import Registry, Resource

            spec_core_schema = load_json(spec_core_path)
            Draft202012Validator.check_schema(spec_core_schema)

            registry = Registry()
            for s in (spec_core_schema, schema):
                sid = s.get("$id")
                if isinstance(sid, str) and sid:
                    registry = registry.with_resource(sid, Resource.from_contents(s))
        except Exception:
            registry = None

    validator = Draft202012Validator(schema, registry=registry) if registry is not None else Draft202012Validator(schema)

    invalid = 0
    for cp in cap_paths:
        instance = load_json(cp)
        errors = sorted(validator.iter_errors(instance), key=lambda e: e.json_path)
        if errors:
            invalid += 1
            print(f"INVALID_CAPABILITY: {cp} (schema={schema_path.name})")
            for err in errors[:10]:
                where = err.json_path or "$"
                print(f"  - {where}: {err.message}")

    return (len(cap_paths), invalid)


def validate_repo_layout(repo_root: Path) -> tuple[int, int]:
    schema_path = repo_root / "schemas" / "repo-layout.schema.json"
    layout_path = repo_root / "docs" / "OPERATIONS" / "repo-layout.v1.json"
    if not schema_path.exists():
        if has_existing_targets(layout_path):
            print("INVALID: schemas/repo-layout.schema.json not found but docs/OPERATIONS/repo-layout.v1.json exists.")
            return (1, 1)
        return (0, 0)
    if not layout_path.exists():
        return (0, 0)

    schema = load_json(schema_path)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    instance = load_json(layout_path)
    errors = sorted(validator.iter_errors(instance), key=lambda e: e.json_path)
    if errors:
        print(f"INVALID_REPO_LAYOUT: {layout_path}")
        for err in errors[:10]:
            where = err.json_path or "$"
            print(f"  - {where}: {err.message}")
        return (1, 1)
    return (1, 0)


def validate_smoke_root_cause_reports(repo_root: Path) -> tuple[int, int]:
    schema_path = repo_root / "schemas" / "smoke-root-cause-report.schema.v1.json"
    fixtures_dir = repo_root / "fixtures" / "reports"
    if not schema_path.exists():
        if has_existing_targets(fixtures_dir):
            print("INVALID: schemas/smoke-root-cause-report.schema.v1.json not found but fixtures/reports exists.")
            return (1, 1)
        return (0, 0)

    if not fixtures_dir.exists():
        return (0, 0)

    report_paths = iter_sorted([p for p in fixtures_dir.glob("smoke_root_cause_report*.json") if p.is_file()])
    if not report_paths:
        return (0, 0)

    schema = load_json(schema_path)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)

    invalid = 0
    for rp in report_paths:
        instance = load_json(rp)
        errors = sorted(validator.iter_errors(instance), key=lambda e: e.json_path)
        if errors:
            invalid += 1
            print(f"INVALID_SMOKE_ROOT_CAUSE_REPORT: {rp} (schema={schema_path.name})")
            for err in errors[:10]:
                where = err.json_path or "$"
                print(f"  - {where}: {err.message}")

    return (len(report_paths), invalid)


def main():
    repo_root = Path(__file__).resolve().parents[1]

    fail_if_forbidden_terms_present(repo_root)

    schema_paths = validate_schema_files(repo_root)
    total_fixtures, invalid_fixtures = validate_request_envelope_fixtures(repo_root)
    total_policies, invalid_policies = validate_policies(repo_root)
    total_roadmaps, invalid_roadmaps = validate_roadmaps(repo_root)
    total_changes, invalid_changes = validate_roadmap_changes(repo_root)
    total_debt_changes, invalid_debt_changes = validate_debt_changes(repo_root)
    total_script_budgets, invalid_script_budgets = validate_script_budget(repo_root)
    total_formats, invalid_formats = validate_formats(repo_root)
    total_packs, invalid_packs = validate_packs(repo_root)
    total_project_manifests, invalid_project_manifests = validate_project_manifests(repo_root)
    total_capabilities, invalid_capabilities = validate_capabilities(repo_root)
    total_repo_layout, invalid_repo_layout = validate_repo_layout(repo_root)
    total_smoke_root_cause_reports, invalid_smoke_root_cause_reports = validate_smoke_root_cause_reports(repo_root)

    if invalid_fixtures:
        raise SystemExit(f"Schema validation failed: {invalid_fixtures}/{total_fixtures} invalid fixtures.")
    if invalid_policies:
        raise SystemExit(f"Schema validation failed: {invalid_policies}/{total_policies} invalid policies.")
    if invalid_roadmaps:
        raise SystemExit(f"Schema validation failed: {invalid_roadmaps}/{total_roadmaps} invalid roadmaps.")
    if invalid_changes:
        raise SystemExit(f"Schema validation failed: {invalid_changes}/{total_changes} invalid roadmap changes.")
    if invalid_debt_changes:
        raise SystemExit(
            f"Schema validation failed: {invalid_debt_changes}/{total_debt_changes} invalid debt change proposals."
        )
    if invalid_script_budgets:
        raise SystemExit(
            f"Schema validation failed: {invalid_script_budgets}/{total_script_budgets} invalid script budget configs."
        )
    if invalid_formats:
        raise SystemExit(f"Schema validation failed: {invalid_formats}/{total_formats} invalid format files.")
    if invalid_packs:
        raise SystemExit(f"Schema validation failed: {invalid_packs}/{total_packs} invalid pack manifests.")
    if invalid_project_manifests:
        raise SystemExit(
            f"Schema validation failed: {invalid_project_manifests}/{total_project_manifests} invalid project manifests."
        )
    if invalid_capabilities:
        raise SystemExit(f"Schema validation failed: {invalid_capabilities}/{total_capabilities} invalid capabilities.")
    if invalid_repo_layout:
        raise SystemExit(f"Schema validation failed: {invalid_repo_layout}/{total_repo_layout} invalid repo layout files.")
    if invalid_smoke_root_cause_reports:
        raise SystemExit(
            "Schema validation failed: "
            + f"{invalid_smoke_root_cause_reports}/{total_smoke_root_cause_reports} invalid smoke root cause reports."
        )

    print(f"OK: {len(schema_paths)} schema files validated.")
    if total_fixtures:
        print(f"OK: {total_fixtures} fixtures validated against request-envelope schema.")
    if total_policies:
        print(f"OK: {total_policies} policies validated against policy schemas.")
    if total_roadmaps:
        print(f"OK: {total_roadmaps} roadmaps validated against roadmap schema.")
    if total_changes:
        print(f"OK: {total_changes} roadmap changes validated against roadmap-change schema.")
    if total_debt_changes:
        print(f"OK: {total_debt_changes} debt change proposals validated against chg-debt schema.")
    if total_script_budgets:
        print(f"OK: {total_script_budgets} script budget configs validated against script-budget schema.")
    if total_formats:
        print(f"OK: {total_formats} format files validated against format schema.")
    if total_packs:
        print(f"OK: {total_packs} pack manifests validated against pack schema.")
    if total_capabilities:
        print(f"OK: {total_capabilities} capabilities validated against spec-capability schema.")
    if total_repo_layout:
        print(f"OK: {total_repo_layout} repo layout files validated against repo-layout schema.")
    if total_smoke_root_cause_reports:
        print(
            "OK: "
            + f"{total_smoke_root_cause_reports} smoke root cause report fixtures validated against smoke root cause schema."
        )


if __name__ == "__main__":
    main()
