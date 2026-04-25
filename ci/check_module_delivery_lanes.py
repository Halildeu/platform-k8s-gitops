from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REQUIRED_LANES = ("unit", "database", "api", "contract", "integration", "e2e")
REQUIRED_EXECUTION_SEQUENCE = ("backend", "database", "api", "frontend", "integration", "e2e")
REQUIRED_SCOPE_LANE_MAP = {
    "backend": "unit",
    "database": "database",
    "api": "api",
    "frontend": "contract",
    "integration": "integration",
    "e2e_gate": "e2e",
}
WORKFLOW_SENTINELS = (
    "module-delivery-contract-check",
    "module-lane-unit",
    "module-lane-database",
    "module-lane-api",
    "module-lane-contract",
    "module-lane-integration",
    "module-lane-e2e",
    "module-delivery-gate",
    "python3 ci/run_module_delivery_lane.py --lane unit",
    "python3 ci/run_module_delivery_lane.py --lane database",
    "python3 ci/run_module_delivery_lane.py --lane api",
    "python3 ci/run_module_delivery_lane.py --lane contract",
    "python3 ci/run_module_delivery_lane.py --lane integration",
    "python3 ci/run_module_delivery_lane.py --lane e2e",
)
WORKFLOW_SEQUENCE_SENTINELS = (
    "module-lane-database:\n    runs-on: ubuntu-latest\n    needs: [module-lane-unit]",
    "module-lane-api:\n    runs-on: ubuntu-latest\n    needs: [module-lane-database]",
    "module-lane-contract:\n    runs-on: ubuntu-latest\n    needs: [module-lane-api]",
    "module-lane-integration:\n    runs-on: ubuntu-latest\n    needs: [module-lane-contract]",
    "module-lane-e2e:\n    runs-on: ubuntu-latest\n    needs: [module-lane-integration]",
)
PLACEHOLDER_TOKENS = (
    "TODO",
    "PLACEHOLDER",
    "<repo_root>",
    "<command>",
    "configure_me",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="ci/module_delivery_lanes.v1.json")
    parser.add_argument("--workflow", default=".github/workflows/module-delivery-lanes.yml")
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args(argv)


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


def _contains_placeholder(value: str) -> bool:
    raw = str(value or "")
    raw_upper = raw.upper()
    for token in PLACEHOLDER_TOKENS:
        if token.upper() in raw_upper:
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    root = _repo_root()

    config_path = Path(str(args.config).strip())
    config_path = (root / config_path).resolve() if not config_path.is_absolute() else config_path.resolve()
    workflow_path = Path(str(args.workflow).strip())
    workflow_path = (root / workflow_path).resolve() if not workflow_path.is_absolute() else workflow_path.resolve()

    if not config_path.exists():
        return _fail(
            "LANE_CONFIG_MISSING",
            "module delivery lane config file is missing.",
            details={"config_path": str(config_path)},
        )
    if not workflow_path.exists():
        return _fail(
            "LANE_WORKFLOW_MISSING",
            "module delivery workflow template is missing.",
            details={"workflow_path": str(workflow_path)},
        )

    try:
        config_obj = _load_json(config_path)
    except Exception:
        return _fail(
            "LANE_CONFIG_INVALID_JSON",
            "module delivery lane config must be valid JSON.",
            details={"config_path": str(config_path)},
        )

    if not isinstance(config_obj, dict):
        return _fail("LANE_CONFIG_INVALID_TYPE", "module delivery lane config root must be an object.")

    if config_obj.get("version") != "v1":
        return _fail("LANE_CONFIG_VERSION_INVALID", "module delivery lane config version must be v1.")
    if config_obj.get("merge_requires_all_green") is not True:
        return _fail(
            "MERGE_GATE_NOT_STRICT",
            "merge_requires_all_green must be true in lane config.",
        )

    scope_lane_map = config_obj.get("scope_lane_map")
    if not isinstance(scope_lane_map, dict):
        return _fail("SCOPE_LANE_MAP_INVALID", "scope_lane_map must be an object.")
    invalid_scope_map: dict[str, Any] = {}
    for scope, expected_lane in REQUIRED_SCOPE_LANE_MAP.items():
        actual_lane = scope_lane_map.get(scope)
        if actual_lane != expected_lane:
            invalid_scope_map[scope] = {"expected": expected_lane, "actual": actual_lane}
    if invalid_scope_map:
        return _fail(
            "SCOPE_LANE_MAP_MISMATCH",
            "scope_lane_map must map backend/database/api/frontend/integration/e2e_gate to required lane ids.",
            details={"mismatches": invalid_scope_map},
        )

    execution_sequence = config_obj.get("execution_sequence")
    if not isinstance(execution_sequence, list) or not execution_sequence:
        return _fail(
            "EXECUTION_SEQUENCE_INVALID",
            "execution_sequence must be a non-empty list.",
        )
    sequence_normalized = [str(item) for item in execution_sequence]
    if sequence_normalized != list(REQUIRED_EXECUTION_SEQUENCE):
        return _fail(
            "EXECUTION_SEQUENCE_MISMATCH",
            "execution_sequence must match the required delivery order.",
            details={
                "expected_sequence": list(REQUIRED_EXECUTION_SEQUENCE),
                "actual_sequence": sequence_normalized,
            },
        )

    lanes = config_obj.get("lanes")
    if not isinstance(lanes, dict):
        return _fail("LANES_SECTION_INVALID", "lanes section must be an object.")

    missing_lanes: list[str] = []
    invalid_commands: list[str] = []
    placeholder_commands: list[str] = []
    for lane in REQUIRED_LANES:
        lane_obj = lanes.get(lane)
        if not isinstance(lane_obj, dict):
            missing_lanes.append(lane)
            continue
        command = lane_obj.get("command")
        if not isinstance(command, str) or not command.strip():
            invalid_commands.append(lane)
            continue
        if _contains_placeholder(command):
            placeholder_commands.append(lane)

    if missing_lanes:
        return _fail(
            "REQUIRED_LANES_MISSING",
            "required module delivery lanes are missing.",
            details={"missing_lanes": missing_lanes},
        )
    if invalid_commands:
        return _fail(
            "LANE_COMMANDS_INVALID",
            "lane commands must be non-empty strings.",
            details={"invalid_lanes": invalid_commands},
        )
    if placeholder_commands and bool(args.strict):
        return _fail(
            "LANE_COMMANDS_PLACEHOLDER",
            "strict mode does not allow placeholder lane commands.",
            details={"placeholder_lanes": placeholder_commands},
        )

    workflow_text = workflow_path.read_text(encoding="utf-8")
    missing_sentinels = [item for item in WORKFLOW_SENTINELS if item not in workflow_text]
    if missing_sentinels:
        return _fail(
            "LANE_WORKFLOW_INVALID",
            "module delivery workflow does not include required jobs/commands.",
            details={"missing_markers": missing_sentinels},
        )
    missing_sequence_markers = [item for item in WORKFLOW_SEQUENCE_SENTINELS if item not in workflow_text]
    if missing_sequence_markers:
        return _fail(
            "LANE_WORKFLOW_SEQUENCE_INVALID",
            "module delivery workflow must enforce backend->database->api->frontend->integration->e2e order.",
            details={"missing_markers": missing_sequence_markers},
        )

    print(
        json.dumps(
            {
                "status": "OK",
                "checked_lanes": list(REQUIRED_LANES),
                "checked_sequence": list(REQUIRED_EXECUTION_SEQUENCE),
                "config_path": str(config_path),
                "workflow_path": str(workflow_path),
                "strict": bool(args.strict),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
