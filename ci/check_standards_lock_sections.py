from __future__ import annotations

from pathlib import Path
from typing import Any

from check_standards_lock_shared import (
    REQUIRED_BRANCH_PROTECTION_CHECKS,
    REQUIRED_COMMANDS,
    REQUIRED_DELIVERY_SEQUENCE,
    REQUIRED_LANES,
    REQUIRED_PRESERVE_PATHS,
    REQUIRED_SCOPE_LANE_MAP,
)


def _check_required_commands(required_commands: Any) -> tuple[bool, dict[str, Any]]:
    details: dict[str, Any] = {"missing_commands": []}
    if not isinstance(required_commands, list):
        details["missing_commands"] = list(REQUIRED_COMMANDS)
        return False, details
    command_set = {str(item) for item in required_commands if isinstance(item, str)}
    details["missing_commands"] = [cmd for cmd in REQUIRED_COMMANDS if cmd not in command_set]
    return not details["missing_commands"], details


def _check_managed_repo_sync(root: Path, section: Any) -> tuple[bool, dict[str, Any]]:
    details: dict[str, Any] = {"missing_keys": [], "invalid_values": [], "missing_files": []}
    if not isinstance(section, dict):
        details["missing_keys"] = [
            "default_mode",
            "script",
            "source_of_truth",
            "apply_requires_flag",
            "validation_command_template",
            "preserve_existing_paths",
        ]
        return False, details

    for key in ("default_mode", "script", "source_of_truth", "apply_requires_flag", "validation_command_template"):
        if key not in section:
            details["missing_keys"].append(key)

    if section.get("default_mode") != "dry-run":
        details["invalid_values"].append("default_mode_must_be_dry-run")
    if section.get("script") != "scripts/sync_managed_repo_standards.py":
        details["invalid_values"].append("script_path_invalid")
    if section.get("source_of_truth") != "standards.lock":
        details["invalid_values"].append("source_of_truth_must_be_standards.lock")
    if section.get("apply_requires_flag") is not True:
        details["invalid_values"].append("apply_requires_flag_must_be_true")
    expected_template = "python3 ci/check_standards_lock.py --repo-root <repo_root>"
    if section.get("validation_command_template") != expected_template:
        details["invalid_values"].append("validation_command_template_invalid")

    preserve = section.get("preserve_existing_paths")
    if not isinstance(preserve, list):
        details["invalid_values"].append("preserve_existing_paths_must_be_list")
    else:
        preserve_set = {str(item) for item in preserve if isinstance(item, str)}
        missing_preserve = [path for path in REQUIRED_PRESERVE_PATHS if path not in preserve_set]
        if missing_preserve:
            details["invalid_values"].append("preserve_existing_paths_missing:" + ",".join(missing_preserve))
        for rel_path in preserve_set:
            if rel_path and not (root / rel_path).exists():
                details["missing_files"].append(rel_path)

    return not details["missing_keys"] and not details["invalid_values"] and not details["missing_files"], details


