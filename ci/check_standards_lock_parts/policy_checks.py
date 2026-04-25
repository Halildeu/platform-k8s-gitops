from __future__ import annotations

from pathlib import Path
from typing import Any

from ci.check_standards_lock_parts.helpers import _require_json_file

def _check_pm_suite_policy(root: Path, rel_path: str) -> tuple[bool, dict[str, Any]]:
    details: dict[str, Any] = {"invalid_values": [], "missing_files": []}
    policy = _require_json_file(root, rel_path, key="pm_suite_policy")
    if not isinstance(policy, dict):
        details["invalid_values"].append("pm_suite_policy:invalid_json")
        return False, details

    if policy.get("version") != "v1":
        details["invalid_values"].append("pm_suite_policy:version_must_be_v1")
    if policy.get("enabled") is not True:
        details["invalid_values"].append("pm_suite_policy:enabled_must_be_true")

    workflow = policy.get("default_workflow")
    statuses = workflow.get("statuses") if isinstance(workflow, dict) else []
    if not isinstance(statuses, list) or not {"OPEN", "IN_PROGRESS", "BLOCKED", "DONE"}.issubset(set(statuses)):
        details["invalid_values"].append("pm_suite_policy:default_workflow_statuses_invalid")

    if policy.get("default_priority") != "P2":
        details["invalid_values"].append("pm_suite_policy:default_priority_must_be_P2")
    if policy.get("default_severity") != "S3":
        details["invalid_values"].append("pm_suite_policy:default_severity_must_be_S3")

    execution_bridge = policy.get("execution_bridge")
    if not isinstance(execution_bridge, dict):
        details["invalid_values"].append("pm_suite_policy:execution_bridge_missing")
    else:
        if execution_bridge.get("enabled") is not True:
            details["invalid_values"].append("pm_suite_policy:execution_bridge.enabled_must_be_true")
        expected_paths = {
            "contract_path": "extensions/PRJ-PM-SUITE/contract/feature_execution_contract.v1.json",
            "checker_path": "extensions/PRJ-PM-SUITE/contract/check_feature_execution_contract.py",
            "seed_script_path": "extensions/PRJ-PM-SUITE/contract/seed_feature_execution_contract.py",
            "contract_schema_path": "schemas/feature-execution-contract.schema.v1.json",
            "report_path": ".cache/reports/feature_execution_contract_check.v1.json",
        }
        for key, expected in expected_paths.items():
            if str(execution_bridge.get(key) or "") != expected:
                details["invalid_values"].append(f"pm_suite_policy:execution_bridge.{key}_invalid")

    delivery_session = policy.get("delivery_session")
    if not isinstance(delivery_session, dict):
        details["invalid_values"].append("pm_suite_policy:delivery_session_missing")
    else:
        if delivery_session.get("enabled") is not True:
            details["invalid_values"].append("pm_suite_policy:delivery_session.enabled_must_be_true")
        expected_paths = {
            "packet_path": ".cache/reports/delivery_session_packet.v1.json",
            "guard_report_path": ".cache/reports/delivery_session_guard.v1.json",
            "builder_path": "extensions/PRJ-PM-SUITE/contract/build_delivery_session_packet.py",
            "guard_path": "extensions/PRJ-PM-SUITE/contract/check_delivery_session_guard.py",
            "packet_schema_path": "schemas/delivery-session-packet.schema.v1.json",
            "note": "delivery_session_compiler_active",
        }
        for key, expected in expected_paths.items():
            if str(delivery_session.get(key) or "") != expected:
                details["invalid_values"].append(f"pm_suite_policy:delivery_session.{key}_invalid")

    return not details["invalid_values"] and not details["missing_files"], details
