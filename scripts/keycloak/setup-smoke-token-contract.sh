#!/usr/bin/env bash
# A2b.1 — smoke-client token contract (desired-state, idempotent, fail-closed).
#
# board #2476 · Codex (OpenAI) thread 019f6b1d — v3.2 SEAL (REVISE ×3 → AGREE).
# Runbook: docs/operations/RUNBOOKS/RB-kc-realm-security-hardening.md
#
# NE YAPAR (yalnız Keycloak; consumer manifest mutasyonu YOK):
#   smoke-runtime-v1 (DEFAULT association)
#     ├── userId  (attr=userId claim=userId jsonType=String)   ← frontend parity (canlıda String, long DEĞİL)
#     └── audience ×6: endpoint-admin-service, permission-service, variant-service,
#                      notification-orchestrator, auth-service (custom) + account (gerçek client)
#   smoke-notify-v1 (OPTIONAL association)
#     └── org_id  (attr=org_id claim=org_id jsonType=String)
#   realm scope-mapping: ENDPOINT_ADMIN  (fullScopeAllowed=false kalır)
#
# NE YAPMAZ (Codex v3.2 gerekçeleriyle):
#   - consumer `azp` allow-list'e smoke-client EKLEMEZ: endpoint-admin validator semantiği
#     `audience OR azp OR client_id` → allow-list'e eklemek audience binding'ini BYPASS eden
#     fallback açar; smoke'un audience'tan geçtiği kanıtı kaybolur.
#   - notify-canary'ye DOKUNMAZ: shared scope (frontend'de DEFAULT); backend scope marker'ını
#     okumuyor (guard: org_id → tenant_id → allowed_orgs → default). Sessizce sahiplenme YASAK.
#   - tenant_id mapper EKLEMEZ: aynı org_id attribute'unun ikinci alias'ı = gereksiz genişleme.
#   - client-level mapper EKLEMEZ: mapper'lar scope-owned kalır (client mapper sayısı 0).
#
# Secret disiplini: admin password stdout/log'a yazılmaz; `set -x` / process-dump YASAK.
set -euo pipefail

MODE="${1:---check}"
REALM="${REALM:-platform-test}"
CLIENT_ID="smoke-client"
RUNTIME_SCOPE="smoke-runtime-v1"
NOTIFY_SCOPE="smoke-notify-v1"
REALM_ROLE="ENDPOINT_ADMIN"

# ---- Ortam hard-bind (A2a Codex must-fix: cross-env drift engeli) ----
case "$REALM" in
  platform-test)
    KC_CONTAINER="platform-kc-test"
    ;;
  serban|platform-prod)
    KC_CONTAINER="platform-kc-prod"
    if [ "${CONFIRM_PROD_SMOKE_CONTRACT:-}" != "$REALM" ]; then
      echo "ERROR: PROD realm '$REALM' owner-gated — CONFIRM_PROD_SMOKE_CONTRACT=$REALM zorunlu" >&2
      exit 1
    fi
    ;;
  *)
    echo "ERROR: bilinmeyen realm '$REALM' (izinli: platform-test | serban)" >&2
    exit 1
    ;;
esac
if [ -n "${KC_CONTAINER_OVERRIDE:-}" ]; then
  echo "ERROR: KC_CONTAINER_OVERRIDE fail-closed — realm→container eşlemesi koda bağlı" >&2
  exit 1
fi
echo "== A2b.1 smoke token contract =="
echo "realm=$REALM container=$KC_CONTAINER mode=$MODE"

K() { docker exec "$KC_CONTAINER" /opt/keycloak/bin/kcadm.sh "$@"; }
KI() { docker exec -i "$KC_CONTAINER" /opt/keycloak/bin/kcadm.sh "$@"; }

