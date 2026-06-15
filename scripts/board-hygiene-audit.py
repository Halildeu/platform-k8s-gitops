#!/usr/bin/env python3
"""Audit and deterministically backfill Project #2 required fields.

Default mode is read-only. The script proposes values only when they can be
derived from canonical labels, the issue body agent-state block, or the owner
repo. Use --apply to mutate Project v2 fields in bounded batches.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = REPO_ROOT / "docs" / "coordination" / "project-field-catalog-v1.json"
REQUIRED_FIELDS = ("Status", "Faz", "Track", "Priority", "Kind")
ITEM_KEYS = {
    "Status": "status",
    "Faz": "faz",
    "Track": "track",
    "Priority": "priority",
    "Kind": "kind",
}


class AuditError(RuntimeError):
    pass


@dataclass
class IssueInfo:
    repo: str
    number: int
    title: str
    body: str
    state: str
    labels: set[str]
    url: str


@dataclass
class FieldProposal:
    field: str
    value: str
    reason: str


@dataclass
class AuditRow:
    item_id: str
    repo: str
    number: int
    title: str
    missing: list[str]
    proposals: list[FieldProposal] = field(default_factory=list)
    manual: list[str] = field(default_factory=list)


def run_json(args: list[str]) -> Any:
    proc = subprocess.run(args, check=False, text=True, capture_output=True)
    if proc.returncode != 0:
        raise AuditError(f"{' '.join(args)} failed: {proc.stderr.strip()}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise AuditError(f"{' '.join(args)} returned invalid JSON: {exc}") from exc


def run_text(args: list[str]) -> str:
    proc = subprocess.run(args, check=False, text=True, capture_output=True)
    if proc.returncode != 0:
        raise AuditError(f"{' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def load_catalog(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        catalog = json.load(handle)
    for field_name in REQUIRED_FIELDS:
        if field_name not in catalog.get("fields", {}):
            raise AuditError(f"field catalog missing {field_name}")
    return catalog


def fetch_project_items(project: int, owner: str, limit: int, fixture: Path | None) -> list[dict[str, Any]]:
    if fixture:
        data = json.loads(fixture.read_text(encoding="utf-8"))
    else:
        data = run_json(
            [
                "gh",
                "project",
                "item-list",
                str(project),
                "--owner",
                owner,
                "--format",
                "json",
                "--limit",
                str(limit),
            ]
        )
    return data.get("items", [])


def issue_ref_from_item(item: dict[str, Any]) -> tuple[str, int] | None:
    content = item.get("content") or {}
    if content.get("type") != "Issue":
        return None
    url = content.get("url") or ""
    match = re.match(r"^https://github\.com/([^/]+/[^/]+)/issues/([0-9]+)$", url)
    if not match:
        return None
    return match.group(1), int(match.group(2))


def fetch_issue(repo: str, number: int, fixture_dir: Path | None) -> IssueInfo:
    if fixture_dir:
        path = fixture_dir / repo.replace("/", "__") / f"{number}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        data = run_json(
            [
                "gh",
                "issue",
                "view",
                str(number),
                "--repo",
                repo,
                "--json",
                "title,body,state,labels,url",
            ]
        )
    return IssueInfo(
        repo=repo,
        number=number,
        title=data.get("title") or "",
        body=data.get("body") or "",
        state=data.get("state") or "",
        labels={str(label.get("name", "")).lower() for label in data.get("labels", [])},
        url=data.get("url") or f"https://github.com/{repo}/issues/{number}",
    )


def issue_from_project_item(repo: str, number: int, item: dict[str, Any]) -> IssueInfo:
    content = item.get("content") or {}
    return IssueInfo(
        repo=repo,
        number=number,
        title=content.get("title") or item.get("title") or "",
        body=content.get("body") or "",
        state=content.get("state") or "",
        labels=set(),
        url=content.get("url") or f"https://github.com/{repo}/issues/{number}",
    )


def agent_state_status(body: str) -> str | None:
    match = re.search(r"^status:\s*([^\n\r]+)\s*$", body, flags=re.MULTILINE)
    if not match:
        return None
    value = match.group(1).strip().lower()
    return {
        "backlog": "Backlog",
        "todo": "Todo",
        "in-progress": "In Progress",
        "needs-verify": "Needs Verify",
        "blocked": "Blocked",
        "done": "Done",
    }.get(value)


def derive_field(field_name: str, item: dict[str, Any], issue: IssueInfo) -> FieldProposal | None:
    title = issue.title or item.get("title") or ""
    labels = issue.labels
    lower_title = title.lower()

    if field_name == "Status":
        from_body = agent_state_status(issue.body)
        if from_body:
            return FieldProposal(field_name, from_body, "agent-state status")
        if issue.state.upper() == "CLOSED":
            return FieldProposal(field_name, "Done", "closed issue state")
        return None

    if field_name == "Faz":
        if "faz-23" in labels or lower_title.startswith("[faz 23]") or "faz 23" in lower_title:
            return FieldProposal(field_name, "Faz 23", "faz label/title")
        if "faz-22.5" in labels or "faz-22" in labels or "faz 22" in lower_title:
            return FieldProposal(field_name, "Faz 22", "faz label/title")
        if lower_title.startswith("schema-service") or "schema-service" in labels:
            return FieldProposal(field_name, "schema-service", "schema-service title/label")
        if lower_title.startswith("faz g") or "faz g" in lower_title:
            return FieldProposal(field_name, "Faz G", "faz title")
        return None

    if field_name == "Track":
        if issue.repo.endswith("/platform-k8s-gitops"):
            return FieldProposal(field_name, "gitops", "owner repo")
        if issue.repo.endswith("/platform-backend"):
            return FieldProposal(field_name, "backend", "owner repo")
        if issue.repo.endswith("/platform-web"):
            return FieldProposal(field_name, "web", "owner repo")
        if issue.repo.endswith("/platform-agent"):
            return FieldProposal(field_name, "agent", "owner repo")
        return None

    if field_name == "Priority":
        for priority in ("p0", "p1", "p2", "p3"):
            if f"priority:{priority}" in labels:
                return FieldProposal(field_name, priority.upper(), "priority label")
        match = re.search(r"\bP([0-3])\b", title)
        if match:
            return FieldProposal(field_name, f"P{match.group(1)}", "priority title token")
        return None

    if field_name == "Kind":
        if "risk" in labels:
            return FieldProposal(field_name, "risk", "risk label")
        if "gate" in labels:
            return FieldProposal(field_name, "gate", "gate label")
        if "milestone" in labels:
            return FieldProposal(field_name, "milestone", "milestone label")
        if "umbrella" in labels:
            return FieldProposal(field_name, "umbrella", "umbrella label")
        if "project-roadmap" in labels:
            return FieldProposal(field_name, "issue", "project-roadmap default issue")
        if re.search(r"\[m[0-9]+[a-z]?\]", lower_title) or "milestone" in lower_title:
            return FieldProposal(field_name, "milestone", "milestone title")
        if "gate" in lower_title:
            return FieldProposal(field_name, "gate", "gate title")
        if "risk" in lower_title or "blocker" in lower_title:
            return FieldProposal(field_name, "risk", "risk/blocker title")
        if not labels:
            return FieldProposal(field_name, "issue", "board issue default")
        return None

    raise AuditError(f"unknown required field {field_name}")


def audit_items(items: list[dict[str, Any]], args: argparse.Namespace) -> list[AuditRow]:
    issue_cache: dict[tuple[str, int], IssueInfo] = {}
    rows: list[AuditRow] = []

    for item in items:
        ref = issue_ref_from_item(item)
        if ref is None:
            continue
        repo, number = ref
        content = item.get("content") or {}
        missing = [field for field, key in ITEM_KEYS.items() if not str(item.get(key) or "").strip()]
        if not missing:
            continue
        if args.issue_fixture_dir or args.hydrate_issues:
            issue = issue_cache.setdefault((repo, number), fetch_issue(repo, number, args.issue_fixture_dir))
        else:
            issue = issue_from_project_item(repo, number, item)
        if not args.include_closed and issue.state.upper() == "CLOSED":
            continue
        if args.only_project_roadmap and issue.labels and "project-roadmap" not in issue.labels:
            continue

        row = AuditRow(
            item_id=item.get("id") or "",
            repo=repo,
            number=number,
            title=content.get("title") or item.get("title") or issue.title,
            missing=missing,
        )
        for field_name in missing:
            proposal = derive_field(field_name, item, issue)
            if proposal:
                row.proposals.append(proposal)
            else:
                row.manual.append(field_name)
        rows.append(row)
    return rows


def option_id(catalog: dict[str, Any], field_name: str, value: str) -> str:
    try:
        return catalog["fields"][field_name]["options"][value]
    except KeyError as exc:
        raise AuditError(f"field catalog missing option {field_name}/{value}") from exc


def field_id(catalog: dict[str, Any], field_name: str) -> str:
    return catalog["fields"][field_name]["id"]


def apply_proposal(project_id: str, item_id: str, field_name: str, value: str, catalog: dict[str, Any]) -> None:
    mutation = """
