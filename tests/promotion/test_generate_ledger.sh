#!/usr/bin/env bash
# tests/promotion/test_generate_ledger.sh — gitops#3677 per-service names + artifact-matched idempotency
# (Codex 01a09219 P1: an existing same-service file with another digest is a different artifact).
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GEN="$REPO_ROOT/scripts/promotion/generate-ledger.sh"
PASS=0; FAIL=0
ok()   { echo "  ✓ $1"; PASS=$((PASS+1)); }
bad()  { echo "  ✗ $1"; echo "    $2" | head -5; FAIL=$((FAIL+1)); }
SHA="3333333333333333333333333333333333333333"
D1="sha256:1111111111111111111111111111111111111111111111111111111111111111"
D2="sha256:2222222222222222222222222222222222222222222222222222222222222222"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
mkdir -p "$T/schema"; cp "$REPO_ROOT/schema/promotion-ledger-v1.schema.json" "$T/schema/"
run() { PLATFORM_GITOPS_REPO="$T" bash "$GEN" "$@" 2>&1; }

echo "1. first write → per-service file name"
out=$(run platform-backend schema-service "$SHA" halildeu/platform-backend-schema-service "$D1"); rc=$?
f="$T/release-candidates/platform-backend/$SHA-schema-service.json"
[[ $rc -eq 0 && -f "$f" ]] && ok "wrote $SHA-schema-service.json" || bad "write" "$out"
[[ "$(jq -r .image.tag "$f")" == "sha-3333333" ]] && ok "tag from the commit" || bad "tag" "$(jq -c . "$f")"

echo "2. same artifact again → idempotent, same file"
out=$(run platform-backend schema-service "$SHA" halildeu/platform-backend-schema-service "$D1"); rc=$?
[[ $rc -eq 0 && "$(printf '%s\n' "$out" | tail -1)" == "$f" ]] && ok "idempotent" || bad "idempotent" "$out"

echo "3. second service of the same commit → its own file"
out=$(run platform-backend permission-service "$SHA" halildeu/platform-backend-permission-service "$D2"); rc=$?
[[ $rc -eq 0 && -f "$T/release-candidates/platform-backend/$SHA-permission-service.json" ]] && ok "two services, two files" || bad "second service" "$out"

echo "4. same name, DIFFERENT digest → refused (exit 3), file untouched"
out=$(run platform-backend schema-service "$SHA" halildeu/platform-backend-schema-service "$D2"); rc=$?
[[ $rc -eq 3 ]] && ok "exit 3 on collision" || bad "collision rc=$rc" "$out"
[[ "$(jq -r .image.digest "$f")" == "$D1" ]] && ok "original entry untouched" || bad "overwritten" "$(jq -c . "$f")"

echo "5. legacy <sha>.json of the same service + same artifact → preserved (legacy path returned)"
SHA2="4444444444444444444444444444444444444444"
mkdir -p "$T/release-candidates/platform-web"
jq -n --arg sha "$SHA2" --arg d "$D1" '{repo:"platform-web",service:"frontend",git_sha:$sha,image:{path:"halildeu/platform-web-frontend",digest:$d}}' > "$T/release-candidates/platform-web/$SHA2.json"
out=$(run platform-web frontend "$SHA2" halildeu/platform-web-frontend "$D1"); rc=$?
[[ $rc -eq 0 && "$(printf '%s\n' "$out" | tail -1)" == "$T/release-candidates/platform-web/$SHA2.json" ]] && ok "legacy preserved" || bad "legacy" "$out"
[[ ! -f "$T/release-candidates/platform-web/$SHA2-frontend.json" ]] && ok "no duplicate per-service file" || bad "duplicate written" ""

echo "6. legacy <sha>.json of the same service but ANOTHER digest → collision (exit 3), nothing written (one commit+service = one artifact)"
out=$(run platform-web frontend "$SHA2" halildeu/platform-web-frontend "$D2"); rc=$?
[[ $rc -eq 3 ]] && ok "exit 3 on legacy collision" || bad "legacy other digest rc=$rc" "$out"
[[ ! -f "$T/release-candidates/platform-web/$SHA2-frontend.json" ]] && ok "no per-service file written beside the legacy one" || bad "file written" ""
[[ "$(jq -r .image.digest "$T/release-candidates/platform-web/$SHA2.json")" == "$D1" ]] && ok "legacy entry untouched" || bad "legacy mutated" ""

echo; echo "==== $PASS passed, $FAIL failed ===="; [[ $FAIL -eq 0 ]]
