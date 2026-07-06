#!/usr/bin/env bash
# vault-policy-reconcile.sh — GitOps reconcile of TEST-Vault CONFIG (ACL policies
# + scoped AppRoles) from bootstrap/vault-policies/, using the
# `vault-config-reconciler` AppRole. NO root token; idempotent; re-runnable.
#
# ADR-0010. Pairs with bootstrap/vault-policies/test/vault-config-reconciler.hcl.
# The PR + cross-AI review of the committed policy files is the CONTENT GATE —
# this script only APPLIES git-reviewed content, never authors policy at runtime.
#
# Auth (no root): role-id/secret-id of the reconciler AppRole, provisioned ONCE by
# the owner (README §6.6) into host-local 0600 files (or env). Token self-revoked.
#
# Usage (on staging-sw, where platform-vault-test :8201 is reachable):
#   VAULT_RECONCILER_ROLE_ID_FILE=/home/halil/.vault/reconciler-role-id \
#   VAULT_RECONCILER_SECRET_ID_FILE=/home/halil/.vault/reconciler-secret-id \
#   scripts/ops/vault-policy-reconcile.sh [--dry-run] [--emit-seed-secret-id <approle>]
#
# Scope: TEST Vault only. Applies common/*.hcl + test/*.hcl. NEVER prod/*.

set -uo pipefail

VAULT_ADDR="${VAULT_ADDR:-http://127.0.0.1:8201}"   # platform-vault-test
REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." 2>/dev/null && pwd || echo /home/halil/platform-k8s-gitops)}"
POLDIR="$REPO_ROOT/bootstrap/vault-policies"
DRY_RUN=0
EMIT_SEED=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --emit-seed-secret-id) EMIT_SEED="$2"; shift 2 ;;
    *) echo "ERROR: unknown flag $1" >&2; exit 2 ;;
  esac
done

# ── Manifest: policy FILE (rel to POLDIR) → Vault policy NAME ────────────────
# Explicit (filename != policy name) + auditable. Add a row per governance policy.
# NOTE (Codex 019f1150): `vault-config-reconciler` itself is INTENTIONALLY ABSENT
# — no self-amendment; its policy/approle are owner-gated (README §6.6).
POLICIES=(
  "common/eso-runtime.hcl|eso-runtime"
  "common/bootstrap-writer.hcl|platform-bootstrap-writer"
  "test/eso-runtime-extras.hcl|eso-runtime-test-extras"
  "test/audio-gateway-mtls-seeder.hcl|audio-gateway-mtls-seeder"
)

# Content linter (Codex 019f1150): fail-closed reject any policy text that would
# grant escalation primitives — defense-in-depth against a malicious git change
# that named-path scoping alone can't stop (the holder could otherwise widen an
# allowlisted policy). A policy carrying these on a non-deny line is rejected.
ESCALATION_RE='(auth/token/create|auth/token/root|sys/policies|sys/policy/|sys/auth|sys/raw|sys/storage|sys/audit|sys/generate-root|sys/seal|sys/unseal|sys/rekey|identity/)'
lint_policy() { # lint_policy <name> <file> ; echo OK / FAIL:<reason>
  local name="$1" file="$2"
  # strip comments + deny lines, then look for escalation paths on grant lines
  local hits
  hits=$(grep -vE '^\s*#' "$file" \
    | awk 'BEGIN{RS="}"} !/deny/' \
    | grep -oE "\"[^\"]*($ESCALATION_RE)[^\"]*\"" 2>/dev/null | sort -u | head)
  if [[ -n "$hits" ]]; then
    echo "FAIL: escalation path(s) on non-deny grant: $(echo "$hits" | tr '\n' ' ')"
  else
    echo "OK"
  fi
}

# ── Manifest: AppRole NAME | token_policies (csv) | extra `vault write` kv args ─
APPROLES=(
  "eso-runtime|eso-runtime,eso-runtime-test-extras|token_ttl=1h token_max_ttl=24h secret_id_ttl=0"
  "platform-bootstrap-writer-test|platform-bootstrap-writer|token_ttl=30m token_max_ttl=60m secret_id_ttl=60m secret_id_num_uses=10 bind_secret_id=true"
  "audio-gateway-mtls-seeder-test|audio-gateway-mtls-seeder|token_ttl=15m token_max_ttl=15m token_num_uses=0 secret_id_ttl=30m secret_id_num_uses=1 bind_secret_id=true"
)

