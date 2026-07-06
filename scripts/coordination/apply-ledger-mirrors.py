#!/usr/bin/env python3
"""Apply post-CAS Coordination Ledger mirror writes.

The command consumes the JSON emitted by `emit-ledger-event.sh` after a remote
branch CAS append succeeds plus a bounded mirror-write plan. It refuses to
touch GitHub issue bodies, Project fields, or PR bodies unless the CAS result
proves the expected ledger event hash.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FIELD_CATALOG = REPO_ROOT / "docs" / "coordination" / "project-field-catalog-v1.json"
HASH_RE = re.compile(r"^(?:sha256:)?[a-f0-9]{64}$")
REPO_RE = re.compile(r"^[^/\s]+/[^/\s]+$")
AGENT_MARKER_START = "<!-- agent-state:v1"
AGENT_MARKER_END = "-->"
PR_MARKER_START = "<!-- coordination-ledger-pr-mirror:v1"
PR_MARKER_END = "-->"
STATUS_ORDER = {
    "Backlog": 0,
    "Todo": 1,
    "In Progress": 2,
    "Needs Verify": 3,
    "Done": 4,
    "Blocked": 4,
}


class MirrorError(Exception):
    """User-facing refusal."""


def load_json_path(path: str) -> dict[str, Any]:
    raw = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise MirrorError(f"{path} must contain a JSON object")
    return data


def require_repo(value: Any, field: str = "repository") -> str:
    if not isinstance(value, str) or not REPO_RE.match(value):
        raise MirrorError(f"{field} must be owner/repo")
    return value


def require_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise MirrorError(f"{field} must be a positive integer")
    return value


def normalize_hash(value: Any, field: str) -> str:
    if not isinstance(value, str) or not HASH_RE.match(value):
        raise MirrorError(f"{field} must be sha256:<64-hex> or bare 64-hex")
    return value if value.startswith("sha256:") else f"sha256:{value}"


def require_event_uuid(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise MirrorError(f"{field} must be a non-empty string")
    return value


def validate_cas_result(cas: dict[str, Any], plan: dict[str, Any]) -> dict[str, str]:
    if cas.get("status") != "ledger_event_emitted_after_remote_cas":
        raise MirrorError("CAS result status is not ledger_event_emitted_after_remote_cas")
    append = cas.get("branch_append", {}).get("append")
    if not isinstance(append, dict):
        raise MirrorError("CAS result missing branch_append.append object")

    event_uuid = require_event_uuid(append.get("event_uuid"), "branch_append.append.event_uuid")
    event_hash = normalize_hash(append.get("event_hash"), "branch_append.append.event_hash")
    valid_prefix_hash = normalize_hash(
        append.get("valid_prefix_hash"), "branch_append.append.valid_prefix_hash"
    )

    expected_uuid = require_event_uuid(plan.get("expected_event_uuid"), "expected_event_uuid")
    expected_hash = normalize_hash(plan.get("expected_event_hash"), "expected_event_hash")
    if event_uuid != expected_uuid:
        raise MirrorError(f"CAS event_uuid mismatch expected={expected_uuid} actual={event_uuid}")
    if event_hash != expected_hash:
        raise MirrorError(f"CAS event_hash mismatch expected={expected_hash} actual={event_hash}")

    return {
        "event_uuid": event_uuid,
        "event_hash": event_hash,
        "valid_prefix_hash": valid_prefix_hash,
    }


def run_gh(gh: str, args: list[str], *, input_text: str | None = None) -> str:
    result = subprocess.run(
        [gh, *args],
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise MirrorError(result.stderr.strip() or result.stdout.strip() or "gh command failed")
    return result.stdout


def parse_key_block(body: str, marker_start: str, marker_end: str) -> tuple[int, int, dict[str, str]] | None:
    start = body.find(marker_start)
    if start < 0:
        return None
    end = body.find(marker_end, start)
    if end < 0:
        raise MirrorError(f"marker {marker_start!r} is not closed")
    end += len(marker_end)
    marker_body = body[start + len(marker_start) : end - len(marker_end)].strip()
    parsed: dict[str, str] = {}
    for raw_line in marker_body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if ":" not in line:
            raise MirrorError(f"marker line missing ':' separator: {line!r}")
        key, value = line.split(":", 1)
        parsed[key.strip()] = value.strip()
    return start, end, parsed


def render_agent_state(values: dict[str, Any]) -> str:
    keys = ("status", "claim_session", "claim_worktree", "claim_branch", "claim_updated_at", "expires_at")
    rendered = [AGENT_MARKER_START]
    for key in keys:
        value = values.get(key)
        if value is None:
            raise MirrorError(f"issue_body.set.{key} is required")
        rendered.append(f"{key}: {value}")
    rendered.append(AGENT_MARKER_END)
    return "\n".join(rendered)


def update_issue_body(current: str, spec: dict[str, Any]) -> tuple[str, list[str]]:
    block = parse_key_block(current, AGENT_MARKER_START, AGENT_MARKER_END)
    if block is None:
        raise MirrorError("issue body missing agent-state:v1 block")
    start, end, parsed = block
    expected = spec.get("expected", {})
    if not isinstance(expected, dict):
        raise MirrorError("issue_body.expected must be an object")
    for key, expected_value in expected.items():
        actual = parsed.get(str(key), "")
        if actual != str(expected_value):
            raise MirrorError(f"issue agent-state stale {key}: expected={expected_value!r} actual={actual!r}")
    set_values = spec.get("set")
    if not isinstance(set_values, dict):
        raise MirrorError("issue_body.set must be an object")
    new_block = render_agent_state(set_values)
    return current[:start] + new_block + current[end:], ["issue_body"]


def render_pr_marker(values: dict[str, Any]) -> str:
    required = ("coordination_state", "event_uuid", "event_hash", "session")
    lines = [PR_MARKER_START]
    for key in required:
        value = values.get(key)
        if value is None:
            raise MirrorError(f"pr_body.set.{key} is required")
        if key == "event_hash":
            value = normalize_hash(value, "pr_body.set.event_hash")
        lines.append(f"{key}: {value}")
    lines.append(PR_MARKER_END)
    return "\n".join(lines)


def update_pr_body(current: str, spec: dict[str, Any]) -> tuple[str, list[str]]:
    block = parse_key_block(current, PR_MARKER_START, PR_MARKER_END)
    expected = spec.get("expected", {})
    if expected is not None and not isinstance(expected, dict):
        raise MirrorError("pr_body.expected must be an object")
    set_values = spec.get("set")
    if not isinstance(set_values, dict):
        raise MirrorError("pr_body.set must be an object")
    new_block = render_pr_marker(set_values)

    if block is None:
        if expected:
            raise MirrorError("PR body missing coordination marker while expected fields were declared")
        return current.rstrip() + "\n\n" + new_block + "\n", ["pr_body"]

    start, end, parsed = block
    for key, expected_value in expected.items():
        actual = parsed.get(str(key), "")
        if str(key) == "event_hash" and actual:
            actual = normalize_hash(actual, "pr marker event_hash")
            expected_value = normalize_hash(expected_value, "pr_body.expected.event_hash")
        if actual != str(expected_value):
            raise MirrorError(f"PR mirror stale {key}: expected={expected_value!r} actual={actual!r}")
    return current[:start] + new_block + current[end:], ["pr_body"]


def project_mutations(spec: dict[str, Any], catalog: dict[str, Any]) -> list[dict[str, str]]:
    item_id = spec.get("item_id")
    if not isinstance(item_id, str) or not item_id:
        raise MirrorError("project.item_id is required")
    current_fields = spec.get("current_fields", {})
    set_fields = spec.get("set_fields", {})
    if not isinstance(current_fields, dict) or not isinstance(set_fields, dict):
        raise MirrorError("project.current_fields and project.set_fields must be objects")

    current_status = current_fields.get("Status")
    target_status = set_fields.get("Status")
    if isinstance(current_status, str) and isinstance(target_status, str):
        current_rank = STATUS_ORDER.get(current_status)
        target_rank = STATUS_ORDER.get(target_status)
        if current_rank is None or target_rank is None:
            raise MirrorError("project Status current/target must be known board statuses")
        if target_rank < current_rank:
            raise MirrorError(f"Project no-downgrade refusal: {current_status} -> {target_status}")

    fields = catalog.get("fields")
    if not isinstance(fields, dict):
        raise MirrorError("Project field catalog missing fields")
    out: list[dict[str, str]] = []
    for field, target in set_fields.items():
        field_spec = fields.get(field)
        if not isinstance(field_spec, dict):
            raise MirrorError(f"Project field {field!r} missing from catalog")
        options = field_spec.get("options")
        if not isinstance(options, dict) or target not in options:
            raise MirrorError(f"Project option {field}/{target} missing from catalog")
        out.append(
            {
                "item_id": item_id,
                "field": field,
                "field_id": str(field_spec["id"]),
                "target": str(target),
                "option_id": str(options[target]),
            }
        )
    return out


def load_catalog(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise MirrorError("Project field catalog must be a JSON object")
    return data


def write_with_temp_stdin(gh: str, args: list[str], body: str) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        handle.write(body)
        path = handle.name
    try:
        run_gh(gh, [*args, "--body-file", path])
    finally:
        Path(path).unlink(missing_ok=True)


def apply_or_plan(args: argparse.Namespace) -> int:
    cas = load_json_path(args.cas_result)
    plan = load_json_path(args.plan)
    evidence = validate_cas_result(cas, plan)
    repo = require_repo(plan.get("repository"))
    issue = require_int(plan.get("issue"), "issue")
    catalog = load_catalog(args.field_catalog)
    gh = args.gh

    planned: list[str] = []
    applied: list[str] = []
    debt: list[dict[str, str]] = []
    issue_update: str | None = None
    pr_update: tuple[int, str] | None = None

    issue_spec = plan.get("issue_body")
    if isinstance(issue_spec, dict) and issue_spec.get("enabled", True):
        current = run_gh(gh, ["issue", "view", str(issue), "--repo", repo, "--json", "body", "--jq", ".body"])
        new_body, surfaces = update_issue_body(current.rstrip("\n"), issue_spec)
        issue_update = new_body
        planned.extend(surfaces)

    project_spec = plan.get("project")
    project_ops: list[dict[str, str]] = []
    if isinstance(project_spec, dict) and project_spec.get("enabled", True):
        project_ops = project_mutations(project_spec, catalog)
        planned.extend([f"project:{op['field']}" for op in project_ops])

    pr_spec = plan.get("pr_body")
    if isinstance(pr_spec, dict) and pr_spec.get("enabled", True):
        pr_number = require_int(pr_spec.get("number"), "pr_body.number")
        current = run_gh(gh, ["pr", "view", str(pr_number), "--repo", repo, "--json", "body", "--jq", ".body"])
        new_body, surfaces = update_pr_body(current.rstrip("\n"), pr_spec)
        pr_update = (pr_number, new_body)
        planned.extend(surfaces)

    if args.apply:
        if issue_update is not None:
            try:
                write_with_temp_stdin(gh, ["issue", "edit", str(issue), "--repo", repo], issue_update)
                applied.append("issue_body")
            except MirrorError as exc:
                debt.append({"surface": "issue_body", "error": str(exc)})

        project_id = str(catalog["project"]["id"])
        for op in project_ops:
            try:
                run_gh(
                    gh,
                    [
                        "project",
                        "item-edit",
                        "--id",
                        op["item_id"],
                        "--project-id",
                        project_id,
                        "--field-id",
                        op["field_id"],
                        "--single-select-option-id",
                        op["option_id"],
                    ],
                )
                applied.append(f"project:{op['field']}")
            except MirrorError as exc:
                debt.append({"surface": f"project:{op['field']}", "error": str(exc)})

        if pr_update is not None:
            pr_number, new_body = pr_update
            try:
                write_with_temp_stdin(gh, ["pr", "edit", str(pr_number), "--repo", repo], new_body)
                applied.append("pr_body")
            except MirrorError as exc:
                debt.append({"surface": "pr_body", "error": str(exc)})

    status = "dry_run_post_cas_mirror_plan"
    rc = 0
    if args.apply:
        status = "post_cas_mirrors_applied"
        if debt:
            status = "mirror_write_failed_repair_required"
            rc = 1

    print(
        json.dumps(
            {
                "status": status,
                "repository": repo,
                "issue": issue,
                "event_uuid": evidence["event_uuid"],
                "event_hash": evidence["event_hash"],
                "valid_prefix_hash": evidence["valid_prefix_hash"],
                "planned_surfaces": planned,
                "applied_surfaces": applied,
                "repair_debt": debt,
                "permission_granted": False,
            },
            sort_keys=True,
        )
    )
    return rc


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cas-result", required=True, help="emit-ledger-event success JSON path, or '-'")
    parser.add_argument("--plan", required=True, help="coordination mirror write plan JSON path")
    parser.add_argument("--field-catalog", type=Path, default=DEFAULT_FIELD_CATALOG)
    parser.add_argument("--gh", default="gh", help="gh executable path")
    parser.add_argument("--apply", action="store_true", help="perform GitHub mirror writes")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    return apply_or_plan(parse_args(argv))


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except (MirrorError, json.JSONDecodeError, OSError) as exc:
        print(
            json.dumps(
                {
                    "status": "post_cas_mirror_refused",
                    "error": str(exc),
                    "permission_granted": False,
                },
                sort_keys=True,
            )
        )
        sys.exit(1)