def _check_module_delivery_contract(section: Any) -> tuple[bool, dict[str, Any]]:
    details: dict[str, Any] = {"missing_keys": [], "invalid_values": []}
    if not isinstance(section, dict):
        details["missing_keys"] = [
            "service_scopes",
            "scope_lane_map",
            "delivery_sequence",
            "required_test_lanes",
            "merge_requires_all_green",
        ]
        return False, details

    for key in ("service_scopes", "scope_lane_map", "delivery_sequence", "required_test_lanes", "merge_requires_all_green"):
        if key not in section:
            details["missing_keys"].append(key)

    service_scopes = section.get("service_scopes")
    if not isinstance(service_scopes, list):
        details["invalid_values"].append("service_scopes_must_be_list")
    else:
        required_scopes = {"backend", "frontend", "database", "api"}
        scope_set = {str(item) for item in service_scopes if isinstance(item, str)}
        missing_scopes = sorted(required_scopes - scope_set)
        if missing_scopes:
            details["invalid_values"].append("service_scopes_missing:" + ",".join(missing_scopes))

    scope_lane_map = section.get("scope_lane_map")
    if not isinstance(scope_lane_map, dict):
        details["invalid_values"].append("scope_lane_map_must_be_object")
    else:
        mismatches = [
            f"{key}->{scope_lane_map.get(key)}"
            for key, expected in REQUIRED_SCOPE_LANE_MAP.items()
            if scope_lane_map.get(key) != expected
        ]
        if mismatches:
            details["invalid_values"].append("scope_lane_map_invalid:" + ",".join(mismatches))

    delivery_sequence = [str(item) for item in (section.get("delivery_sequence") or []) if isinstance(item, str)]
    if delivery_sequence != list(REQUIRED_DELIVERY_SEQUENCE):
        details["invalid_values"].append("delivery_sequence_invalid")

    required_test_lanes = section.get("required_test_lanes")
    if not isinstance(required_test_lanes, list):
        details["invalid_values"].append("required_test_lanes_must_be_list")
    else:
        lane_set = {str(item) for item in required_test_lanes if isinstance(item, str)}
        missing_lanes = [lane for lane in REQUIRED_LANES if lane not in lane_set]
        if missing_lanes:
            details["invalid_values"].append("required_test_lanes_missing:" + ",".join(missing_lanes))

    if section.get("merge_requires_all_green") is not True:
        details["invalid_values"].append("merge_requires_all_green_must_be_true")

    return not details["missing_keys"] and not details["invalid_values"], details


def _check_branch_protection(section: Any) -> tuple[bool, dict[str, Any]]:
    details: dict[str, Any] = {"missing_keys": [], "invalid_values": []}
    if not isinstance(section, dict):
        details["missing_keys"] = ["default_branch", "required_checks", "verification_mode"]
        return False, details

    for key in ("default_branch", "required_checks", "verification_mode"):
        if key not in section:
            details["missing_keys"].append(key)

    if section.get("default_branch") != "main":
        details["invalid_values"].append("default_branch_must_be_main")
    if section.get("verification_mode") != "live_evidence":
        details["invalid_values"].append("verification_mode_must_be_live_evidence")
    required_checks = section.get("required_checks")
    if not isinstance(required_checks, list):
        details["invalid_values"].append("required_checks_must_be_list")
    else:
        actual_checks = {str(item) for item in required_checks if isinstance(item, str)}
        missing_checks = [check for check in REQUIRED_BRANCH_PROTECTION_CHECKS if check not in actual_checks]
        if missing_checks:
            details["invalid_values"].append("required_checks_missing:" + ",".join(missing_checks))

    return not details["missing_keys"] and not details["invalid_values"], details


def _check_solo_developer_policy(section: Any) -> tuple[bool, dict[str, Any]]:
    details: dict[str, Any] = {"missing_keys": [], "invalid_values": []}
    if not isinstance(section, dict):
        details["missing_keys"] = [
            "enabled",
            "single_writer_requires_review_count",
            "single_writer_require_code_owner_reviews",
            "multi_writer_min_review_count",
            "multi_writer_require_code_owner_reviews",
            "strict_required_status_checks",
            "enforce_admins_required",
        ]
        return False, details

    for key in (
        "enabled",
        "single_writer_requires_review_count",
        "single_writer_require_code_owner_reviews",
        "multi_writer_min_review_count",
        "multi_writer_require_code_owner_reviews",
        "strict_required_status_checks",
        "enforce_admins_required",
    ):
        if key not in section:
            details["missing_keys"].append(key)

    if section.get("enabled") is not True:
        details["invalid_values"].append("enabled_must_be_true")
    if int(section.get("single_writer_requires_review_count") or 0) != 0:
        details["invalid_values"].append("single_writer_requires_review_count_must_be_0")
    if section.get("single_writer_require_code_owner_reviews") is not False:
        details["invalid_values"].append("single_writer_require_code_owner_reviews_must_be_false")
    if int(section.get("multi_writer_min_review_count") or 0) < 1:
        details["invalid_values"].append("multi_writer_min_review_count_must_be_gte_1")
    if section.get("multi_writer_require_code_owner_reviews") is not True:
        details["invalid_values"].append("multi_writer_require_code_owner_reviews_must_be_true")
    if section.get("strict_required_status_checks") is not True:
        details["invalid_values"].append("strict_required_status_checks_must_be_true")
    if section.get("enforce_admins_required") is not True:
        details["invalid_values"].append("enforce_admins_required_must_be_true")

    return not details["missing_keys"] and not details["invalid_values"], details