# ── reconciler AppRole auth ──────────────────────────────────────────────────
ROLE_ID="${VAULT_RECONCILER_ROLE_ID:-$(cat "${VAULT_RECONCILER_ROLE_ID_FILE:-/home/halil/.vault/reconciler-role-id}" 2>/dev/null | tr -d '\r\n')}"
SECRET_ID="${VAULT_RECONCILER_SECRET_ID:-$(cat "${VAULT_RECONCILER_SECRET_ID_FILE:-/home/halil/.vault/reconciler-secret-id}" 2>/dev/null | tr -d '\r\n')}"
[[ -n "$ROLE_ID" && -n "$SECRET_ID" ]] || { echo "ERROR: reconciler role-id/secret-id missing (owner provision — README §6.6)" >&2; exit 2; }

api() { # api METHOD PATH [JSON]
  local m="$1" p="$2" body="${3:-}"
  if [[ -n "$body" ]]; then
    curl -sf -X "$m" -H "X-Vault-Token: ${TOKEN:-}" "$VAULT_ADDR/v1/$p" -d "$body"
  else
    curl -sf -X "$m" -H "X-Vault-Token: ${TOKEN:-}" "$VAULT_ADDR/v1/$p"
  fi
}

TOKEN=$(curl -sf -X POST "$VAULT_ADDR/v1/auth/approle/login" \
  -d "{\"role_id\":\"$ROLE_ID\",\"secret_id\":\"$SECRET_ID\"}" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["auth"]["client_token"])' 2>/dev/null) \
  || { echo "ERROR: reconciler AppRole login failed" >&2; exit 3; }
cleanup() { [[ -n "${TOKEN:-}" ]] && curl -sf -X POST -H "X-Vault-Token: $TOKEN" "$VAULT_ADDR/v1/auth/token/revoke-self" >/dev/null 2>&1 || true; unset TOKEN SECRET_ID; }
trap cleanup EXIT

echo "=== reconcile @ $VAULT_ADDR (dry-run=$DRY_RUN) ==="

# ── apply ACL policies (git content → sys/policies/acl/<name>) ───────────────
LINT_FAIL=0
for row in "${POLICIES[@]}"; do
  f="${row%%|*}"; name="${row##*|}"; path="$POLDIR/$f"
  [[ -f "$path" ]] || { echo "  SKIP  $name (file yok: $f)"; continue; }
  lint=$(lint_policy "$name" "$path")
  if [[ "$lint" != "OK" ]]; then echo "  REJECT $name — $lint" >&2; LINT_FAIL=1; continue; fi
  body=$(python3 -c 'import json,sys; print(json.dumps({"policy": open(sys.argv[1]).read()}))' "$path")
  if [[ "$DRY_RUN" == "1" ]]; then echo "  DRY   policy $name <- $f (lint OK)"; continue; fi
  if api PUT "sys/policies/acl/$name" "$body" >/dev/null; then echo "  OK    policy $name"; else echo "  FAIL  policy $name" >&2; fi
done
[[ "$LINT_FAIL" == "1" ]] && { echo "ABORT: bir policy escalation-linter'a takıldı (yukarı bak)." >&2; exit 4; }

# ── ensure scoped AppRoles ───────────────────────────────────────────────────
for row in "${APPROLES[@]}"; do
  IFS='|' read -r rname rpol rargs <<<"$row"
  read -ra argpairs <<<"token_policies=$rpol $rargs"
  if [[ "$DRY_RUN" == "1" ]]; then echo "  DRY   approle $rname (${argpairs[*]})"; continue; fi
  body=$(python3 -c 'import json,sys; d={}; [d.update({k:v}) for k,v in (a.split("=",1) for a in sys.argv[1:])]; print(json.dumps(d))' "${argpairs[@]}")
  if api POST "auth/approle/role/$rname" "$body" >/dev/null; then echo "  OK    approle $rname"; else echo "  FAIL  approle $rname" >&2; fi
done

# ── optionally emit a fresh secret-id for one seed AppRole (for the agent) ────
if [[ -n "$EMIT_SEED" && "$DRY_RUN" != "1" ]]; then
  RID=$(api GET "auth/approle/role/$EMIT_SEED/role-id" | python3 -c 'import sys,json;print(json.load(sys.stdin)["data"]["role_id"])' 2>/dev/null)
  SID=$(api POST "auth/approle/role/$EMIT_SEED/secret-id" '' | python3 -c 'import sys,json;print(json.load(sys.stdin)["data"]["secret_id"])' 2>/dev/null)
  umask 077
  printf '%s' "$RID" > "/tmp/${EMIT_SEED}-role-id.txt"
  printf '%s' "$SID" > "/tmp/${EMIT_SEED}-secret-id.txt"
  chmod 600 "/tmp/${EMIT_SEED}-role-id.txt" "/tmp/${EMIT_SEED}-secret-id.txt"
  echo "  EMIT  $EMIT_SEED → role-id (paylasilabilir): $RID ; secret-id: /tmp/${EMIT_SEED}-secret-id.txt (0600)"
fi

echo "=== reconcile done ==="
