from __future__ import annotations

from pathlib import Path
from typing import Any

from check_standards_lock_shared import (
    REQUIRED_BACKEND_LAYERS,
    REQUIRED_DELIVERY_SEQUENCE,
    REQUIRED_FRONTEND_LAYOUT_EXPORTS,
    REQUIRED_LANES,
    REQUIRED_STANDARD_SOURCES,
    _require_json_file,
)


def _check_pm_suite_policy(root: Path, rel_path: str) -> tuple[bool, dict[str, Any]]:
    details: dict[str, Any] = {"invalid_values": [], "missing_files": []}
    policy = _require_json_file(root, rel_path)
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
    policy = _require_json_file(root, rel_path)
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
    lock = _require_json_file(root, rel_path)
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
    policy = _require_json_file(root, rel_path)
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
        if validation.get("required_execution_sequence_from_lock") is not True:
            details["invalid_values"].append(
                "feature_execution_bridge_policy:validation.required_execution_sequence_from_lock_must_be_true"
            )
        if validation.get("required_lanes_from_lock") is not True:
            details["invalid_values"].append(
                "feature_execution_bridge_policy:validation.required_lanes_from_lock_must_be_true"
            )
        placeholder_tokens = validation.get("placeholder_tokens")
        if not isinstance(placeholder_tokens, list) or not placeholder_tokens:
            details["invalid_values"].append("feature_execution_bridge_policy:validation.placeholder_tokens_invalid")

    return not details["invalid_values"] and not details["missing_files"], details