def _check_enforcement_workflow(root: Path) -> tuple[bool, dict[str, Any]]:
    workflow_path = root / ".github/workflows/gate-enforcement-check.yml"
    details: dict[str, Any] = {"issues": []}
    if not workflow_path.exists():
        details["issues"].append("workflow_missing")
        return False, details

    text = workflow_path.read_text(encoding="utf-8")
    required_markers = (
        "python3 ci/check_standards_lock.py",
        "python3 ci/check_script_budget.py --out .cache/script_budget/report.json",
        "python3 ci/check_module_delivery_lanes.py --strict",
        "python3 extensions/PRJ-PM-SUITE/contract/check_feature_execution_contract.py",
        "python3 extensions/PRJ-PM-SUITE/contract/build_delivery_session_packet.py",
        "python3 extensions/PRJ-PM-SUITE/contract/check_delivery_session_guard.py",
        "python3 extensions/PRJ-UX-NORTH-STAR/contract/check_ux_catalog_enforcement.py",
        "python3 scripts/check_branch_protection_solo_policy.py",
        "python3 -m src.ops.manage enforcement-check --profile strict",
        "actions/upload-artifact@v4",
    )
    for marker in required_markers:
        if marker not in text:
            details["issues"].append(f"missing_marker:{marker}")
    return not details["issues"], details


def _check_module_delivery_workflow(root: Path) -> tuple[bool, dict[str, Any]]:
    workflow_path = root / ".github/workflows/module-delivery-lanes.yml"
    details: dict[str, Any] = {"issues": []}
    if not workflow_path.exists():
        details["issues"].append("workflow_missing")
        return False, details

    text = workflow_path.read_text(encoding="utf-8")
    required_markers = (
        "module-delivery-contract-check",
        "Script budget precheck",
        "module-lane-unit",
        "module-lane-database",
        "module-lane-api",
        "module-lane-contract",
        "module-lane-integration",
        "module-lane-e2e",
        "module-delivery-gate",
        "python3 ci/check_script_budget.py --out .cache/script_budget/report.json",
        "python3 ci/run_module_delivery_lane.py --lane unit",
        "python3 ci/run_module_delivery_lane.py --lane database",
        "python3 ci/run_module_delivery_lane.py --lane api",
        "python3 ci/run_module_delivery_lane.py --lane contract",
        "python3 ci/run_module_delivery_lane.py --lane integration",
        "python3 ci/run_module_delivery_lane.py --lane e2e",
        "Upload unit lane artifacts",
        "Upload database lane artifacts",
        "Upload api lane artifacts",
        "Upload contract lane artifacts",
        "Upload integration lane artifacts",
        "Upload e2e lane artifacts",
        "actions/upload-artifact@v4",
    )
    for marker in required_markers:
        if marker not in text:
            details["issues"].append(f"missing_marker:{marker}")

    required_sequence_markers = (
        "module-lane-database:\n    runs-on: ubuntu-latest\n    needs: [module-lane-unit]",
        "module-lane-api:\n    runs-on: ubuntu-latest\n    needs: [module-lane-unit]",
        "module-lane-contract:\n    runs-on: ubuntu-latest\n    needs: [module-lane-unit]",
        "module-lane-integration:\n    runs-on: ubuntu-latest\n    needs: [module-lane-database, module-lane-api, module-lane-contract]",
        "module-lane-e2e:\n    runs-on: ubuntu-latest\n    needs: [module-lane-integration]",
    )
    for marker in required_sequence_markers:
        if marker not in text:
            details["issues"].append(f"missing_sequence:{marker}")

    required_gate_checks = (
        "needs.module-lane-unit.result",
        "needs.module-lane-database.result",
        "needs.module-lane-api.result",
        "needs.module-lane-contract.result",
        "needs.module-lane-integration.result",
        "needs.module-lane-e2e.result",
    )
    for marker in required_gate_checks:
        if marker not in text:
            details["issues"].append(f"missing_gate_check:{marker}")

    return not details["issues"], details
