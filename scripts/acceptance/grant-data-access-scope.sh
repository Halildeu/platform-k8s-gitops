#!/usr/bin/env bash
# Canonical data-access scope helper — board #2534 (Faz 22).
#
# ## Why this exists
#
# The tools this replaces all produced FALSE evidence:
#   * bootstrap/seed-test-variant-canary-scope.sh wrote permission_db tables
#     that are never read while ERP_OPENFGA_ENABLED=true — reported success,
#     changed nothing observable.
#   * scripts/d35-3/openfga-access-tuple-seed.sh POSTs OpenFGA
#     /stores/{id}/write directly, which is a DD-EA-2 boundary violation and
#     bypasses every product-side invariant (scope_ref validation, outbox,
#     audit row, authz version bump).
#
# #2534 decision: producing a 200 by seeding the DB or OpenFGA directly is NOT
# evidence that the supported product path works. Acceptance must traverse the
# product API. This helper therefore does exactly one thing: it drives
# POST/DELETE /api/v1/access/scope the way a real admin would, and reads back
# through /authz/me.
#
# ## Separation of concerns (#2534)
#
# Mutation and observation are separate verbs on purpose — a runner that grants
# and asserts in one breath cannot distinguish "the grant worked" from "the
# assertion is reading its own write".
#
#   --check    read-only. Never mutates. Safe against any environment.
#   --apply    idempotent grant through the product API.
#   --dispose  revoke ONLY what this helper created (ownership-marked).
#
# ## Ownership marker
#
# --apply stamps `grantedBy` with the acting subject and records the scope id
# in a local ledger under ${STATE_DIR}. --dispose revokes only ids present in
# that ledger, so it can never sweep a grant made by an operator or another
# tool. Narrow cleanup, by construction.
#
# ## No rollout restart
#
# The predecessor told operators to `kubectl rollout restart` to clear the
# scope cache — forbidden by ADR-0023 on the shared k3d-test cluster and
# disruptive to parallel sessions. Instead --check POLLS until the authz
# version/cache TTL has propagated (bounded by SCOPE_PROPAGATION_TIMEOUT), so
# convergence is observed rather than forced.
#
# ## Usage
#
#   TOKEN=<jwt> ./grant-data-access-scope.sh --check   --user <kc-uuid>
#   TOKEN=<jwt> ./grant-data-access-scope.sh --apply   --user <kc-uuid> \
#                                            --kind PROJECT --ref 1204
#   TOKEN=<jwt> ./grant-data-access-scope.sh --dispose --user <kc-uuid>
#
# TOKEN must carry module:ACCESS#can_manage for --apply/--dispose. Obtain it
# via the smoke-client ROPC recipe (see docs/handoff-smoke-client-keycloak.md);
# never inline a secret into argv.

set -euo pipefail

BASE_URL="${BASE_URL:-https://testai.acik.com}"
STATE_DIR="${STATE_DIR:-${TMPDIR:-/tmp}/acceptance-scope-ledger}"
SCOPE_PROPAGATION_TIMEOUT="${SCOPE_PROPAGATION_TIMEOUT:-60}"
ORG_ID="${ORG_ID:-1}"

MODE=""
USER_UUID=""
SCOPE_KIND=""
SCOPE_REF=""

die() { echo "[grant-data-access-scope] $*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --check|--apply|--dispose)
      [[ -n "$MODE" ]] && die "only one of --check/--apply/--dispose"
      MODE="${1#--}"; shift ;;
    --user) USER_UUID="${2:-}"; shift 2 ;;
    --kind) SCOPE_KIND="${2:-}"; shift 2 ;;
    --ref)  SCOPE_REF="${2:-}";  shift 2 ;;
    *) die "unknown argument: $1" ;;
  esac
done

[[ -n "$MODE" ]] || die "one of --check / --apply / --dispose is required"
[[ -n "$USER_UUID" ]] || die "--user <kc-uuid> is required"
: "${TOKEN:?TOKEN env required (JWT; never pass a secret in argv)}"

# The subject is a Keycloak UUID, never a platform numeric id. Conflating the
# two identity spaces is the #2530 root cause; reject the numeric form loudly
# instead of sending it and debugging an empty allowedScopes later.
if [[ "$USER_UUID" =~ ^[0-9]+$ ]]; then
  die "--user got a numeric id ('$USER_UUID'). The access-scope API keys on the Keycloak subject (UUID). Passing a platform numeric id is the #2530 identity drift — it will 201 and grant nothing reachable."
fi

mkdir -p "$STATE_DIR"
LEDGER="${STATE_DIR}/$(printf '%s' "$USER_UUID" | tr -c 'a-zA-Z0-9-' '_').ids"

api() {
  # $1=method $2=path ; body on stdin when present. Prints "<http_code>\n<body>".
  local method="$1" path="$2" body_file
  body_file="$(mktemp)"
  local code
  if [[ ! -t 0 ]]; then
    code=$(curl -sk -o "$body_file" -w '%{http_code}' -X "$method" "${BASE_URL}${path}" \
      -H "Authorization: Bearer ${TOKEN}" -H 'Content-Type: application/json' --data-binary @-)
  else
    code=$(curl -sk -o "$body_file" -w '%{http_code}' -X "$method" "${BASE_URL}${path}" \
      -H "Authorization: Bearer ${TOKEN}")
  fi
  printf '%s\n' "$code"
  cat "$body_file"
  rm -f "$body_file"
}

