from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ci.check_standards_lock_parts.constants import (
    REQUIRED_FILES,
    REQUIRED_COMMANDS,
    REQUIRED_GATES,
    REQUIRED_LOCK_KEYS,
    REQUIRED_STANDARD_SOURCES,
)
from ci.check_standards_lock_parts.helpers import _fail, _load_json, _parse_args, _repo_root
from ci.check_standards_lock_parts.lock_checks import (
    _check_branch_protection,
    _check_enforcement_workflow,
    _check_managed_repo_sync,
    _check_module_delivery_contract,
    _check_module_delivery_workflow,
    _check_required_commands,
    _check_solo_developer_policy,
    _check_standard_sources,
)

def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root_arg = str(args.repo_root).strip()
    root = Path(repo_root_arg).expanduser().resolve() if repo_root_arg else _repo_root()
    missing = [rel for rel in REQUIRED_FILES if not (root / rel).exists()]
    if missing:
        return _fail(
            "REQUIRED_FILES_MISSING",
            "Required standards files are missing.",
            details={"missing": missing},
        )

    lock_path = root / "standards.lock"
    try:
        lock = _load_json(lock_path)
    except Exception:
        return _fail("STANDARDS_LOCK_INVALID_JSON", "standards.lock must be valid JSON.")

    if not isinstance(lock, dict):
        return _fail("STANDARDS_LOCK_INVALID_TYPE", "standards.lock root must be an object.")

    missing_keys = [k for k in REQUIRED_LOCK_KEYS if k not in lock]
    if missing_keys:
        return _fail(
            "STANDARDS_LOCK_MISSING_KEYS",
            "standards.lock is missing required keys.",
            details={"missing_keys": missing_keys},
        )

    if lock.get("version") != "v1":
        return _fail("STANDARDS_LOCK_VERSION_INVALID", "standards.lock version must be v1.")

    operating_contract = lock.get("operating_contract")
    if operating_contract != "docs/OPERATIONS/AI-MULTIREPO-OPERATING-CONTRACT.v1.md":
        return _fail(
            "OPERATING_CONTRACT_PATH_INVALID",
            "operating_contract path must point to the v1 contract document.",
        )

    required_files = lock.get("required_files")
    if not isinstance(required_files, list):
        return _fail("REQUIRED_FILES_INVALID", "required_files must be a list.")
    file_set = {str(item) for item in required_files if isinstance(item, str)}
    missing_from_lock = [rel for rel in REQUIRED_FILES if rel not in file_set]
    if missing_from_lock:
        return _fail(
            "REQUIRED_FILES_INCOMPLETE",
            "standards.lock required_files does not include all critical files.",
            details={"missing": missing_from_lock},
        )

    commands_ok, command_details = _check_required_commands(lock.get("required_commands"))
    if not commands_ok:
        return _fail(
            "REQUIRED_COMMANDS_INCOMPLETE",
            "standards.lock required_commands does not include all baseline commands.",
            details=command_details,
        )

    sync_ok, sync_details = _check_managed_repo_sync(root, lock.get("managed_repo_sync"))
    if not sync_ok:
        return _fail(
            "MANAGED_REPO_SYNC_INVALID",
            "managed_repo_sync section is missing required keys or contains invalid values.",
            details=sync_details,
        )

    module_ok, module_details = _check_module_delivery_contract(lock.get("module_delivery_contract"))
    if not module_ok:
        return _fail(
            "MODULE_DELIVERY_CONTRACT_INVALID",
            "module_delivery_contract section is missing required keys or contains invalid values.",
            details=module_details,
        )

    branch_ok, branch_details = _check_branch_protection(lock.get("branch_protection"))
    if not branch_ok:
        return _fail(
            "BRANCH_PROTECTION_POLICY_INVALID",
            "branch_protection section is missing required keys or contains invalid values.",
            details=branch_details,
        )

    solo_ok, solo_details = _check_solo_developer_policy(lock.get("solo_developer_policy"))
    if not solo_ok:
        return _fail(
            "SOLO_DEVELOPER_POLICY_INVALID",
            "solo_developer_policy section is missing required keys or contains invalid values.",
            details=solo_details,
        )

    standard_sources = lock.get("standard_sources")
    if not isinstance(standard_sources, dict):
        return _fail("STANDARD_SOURCES_INVALID", "standard_sources must be an object.")
    sources_ok, source_details = _check_standard_sources(root, standard_sources)
    if not sources_ok:
        return _fail(
            "STANDARD_SOURCES_INVALID",
            "standard_sources references are missing or invalid against baseline expectations.",
            details=source_details,
        )

    workflow_ok, workflow_details = _check_enforcement_workflow(root)
    if not workflow_ok:
        return _fail(
            "ENFORCEMENT_WORKFLOW_NOT_HARDENED",
            "gate-enforcement-check workflow is not in hardened mode.",
            details=workflow_details,
        )

    module_wf_ok, module_wf_details = _check_module_delivery_workflow(root)
    if not module_wf_ok:
        return _fail(
            "MODULE_DELIVERY_WORKFLOW_INVALID",
            "module delivery workflow template is missing required jobs or checks.",
            details=module_wf_details,
        )

    required_gates = lock.get("required_gates")
    if not isinstance(required_gates, list):
        return _fail("REQUIRED_GATES_INVALID", "required_gates must be a list.")
    gate_set = {str(item) for item in required_gates if isinstance(item, str)}
    missing_gates = [gate for gate in REQUIRED_GATES if gate not in gate_set]
    if missing_gates:
        return _fail(
            "REQUIRED_GATES_INCOMPLETE",
            "standards.lock required_gates does not include all baseline gates.",
            details={"missing": missing_gates},
        )

    pr_gate_mode = lock.get("pr_gate_mode")
    if not isinstance(pr_gate_mode, dict):
        return _fail("PR_GATE_MODE_INVALID", "pr_gate_mode must be an object.")
    enf_mode = pr_gate_mode.get("enforcement_check_pull_request")
    if enf_mode != "blocking":
        return _fail(
            "PR_GATE_MODE_NOT_BLOCKING",
            "enforcement_check_pull_request must be blocking.",
        )

    print(
        json.dumps(
            {
                "status": "OK",
                "checked_files": list(REQUIRED_FILES),
                "checked_standard_sources": list(REQUIRED_STANDARD_SOURCES),
                "checked_commands": list(REQUIRED_COMMANDS),
                "checked_gates": list(REQUIRED_GATES),
                "checked_sections": [
                    "managed_repo_sync",
                    "module_delivery_contract",
                    "branch_protection",
                    "solo_developer_policy",
                ],
                "lock_path": str(lock_path.as_posix()),
                "repo_root": str(root.as_posix()),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
