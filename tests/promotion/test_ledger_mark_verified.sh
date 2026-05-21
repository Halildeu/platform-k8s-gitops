#!/usr/bin/env bash
# tests/promotion/test_ledger_mark_verified.sh
#
# Integration test for scripts/promotion/ledger-mark-verified.sh.
#
# Scope: end-to-end exercise of report → target resolution → policy →
# ledger patch with LEDGER_DRY_RUN=1 (skips git push + PR creation).
#
# 4 scenarios:
#   1. Frontend variant report with d29_zanzibar=AMBER → MARK
#      (variant=frontend-prod-variant, jwt_validates=false from fixture catalog)
#   2. Frontend variant report with d29_zanzibar=RED   → SKIP
#      (policy reject — RED unacceptable even for lenient service)
#   3. Backend overlay-render report all GREEN        → MARK
#      (existing behavior preserved)
#   4. Backend overlay-render report with d29_zanzibar=AMBER → SKIP
#      (strict policy — backend AMBER fails for jwt_validates=true)
#
# Pattern: tempdir-isolated mini repo (services.yaml + release-candidates/),
# fed to the script via PLATFORM_GITOPS_REPO env var. Tests assert on the
# script's stdout pattern (MARK/SKIP/POLICY) rather than committing to git.
#
# Run:
#   bash tests/promotion/test_ledger_mark_verified.sh
# Exit code: 0 all pass, 1 any fail.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="$REPO_ROOT/scripts/promotion/ledger-mark-verified.sh"

PASS=0
FAIL=0

assert_contains() {
  local label="$1" haystack="$2" needle="$3"
  if printf '%s' "$haystack" | grep -F -q -- "$needle"; then
    echo "  ✓ $label"
    PASS=$((PASS + 1))
  else
    echo "  ✗ $label"
    echo "    expected to contain: $needle"
    echo "    actual: $haystack" | head -20
    FAIL=$((FAIL + 1))
  fi
}

assert_not_contains() {
  local label="$1" haystack="$2" needle="$3"
  if printf '%s' "$haystack" | grep -F -q -- "$needle"; then
    echo "  ✗ $label"
    echo "    UNEXPECTED match: $needle"
    echo "    actual: $haystack" | head -20
    FAIL=$((FAIL + 1))
  else
    echo "  ✓ $label"
    PASS=$((PASS + 1))
  fi
}

setup_fixture_repo() {
  local repo="$1"
  mkdir -p "$repo/docs/operations"
  mkdir -p "$repo/release-candidates/platform-backend"
  mkdir -p "$repo/release-candidates/platform-web"
  mkdir -p "$repo/kustomize/overlays/test"

  cat > "$repo/docs/operations/services.yaml" <<'YAML'
schema_version: "1.0"
services:
  - name: user-service
    repo: platform-backend
    jwt_validates: true
    environments: {test: enabled, prod: enabled}
  - name: frontend
    repo: platform-web
    jwt_validates: false
    environments: {test: enabled, prod: enabled}
YAML
}

write_backend_ledger() {
  local repo="$1" digest="$2"
  # Strip "sha256:" for filename to match repo convention.
  local sha_hex="${digest#sha256:}"
  cat > "$repo/release-candidates/platform-backend/${sha_hex}.json" <<JSON
{
  "schema_version": "1.0",
  "repo": "platform-backend",
  "service": "user-service",
  "git_sha": "${sha_hex}",
  "image": {
    "path": "halildeu/platform-backend-user-service",
    "digest": "${digest}"
  },
  "promotion": {
    "test": {
      "smoke_evidence": null,
      "verified_at": null
    },
    "prod": { "smoke_evidence": null, "verified_at": null }
  },
  "audit": { "last_updated_at": null }
}
JSON
}