mutation($projectId:ID!, $itemId:ID!, $fieldId:ID!, $optionId:String!) {
  updateProjectV2ItemFieldValue(input:{
    projectId:$projectId,
    itemId:$itemId,
    fieldId:$fieldId,
    value:{singleSelectOptionId:$optionId}
  }) { projectV2Item { id } }
}
"""
    run_text(
        [
            "gh",
            "api",
            "graphql",
            "-f",
            f"query={mutation}",
            "-F",
            f"projectId={project_id}",
            "-F",
            f"itemId={item_id}",
            "-F",
            f"fieldId={field_id(catalog, field_name)}",
            "-F",
            f"optionId={option_id(catalog, field_name, value)}",
        ]
    )


def print_report(rows: list[AuditRow], applied: list[tuple[AuditRow, FieldProposal]], json_output: bool) -> None:
    if json_output:
        print(
            json.dumps(
                {
                    "items_with_missing_fields": len(rows),
                    "proposal_count": sum(len(row.proposals) for row in rows),
                    "manual_count": sum(len(row.manual) for row in rows),
                    "applied_count": len(applied),
                    "rows": [
                        {
                            "repo": row.repo,
                            "number": row.number,
                            "title": row.title,
                            "missing": row.missing,
                            "proposals": [proposal.__dict__ for proposal in row.proposals],
                            "manual": row.manual,
                        }
                        for row in rows
                    ],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return

    print("Project #2 board hygiene audit")
    print("--------------------------------")
    print(f"items with missing fields : {len(rows)}")
    print(f"deterministic proposals   : {sum(len(row.proposals) for row in rows)}")
    print(f"manual fields             : {sum(len(row.manual) for row in rows)}")
    print(f"applied mutations         : {len(applied)}")
    print("")

    for row in rows:
        proposal_text = ", ".join(f"{p.field}={p.value} ({p.reason})" for p in row.proposals) or "-"
        manual_text = ", ".join(row.manual) or "-"
        print(f"- {row.repo}#{row.number}: {row.title}")
        print(f"  missing : {', '.join(row.missing)}")
        print(f"  propose : {proposal_text}")
        print(f"  manual  : {manual_text}")


def markdown_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ").strip()


def manual_exception_markdown(rows: list[AuditRow]) -> str:
    manual_rows = [row for row in rows if row.manual]
    proposal_count = sum(len(row.proposals) for row in rows)
    manual_count = sum(len(row.manual) for row in rows)
    lines = [
        "# Project #2 Board Hygiene Manual Exception Report",
        "",
        "This report lists Project #2 items whose required fields cannot be",
        "deterministically derived from labels, issue body, title, state, or owner repo.",
        "Agents must not guess these values; a human or explicit follow-up issue must",
        "triage them.",
        "",
        "## Summary",
        "",
        f"- Items with missing fields: {len(rows)}",
        f"- Deterministic proposals available: {proposal_count}",
        f"- Manual fields requiring triage: {manual_count}",
        f"- Manual exception rows: {len(manual_rows)}",
        "",
        "## Manual Exceptions",
        "",
    ]

    if not manual_rows:
        lines.append("No manual exceptions remain.")
        return "\n".join(lines) + "\n"

    lines.extend(
        [
            "| Repo | Issue | Missing manual fields | Title |",
            "|---|---:|---|---|",
        ]
    )
    for row in manual_rows:
        issue_url = f"https://github.com/{row.repo}/issues/{row.number}"
        lines.append(
            "| "
            + markdown_escape(row.repo)
            + " | "
            + f"[#{row.number}]({issue_url})"
            + " | "
            + markdown_escape(", ".join(row.manual))
            + " | "
            + markdown_escape(row.title)
            + " |"
        )
    return "\n".join(lines) + "\n"


def write_manual_exception_report(path_value: str, rows: list[AuditRow]) -> None:
    report = manual_exception_markdown(rows)
    if path_value == "-":
        print(report, end="")
        return
    output_path = Path(path_value)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=int, default=2)
    parser.add_argument("--owner", default="Halildeu")
    parser.add_argument("--limit", type=int, default=int(os.environ.get("PROJECT_ITEM_LIMIT", "1000")))
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--issue-fixture-dir", type=Path)
    parser.add_argument("--include-closed", action="store_true")
    parser.add_argument("--only-project-roadmap", action="store_true", default=True)
    parser.add_argument("--all-issues", dest="only_project_roadmap", action="store_false")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--max-mutations", type=int, default=25)
    parser.add_argument("--hydrate-issues", action="store_true", help="fetch issue labels/state with gh issue view; slower but richer")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--manual-exception-report",
        metavar="PATH|-",
        help="write a markdown report for unresolved manual fields without mutating Project #2",
    )
    parser.add_argument("--strict", action="store_true", help="exit non-zero when any open roadmap issue still has manual missing fields")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.limit < 200:
        raise AuditError("--limit must be >= 200 so Project #2 full-board audits do not silently truncate")
    if args.max_mutations < 0:
        raise AuditError("--max-mutations must be >= 0")
    catalog = load_catalog(args.catalog)
    project_id = catalog["project"]["id"]
    items = fetch_project_items(args.project, args.owner, args.limit, args.fixture)
    rows = audit_items(items, args)

    applied: list[tuple[AuditRow, FieldProposal]] = []
    if args.apply:
        budget = args.max_mutations
        for row in rows:
            for proposal in row.proposals:
                if budget <= 0:
                    break
                apply_proposal(project_id, row.item_id, proposal.field, proposal.value, catalog)
                applied.append((row, proposal))
                budget -= 1
            if budget <= 0:
                break

    print_report(rows, applied, args.json)

    if args.manual_exception_report:
        write_manual_exception_report(args.manual_exception_report, rows)

    if args.strict and any(row.manual for row in rows):
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AuditError as exc:
        print(f"board-hygiene-audit: {exc}", file=sys.stderr)
        raise SystemExit(2)
