from __future__ import annotations

from pathlib import Path
from typing import Any

from ci.check_standards_lock_parts.constants import (
    REQUIRED_BACKEND_LAYERS,
    REQUIRED_DELIVERY_SEQUENCE,
    REQUIRED_FRONTEND_LAYOUT_EXPORTS,
    REQUIRED_LANES,
)
from ci.check_standards_lock_parts.helpers import _require_json_file

def _check_technical_baseline_aistd(root: Path, rel_path: str) -> tuple[bool, dict[str, Any]]:
    details: dict[str, Any] = {"invalid_values": [], "missing_files": []}
    baseline = _require_json_file(root, rel_path, key="technical_baseline_aistd")
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
                f"technical_baseline_aistd:backend.required_layers_missing_{','.join(missing_layers)}"
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
            details["invalid_values"].append("technical_baseline_aistd:backend.inter_service_communication_must_include_rest_event")

    frontend = baseline_obj.get("frontend")
    if not isinstance(frontend, dict):
        details["invalid_values"].append("technical_baseline_aistd:baseline.frontend_missing")
    else:
        if frontend.get("language") != "typescript":
            details["invalid_values"].append("technical_baseline_aistd:frontend.language_must_be_typescript")
        if frontend.get("framework") != "react":
            details["invalid_values"].append("technical_baseline_aistd:frontend.framework_must_be_react")
        if int(frontend.get("node_major") or 0) < 20:
            details["invalid_values"].append("technical_baseline_aistd:frontend.node_major_must_be_gte_20")
        if frontend.get("package_manager") != "npm":
            details["invalid_values"].append("technical_baseline_aistd:frontend.package_manager_must_be_npm")
        design_contract = frontend.get("design_contract")
        if not isinstance(design_contract, dict):
            details["invalid_values"].append("technical_baseline_aistd:frontend.design_contract_missing")
        else:
            if design_contract.get("single_ui_library") not in ("mfe-ui-kit", "@mfe/design-system"):
                details["invalid_values"].append("technical_baseline_aistd:frontend.design_contract.single_ui_library_invalid")
            if str(design_contract.get("ui_package_manifest_path") or "") not in (
                "web/packages/ui-kit/package.json",
                "web/packages/design-system/package.json",
            ):
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
            if str(page_composition.get("ui_import_prefix") or "") not in (
                "from 'mfe-ui-kit'",
                "from '@mfe/design-system'",
            ):
                details["invalid_values"].append(
                    "technical_baseline_aistd:frontend.page_composition.ui_import_prefix_invalid"
                )
            if str(page_composition.get("pages_root") or "") != "web/apps":
                details["invalid_values"].append("technical_baseline_aistd:frontend.page_composition.pages_root_invalid")

        parametric_data = frontend.get("parametric_data")
        if not isinstance(parametric_data, dict):
            details["invalid_values"].append("technical_baseline_aistd:frontend.parametric_data_missing")
        else:
            qb_path = str(parametric_data.get("query_builder_path") or "")
            if "buildEntityGridQueryParams" not in qb_path:
                details["invalid_values"].append("technical_baseline_aistd:frontend.parametric_data.query_builder_path_invalid")
            tc_path = str(parametric_data.get("theme_contract_runtime_path") or "")
            if "theme-contract" not in tc_path:
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
        required_fields = {"code", "message", "timestamp", "path"}
        missing_fields = sorted(required_fields - fields)
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
                manifest_obj = _require_json_file(root, manifest_rel, key="legacy_standards_archive_aistd")
                if not isinstance(manifest_obj, dict):
                    details["invalid_values"].append("technical_baseline_aistd:archive.manifest_invalid_json")
                else:
                    if manifest_obj.get("kind") != "legacy-standards-archive-aistd":
                        details["invalid_values"].append("technical_baseline_aistd:archive.manifest_kind_invalid")
                    if manifest_obj.get("version") != "v1":
                        details["invalid_values"].append("technical_baseline_aistd:archive.manifest_version_invalid")

    ok = not details["invalid_values"] and not details["missing_files"]
    return ok, details