def _check_ux_catalog_enforcement_policy(root: Path, rel_path: str) -> tuple[bool, dict[str, Any]]:
    details: dict[str, Any] = {"invalid_values": [], "missing_files": []}
    policy = _require_json_file(root, rel_path, key="ux_catalog_enforcement_policy")
    if not isinstance(policy, dict):
        details["invalid_values"].append("ux_catalog_enforcement_policy:invalid_json")
        return False, details

    if policy.get("version") != "v1":
        details["invalid_values"].append("ux_catalog_enforcement_policy:version_must_be_v1")
    if policy.get("kind") != "policy-ux-catalog-enforcement":
        details["invalid_values"].append("ux_catalog_enforcement_policy:kind_invalid")
    if policy.get("status") != "ACTIVE":
        details["invalid_values"].append("ux_catalog_enforcement_policy:status_must_be_ACTIVE")
    if policy.get("enforcement_mode") != "blocking":
        details["invalid_values"].append("ux_catalog_enforcement_policy:enforcement_mode_must_be_blocking")
    if str(policy.get("lock_file") or "") != "extensions/PRJ-UX-NORTH-STAR/contract/ux_katalogu.final_lock.v1.json":
        details["invalid_values"].append("ux_catalog_enforcement_policy:lock_file_invalid")

    change_map = policy.get("change_map")
    if not isinstance(change_map, dict):
        details["invalid_values"].append("ux_catalog_enforcement_policy:change_map_missing")
    else:
        if str(change_map.get("path") or "") != "extensions/PRJ-UX-NORTH-STAR/contract/ux_change_map.v1.json":
            details["invalid_values"].append("ux_catalog_enforcement_policy:change_map.path_invalid")
        if int(change_map.get("min_entries") or 0) < 1:
            details["invalid_values"].append("ux_catalog_enforcement_policy:change_map.min_entries_invalid")

    return not details["invalid_values"] and not details["missing_files"], details
def _check_ux_catalog_lock(root: Path, rel_path: str) -> tuple[bool, dict[str, Any]]:
    details: dict[str, Any] = {"invalid_values": [], "missing_files": []}
    lock = _require_json_file(root, rel_path, key="ux_catalog_lock")
    if not isinstance(lock, dict):
        details["invalid_values"].append("ux_catalog_lock:invalid_json")
        return False, details

    if lock.get("version") != "v1":
        details["invalid_values"].append("ux_catalog_lock:version_must_be_v1")
    if lock.get("kind") != "ux-catalog-lock":
        details["invalid_values"].append("ux_catalog_lock:kind_invalid")
    if lock.get("status") != "ACTIVE":
        details["invalid_values"].append("ux_catalog_lock:status_must_be_ACTIVE")
    if str(lock.get("subject_id") or "") != "ux_katalogu":
        details["invalid_values"].append("ux_catalog_lock:subject_id_invalid")
    if int(lock.get("theme_count") or 0) <= 0:
        details["invalid_values"].append("ux_catalog_lock:theme_count_invalid")
    if int(lock.get("subtheme_count") or 0) <= 0:
        details["invalid_values"].append("ux_catalog_lock:subtheme_count_invalid")

    return not details["invalid_values"] and not details["missing_files"], details
