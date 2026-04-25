from __future__ import annotations

from pathlib import Path
from typing import Any

from ci.check_standards_lock_parts.constants import (
    REQUIRED_BRANCH_PROTECTION_CHECKS,
    REQUIRED_COMMANDS,
    REQUIRED_DELIVERY_SEQUENCE,
    REQUIRED_FRONTEND_LAYOUT_EXPORTS,
    REQUIRED_GATES,
    REQUIRED_PRESERVE_PATHS,
    REQUIRED_SCOPE_LANE_MAP,
    REQUIRED_STANDARD_SOURCES,
)
from ci.check_standards_lock_parts.helpers import _require_json_file
from ci.check_standards_lock_parts.policy_checks import (
    _check_feature_execution_bridge_policy,
    _check_pm_suite_policy,
    _check_ux_catalog_enforcement_policy,
    _check_ux_catalog_lock,
)
from ci.check_standards_lock_parts.technical_baseline import _check_technical_baseline_aistd

def _check_standard_sources(root: Path, standard_sources: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    details: dict[str, Any] = {"missing_keys": [], "missing_files": [], "invalid_content": []}

    for key in REQUIRED_STANDARD_SOURCES:
        if key not in standard_sources:
            details["missing_keys"].append(key)
    if details["missing_keys"]:
        return False, details

    # Existence check
    for key in REQUIRED_STANDARD_SOURCES:
        rel = standard_sources.get(key)
        if not isinstance(rel, str) or not rel.strip():
            details["invalid_content"].append(f"{key}:path_invalid")
            continue
        if not (root / rel).exists():
            details["missing_files"].append(rel)

    if details["missing_files"] or any(item.endswith(":path_invalid") for item in details["invalid_content"]):
        return False, details

    layer_boundary = _require_json_file(root, str(standard_sources["layer_boundary_policy"]), key="layer_boundary_policy")
    if not isinstance(layer_boundary, dict):
        details["invalid_content"].append("layer_boundary_policy:invalid_json")
    else:
        if layer_boundary.get("enforcement_mode") != "fail_closed":
            details["invalid_content"].append("layer_boundary_policy:enforcement_mode_must_be_fail_closed")
        if layer_boundary.get("workspace_root_required") is not True:
            details["invalid_content"].append("layer_boundary_policy:workspace_root_required_must_be_true")

    llm_live = _require_json_file(root, str(standard_sources["llm_live_policy"]), key="llm_live_policy")
    if not isinstance(llm_live, dict):
        details["invalid_content"].append("llm_live_policy:invalid_json")
    else:
        allowed = llm_live.get("allowed_providers")
        if llm_live.get("live_enabled") is not True:
            details["invalid_content"].append("llm_live_policy:live_enabled_must_be_true")
        if not isinstance(allowed, list) or not allowed:
            details["invalid_content"].append("llm_live_policy:allowed_providers_missing")

    provider_guardrails = _require_json_file(
        root, str(standard_sources["llm_provider_guardrails_policy"]), key="llm_provider_guardrails_policy"
    )
    if not isinstance(provider_guardrails, dict):
        details["invalid_content"].append("llm_provider_guardrails_policy:invalid_json")
    else:
        live_gate = provider_guardrails.get("live_gate")
        if not isinstance(live_gate, dict):
            details["invalid_content"].append("llm_provider_guardrails_policy:live_gate_missing")
        else:
            explicit_env = live_gate.get("explicit_live_flag_env")
            if not isinstance(explicit_env, str) or not explicit_env.strip():
                details["invalid_content"].append("llm_provider_guardrails_policy:explicit_live_flag_env_missing")

    kernel_guardrails = _require_json_file(
        root, str(standard_sources["kernel_api_guardrails_policy"]), key="kernel_api_guardrails_policy"
    )
    if not isinstance(kernel_guardrails, dict):
        details["invalid_content"].append("kernel_api_guardrails_policy:invalid_json")
    else:
        actions = kernel_guardrails.get("actions")
        audit = kernel_guardrails.get("audit")
        if not isinstance(actions, dict) or not isinstance(actions.get("allowlist"), list):
            details["invalid_content"].append("kernel_api_guardrails_policy:actions_allowlist_missing")
        if not isinstance(audit, dict) or audit.get("enabled") is not True:
            details["invalid_content"].append("kernel_api_guardrails_policy:audit_enabled_required")

    ui_design_policy = _require_json_file(root, str(standard_sources["ui_design_system_policy"]), key="ui_design_system_policy")
    if not isinstance(ui_design_policy, dict):
        details["invalid_content"].append("ui_design_system_policy:invalid_json")
    else:
        if ui_design_policy.get("version") != "v1":
            details["invalid_content"].append("ui_design_system_policy:version_must_be_v1")
        if ui_design_policy.get("kind") != "policy-ui-design-system":
            details["invalid_content"].append("ui_design_system_policy:kind_invalid")
        if ui_design_policy.get("status") != "ACTIVE":
            details["invalid_content"].append("ui_design_system_policy:status_must_be_ACTIVE")
        if ui_design_policy.get("enforcement_mode") != "blocking":
            details["invalid_content"].append("ui_design_system_policy:enforcement_mode_must_be_blocking")
        if ui_design_policy.get("ci_lane") != "contract":
            details["invalid_content"].append("ui_design_system_policy:ci_lane_must_be_contract")
        single_ui = ui_design_policy.get("single_ui_library")
        if not isinstance(single_ui, dict):
            details["invalid_content"].append("ui_design_system_policy:single_ui_library_missing")
        else:
            if single_ui.get("package_name") != "mfe-ui-kit":
                details["invalid_content"].append("ui_design_system_policy:single_ui_library.package_name_invalid")
            if str(single_ui.get("package_manifest_path") or "") != "web/packages/ui-kit/package.json":
                details["invalid_content"].append(
                    "ui_design_system_policy:single_ui_library.package_manifest_path_invalid"
                )
            if (
                str(single_ui.get("design_catalog_index_path") or "")
                != "web/apps/mfe-shell/src/pages/admin/design-lab.index.json"
            ):
                details["invalid_content"].append(
                    "ui_design_system_policy:single_ui_library.design_catalog_index_path_invalid"
                )
            forbidden_imports = {
                str(item).strip()
                for item in (
                    single_ui.get("forbidden_imports")
                    if isinstance(single_ui.get("forbidden_imports"), list)
                    else []
                )
                if isinstance(item, str) and str(item).strip()
            }
            if "antd" not in forbidden_imports or "@ant-design/icons" not in forbidden_imports:
                details["invalid_content"].append(
                    "ui_design_system_policy:single_ui_library.forbidden_imports_missing_antd_rules"
                )
        design_tokens = ui_design_policy.get("design_tokens")
        if not isinstance(design_tokens, dict):
            details["invalid_content"].append("ui_design_system_policy:design_tokens_missing")
        else:
            if str(design_tokens.get("source_path") or "") != "web/design-tokens/figma.tokens.json":
                details["invalid_content"].append("ui_design_system_policy:design_tokens.source_path_invalid")
            generated_paths = {
                str(item).strip()
                for item in (
                    design_tokens.get("generated_paths")
                    if isinstance(design_tokens.get("generated_paths"), list)
                    else []
                )
                if isinstance(item, str) and str(item).strip()
            }
            required_generated = {
                "web/apps/mfe-shell/src/styles/theme.css",
                "web/design-tokens/generated/theme-contract.json",
            }
            missing_generated = sorted(required_generated - generated_paths)
            if missing_generated:
                details["invalid_content"].append(
                    "ui_design_system_policy:design_tokens.generated_paths_missing_" + ",".join(missing_generated)
                )
        page_modularity = ui_design_policy.get("page_modularity")
        if not isinstance(page_modularity, dict):
            details["invalid_content"].append("ui_design_system_policy:page_modularity_missing")
        else:
            layout_exports = {
                str(item).strip()
                for item in (
                    page_modularity.get("layout_exports_required")
                    if isinstance(page_modularity.get("layout_exports_required"), list)
                    else []
                )
                if isinstance(item, str) and str(item).strip()
            }
            missing_layout_exports = [name for name in REQUIRED_FRONTEND_LAYOUT_EXPORTS if name not in layout_exports]
            if missing_layout_exports:
                details["invalid_content"].append(
                    "ui_design_system_policy:page_modularity.layout_exports_required_missing_"
                    + ",".join(missing_layout_exports)
                )
            if str(page_modularity.get("ui_usage_import_prefix") or "") != "from 'mfe-ui-kit'":
                details["invalid_content"].append("ui_design_system_policy:page_modularity.ui_usage_import_prefix_invalid")
            if str(page_modularity.get("pages_root") or "") != "web/apps":
                details["invalid_content"].append("ui_design_system_policy:page_modularity.pages_root_invalid")
        parametric_data = ui_design_policy.get("parametric_data")
        if not isinstance(parametric_data, dict):
            details["invalid_content"].append("ui_design_system_policy:parametric_data_missing")
        else:
            if (
                str(parametric_data.get("query_builder_path") or "")
                != "web/packages/ui-kit/src/components/entity-grid/buildEntityGridQueryParams.ts"
            ):
                details["invalid_content"].append("ui_design_system_policy:parametric_data.query_builder_path_invalid")
            if (
                str(parametric_data.get("theme_contract_runtime_path") or "")
                != "web/packages/ui-kit/src/runtime/theme-contract.ts"
            ):
                details["invalid_content"].append(
                    "ui_design_system_policy:parametric_data.theme_contract_runtime_path_invalid"
                )
            if (
                str(parametric_data.get("theme_context_provider_path") or "")
                != "web/apps/mfe-shell/src/app/theme/theme-context.provider.tsx"
            ):
                details["invalid_content"].append(
                    "ui_design_system_policy:parametric_data.theme_context_provider_path_invalid"
                )

    security = _require_json_file(root, str(standard_sources["security_policy"]), key="security_policy")
    if not isinstance(security, dict):
        details["invalid_content"].append("security_policy:invalid_json")
    else:
        if security.get("network_access") is not False:
            details["invalid_content"].append("security_policy:network_access_must_be_false")
        allowlist = security.get("network_allowlist")
        if not isinstance(allowlist, list) or not allowlist:
            details["invalid_content"].append("security_policy:network_allowlist_missing")

    secrets = _require_json_file(root, str(standard_sources["secrets_policy"]), key="secrets_policy")
    if not isinstance(secrets, dict):
        details["invalid_content"].append("secrets_policy:invalid_json")
    else:
        allowed_ids = secrets.get("allowed_secret_ids")
        if not isinstance(allowed_ids, list) or not allowed_ids:
            details["invalid_content"].append("secrets_policy:allowed_secret_ids_missing")

    technical_rel = str(standard_sources["technical_baseline_aistd"])
    tech_ok, tech_details = _check_technical_baseline_aistd(root, technical_rel)
    if not tech_ok:
        for item in tech_details.get("invalid_values", []):
            details["invalid_content"].append(item)
        for item in tech_details.get("missing_files", []):
            details["missing_files"].append(item)

    pm_ok, pm_details = _check_pm_suite_policy(root, str(standard_sources["pm_suite_policy"]))
    if not pm_ok:
        for item in pm_details.get("invalid_values", []):
            details["invalid_content"].append(item)
        for item in pm_details.get("missing_files", []):
            details["missing_files"].append(item)

    ux_policy_ok, ux_policy_details = _check_ux_catalog_enforcement_policy(
        root, str(standard_sources["ux_catalog_enforcement_policy"])
    )
    if not ux_policy_ok:
        for item in ux_policy_details.get("invalid_values", []):
            details["invalid_content"].append(item)
        for item in ux_policy_details.get("missing_files", []):
            details["missing_files"].append(item)

    ux_lock_ok, ux_lock_details = _check_ux_catalog_lock(root, str(standard_sources["ux_catalog_lock"]))
    if not ux_lock_ok:
        for item in ux_lock_details.get("invalid_values", []):
            details["invalid_content"].append(item)
        for item in ux_lock_details.get("missing_files", []):
            details["missing_files"].append(item)

    feature_bridge_ok, feature_bridge_details = _check_feature_execution_bridge_policy(
        root, str(standard_sources["feature_execution_bridge_policy"])
    )
    if not feature_bridge_ok:
        for item in feature_bridge_details.get("invalid_values", []):
            details["invalid_content"].append(item)
        for item in feature_bridge_details.get("missing_files", []):
            details["missing_files"].append(item)

    # Test quality policy (PRJ-TEST-QUALITY-GATE)
    tq_policy = _require_json_file(root, str(standard_sources.get("test_quality_policy", "")), key="test_quality_policy")
    if not isinstance(tq_policy, dict):
        details["invalid_content"].append("test_quality_policy:invalid_json")
    else:
        if tq_policy.get("version") != "v1":
            details["invalid_content"].append("test_quality_policy:version_must_be_v1")
        if tq_policy.get("status") != "ACTIVE":
            details["invalid_content"].append("test_quality_policy:status_must_be_ACTIVE")
        rules = tq_policy.get("rules")
        if not isinstance(rules, list) or len(rules) < 6:
            details["invalid_content"].append("test_quality_policy:must_have_at_least_6_rules")
        thresholds = tq_policy.get("thresholds")
        if not isinstance(thresholds, dict):
            details["invalid_content"].append("test_quality_policy:thresholds_missing")

    ok = not details["missing_keys"] and not details["missing_files"] and not details["invalid_content"]
    return ok, details


def _check_required_commands(required_commands: Any) -> tuple[bool, dict[str, Any]]:
    details: dict[str, Any] = {"missing_commands": []}
    if not isinstance(required_commands, list):
        details["missing_commands"] = list(REQUIRED_COMMANDS)
        return False, details

    cmd_set = {str(item) for item in required_commands if isinstance(item, str)}
    for cmd in REQUIRED_COMMANDS:
        if cmd not in cmd_set:
            details["missing_commands"].append(cmd)
    return not details["missing_commands"], details
def _check_managed_repo_sync(root: Path, section: Any) -> tuple[bool, dict[str, Any]]:
    details: dict[str, Any] = {"missing_keys": [], "invalid_values": [], "missing_files": []}
    if not isinstance(section, dict):
        details["invalid_values"].append("managed_repo_sync:not_object")
        return False, details

    required_keys = (
        "default_mode",
        "script",
        "source_of_truth",
        "apply_requires_flag",
        "validation_command_template",
        "preserve_existing_paths",
    )
    for key in required_keys:
        if key not in section:
            details["missing_keys"].append(key)
    if details["missing_keys"]:
        return False, details

    if section.get("default_mode") != "dry-run":
        details["invalid_values"].append("default_mode:must_be_dry-run")
    if section.get("source_of_truth") != "standards.lock":
        details["invalid_values"].append("source_of_truth:must_be_standards.lock")
    if section.get("apply_requires_flag") is not True:
        details["invalid_values"].append("apply_requires_flag:must_be_true")

    script_rel = section.get("script")
    if not isinstance(script_rel, str) or not script_rel.strip():
        details["invalid_values"].append("script:path_invalid")
    else:
        script_path = root / script_rel
        if not script_path.exists():
            details["missing_files"].append(script_rel)

    validation_tmpl = section.get("validation_command_template")
    if not isinstance(validation_tmpl, str) or "<repo_root>" not in validation_tmpl:
        details["invalid_values"].append("validation_command_template:repo_root_placeholder_required")

    preserve_paths = section.get("preserve_existing_paths")
    if not isinstance(preserve_paths, list):
        details["invalid_values"].append("preserve_existing_paths:must_be_list")
    else:
        preserve_set = {str(item) for item in preserve_paths if isinstance(item, str)}
        for required_path in REQUIRED_PRESERVE_PATHS:
            if required_path not in preserve_set:
                details["invalid_values"].append(f"preserve_existing_paths:missing_{required_path}")

    ok = not details["missing_keys"] and not details["invalid_values"] and not details["missing_files"]
    return ok, details
def _check_module_delivery_contract(section: Any) -> tuple[bool, dict[str, Any]]:
    details: dict[str, Any] = {"missing_keys": [], "invalid_values": []}
    if not isinstance(section, dict):
        details["invalid_values"].append("module_delivery_contract:not_object")
        return False, details

    required_keys = (
        "service_scopes",
        "required_test_lanes",
        "delivery_sequence",
        "scope_lane_map",
        "merge_requires_all_green",
    )
    for key in required_keys:
        if key not in section:
            details["missing_keys"].append(key)
    if details["missing_keys"]:
        return False, details

    service_scopes = section.get("service_scopes")
    if not isinstance(service_scopes, list) or not service_scopes:
        details["invalid_values"].append("service_scopes:must_be_nonempty_list")
    else:
        expected = {"backend", "frontend", "database", "api"}
        actual = {str(item) for item in service_scopes}
        missing = sorted(expected - actual)
        if missing:
            details["invalid_values"].append(f"service_scopes:missing_{','.join(missing)}")

    lanes = section.get("required_test_lanes")
    if not isinstance(lanes, list) or not lanes:
        details["invalid_values"].append("required_test_lanes:must_be_nonempty_list")
    else:
        expected_lanes = {"unit", "database", "api", "contract", "integration", "e2e"}
        actual_lanes = {str(item) for item in lanes}
        missing_lanes = sorted(expected_lanes - actual_lanes)
        if missing_lanes:
            details["invalid_values"].append(f"required_test_lanes:missing_{','.join(missing_lanes)}")

    delivery_sequence = section.get("delivery_sequence")
    if not isinstance(delivery_sequence, list) or not delivery_sequence:
        details["invalid_values"].append("delivery_sequence:must_be_nonempty_list")
    else:
        actual_sequence = [str(item) for item in delivery_sequence]
        if actual_sequence != list(REQUIRED_DELIVERY_SEQUENCE):
            details["invalid_values"].append(
                f"delivery_sequence:must_equal_{','.join(REQUIRED_DELIVERY_SEQUENCE)}"
            )

    scope_lane_map = section.get("scope_lane_map")
    if not isinstance(scope_lane_map, dict):
        details["invalid_values"].append("scope_lane_map:must_be_object")
    else:
        for scope, expected_lane in REQUIRED_SCOPE_LANE_MAP.items():
            actual_lane = scope_lane_map.get(scope)
            if actual_lane != expected_lane:
                details["invalid_values"].append(
                    f"scope_lane_map:{scope}_must_map_to_{expected_lane}"
                )

    if section.get("merge_requires_all_green") is not True:
        details["invalid_values"].append("merge_requires_all_green:must_be_true")

    ok = not details["missing_keys"] and not details["invalid_values"]
    return ok, details
def _check_branch_protection(section: Any) -> tuple[bool, dict[str, Any]]:
    details: dict[str, Any] = {"missing_keys": [], "invalid_values": []}
    if not isinstance(section, dict):
        details["invalid_values"].append("branch_protection:not_object")
        return False, details

    required_keys = ("default_branch", "required_checks", "verification_mode")
    for key in required_keys:
        if key not in section:
            details["missing_keys"].append(key)
    if details["missing_keys"]:
        return False, details

    default_branch = section.get("default_branch")
    if not isinstance(default_branch, str) or not default_branch.strip():
        details["invalid_values"].append("default_branch:must_be_nonempty_string")

    verification_mode = section.get("verification_mode")
    if verification_mode not in {"live_evidence", "report_only"}:
        details["invalid_values"].append("verification_mode:must_be_live_evidence_or_report_only")

    required_checks = section.get("required_checks")
    if not isinstance(required_checks, list) or not required_checks:
        details["invalid_values"].append("required_checks:must_be_nonempty_list")
    else:
        checks_set = {str(item) for item in required_checks if isinstance(item, str) and str(item).strip()}
        for required_check in REQUIRED_BRANCH_PROTECTION_CHECKS:
            if required_check not in checks_set:
                details["invalid_values"].append(f"required_checks:missing_{required_check}")

    ok = not details["missing_keys"] and not details["invalid_values"]
    return ok, details
def _check_solo_developer_policy(section: Any) -> tuple[bool, dict[str, Any]]:
    details: dict[str, Any] = {"missing_keys": [], "invalid_values": []}
    if not isinstance(section, dict):
        details["invalid_values"].append("solo_developer_policy:not_object")
        return False, details

    required_keys = (
        "enabled",
        "single_writer_requires_review_count",
        "single_writer_require_code_owner_reviews",
        "multi_writer_min_review_count",
        "multi_writer_require_code_owner_reviews",
        "strict_required_status_checks",
        "enforce_admins_required",
    )
    for key in required_keys:
        if key not in section:
            details["missing_keys"].append(key)
    if details["missing_keys"]:
        return False, details

    if section.get("enabled") is not True:
        details["invalid_values"].append("enabled:must_be_true")

    single_reviews = section.get("single_writer_requires_review_count")
    if not isinstance(single_reviews, int) or single_reviews != 0:
        details["invalid_values"].append("single_writer_requires_review_count:must_be_0")

    single_code_owner = section.get("single_writer_require_code_owner_reviews")
    if single_code_owner is not False:
        details["invalid_values"].append("single_writer_require_code_owner_reviews:must_be_false")

    multi_reviews = section.get("multi_writer_min_review_count")
    if not isinstance(multi_reviews, int) or multi_reviews < 1:
        details["invalid_values"].append("multi_writer_min_review_count:must_be_int_gte_1")

    multi_code_owner = section.get("multi_writer_require_code_owner_reviews")
    if multi_code_owner is not True:
        details["invalid_values"].append("multi_writer_require_code_owner_reviews:must_be_true")

    if section.get("strict_required_status_checks") is not True:
        details["invalid_values"].append("strict_required_status_checks:must_be_true")
    if section.get("enforce_admins_required") is not True:
        details["invalid_values"].append("enforce_admins_required:must_be_true")

    ok = not details["missing_keys"] and not details["invalid_values"]
    return ok, details
def _check_enforcement_workflow(root: Path) -> tuple[bool, dict[str, Any]]:
    details: dict[str, Any] = {"issues": []}
    wf_path = root / ".github/workflows/gate-enforcement-check.yml"
    text = wf_path.read_text(encoding="utf-8")
    if "Standards lock + ownership baseline" not in text:
        details["issues"].append("standards_lock_step_missing")
    if "python3 ci/check_standards_lock.py" not in text:
        details["issues"].append("standards_lock_command_missing")
    if "Work intake policy modularization contract" not in text:
        details["issues"].append("work_intake_modularization_step_missing")
    if "python3 extensions/PRJ-WORK-INTAKE/check_policy_work_intake_modularization.py --repo-root ." not in text:
        details["issues"].append("work_intake_modularization_command_missing")
    if "Coverage visibility (report-only)" not in text:
        details["issues"].append("coverage_visibility_step_missing")
    if "python3 extensions/PRJ-OBSERVABILITY-OTEL/coverage_visibility_report.py" not in text:
        details["issues"].append("coverage_visibility_command_missing")
    if "Observability coverage matrix" not in text:
        details["issues"].append("observability_matrix_step_missing")
    if "python3 extensions/PRJ-OBSERVABILITY-OTEL/export_observability_coverage_matrix.py" not in text:
        details["issues"].append("observability_matrix_command_missing")
    if "Feature execution bridge gate" not in text:
        details["issues"].append("feature_execution_bridge_step_missing")
    if "python3 extensions/PRJ-PM-SUITE/contract/check_feature_execution_contract.py" not in text:
        details["issues"].append("feature_execution_bridge_command_missing")
    if "Delivery session packet build" not in text:
        details["issues"].append("delivery_session_packet_step_missing")
    if "python3 extensions/PRJ-PM-SUITE/contract/build_delivery_session_packet.py" not in text:
        details["issues"].append("delivery_session_packet_command_missing")
    if "Delivery session guard" not in text:
        details["issues"].append("delivery_session_guard_step_missing")
    if "python3 extensions/PRJ-PM-SUITE/contract/check_delivery_session_guard.py" not in text:
        details["issues"].append("delivery_session_guard_command_missing")
    if "Enforcement check (PR strict)" not in text:
        details["issues"].append("pr_strict_step_missing")
    if "continue-on-error: true" in text:
        details["issues"].append("pr_advisory_mode_detected")
    return not details["issues"], details
def _check_module_delivery_workflow(root: Path) -> tuple[bool, dict[str, Any]]:
    details: dict[str, Any] = {"issues": []}
    wf_path = root / ".github/workflows/module-delivery-lanes.yml"
    text = wf_path.read_text(encoding="utf-8")
    required_markers = (
        "module-delivery-contract-check",
        "module-lane-unit",
        "module-lane-database",
        "module-lane-api",
        "module-lane-contract",
        "module-lane-integration",
        "module-lane-e2e",
        "module-delivery-gate",
        "python3 ci/check_module_delivery_lanes.py --strict",
        "python3 extensions/PRJ-PM-SUITE/contract/check_feature_execution_contract.py",
        "python3 extensions/PRJ-PM-SUITE/contract/build_delivery_session_packet.py",
        "python3 extensions/PRJ-PM-SUITE/contract/check_delivery_session_guard.py",
        "python3 ci/run_module_delivery_lane.py --lane unit",
        "python3 ci/run_module_delivery_lane.py --lane database",
        "python3 ci/run_module_delivery_lane.py --lane api",
        "python3 ci/run_module_delivery_lane.py --lane contract",
        "python3 ci/run_module_delivery_lane.py --lane integration",
        "python3 ci/run_module_delivery_lane.py --lane e2e",
    )
    for marker in required_markers:
        if marker not in text:
            details["issues"].append(f"missing:{marker}")
    required_sequence_markers = (
        "module-lane-database:\n    runs-on: ubuntu-latest\n    needs: [module-lane-unit]",
        "module-lane-api:\n    runs-on: ubuntu-latest\n    needs: [module-lane-database]",
        "module-lane-contract:\n    runs-on: ubuntu-latest\n    needs: [module-lane-api]",
        "module-lane-integration:\n    runs-on: ubuntu-latest\n    needs: [module-lane-contract]",
        "module-lane-e2e:\n    runs-on: ubuntu-latest\n    needs: [module-lane-integration]",
    )
    for marker in required_sequence_markers:
        if marker not in text:
            details["issues"].append(f"missing_sequence:{marker}")
    if "needs.module-lane-unit.result" not in text:
        details["issues"].append("gate_job_result_check_missing")
    if "needs.module-lane-database.result" not in text:
        details["issues"].append("gate_job_database_result_check_missing")
    if "needs.module-lane-api.result" not in text:
        details["issues"].append("gate_job_api_result_check_missing")
    if "needs.module-lane-contract.result" not in text:
        details["issues"].append("gate_job_contract_result_check_missing")
    if "needs.module-lane-integration.result" not in text:
        details["issues"].append("gate_job_integration_result_check_missing")
    if "needs.module-lane-e2e.result" not in text:
        details["issues"].append("gate_job_e2e_result_check_missing")
    return not details["issues"], details