write_frontend_ledger() {
  local repo="$1" digest="$2" git_sha="$3"
  cat > "$repo/release-candidates/platform-web/${git_sha}.json" <<JSON
{
  "schema_version": "1.0",
  "repo": "platform-web",
  "service": "frontend",
  "git_sha": "${git_sha}",
  "image": {
    "path": "halildeu/platform-web-frontend",
    "digest": "${digest}"
  },
  "promotion": {
    "test": {
      "smoke_evidence": null,
      "verified_at": null
    },
    "prod": { "smoke_evidence": null, "verified_at": null }
  },
  "audit": { "last_updated_at": null }
}
JSON
}

write_backend_overlay() {
  local repo="$1" digest="$2"
  cat > "$repo/kustomize/overlays/test/kustomization.yaml" <<YAML
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: platform-test
resources:
  - deploy-user-service.yaml
YAML
  cat > "$repo/kustomize/overlays/test/deploy-user-service.yaml" <<YAML
apiVersion: apps/v1
kind: Deployment
metadata:
  name: user-service
  labels:
    app.kubernetes.io/name: user-service
spec:
  template:
    spec:
      containers:
        - name: app
          image: ghcr.io/halildeu/platform-backend-user-service@${digest}
YAML
}

write_report() {
  local out="$1" env="$2" variant="$3" up="$4" fn="$5" zb="$6" image="$7" digest="$8" git_sha="$9"
  jq -n \
    --arg env "$env" \
    --arg variant "$variant" \
    --arg up "$up" --arg fn "$fn" --arg zb "$zb" \
    --arg image "$image" --arg digest "$digest" --arg git_sha "$git_sha" \
    '{
       environment: $env,
       variant: (if $variant == "" then null else $variant end),
       exit_code: 0,
       timestamp: "2026-05-21T00:00:00Z",
       image: $image,
       image_digest: $digest,
       git_sha: $git_sha,
       tiers: {
         d29_up:         { status: $up, checked_at: "2026-05-21T00:00:00Z", details: "" },
         d29_functional: { status: $fn, checked_at: "2026-05-21T00:00:00Z", details: "", endpoints: [] },
         d29_zanzibar:   { status: $zb, checked_at: "2026-05-21T00:00:00Z", details: "", allow_deny_synthetic: (if $zb == "GREEN" then "PASS" else "SKIP" end) }
       }
     }' > "$out"
}

run_script() {
  local tmpdir="$1" report="$2"
  # Run the script with PLATFORM_GITOPS_REPO + LEDGER_DRY_RUN=1; capture output.
  PLATFORM_GITOPS_REPO="$tmpdir" \
    LEDGER_DRY_RUN=1 \
    bash "$SCRIPT" "$report" 2>&1 || true
}

# --- Scenario 1: frontend variant AMBER → MARK -------------------------------

scenario_1_frontend_variant_amber_marks() {
  echo "Scenario 1: frontend-prod-variant AMBER zanzibar → MARK"
  local tmpdir; tmpdir=$(mktemp -d)
  trap 'rm -rf "$tmpdir"' RETURN

  setup_fixture_repo "$tmpdir"
  local digest="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  local git_sha="fffffffffffffffffffffffffffffffffffffffff"
  write_frontend_ledger "$tmpdir" "$digest" "$git_sha"

  local report="$tmpdir/report.json"
  write_report "$report" "test" "frontend-prod-variant" "GREEN" "GREEN" "AMBER" \
    "ghcr.io/halildeu/platform-web-frontend@${digest}" "$digest" "$git_sha"

  local out
  out=$(run_script "$tmpdir" "$report")

  assert_contains "target-mode=report_driven detected" "$out" "target-mode=report_driven"
  assert_contains "policy passed for frontend AMBER" "$out" "[POLICY] frontend passed"
  assert_contains "MARK emitted for frontend" "$out" "[MARK] frontend"
  assert_not_contains "no SKIP for AMBER on frontend" "$out" "policy reject"

  rm -rf "$tmpdir"
  trap - RETURN
}

# --- Scenario 2: frontend variant RED → SKIP ---------------------------------