kc_login() {
  local p
  p="$(docker exec "$KC_CONTAINER" sh -lc 'cat "$KEYCLOAK_ADMIN_PASSWORD_FILE"' | tr -d '\n')"
  [ -n "$p" ] || { echo "ERROR: admin password okunamadı" >&2; return 1; }
  K config credentials --server http://localhost:8080 --realm master --user admin --password "$p" >/dev/null 2>&1
  unset p
}

# ---- Desired state (tek kaynak) ----
# Audience mapper'ları: 5 custom + 1 gerçek client (account).
DESIRED_AUDIENCES_CUSTOM="endpoint-admin-service permission-service variant-service notification-orchestrator auth-service"
DESIRED_AUDIENCE_CLIENT="account"

desired_runtime_json() {
  python3 - "$RUNTIME_SCOPE" "$DESIRED_AUDIENCES_CUSTOM" "$DESIRED_AUDIENCE_CLIENT" <<'PY'
import json, sys
name, customs, client_aud = sys.argv[1], sys.argv[2].split(), sys.argv[3]
mappers = [{
    "name": "userId",
    "protocol": "openid-connect",
    "protocolMapper": "oidc-usermodel-attribute-mapper",
    "consentRequired": False,
    "config": {
        "user.attribute": "userId",
        "claim.name": "userId",
        "jsonType.label": "String",
        "access.token.claim": "true",
        "id.token.claim": "false",
        "userinfo.token.claim": "false",
    },
}]
for a in customs:
    mappers.append({
        "name": f"aud-{a}",
        "protocol": "openid-connect",
        "protocolMapper": "oidc-audience-mapper",
        "consentRequired": False,
        "config": {
            "included.custom.audience": a,
            "access.token.claim": "true",
            "id.token.claim": "false",
        },
    })
mappers.append({
    "name": f"aud-{client_aud}",
    "protocol": "openid-connect",
    "protocolMapper": "oidc-audience-mapper",
    "consentRequired": False,
    "config": {
        "included.client.audience": client_aud,
        "access.token.claim": "true",
        "id.token.claim": "false",
    },
})
print(json.dumps({
    "name": name,
    "description": "A2b.1 smoke-client runtime token contract (board #2476, Codex 019f6b1d v3.2)",
    "protocol": "openid-connect",
    "attributes": {"include.in.token.scope": "true", "display.on.consent.screen": "false"},
    "protocolMappers": mappers,
}))
PY
}

desired_notify_json() {
  python3 - "$NOTIFY_SCOPE" <<'PY'
import json, sys
print(json.dumps({
    "name": sys.argv[1],
    "description": "A2b.1 smoke-client optional org boundary claim (board #2476, Codex 019f6b1d v3.2)",
    "protocol": "openid-connect",
    "attributes": {"include.in.token.scope": "true", "display.on.consent.screen": "false"},
    "protocolMappers": [{
        "name": "org_id",
        "protocol": "openid-connect",
        "protocolMapper": "oidc-usermodel-attribute-mapper",
        "consentRequired": False,
        "config": {
            "user.attribute": "org_id",
            "claim.name": "org_id",
            "jsonType.label": "String",
            "access.token.claim": "true",
            "id.token.claim": "false",
            "userinfo.token.claim": "false",
        },
    }],
}))
PY
}

scope_id() {  # $1=scope name → id ("" yoksa)
  K get client-scopes -r "$REALM" --fields id,name 2>/dev/null | python3 -c '
import json, sys
d = json.load(sys.stdin)
print(next((x["id"] for x in d if x["name"] == sys.argv[1]), ""))' "$1"
}

client_uuid() {
  K get clients -r "$REALM" -q "clientId=$CLIENT_ID" --fields id 2>/dev/null | python3 -c '
import json, sys
d = json.load(sys.stdin)
print(d[0]["id"] if d else "")'
}

