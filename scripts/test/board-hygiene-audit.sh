#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d -t board-hygiene-audit.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

mkdir -p "$WORK/issues/Halildeu__platform-agent" "$WORK/issues/Halildeu__platform-k8s-gitops"

cat >"$WORK/project.json" <<'JSON'
{
  "items": [
    {
      "id": "ITEM_agent_151",
      "content": {
        "type": "Issue",
        "url": "https://github.com/Halildeu/platform-agent/issues/151",
        "title": "Faz 22.5 agent tokenless lifecycle"
      },
      "status": "Needs Verify",
      "faz": "",
      "track": "",
      "priority": "",
      "kind": ""
    },
    {
      "id": "ITEM_gitops_1537",
      "content": {
        "type": "Issue",
        "url": "https://github.com/Halildeu/platform-k8s-gitops/issues/1537",
        "title": "Project #2 board hygiene"
      },
      "status": "",
      "faz": "Faz 22",
      "track": "gitops",
      "priority": "P0",
      "kind": "issue"
    },
    {
      "id": "ITEM_manual_9999",
      "content": {
        "type": "Issue",
        "url": "https://github.com/Halildeu/platform-agent/issues/9999",
        "title": "Manual case"
      },
      "status": "",
      "faz": "",
      "track": "",
      "priority": "",
      "kind": ""
    }
  ]
}
JSON

cat >"$WORK/issues/Halildeu__platform-agent/151.json" <<'JSON'
{
  "title": "Faz 22.5 agent tokenless lifecycle",
  "body": "<!-- agent-state:v1\nstatus: needs-verify\n-->",
  "state": "OPEN",
  "url": "https://github.com/Halildeu/platform-agent/issues/151",
  "labels": [
    {"name": "project-roadmap"},
    {"name": "faz-22.5"},
    {"name": "priority:p0"},
    {"name": "gate"}
  ]
}
JSON

cat >"$WORK/issues/Halildeu__platform-k8s-gitops/1537.json" <<'JSON'
{
  "title": "Project #2 board hygiene",
  "body": "<!-- agent-state:v1\nstatus: in-progress\n-->",
  "state": "OPEN",
  "url": "https://github.com/Halildeu/platform-k8s-gitops/issues/1537",
  "labels": [
    {"name": "project-roadmap"},
    {"name": "faz-22"},
    {"name": "priority:p0"},
    {"name": "quality"}
  ]
}
JSON

cat >"$WORK/issues/Halildeu__platform-agent/9999.json" <<'JSON'
{
  "title": "Manual case",
  "body": "",
  "state": "OPEN",
  "url": "https://github.com/Halildeu/platform-agent/issues/9999",
  "labels": [
    {"name": "project-roadmap"}
  ]
}
JSON

JSON_OUT="$WORK/out.json"
MANUAL_REPORT="$WORK/manual-exceptions.md"
python3 "$ROOT/scripts/board-hygiene-audit.py" \
  --fixture "$WORK/project.json" \
  --issue-fixture-dir "$WORK/issues" \
  --json \
  --manual-exception-report "$MANUAL_REPORT" >"$JSON_OUT"

jq -e '.items_with_missing_fields == 3' "$JSON_OUT" >/dev/null
jq -e '.proposal_count == 7' "$JSON_OUT" >/dev/null
jq -e '.manual_count == 3' "$JSON_OUT" >/dev/null
jq -e '.rows[] | select(.number == 151) | .proposals | map(.field + "=" + .value) | index("Faz=Faz 22")' "$JSON_OUT" >/dev/null
jq -e '.rows[] | select(.number == 151) | .proposals | map(.field + "=" + .value) | index("Track=agent")' "$JSON_OUT" >/dev/null
jq -e '.rows[] | select(.number == 151) | .proposals | map(.field + "=" + .value) | index("Kind=gate")' "$JSON_OUT" >/dev/null
jq -e '.rows[] | select(.number == 1537) | .proposals | map(.field + "=" + .value) | index("Status=In Progress")' "$JSON_OUT" >/dev/null

grep -F "# Project #2 Board Hygiene Manual Exception Report" "$MANUAL_REPORT" >/dev/null
grep -F "Manual fields requiring triage: 3" "$MANUAL_REPORT" >/dev/null
grep -F "[#9999](https://github.com/Halildeu/platform-agent/issues/9999)" "$MANUAL_REPORT" >/dev/null
grep -F "Status, Faz, Priority" "$MANUAL_REPORT" >/dev/null

if python3 "$ROOT/scripts/board-hygiene-audit.py" \
  --fixture "$WORK/project.json" \
  --issue-fixture-dir "$WORK/issues" \
  --strict >/dev/null 2>&1; then
  echo "strict mode unexpectedly passed despite manual fields" >&2
  exit 1
fi

echo "PASS board-hygiene-audit fixture harness"
