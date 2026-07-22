#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEST_RENDER="$(mktemp)"
PROD_RENDER="$(mktemp)"
MUTATED_RENDER="$(mktemp)"
trap 'rm -f "${TEST_RENDER}" "${PROD_RENDER}" "${MUTATED_RENDER}"' EXIT

kustomize build "${ROOT}/kustomize/overlays/test" >"${TEST_RENDER}"
kustomize build "${ROOT}/kustomize/overlays/prod" >"${PROD_RENDER}"

python3 "${ROOT}/scripts/test/verify-faz24-live-analyze-enable.py" \
  "${TEST_RENDER}" \
  "${PROD_RENDER}" \
  "${ROOT}/kustomize/base/apps/audio-gateway/configmap.yaml"

for mutation in service-load-balancer service-external-ips service-late-wave; do
  python3 - "${mutation}" "${TEST_RENDER}" "${MUTATED_RENDER}" <<'PY'
import sys

import yaml

mutation, source, destination = sys.argv[1:]
documents = list(yaml.safe_load_all(open(source, encoding="utf-8")))
for document in documents:
    if not isinstance(document, dict):
        continue
    if document.get("kind") != "Service":
        continue
    if document.get("metadata", {}).get("name") != "meeting-ai-service":
        continue
    if mutation == "service-load-balancer":
        document["spec"]["type"] = "LoadBalancer"
    elif mutation == "service-external-ips":
        document["spec"]["externalIPs"] = ["192.0.2.10"]
    elif mutation == "service-late-wave":
        document.setdefault("metadata", {}).setdefault("annotations", {})[
            "argocd.argoproj.io/sync-wave"
        ] = "19"
with open(destination, "w", encoding="utf-8") as output:
    yaml.safe_dump_all(documents, output, sort_keys=False)
PY

  if python3 "${ROOT}/scripts/test/verify-faz24-live-analyze-enable.py" \
    "${MUTATED_RENDER}" \
    "${PROD_RENDER}" \
    "${ROOT}/kustomize/base/apps/audio-gateway/configmap.yaml" \
    >/dev/null 2>&1; then
    echo "Faz 24 live-analyze negative mutation unexpectedly passed: ${mutation}" >&2
    exit 1
  fi
done

echo 'Faz 24 live-analyze test-only enable guard: PASS'