# Mevcut scope'un mapper shape'ini desired ile karşılaştırır.
# stdout: MATCH | DRIFT:<detay>   (exit her zaman 0; karar çağırana ait)
compare_scope() {  # $1=scope-id  $2=desired-json
  # NOT: python heredoc stdin'i kullanır → desired/live PIPE ile verilemez (SC2259:
  # heredoc pipe'ı ezer). İkisi de tmpfile + argv ile geçilir.
  local sid="$1" desired="$2" lf df out
  lf="$(mktemp "${TMPDIR:-/tmp}/.kcsc-live.XXXXXX")"
  df="$(mktemp "${TMPDIR:-/tmp}/.kcsc-desired.XXXXXX")"
  K get "client-scopes/$sid" -r "$REALM" > "$lf" 2>/dev/null || true
  printf '%s' "$desired" > "$df"
  out="$(python3 - "$df" "$lf" <<'PY'
import json, sys
with open(sys.argv[1]) as f:
    desired = json.load(f)
with open(sys.argv[2]) as f:
    live = json.load(f)

def norm(ms):
    out = {}
    for m in ms or []:
        out[m["name"]] = {
            "protocolMapper": m.get("protocolMapper"),
            "config": {k: v for k, v in (m.get("config") or {}).items()
                       if k in ("user.attribute", "claim.name", "jsonType.label",
                                "access.token.claim", "id.token.claim",
                                "userinfo.token.claim", "included.custom.audience",
                                "included.client.audience")},
        }
    return out

d_m, l_m = norm(desired["protocolMappers"]), norm(live.get("protocolMappers"))
issues = []
if live.get("protocol") != desired["protocol"]:
    issues.append("protocol=%s (beklenen %s)" % (live.get("protocol"), desired["protocol"]))
for k, v in desired["attributes"].items():
    if (live.get("attributes") or {}).get(k) != v:
        issues.append("attr %s=%s (beklenen %s)" % (k, (live.get("attributes") or {}).get(k), v))
missing = sorted(set(d_m) - set(l_m))
extra = sorted(set(l_m) - set(d_m))
if missing:
    issues.append("eksik mapper: %s" % ",".join(missing))
if extra:
    issues.append("BEKLENMEYEN mapper: %s" % ",".join(extra))
for n in sorted(set(d_m) & set(l_m)):
    if d_m[n] != l_m[n]:
        issues.append("mapper %s config farkli: live=%s" % (n, json.dumps(l_m[n], sort_keys=True)))
print("MATCH" if not issues else "DRIFT:" + " | ".join(issues))
PY
  )" || { rm -f "$lf" "$df"; echo "DRIFT:compare hatası (live JSON parse edilemedi)"; return 0; }
  rm -f "$lf" "$df"
  printf '%s\n' "$out"
}

ensure_scope() {  # $1=name $2=desired-json ; echo'lar: CREATED|MATCH|DRIFT:...
  local name="$1" desired="$2" sid
  sid="$(scope_id "$name")"
  if [ -z "$sid" ]; then
    if [ "$MODE" = "--apply" ]; then
      printf '%s' "$desired" | KI create client-scopes -r "$REALM" -f - >/dev/null 2>&1 || {
        echo "ERROR: client-scope create başarısız: $name" >&2; return 1; }
      sid="$(scope_id "$name")"
      [ -n "$sid" ] || { echo "ERROR: create sonrası scope bulunamadı: $name" >&2; return 1; }
      echo "CREATED"
    else
      echo "DRIFT:scope YOK (create gerekli)"
    fi
    return 0
  fi
  compare_scope "$sid" "$desired"
}

