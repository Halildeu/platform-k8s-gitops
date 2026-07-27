#!/usr/bin/env bash
set -euo pipefail

K8S_CONTEXT="k3d-test"
K8S_NAMESPACE="platform-test"
K8S_DEPLOYMENT="frontend"
K8S_SELECTOR="app.kubernetes.io/name=frontend"
TESTAI_URL="https://testai.acik.com"
EXPECTED_DIGEST=""
EXPECTED_SHA=""
EXPECTED_SHORT_SHA=""
RUN_CLUSTER=true
RUN_PUBLIC=true

usage() {
  cat <<'EOF'
Usage: verify-testai-frontend-runtime.sh \
  --expected-digest sha256:<64hex> --expected-sha <40hex> \
  --expected-short-sha <7hex> [options]

Options:
  --cluster-only  Verify rollout and pod digest without public network access
  --public-only   Verify public entry and build lineage without cluster access
  --context, --namespace, --deployment, --selector, --url
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --expected-digest) EXPECTED_DIGEST="$2"; shift 2 ;;
    --expected-sha) EXPECTED_SHA="$2"; shift 2 ;;
    --expected-short-sha) EXPECTED_SHORT_SHA="$2"; shift 2 ;;
    --context) K8S_CONTEXT="$2"; shift 2 ;;
    --namespace) K8S_NAMESPACE="$2"; shift 2 ;;
    --deployment) K8S_DEPLOYMENT="$2"; shift 2 ;;
    --selector) K8S_SELECTOR="$2"; shift 2 ;;
    --url) TESTAI_URL="${2%/}"; shift 2 ;;
    --cluster-only) RUN_PUBLIC=false; shift ;;
    --public-only) RUN_CLUSTER=false; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ "$RUN_CLUSTER" == "true" || "$RUN_PUBLIC" == "true" ]] || {
  echo "::error::cluster-only and public-only are mutually exclusive"; exit 2;
}
[[ "$EXPECTED_DIGEST" =~ ^sha256:[a-f0-9]{64}$ ]] || {
  echo "::error::expected digest must match sha256:<64 lowercase hex>"; exit 1;
}
[[ "$EXPECTED_SHORT_SHA" =~ ^[a-f0-9]{7}$ ]] || {
  echo "::error::expected short SHA must be seven lowercase hex characters"; exit 1;
}
[[ "$EXPECTED_SHA" =~ ^[a-f0-9]{40}$ && "${EXPECTED_SHA:0:7}" == "$EXPECTED_SHORT_SHA" ]] || {
  echo "::error::expected full SHA must be 40 lowercase hex and match short SHA"; exit 1;
}

if [[ "$RUN_CLUSTER" == "true" ]]; then
  kubectl --context="$K8S_CONTEXT" rollout status \
    "deployment/${K8S_DEPLOYMENT}" -n "$K8S_NAMESPACE" --timeout=300s

  "$(dirname "$0")/verify-pod-digest.sh" \
    --context "$K8S_CONTEXT" \
    --namespace "$K8S_NAMESPACE" \
    --selector "$K8S_SELECTOR" \
    --expected-digest "$EXPECTED_DIGEST"
fi

if [[ "$RUN_PUBLIC" == "true" ]]; then
  index_body=""
  root_entry=""
  for attempt in 1 2 3 4 5; do
    index_body=$(curl -fsSkL --connect-timeout 10 --max-time 30 "$TESTAI_URL/" || true)
    root_entry=$(printf '%s' "$index_body" | python3 -c '
from html.parser import HTMLParser
import sys

class ModuleScript(HTMLParser):
    src = ""
    def handle_starttag(self, tag, attrs):
        if self.src or tag.lower() != "script":
            return
        values = dict(attrs)
        src = values.get("src", "")
        if values.get("type", "").lower() == "module" and src.split("?", 1)[0].endswith(".js"):
            self.src = src

parser = ModuleScript()
parser.feed(sys.stdin.read())
print(parser.src)
' || true)
    if [[ -n "$root_entry" ]]; then
      break
    fi
    echo "module entry not ready (${attempt}/5); retrying in 3s"
    sleep 3
  done

  [[ -n "$root_entry" ]] || {
    echo "::error::public index has no module entry after retries"; exit 1;
  }
  case "$root_entry" in
    *..*) echo "::error::module entry contains traversal segment: $root_entry"; exit 1 ;;
    /mf-entry-bootstrap-*.js|/mf-entry-bootstrap-*.js\?*|/assets/mf-entry-bootstrap-*.js|/assets/mf-entry-bootstrap-*.js\?*|/assets/index-*.js|/assets/index-*.js\?*) ;;
    *) echo "::error::unexpected or cross-origin module entry: $root_entry"; exit 1 ;;
  esac

  curl -fsSkL --connect-timeout 10 --max-time 30 \
    --retry 3 --retry-delay 2 --retry-all-errors \
    -o /dev/null "${TESTAI_URL}${root_entry}"
  echo "PASS: public module entry reachable: ${root_entry}"

  build_info=$(curl -fsSkL --connect-timeout 10 --max-time 30 \
    --retry 3 --retry-delay 2 --retry-all-errors \
    "${TESTAI_URL}/build-info.json")
  printf '%s' "$build_info" | jq -e . >/dev/null
  actual_sha=$(printf '%s' "$build_info" | jq -r '.sha // empty')
  actual_short=$(printf '%s' "$build_info" | jq -r '.shortSha // empty')

  [[ "$actual_sha" =~ ^[a-f0-9]{40}$ ]] || {
    echo "::error::build-info.json .sha is missing or malformed"; exit 1;
  }
  [[ "$actual_sha" == "$EXPECTED_SHA" ]] || {
    echo "::error::build-info full SHA mismatch: expected=$EXPECTED_SHA actual=$actual_sha"; exit 1;
  }
  [[ "$actual_short" == "$EXPECTED_SHORT_SHA" ]] || {
    echo "::error::build-info shortSha mismatch: expected=$EXPECTED_SHORT_SHA actual=$actual_short"; exit 1;
  }
  [[ "${actual_sha:0:7}" == "$EXPECTED_SHORT_SHA" ]] || {
    echo "::error::build-info full SHA does not start with expected short SHA"; exit 1;
  }
  echo "PASS: build-info lineage ${actual_sha} matches sha-${EXPECTED_SHORT_SHA}"
fi
