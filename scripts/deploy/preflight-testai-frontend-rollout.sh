#!/usr/bin/env bash
set -euo pipefail

# Read-only rollout preflight. The only server operations are GETs; desired
# resources are rendered from Git and converted to JSON with client dry-run.

TEST_CONTEXT="${TEST_CONTEXT:-k3d-test}"
TEST_NAMESPACE="${TEST_NAMESPACE:-platform-test}"
OVERLAY_PATH="${OVERLAY_PATH:-kustomize/overlays/test}"
DEPLOYMENT_NAME="${DEPLOYMENT_NAME:-frontend}"
QUOTA_NAME="${QUOTA_NAME:-platform-quota}"
PREFLIGHT_REPORT_PATH="${PREFLIGHT_REPORT_PATH:-}"

for command in kubectl jq python3; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "FAIL: required command not found: $command" >&2
    exit 1
  }
done

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT
render_file="$tmp_dir/test-render.yaml"
deployment_yaml="$tmp_dir/frontend-deployment.yaml"
quota_yaml="$tmp_dir/platform-quota.yaml"
deployment_json="$tmp_dir/frontend-deployment.json"
desired_quota_json="$tmp_dir/desired-quota.json"
live_quota_json="$tmp_dir/live-quota.json"

kubectl kustomize "$OVERLAY_PATH" > "$render_file"

extract_resource() {
  local kind="$1"
  local name="$2"
  local output_file="$3"
  python3 - "$render_file" "$kind" "$name" "$output_file" <<'PY'
from pathlib import Path
import sys

render_file, wanted_kind, wanted_name, output_file = sys.argv[1:5]

def scalar(lines, key):
    prefix = f"{key}:"
    for line in lines:
        if line.startswith(prefix):
            return line.split(":", 1)[1].strip()
    return None

def metadata_name(lines):
    inside = False
    for line in lines:
        if line == "metadata:":
            inside = True
            continue
        if inside and line and not line.startswith(" "):
            return None
        if inside and line.startswith("  name:"):
            return line.split(":", 1)[1].strip()
    return None

text = Path(render_file).read_text(encoding="utf-8")
for raw in text.split("\n---"):
    document = raw.strip()
    if not document:
        continue
    lines = document.splitlines()
    if scalar(lines, "kind") == wanted_kind and metadata_name(lines) == wanted_name:
        Path(output_file).write_text(document + "\n", encoding="utf-8")
        raise SystemExit(0)
print(f"resource not found in render: {wanted_kind}/{wanted_name}", file=sys.stderr)
raise SystemExit(1)
PY
}

extract_resource Deployment "$DEPLOYMENT_NAME" "$deployment_yaml"
extract_resource ResourceQuota "$QUOTA_NAME" "$quota_yaml"

# The active test context supplies discovery only. --dry-run=client performs no
# API mutation and preserves the rendered desired state as structured JSON.
kubectl --context "$TEST_CONTEXT" -n "$TEST_NAMESPACE" create \
  --dry-run=client --validate=false -f "$deployment_yaml" -o json > "$deployment_json"
kubectl --context "$TEST_CONTEXT" -n "$TEST_NAMESPACE" create \
  --dry-run=client --validate=false -f "$quota_yaml" -o json > "$desired_quota_json"
kubectl --context "$TEST_CONTEXT" -n "$TEST_NAMESPACE" get \
  resourcequota "$QUOTA_NAME" -o json > "$live_quota_json"

args=(
  --deployment-json "$deployment_json"
  --desired-quota-json "$desired_quota_json"
  --live-quota-json "$live_quota_json"
)
if [[ -n "$PREFLIGHT_REPORT_PATH" ]]; then
  args+=(--output-json "$PREFLIGHT_REPORT_PATH")
fi

python3 scripts/deploy/check-testai-frontend-rollout-headroom.py "${args[@]}"