# ---- Preflight (Codex şartı) ----
preflight() {
  local rc=0
  echo "-- preflight --"
  local role_json
  role_json="$(K get "roles/$REALM_ROLE" -r "$REALM" --fields name,composite 2>/dev/null || true)"
  if ! printf '%s' "$role_json" | grep -q '"name"'; then
    echo "  [FAIL] realm rolü '$REALM_ROLE' YOK — scope-mapping apply edilemez"; rc=1
  elif printf '%s' "$role_json" | grep -q '"composite" : true'; then
    echo "  [FAIL] '$REALM_ROLE' composite=true — effective child role listesi incelenmeden apply YASAK (Codex)"; rc=1
  else
    echo "  [OK] $REALM_ROLE var, composite=false"
  fi

  local cid; cid="$(client_uuid)"
  [ -n "$cid" ] || { echo "  [FAIL] client '$CLIENT_ID' YOK — önce A2a (setup-smoke-client.sh)"; return 1; }
  local cj; cj="$(K get "clients/$cid" -r "$REALM" --fields fullScopeAllowed,serviceAccountsEnabled 2>/dev/null)"
  printf '%s' "$cj" | grep -q '"fullScopeAllowed" : false' \
    && echo "  [OK] fullScopeAllowed=false" || { echo "  [FAIL] fullScopeAllowed=false DEĞİL"; rc=1; }
  printf '%s' "$cj" | grep -q '"serviceAccountsEnabled" : false' \
    && echo "  [OK] serviceAccounts=false (A2a shape korunuyor)" || { echo "  [FAIL] serviceAccountsEnabled≠false"; rc=1; }

  # notify-canary'ye dokunmadığımızın kanıtı: association listesinde olmamalı
  local assoc; assoc="$(K get "clients/$cid" -r "$REALM" --fields defaultClientScopes,optionalClientScopes 2>/dev/null)"
  if printf '%s' "$assoc" | grep -q 'notify-canary'; then
    echo "  [FAIL] smoke-client'a notify-canary bağlanmış — Codex v3.2: association YOK"; rc=1
  else
    echo "  [OK] notify-canary smoke-client'a bağlı değil (shared scope'a dokunulmuyor)"
  fi
  return $rc
}

# ---- Association + scope-mapping ----
ensure_association() {  # $1=scope-name $2=default|optional
  local name="$1" kind="$2" cid sid live
  cid="$(client_uuid)"; sid="$(scope_id "$name")"
  [ -n "$sid" ] || { echo "SKIP(scope yok)"; return 0; }
  live="$(K get "clients/$cid/$kind-client-scopes" -r "$REALM" --fields name 2>/dev/null | python3 -c '
import json, sys
d = json.load(sys.stdin)
print("YES" if any(x["name"] == sys.argv[1] for x in d) else "NO")' "$name")"
  if [ "$live" = "YES" ]; then echo "MATCH"; return 0; fi
  if [ "$MODE" = "--apply" ]; then
    K update "clients/$cid/$kind-client-scopes/$sid" -r "$REALM" >/dev/null 2>&1 \
      || { echo "ERROR: $kind association başarısız: $name" >&2; return 1; }
    echo "ADDED"
  else
    echo "DRIFT:$kind association yok"
  fi
}

ensure_scope_mapping() {
  local cid; cid="$(client_uuid)"
  local live
  live="$(K get "clients/$cid/scope-mappings/realm" -r "$REALM" --fields name 2>/dev/null | python3 -c '
import json, sys
d = json.load(sys.stdin)
print(",".join(sorted(x["name"] for x in d)) or "-")')"
  if [ "$live" = "$REALM_ROLE" ]; then echo "MATCH"; return 0; fi
  if [ "$live" != "-" ] && [ "$live" != "$REALM_ROLE" ]; then
    echo "DRIFT:beklenmeyen scope-mapping: $live (beklenen yalnız $REALM_ROLE)"; return 0
  fi
  if [ "$MODE" = "--apply" ]; then
    local rid
    rid="$(K get "roles/$REALM_ROLE" -r "$REALM" --fields id 2>/dev/null | python3 -c '
import json, sys
print(json.load(sys.stdin).get("id", ""))')"
    [ -n "$rid" ] || { echo "ERROR: rol id alınamadı" >&2; return 1; }
    printf '[{"id":"%s","name":"%s"}]' "$rid" "$REALM_ROLE" \
      | KI create "clients/$cid/scope-mappings/realm" -r "$REALM" -f - >/dev/null 2>&1 \
      || { echo "ERROR: scope-mapping ekleme başarısız" >&2; return 1; }
    echo "ADDED"
  else
    echo "DRIFT:$REALM_ROLE scope-mapping yok"
  fi
}