scenario_2_frontend_variant_red_skips() {
  echo "Scenario 2: frontend-prod-variant RED zanzibar → SKIP"
  local tmpdir; tmpdir=$(mktemp -d)
  trap 'rm -rf "$tmpdir"' RETURN

  setup_fixture_repo "$tmpdir"
  local digest="sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  local git_sha="eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
  write_frontend_ledger "$tmpdir" "$digest" "$git_sha"

  local report="$tmpdir/report.json"
  write_report "$report" "test" "frontend-prod-variant" "GREEN" "GREEN" "RED" \
    "ghcr.io/halildeu/platform-web-frontend@${digest}" "$digest" "$git_sha"

  local out
  out=$(run_script "$tmpdir" "$report")

  assert_contains "policy reject for RED zanzibar" "$out" "policy reject"
  assert_contains "reason mentions RED" "$out" "d29_zanzibar status=RED"
  assert_not_contains "no MARK emitted" "$out" "[MARK] frontend"

  rm -rf "$tmpdir"
  trap - RETURN
}

# --- Scenario 3: backend overlay all GREEN → MARK ----------------------------

scenario_3_backend_overlay_all_green_marks() {
  echo "Scenario 3: backend overlay-render all GREEN → MARK"
  local tmpdir; tmpdir=$(mktemp -d)
  trap 'rm -rf "$tmpdir"' RETURN

  if ! command -v kubectl >/dev/null 2>&1; then
    echo "  (skipped — kubectl not available in test env, overlay-render mode requires kubectl kustomize)"
    return 0
  fi

  setup_fixture_repo "$tmpdir"
  local digest="sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
  write_backend_ledger "$tmpdir" "$digest"
  write_backend_overlay "$tmpdir" "$digest"

  local report="$tmpdir/report.json"
  write_report "$report" "test" "" "GREEN" "GREEN" "GREEN" \
    "ghcr.io/halildeu/platform-backend-user-service@${digest}" "$digest" "${digest#sha256:}"

  local out
  out=$(run_script "$tmpdir" "$report")

  assert_contains "target-mode=overlay_render detected" "$out" "target-mode=overlay_render"
  assert_contains "policy passed for backend GREEN" "$out" "[POLICY] user-service passed"
  assert_contains "MARK emitted for user-service" "$out" "[MARK] user-service"

  rm -rf "$tmpdir"
  trap - RETURN
}

# --- Scenario 4: backend overlay AMBER zanzibar → SKIP -----------------------

scenario_4_backend_overlay_amber_skips() {
  echo "Scenario 4: backend overlay-render AMBER zanzibar → SKIP (strict for jwt_validates=true)"
  local tmpdir; tmpdir=$(mktemp -d)
  trap 'rm -rf "$tmpdir"' RETURN

  if ! command -v kubectl >/dev/null 2>&1; then
    echo "  (skipped — kubectl not available in test env, overlay-render mode requires kubectl kustomize)"
    return 0
  fi

  setup_fixture_repo "$tmpdir"
  local digest="sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
  write_backend_ledger "$tmpdir" "$digest"
  write_backend_overlay "$tmpdir" "$digest"

  local report="$tmpdir/report.json"
  write_report "$report" "test" "" "GREEN" "GREEN" "AMBER" \
    "ghcr.io/halildeu/platform-backend-user-service@${digest}" "$digest" "${digest#sha256:}"

  local out
  out=$(run_script "$tmpdir" "$report")

  assert_contains "policy reject for AMBER on backend" "$out" "policy reject"
  assert_contains "reason mentions Zanzibar-required" "$out" "Zanzibar-required"
  assert_not_contains "no MARK emitted" "$out" "[MARK] user-service"

  rm -rf "$tmpdir"
  trap - RETURN
}

# --- Driver ------------------------------------------------------------------

scenario_1_frontend_variant_amber_marks
scenario_2_frontend_variant_red_skips
scenario_3_backend_overlay_all_green_marks
scenario_4_backend_overlay_amber_skips

echo
echo "==== Test summary: $PASS passed, $FAIL failed ===="
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
