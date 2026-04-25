from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REQUIRED_FILES = (
    "standards.lock",
    ".github/CODEOWNERS",
    ".github/workflows/gate-enforcement-check.yml",
    ".github/workflows/module-delivery-lanes.yml",
    "docs/OPERATIONS/AI-MULTIREPO-OPERATING-CONTRACT.v1.md",
    "docs/OPERATIONS/ARCHITECTURE-CONSTRAINTS.md",
    "docs/OPERATIONS/CACHE-BOUNDARY-RULES.v1.md",
    "docs/OPERATIONS/maintainability-guardrails.md",
    "policies/policy_pm_suite.v1.json",
    "policies/policy_feature_execution_bridge.v1.json",
    "policies/policy_ui_design_system.v1.json",
    "policies/policy_ux_catalog_enforcement.v1.json",
    "registry/technical_baseline.aistd.v1.json",
    "registry/archives/legacy_standards_archive.aistd.v1.json",
    "schemas/policy-pm-suite.schema.v1.json",
    "schemas/policy-feature-execution-bridge.schema.v1.json",
    "schemas/feature-execution-contract.schema.v1.json",
    "schemas/delivery-session-packet.schema.v1.json",
    "schemas/policy-ui-design-system.schema.v1.json",
    "schemas/policy-ux-catalog-enforcement.schema.v1.json",
    "schemas/technical-baseline-aistd.schema.v1.json",
    "schemas/legacy-standards-archive-aistd.schema.v1.json",
    "schemas/module-delivery-lanes.schema.v1.json",
    "schemas/script-budget.schema.json",
    "scripts/sync_managed_repo_standards.py",
    "scripts/archive_legacy_standards.py",
    "scripts/ops_technical_baseline_checklist.py",
    "scripts/export_managed_repo_standards_dashboard.py",
    "scripts/check_cache_boundary.py",
    "ci/check_standards_lock.py",
    "ci/check_standards_lock_shared.py",
    "ci/check_standards_lock_validators.py",
    "ci/check_standards_lock_sections.py",
    "ci/check_script_budget.py",
    "ci/check_module_delivery_lanes.py",
    "ci/run_module_delivery_lane.py",
    "ci/module_delivery_lanes.v1.json",
    "ci/script_budget.v1.json",
    "scripts/check_branch_protection_solo_policy.py",
    "extensions/PRJ-UX-NORTH-STAR/contract/ux_katalogu.final_lock.v1.json",
    "extensions/PRJ-UX-NORTH-STAR/contract/ux_change_map.v1.json",
    "extensions/PRJ-UX-NORTH-STAR/contract/check_ux_catalog_enforcement.py",
    "extensions/PRJ-PM-SUITE/contract/feature_execution_contract.v1.json",
    "extensions/PRJ-PM-SUITE/contract/check_feature_execution_contract.py",
    "extensions/PRJ-PM-SUITE/contract/seed_feature_execution_contract.py",
    "extensions/PRJ-PM-SUITE/contract/build_delivery_session_packet.py",
    "extensions/PRJ-PM-SUITE/contract/check_delivery_session_guard.py",
)

REQUIRED_LOCK_KEYS = (
    "version",
    "operating_contract",
    "standard_sources",
    "required_files",
    "required_commands",
    "required_gates",
    "managed_repo_sync",
    "module_delivery_contract",
    "branch_protection",
    "solo_developer_policy",
    "pr_gate_mode",
)

REQUIRED_GATES = (
    "enforcement-check",
    "gate-schema",
    "gate-policy-dry-run",
    "gate-secrets",
    "module-delivery-gate",
    "ux-catalog-gate",
    "feature-execution-bridge",
)

REQUIRED_STANDARD_SOURCES = (
    "technical_baseline_aistd",
    "pm_suite_policy",
    "feature_execution_bridge_policy",
    "layer_boundary_policy",
    "llm_live_policy",
    "llm_provider_guardrails_policy",
    "kernel_api_guardrails_policy",
    "ui_design_system_policy",
    "security_policy",
    "secrets_policy",
    "ux_catalog_enforcement_policy",
    "ux_catalog_lock",
)

REQUIRED_COMMANDS = (
    "python ci/validate_schemas.py",
    "python ci/policy_dry_run.py --fixtures fixtures/envelopes --out sim_report.json",
    "python ci/check_script_budget.py --out .cache/script_budget/report.json",
    "python -m src.ops.manage enforcement-check --profile strict",
    "python3 scripts/ops_technical_baseline_checklist.py --repo-root .",
    "python3 scripts/export_managed_repo_standards_dashboard.py --workspace-root .",
    "python3 scripts/check_cache_boundary.py",
    "python3 scripts/sync_managed_repo_standards.py --target-repo-root <repo_root>",
    "python3 ci/check_module_delivery_lanes.py --strict",
    "python3 scripts/check_branch_protection_solo_policy.py --repo-slug <owner/repo>",
    "python3 extensions/PRJ-UX-NORTH-STAR/contract/check_ux_catalog_enforcement.py --repo-root .",
    "python3 extensions/PRJ-PM-SUITE/contract/check_feature_execution_contract.py --repo-root .",
    "python3 extensions/PRJ-PM-SUITE/contract/build_delivery_session_packet.py --repo-root . --out .cache/reports/delivery_session_packet.v1.json",
    "python3 extensions/PRJ-PM-SUITE/contract/check_delivery_session_guard.py --repo-root . --packet .cache/reports/delivery_session_packet.v1.json",
)

REQUIRED_PRESERVE_PATHS = (
    "ci/module_delivery_lanes.v1.json",
    "registry/archives/legacy_standards_archive.aistd.v1.json",
    "extensions/PRJ-UX-NORTH-STAR/contract/ux_change_map.v1.json",
    "extensions/PRJ-PM-SUITE/contract/feature_execution_contract.v1.json",
)

REQUIRED_BRANCH_PROTECTION_CHECKS = (
    "module-delivery-gate",
    "enforcement-check",
    "validate-schemas",
    "policy-dry-run",
    "gitleaks",
)

REQUIRED_DELIVERY_SEQUENCE = ("backend", "database", "api", "frontend", "integration", "e2e")
REQUIRED_SCOPE_LANE_MAP = {
    "backend": "unit",
    "database": "database",
    "api": "api",
    "frontend": "contract",
    "integration": "integration",
    "e2e_gate": "e2e",
}
REQUIRED_LANES = ("unit", "database", "api", "contract", "integration", "e2e")
REQUIRED_BACKEND_LAYERS = ("config", "controller", "dto", "model", "repository", "security", "service")
REQUIRED_FRONTEND_LAYOUT_EXPORTS = ("PageLayout", "DetailDrawer", "FormDrawer")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repo-root",
        default="",
        help="Target repo root to validate (default: current repository root).",
    )
    return parser.parse_args(argv)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _fail(error_code: str, message: str, *, details: dict[str, Any] | None = None) -> int:
    payload: dict[str, Any] = {
        "status": "FAIL",
        "error_code": error_code,
        "message": message,
    }
    if isinstance(details, dict) and details:
        payload["details"] = details
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 1


def _require_json_file(root: Path, rel_path: str) -> dict[str, Any] | None:
    path = root / rel_path
    if not path.exists():
        return None
    try:
        obj = _load_json(path)
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None