# ---- Main ----
case "$MODE" in
  --check|--apply) ;;
  *) echo "kullanım: $0 [--check|--apply]   (env: REALM, CONFIRM_PROD_SMOKE_CONTRACT)" >&2; exit 1 ;;
esac

kc_login || exit 1
preflight || { echo ""; echo "PREFLIGHT FAIL → mutasyon yapılmadı"; exit 1; }

echo ""
echo "-- desired-state converge --"
R_RUNTIME="$(ensure_scope "$RUNTIME_SCOPE" "$(desired_runtime_json)")" || exit 1
echo "  $RUNTIME_SCOPE : $R_RUNTIME"
R_NOTIFY="$(ensure_scope "$NOTIFY_SCOPE" "$(desired_notify_json)")" || exit 1
echo "  $NOTIFY_SCOPE  : $R_NOTIFY"
R_ASSOC_D="$(ensure_association "$RUNTIME_SCOPE" default)" || exit 1
echo "  assoc default  : $R_ASSOC_D"
R_ASSOC_O="$(ensure_association "$NOTIFY_SCOPE" optional)" || exit 1
echo "  assoc optional : $R_ASSOC_O"
R_MAP="$(ensure_scope_mapping)" || exit 1
echo "  scope-mapping  : $R_MAP"

ALL="$R_RUNTIME|$R_NOTIFY|$R_ASSOC_D|$R_ASSOC_O|$R_MAP"

if [ "$MODE" = "--check" ]; then
  echo ""
  if printf '%s' "$ALL" | grep -q 'DRIFT'; then
    echo "SONUÇ: DRIFT var (exit 2)"; exit 2
  fi
  echo "SONUÇ: converged (exit 0)"; exit 0
fi

# --apply → exact read-back (Codex: postcondition)
echo ""
echo "-- exact read-back --"
rc=0
RB_RUNTIME="$(compare_scope "$(scope_id "$RUNTIME_SCOPE")" "$(desired_runtime_json)")"
RB_NOTIFY="$(compare_scope "$(scope_id "$NOTIFY_SCOPE")" "$(desired_notify_json)")"
echo "  $RUNTIME_SCOPE : $RB_RUNTIME"
echo "  $NOTIFY_SCOPE  : $RB_NOTIFY"
[ "$RB_RUNTIME" = "MATCH" ] || rc=3
[ "$RB_NOTIFY" = "MATCH" ] || rc=3
RB_D="$(MODE=--check ensure_association "$RUNTIME_SCOPE" default)"
RB_O="$(MODE=--check ensure_association "$NOTIFY_SCOPE" optional)"
RB_M="$(MODE=--check ensure_scope_mapping)"
echo "  assoc default  : $RB_D"
echo "  assoc optional : $RB_O"
echo "  scope-mapping  : $RB_M"
[ "$RB_D" = "MATCH" ] || rc=3
[ "$RB_O" = "MATCH" ] || rc=3
[ "$RB_M" = "MATCH" ] || rc=3

CID="$(client_uuid)"
CLIENT_MAPPERS="$(K get "clients/$CID/protocol-mappers/models" -r "$REALM" 2>/dev/null | python3 -c '
import json, sys
print(len(json.load(sys.stdin)))')"
echo "  client-level mapper sayısı: $CLIENT_MAPPERS (beklenen 0 — mapper'lar scope-owned)"
[ "$CLIENT_MAPPERS" = "0" ] || rc=3

echo ""
if [ "$rc" -eq 0 ]; then
  echo "SONUÇ: APPLY PASS — token contract converged"
else
  echo "SONUÇ: POSTCONDITION FAIL (exit $rc)"
fi
exit $rc