def _check_feature_execution_bridge_policy(root: Path, rel_path: str) -> tuple[bool, dict[str, Any]]:
    details: dict[str, Any] = {"invalid_values": [], "missing_files": []}
    policy = _require_json_file(root, rel_path, key="feature_execution_bridge_policy")
    if not isinstance(policy, dict):
        details["invalid_values"].append("feature_execution_bridge_policy:invalid_json")
        return False, details

    if policy.get("version") != "v1":
        details["invalid_values"].append("feature_execution_bridge_policy:version_must_be_v1")
    if policy.get("kind") != "policy-feature-execution-bridge":
        details["invalid_values"].append("feature_execution_bridge_policy:kind_invalid")
    if policy.get("status") != "ACTIVE":
        details["invalid_values"].append("feature_execution_bridge_policy:status_must_be_ACTIVE")
    if policy.get("enforcement_mode") != "blocking":
        details["invalid_values"].append("feature_execution_bridge_policy:enforcement_mode_must_be_blocking")

    expected_paths = {
        "contract_path": "extensions/PRJ-PM-SUITE/contract/feature_execution_contract.v1.json",
        "contract_schema_path": "schemas/feature-execution-contract.schema.v1.json",
        "pm_policy_path": "policies/policy_pm_suite.v1.json",
        "technical_baseline_path": "registry/technical_baseline.aistd.v1.json",
        "ux_lock_path": "extensions/PRJ-UX-NORTH-STAR/contract/ux_katalogu.final_lock.v1.json",
    }
    for key, expected in expected_paths.items():
        if str(policy.get(key) or "") != expected:
            details["invalid_values"].append(f"feature_execution_bridge_policy:{key}_invalid")

    scope_detection = policy.get("scope_detection")
    if not isinstance(scope_detection, dict):
        details["invalid_values"].append("feature_execution_bridge_policy:scope_detection_missing")
    else:
        if not isinstance(scope_detection.get("include_globs"), list) or not scope_detection.get("include_globs"):
            details["invalid_values"].append("feature_execution_bridge_policy:scope_detection.include_globs_invalid")
        if not isinstance(scope_detection.get("exclude_globs"), list):
            details["invalid_values"].append("feature_execution_bridge_policy:scope_detection.exclude_globs_invalid")
        scope_globs = scope_detection.get("scope_globs")
        required_scope_keys = {"backend", "frontend", "database", "api"}
        if not isinstance(scope_globs, dict) or not required_scope_keys.issubset(set(scope_globs.keys())):
            details["invalid_values"].append("feature_execution_bridge_policy:scope_detection.scope_globs_invalid")

    ux_scope = policy.get("ux_scope")
    if not isinstance(ux_scope, dict):
        details["invalid_values"].append("feature_execution_bridge_policy:ux_scope_missing")
    else:
        if not isinstance(ux_scope.get("required_globs"), list) or not ux_scope.get("required_globs"):
            details["invalid_values"].append("feature_execution_bridge_policy:ux_scope.required_globs_invalid")
        if ux_scope.get("require_ux_on_frontend_changes") is not True:
            details["invalid_values"].append(
                "feature_execution_bridge_policy:ux_scope.require_ux_on_frontend_changes_must_be_true"
            )

    validation = policy.get("validation")
    if not isinstance(validation, dict):
        details["invalid_values"].append("feature_execution_bridge_policy:validation_missing")
    else:
        if validation.get("active_status_on_scoped_change") is not True:
            details["invalid_values"].append(
                "feature_execution_bridge_policy:validation.active_status_on_scoped_change_must_be_true"
            )
        if int(validation.get("required_source_refs_min") or 0) < 1:
            details["invalid_values"].append(
                "feature_execution_bridge_policy:validation.required_source_refs_min_invalid"
            )
        if not isinstance(validation.get("placeholder_tokens"), list) or not validation.get("placeholder_tokens"):
            details["invalid_values"].append("feature_execution_bridge_policy:validation.placeholder_tokens_invalid")
        if validation.get("required_execution_sequence_from_lock") is not True:
            details["invalid_values"].append(
                "feature_execution_bridge_policy:validation.required_execution_sequence_from_lock_must_be_true"
            )
        if validation.get("required_lanes_from_lock") is not True:
            details["invalid_values"].append(
                "feature_execution_bridge_policy:validation.required_lanes_from_lock_must_be_true"
            )

    reporting = policy.get("reporting")
    if not isinstance(reporting, dict) or str(reporting.get("out_path") or "") != ".cache/reports/feature_execution_contract_check.v1.json":
        details["invalid_values"].append("feature_execution_bridge_policy:reporting.out_path_invalid")

    return not details["invalid_values"] and not details["missing_files"], details