def _check_technical_baseline_aistd(root: Path, rel_path: str) -> tuple[bool, dict[str, Any]]:
    details: dict[str, Any] = {"invalid_values": [], "missing_files": []}
    baseline = _require_json_file(root, rel_path)
    if not isinstance(baseline, dict):
        details["invalid_values"].append("technical_baseline_aistd:invalid_json")
        return False, details

    if baseline.get("version") != "v1":
        details["invalid_values"].append("technical_baseline_aistd:version_must_be_v1")
    if baseline.get("kind") != "technical-baseline-aistd":
        details["invalid_values"].append("technical_baseline_aistd:kind_must_be_technical-baseline-aistd")
    if baseline.get("status") != "ACTIVE":
        details["invalid_values"].append("technical_baseline_aistd:status_must_be_ACTIVE")

    ownership = baseline.get("ownership")
    if not isinstance(ownership, dict):
        details["invalid_values"].append("technical_baseline_aistd:ownership_missing")
    else:
        if str(ownership.get("sync_script") or "") != "scripts/sync_managed_repo_standards.py":
            details["invalid_values"].append("technical_baseline_aistd:ownership.sync_script_invalid")
        if str(ownership.get("validation_script") or "") != "ci/check_standards_lock.py":
            details["invalid_values"].append("technical_baseline_aistd:ownership.validation_script_invalid")

    baseline_obj = baseline.get("baseline")
    if not isinstance(baseline_obj, dict):
        details["invalid_values"].append("technical_baseline_aistd:baseline_missing")
        return False, details

    backend = baseline_obj.get("backend")
    if not isinstance(backend, dict):
        details["invalid_values"].append("technical_baseline_aistd:baseline.backend_missing")
    else:
        if backend.get("language") != "java":
            details["invalid_values"].append("technical_baseline_aistd:backend.language_must_be_java")
        if int(backend.get("java_major") or 0) < 21:
            details["invalid_values"].append("technical_baseline_aistd:backend.java_major_must_be_gte_21")
        if backend.get("framework") != "spring-boot":
            details["invalid_values"].append("technical_baseline_aistd:backend.framework_must_be_spring-boot")
        if backend.get("service_architecture") != "microservice":
            details["invalid_values"].append("technical_baseline_aistd:backend.service_architecture_must_be_microservice")
        layer_set = {
            str(item).strip()
            for item in (backend.get("required_layers") if isinstance(backend.get("required_layers"), list) else [])
            if isinstance(item, str) and str(item).strip()
        }
        missing_layers = [name for name in REQUIRED_BACKEND_LAYERS if name not in layer_set]
        if missing_layers:
            details["invalid_values"].append(
                "technical_baseline_aistd:backend.required_layers_missing_" + ",".join(missing_layers)
            )
        comm_set = {
            str(item).strip()
            for item in (
                backend.get("inter_service_communication")
                if isinstance(backend.get("inter_service_communication"), list)
                else []
            )
            if isinstance(item, str) and str(item).strip()
        }
        if "rest" not in comm_set or "event" not in comm_set:
            details["invalid_values"].append(
                "technical_baseline_aistd:backend.inter_service_communication_must_include_rest_event"
            )

    frontend = baseline_obj.get("frontend")
    if not isinstance(frontend, dict):
        details["invalid_values"].append("technical_baseline_aistd:baseline.frontend_missing")
    else:
        if frontend.get("language") != "typescript":
            details["invalid_values"].append("technical_baseline_aistd:frontend.language_must_be_typescript")
        if frontend.get("framework") != "react":
            details["invalid_values"].append("technical_baseline_aistd:frontend.framework_must_be_react")
        if int(frontend.get("node_major") or 0) != 22:
            details["invalid_values"].append("technical_baseline_aistd:frontend.node_major_must_be_22")
        if frontend.get("package_manager") != "npm":
            details["invalid_values"].append("technical_baseline_aistd:frontend.package_manager_must_be_npm")

        design_contract = frontend.get("design_contract")
        if not isinstance(design_contract, dict):
            details["invalid_values"].append("technical_baseline_aistd:frontend.design_contract_missing")
        else:
            if design_contract.get("single_ui_library") != "mfe-ui-kit":
                details["invalid_values"].append("technical_baseline_aistd:frontend.design_contract.single_ui_library_invalid")
            if str(design_contract.get("ui_package_manifest_path") or "") != "web/packages/ui-kit/package.json":
                details["invalid_values"].append(
                    "technical_baseline_aistd:frontend.design_contract.ui_package_manifest_path_invalid"
                )
            if (
                str(design_contract.get("design_catalog_index_path") or "")
                != "web/apps/mfe-shell/src/pages/admin/design-lab.index.json"
            ):
                details["invalid_values"].append(
                    "technical_baseline_aistd:frontend.design_contract.design_catalog_index_path_invalid"
                )
            if str(design_contract.get("token_source_path") or "") != "web/design-tokens/figma.tokens.json":
                details["invalid_values"].append(
                    "technical_baseline_aistd:frontend.design_contract.token_source_path_invalid"
                )
            forbidden_imports = {
                str(item).strip()
                for item in (
                    design_contract.get("forbidden_imports")
                    if isinstance(design_contract.get("forbidden_imports"), list)
                    else []
                )
                if isinstance(item, str) and str(item).strip()
            }
            if "antd" not in forbidden_imports or "@ant-design/icons" not in forbidden_imports:
                details["invalid_values"].append(
                    "technical_baseline_aistd:frontend.design_contract.forbidden_imports_missing_antd_rules"
                )
            generated_paths = {
                str(item).strip()
                for item in (
                    design_contract.get("token_generated_paths")
                    if isinstance(design_contract.get("token_generated_paths"), list)
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
                details["invalid_values"].append(
                    "technical_baseline_aistd:frontend.design_contract.token_generated_paths_missing_"
                    + ",".join(missing_generated)
                )

        page_composition = frontend.get("page_composition")
        if not isinstance(page_composition, dict):
            details["invalid_values"].append("technical_baseline_aistd:frontend.page_composition_missing")
        else:
            layout_exports = {
                str(item).strip()
                for item in (
                    page_composition.get("required_layout_exports")
                    if isinstance(page_composition.get("required_layout_exports"), list)
                    else []
                )
                if isinstance(item, str) and str(item).strip()
            }
            missing_layout_exports = [name for name in REQUIRED_FRONTEND_LAYOUT_EXPORTS if name not in layout_exports]
            if missing_layout_exports:
                details["invalid_values"].append(
                    "technical_baseline_aistd:frontend.page_composition.required_layout_exports_missing_"
                    + ",".join(missing_layout_exports)
                )
            if str(page_composition.get("ui_import_prefix") or "") != "from 'mfe-ui-kit'":
                details["invalid_values"].append(
                    "technical_baseline_aistd:frontend.page_composition.ui_import_prefix_invalid"
                )
            if str(page_composition.get("pages_root") or "") != "web/apps":
                details["invalid_values"].append("technical_baseline_aistd:frontend.page_composition.pages_root_invalid")

        parametric_data = frontend.get("parametric_data")
        if not isinstance(parametric_data, dict):
            details["invalid_values"].append("technical_baseline_aistd:frontend.parametric_data_missing")
        else:
            if (
                str(parametric_data.get("query_builder_path") or "")
                != "web/packages/ui-kit/src/components/entity-grid/buildEntityGridQueryParams.ts"
            ):
                details["invalid_values"].append(
                    "technical_baseline_aistd:frontend.parametric_data.query_builder_path_invalid"
                )
            if (
                str(parametric_data.get("theme_contract_runtime_path") or "")
                != "web/packages/ui-kit/src/runtime/theme-contract.ts"
            ):
                details["invalid_values"].append(
                    "technical_baseline_aistd:frontend.parametric_data.theme_contract_runtime_path_invalid"
                )
            if (
                str(parametric_data.get("theme_context_provider_path") or "")
                != "web/apps/mfe-shell/src/app/theme/theme-context.provider.tsx"
            ):
                details["invalid_values"].append(
                    "technical_baseline_aistd:frontend.parametric_data.theme_context_provider_path_invalid"
                )

    database = baseline_obj.get("database")
    if not isinstance(database, dict):
        details["invalid_values"].append("technical_baseline_aistd:baseline.database_missing")
    else:
        if database.get("engine") != "postgresql":
            details["invalid_values"].append("technical_baseline_aistd:database.engine_must_be_postgresql")
        if database.get("migration_tool") != "flyway":
            details["invalid_values"].append("technical_baseline_aistd:database.migration_tool_must_be_flyway")

    api = baseline_obj.get("api")
    if not isinstance(api, dict):
        details["invalid_values"].append("technical_baseline_aistd:baseline.api_missing")
    else:
        if api.get("protocol") != "rest":
            details["invalid_values"].append("technical_baseline_aistd:api.protocol_must_be_rest")
        if api.get("version_prefix") != "/api/v1":
            details["invalid_values"].append("technical_baseline_aistd:api.version_prefix_must_be_/api/v1")
        if api.get("auth_scheme") != "bearer-jwt":
            details["invalid_values"].append("technical_baseline_aistd:api.auth_scheme_must_be_bearer-jwt")
        fields = {
            str(item).strip()
            for item in (api.get("error_envelope_fields") if isinstance(api.get("error_envelope_fields"), list) else [])
            if isinstance(item, str) and str(item).strip()
        }
        missing_fields = sorted({"code", "message", "timestamp", "path"} - fields)
        if missing_fields:
            details["invalid_values"].append(
                f"technical_baseline_aistd:api.error_envelope_fields_missing_{','.join(missing_fields)}"
            )

    topology = baseline.get("topology")
    if not isinstance(topology, dict):
        details["invalid_values"].append("technical_baseline_aistd:topology_missing")
    else:
        if topology.get("edge_gateway") != "spring-cloud-gateway":
            details["invalid_values"].append("technical_baseline_aistd:topology.edge_gateway_invalid")
        if topology.get("service_discovery") != "eureka":
            details["invalid_values"].append("technical_baseline_aistd:topology.service_discovery_invalid")

    ci_contract = baseline.get("ci_contract")
    if not isinstance(ci_contract, dict):
        details["invalid_values"].append("technical_baseline_aistd:ci_contract_missing")
    else:
        actual_sequence = [str(item) for item in (ci_contract.get("delivery_sequence") or [])]
        if actual_sequence != list(REQUIRED_DELIVERY_SEQUENCE):
            details["invalid_values"].append(
                f"technical_baseline_aistd:ci_contract.delivery_sequence_must_equal_{','.join(REQUIRED_DELIVERY_SEQUENCE)}"
            )
        lane_set = {
            str(item).strip()
            for item in (ci_contract.get("required_lanes") if isinstance(ci_contract.get("required_lanes"), list) else [])
            if isinstance(item, str) and str(item).strip()
        }
        missing_lanes = [name for name in REQUIRED_LANES if name not in lane_set]
        if missing_lanes:
            details["invalid_values"].append(
                f"technical_baseline_aistd:ci_contract.required_lanes_missing_{','.join(missing_lanes)}"
            )
        if ci_contract.get("gate_name") != "module-delivery-gate":
            details["invalid_values"].append("technical_baseline_aistd:ci_contract.gate_name_invalid")
        if ci_contract.get("merge_requires_all_green") is not True:
            details["invalid_values"].append("technical_baseline_aistd:ci_contract.merge_requires_all_green_must_be_true")

    archive = baseline.get("archive")
    if not isinstance(archive, dict):
        details["invalid_values"].append("technical_baseline_aistd:archive_missing")
    else:
        if archive.get("legacy_mode") != "read-only":
            details["invalid_values"].append("technical_baseline_aistd:archive.legacy_mode_must_be_read-only")
        manifest_rel = str(archive.get("legacy_manifest_path") or "")
        if manifest_rel != "registry/archives/legacy_standards_archive.aistd.v1.json":
            details["invalid_values"].append("technical_baseline_aistd:archive.legacy_manifest_path_invalid")
        else:
            manifest_path = root / manifest_rel
            if not manifest_path.exists():
                details["missing_files"].append(manifest_rel)
            else:
                manifest_obj = _require_json_file(root, manifest_rel)
                if not isinstance(manifest_obj, dict):
                    details["invalid_values"].append("technical_baseline_aistd:archive.manifest_invalid_json")
                else:
                    if manifest_obj.get("kind") != "legacy-standards-archive-aistd":
                        details["invalid_values"].append("technical_baseline_aistd:archive.manifest_kind_invalid")
                    if manifest_obj.get("version") != "v1":
                        details["invalid_values"].append("technical_baseline_aistd:archive.manifest_version_invalid")

    ok = not details["invalid_values"] and not details["missing_files"]
    return ok, details


def _check_standard_sources(root: Path, standard_sources: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    details: dict[str, Any] = {"missing_keys": [], "missing_files": [], "invalid_content": []}

    for key in REQUIRED_STANDARD_SOURCES:
        if key not in standard_sources:
            details["missing_keys"].append(key)
    if details["missing_keys"]:
        return False, details

    for key in REQUIRED_STANDARD_SOURCES:
        rel = standard_sources.get(key)
        if not isinstance(rel, str) or not rel.strip():
            details["invalid_content"].append(f"{key}:path_invalid")
            continue
        if not (root / rel).exists():
            details["missing_files"].append(rel)

    if details["missing_files"] or any(item.endswith(":path_invalid") for item in details["invalid_content"]):
        return False, details

    layer_boundary = _require_json_file(root, str(standard_sources["layer_boundary_policy"]))
    if not isinstance(layer_boundary, dict):
        details["invalid_content"].append("layer_boundary_policy:invalid_json")
    else:
        if layer_boundary.get("enforcement_mode") != "fail_closed":
            details["invalid_content"].append("layer_boundary_policy:enforcement_mode_must_be_fail_closed")
        if layer_boundary.get("workspace_root_required") is not True:
            details["invalid_content"].append("layer_boundary_policy:workspace_root_required_must_be_true")

    llm_live = _require_json_file(root, str(standard_sources["llm_live_policy"]))
    if not isinstance(llm_live, dict):
        details["invalid_content"].append("llm_live_policy:invalid_json")
    else:
        allowed = llm_live.get("allowed_providers")
        if llm_live.get("live_enabled") is not True:
            details["invalid_content"].append("llm_live_policy:live_enabled_must_be_true")
        if not isinstance(allowed, list) or not allowed:
            details["invalid_content"].append("llm_live_policy:allowed_providers_missing")

    provider_guardrails = _require_json_file(root, str(standard_sources["llm_provider_guardrails_policy"]))
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

    kernel_guardrails = _require_json_file(root, str(standard_sources["kernel_api_guardrails_policy"]))
    if not isinstance(kernel_guardrails, dict):
        details["invalid_content"].append("kernel_api_guardrails_policy:invalid_json")
    else:
        actions = kernel_guardrails.get("actions")
        audit = kernel_guardrails.get("audit")
        if not isinstance(actions, dict) or not isinstance(actions.get("allowlist"), list):
            details["invalid_content"].append("kernel_api_guardrails_policy:actions_allowlist_missing")
        if not isinstance(audit, dict) or audit.get("enabled") is not True:
            details["invalid_content"].append("kernel_api_guardrails_policy:audit_enabled_required")

    ui_design_policy = _require_json_file(root, str(standard_sources["ui_design_system_policy"]))
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
                    single_ui.get("forbidden_imports") if isinstance(single_ui.get("forbidden_imports"), list) else []
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
                    design_tokens.get("generated_paths") if isinstance(design_tokens.get("generated_paths"), list) else []
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

    security = _require_json_file(root, str(standard_sources["security_policy"]))
    if not isinstance(security, dict):
        details["invalid_content"].append("security_policy:invalid_json")
    else:
        if security.get("network_access") is not False:
            details["invalid_content"].append("security_policy:network_access_must_be_false")
        allowlist = security.get("network_allowlist")
        if not isinstance(allowlist, list) or not allowlist:
            details["invalid_content"].append("security_policy:network_allowlist_missing")

    secrets = _require_json_file(root, str(standard_sources["secrets_policy"]))
    if not isinstance(secrets, dict):
        details["invalid_content"].append("secrets_policy:invalid_json")
    else:
        allowed_ids = secrets.get("allowed_secret_ids")
        if not isinstance(allowed_ids, list) or not allowed_ids:
            details["invalid_content"].append("secrets_policy:allowed_secret_ids_missing")

    for ok, payload in (
        _check_pm_suite_policy(root, str(standard_sources["pm_suite_policy"])),
        _check_feature_execution_bridge_policy(root, str(standard_sources["feature_execution_bridge_policy"])),
        _check_ux_catalog_enforcement_policy(root, str(standard_sources["ux_catalog_enforcement_policy"])),
        _check_ux_catalog_lock(root, str(standard_sources["ux_catalog_lock"])),
        _check_technical_baseline_aistd(root, str(standard_sources["technical_baseline_aistd"])),
    ):
        if not ok:
            details["invalid_content"].extend(payload["invalid_values"])
            details["missing_files"].extend(payload["missing_files"])

    details["missing_files"] = sorted(set(details["missing_files"]))
    details["invalid_content"] = sorted(set(details["invalid_content"]))
    return not details["missing_keys"] and not details["missing_files"] and not details["invalid_content"], details
