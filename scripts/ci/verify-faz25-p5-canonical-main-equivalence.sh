#!/usr/bin/env bash
set -euo pipefail

# A protected workflow may wait for a named reviewer and then queue behind the
# single testai runner. During that delay main can advance for an unrelated
# phase. Accept only an authenticated descendant whose Faz 25 acceptance
# authority and platform-test desired-state inputs are byte-for-byte unchanged.

BASELINE_REF="${1:-}"
CANDIDATE_REF="${2:-}"

if [[ -z "$BASELINE_REF" || -z "$CANDIDATE_REF" || $# -ne 2 ]]; then
  echo "usage: $0 <approved-baseline-revision> <canonical-main-candidate>" >&2
  exit 2
fi

command -v git >/dev/null 2>&1 || { echo "git is required" >&2; exit 2; }
command -v jq >/dev/null 2>&1 || { echo "jq is required" >&2; exit 2; }

BASELINE_REVISION="$(git rev-parse --verify "${BASELINE_REF}^{commit}")"
CANDIDATE_REVISION="$(git rev-parse --verify "${CANDIDATE_REF}^{commit}")"

AUTHORITY_PATHS=(
  ".github/workflows/verify-faz25-p5-product-surface.yml"
  "scripts/ci/verify-faz25-p5-canonical-main-equivalence.sh"
  "scripts/deploy/collect-faz25-p5-frontend-lineage.sh"
  "scripts/deploy/watch-faz25-p5-frontend-routes.sh"
  "scripts/deploy/verify-faz25-p5-frontend-routes.py"
  "tests/deploy/test_faz25_p5_canonical_main_equivalence.py"
  "tests/deploy/test_faz25_p5_product_acceptance_contract.py"
  "tests/smoke/faz25-p5-product-surface.spec.ts"
  "tests/smoke/playwright.faz25-p5.config.ts"
  "tests/smoke/faz25-p5-runtime"
  "tests/smoke/faz25-p5-product-surface.schema.json"
  "tests/smoke/faz25-p5-frontend-lineage.schema.json"
  "tests/smoke/faz25-p5-continuous-route-watch.schema.json"
  "tests/smoke/faz25-p5-evidence-manifest.schema.json"
  "kustomize"
  "argocd"
)

hash_stream() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum | awk '{print $1}'
  else
    shasum -a 256 | awk '{print $1}'
  fi
}

AUTHORITY_PATH_SET_SHA256="$(printf '%s\n' "${AUTHORITY_PATHS[@]}" | hash_stream)"

authority_tree_sha256() {
  local revision="$1"
  {
    printf 'authority-path-set %s\n' "$AUTHORITY_PATH_SET_SHA256"
    git ls-tree -r "$revision" -- "${AUTHORITY_PATHS[@]}"
  } | hash_stream
}

MODE="EXACT_HEAD"
if [[ "$BASELINE_REVISION" != "$CANDIDATE_REVISION" ]]; then
  if ! git merge-base --is-ancestor "$BASELINE_REVISION" "$CANDIDATE_REVISION"; then
    echo "candidate is not a descendant of the approved baseline" >&2
    exit 1
  fi

  if ! git diff --quiet "$BASELINE_REVISION" "$CANDIDATE_REVISION" -- \
      "${AUTHORITY_PATHS[@]}"; then
    echo "acceptance authority drift detected:" >&2
    git diff --name-only "$BASELINE_REVISION" "$CANDIDATE_REVISION" -- \
      "${AUTHORITY_PATHS[@]}" >&2
    exit 1
  fi
  MODE="AUTHORITY_EQUIVALENT_DESCENDANT"
fi

BASELINE_AUTHORITY_TREE_SHA256="$(authority_tree_sha256 "$BASELINE_REVISION")"
CANDIDATE_AUTHORITY_TREE_SHA256="$(authority_tree_sha256 "$CANDIDATE_REVISION")"
if [[ "$BASELINE_AUTHORITY_TREE_SHA256" != \
      "$CANDIDATE_AUTHORITY_TREE_SHA256" ]]; then
  echo "authority tree hash mismatch after byte-equivalence verification" >&2
  exit 1
fi

jq -cn \
  --arg mode "$MODE" \
  --arg baselineRevision "$BASELINE_REVISION" \
  --arg candidateRevision "$CANDIDATE_REVISION" \
  --arg authorityPathSetSha256 "$AUTHORITY_PATH_SET_SHA256" \
  --arg baselineAuthorityTreeSha256 "$BASELINE_AUTHORITY_TREE_SHA256" \
  --arg candidateAuthorityTreeSha256 "$CANDIDATE_AUTHORITY_TREE_SHA256" '
  {
    schemaVersion: "faz25-p5-canonical-main-equivalence-v2",
    verdict: "PASS",
    mode: $mode,
    baselineRevision: $baselineRevision,
    candidateRevision: $candidateRevision,
    authorityPathSetSha256: $authorityPathSetSha256,
    baselineAuthorityTreeSha256: $baselineAuthorityTreeSha256,
    candidateAuthorityTreeSha256: $candidateAuthorityTreeSha256,
    authorityTreeSha256: $candidateAuthorityTreeSha256
  }
'