read_allowed_scopes() {
  local out code
  out="$(api GET /api/v1/authz/me < /dev/null)"
  code="$(printf '%s' "$out" | head -1)"
  [[ "$code" == "200" ]] || { echo "[check] /authz/me → HTTP $code" >&2; return 1; }
  printf '%s' "$out" | tail -n +2 | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    print("{}"); raise SystemExit(0)
print(json.dumps(d.get("allowedScopes", {}), sort_keys=True))
'
}

case "$MODE" in
  check)
    echo "[check] read-only — no mutation will be attempted"
    scopes="$(read_allowed_scopes)" || die "cannot read /authz/me"
    echo "[check] allowedScopes: $scopes"
    ;;

  apply)
    [[ -n "$SCOPE_KIND" && -n "$SCOPE_REF" ]] || die "--apply requires --kind and --ref"
    [[ "$SCOPE_REF" =~ ^[0-9]+$ ]] || die "--ref must be the bare numeric entity id (e.g. 1204); this helper wraps it in the JSON-array form the API requires"

    # scopeRef is a JSON ARRAY STRING ('["1204"]'). A bare "1204" is rejected
    # 400 ScopeReferenceInvalid — that validation is #2555 Slice B and is
    # deliberately not worked around here; the helper produces the canonical
    # shape so the product invariant stays exercised.
    payload=$(python3 -c '
import json, sys
uid, org, kind, ref = sys.argv[1:5]
print(json.dumps({
    "userId": uid,
    "orgId": int(org),
    "scopeKind": kind,
    "scopeRef": json.dumps([ref]),
    "grantedBy": uid,
}))' "$USER_UUID" "$ORG_ID" "$SCOPE_KIND" "$SCOPE_REF")

    out="$(printf '%s' "$payload" | api POST /api/v1/access/scope)"
    code="$(printf '%s' "$out" | head -1)"
    body="$(printf '%s' "$out" | tail -n +2)"

    case "$code" in
      201)
        scope_id="$(printf '%s' "$body" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("scopeId",""))' 2>/dev/null || true)"
        [[ -n "$scope_id" ]] && echo "$scope_id" >> "$LEDGER"
        echo "[apply] granted ${SCOPE_KIND}:${SCOPE_REF} → scopeId=${scope_id:-?} (ledger: $LEDGER)" ;;
      409)
        # Idempotent: the grant already exists. Not an error — re-running the
        # helper must converge, not fail.
        echo "[apply] already granted ${SCOPE_KIND}:${SCOPE_REF} (409) — idempotent no-op" ;;
      400)
        die "400 from /access/scope — payload rejected by a product invariant, NOT worked around: $body" ;;
      403)
        die "403 — TOKEN lacks module:ACCESS#can_manage. Grant the acting principal first (board #2704)." ;;
      *)
        die "unexpected HTTP $code from /access/scope: $body" ;;
    esac

    # Observe convergence instead of forcing it (no rollout restart, ADR-0023).
    echo "[apply] polling /authz/me for propagation (timeout ${SCOPE_PROPAGATION_TIMEOUT}s)…"
    deadline=$(( SECONDS + SCOPE_PROPAGATION_TIMEOUT ))
    while (( SECONDS < deadline )); do
      if read_allowed_scopes | grep -q "\"${SCOPE_REF}\"\\|${SCOPE_REF}"; then
        echo "[apply] converged — ${SCOPE_KIND}:${SCOPE_REF} visible in allowedScopes"
        exit 0
      fi
      sleep 3
    done
    die "grant accepted but did NOT appear in /authz/me within ${SCOPE_PROPAGATION_TIMEOUT}s — report this rather than treating the 201 as acceptance (that gap is exactly the #2531 class of bug)"
    ;;

  dispose)
    [[ -s "$LEDGER" ]] || { echo "[dispose] nothing owned by this helper for $USER_UUID — no-op"; exit 0; }
    rc=0
    while IFS= read -r scope_id; do
      [[ -z "$scope_id" ]] && continue
      out="$(api DELETE "/api/v1/access/scope/${scope_id}" < /dev/null)"
      code="$(printf '%s' "$out" | head -1)"
      case "$code" in
        200|204|404) echo "[dispose] scopeId=${scope_id} revoked (HTTP $code)" ;;
        *) echo "[dispose] scopeId=${scope_id} FAILED (HTTP $code)" >&2; rc=1 ;;
      esac
    done < "$LEDGER"
    # Only clear the ledger when every entry was actually disposed — a partial
    # failure must stay recoverable rather than being forgotten.
    if [[ "$rc" == "0" ]]; then
      rm -f "$LEDGER"
      echo "[dispose] ledger cleared"
    else
      echo "[dispose] ledger RETAINED — some revokes failed, re-run after fixing" >&2
    fi
    exit "$rc"
    ;;
esac
