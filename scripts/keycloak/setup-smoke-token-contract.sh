#!/usr/bin/env bash
# A2b.1 — smoke-client token contract (desired-state, idempotent, FAIL-CLOSED).
#
# board #2476 · Codex (OpenAI) thread 019f6b1d — v3.2 matris SEAL + post-impl REVISE (6 blocker) absorb.
# Runbook: docs/operations/RUNBOOKS/RB-kc-realm-security-hardening.md
#
# MİMARİ (Codex post-impl REVISE'ın kökü):  collect → audit → (SAFE/MISSING ise) mutate → collect → audit
#   * TEK canonical audit: `--check`, `--apply` öncesi safety barrier ve `--apply` sonrası postcondition
#     AYNI invariant setini kullanır. Ayrı kod yolları zamanla sapar → gerçekte bozuk kontrat için
#     "converged" denebilir.
#   * UNSAFE mevcut state'te HİÇBİR mutasyon yapılmaz. (Önceki sürüm driftli scope'u client'a
#     bağlayıp EN SONDA exit 3 veriyordu — "fail-closed" yalnız son exit code'da yaşıyordu.)
#   * Script hiçbir şeyi SİLMEZ / mutate ETMEZ; yalnız güvenli EKSİKLERİ yaratır.
#
# NE YAPAR (yalnız Keycloak; consumer manifest mutasyonu YOK):
#   smoke-runtime-v1 (DEFAULT association)
#     ├── userId  (attr=userId claim=userId jsonType=String)   ← frontend parity (canlıda String, long DEĞİL)
#     └── audience ×6: endpoint-admin-service, permission-service, variant-service,
#                      notification-orchestrator, auth-service (custom) + account (gerçek client)
#   smoke-notify-v1 (OPTIONAL association)
#     └── org_id  (attr=org_id claim=org_id jsonType=String)   ← capability switch
#   realm scope-mapping: ENDPOINT_ADMIN  (fullScopeAllowed=false kalır)
#
# NE YAPMAZ (Codex v3.2 gerekçeleriyle — değiştirmeden önce runbook'u oku):
#   - consumer `azp` allow-list'e smoke-client EKLEMEZ: endpoint-admin validator semantiği
#     `audience OR azp OR client_id` → allow-list'e eklemek audience binding'ini BYPASS eden
#     fallback açar ve "doğru audience ile geçti" kanıtını yok eder.
#   - notify-canary'ye DOKUNMAZ: shared scope (frontend'de DEFAULT, 0 mapper); backend onu okumuyor
#     (guard sırası: org_id → tenant_id → allowed_orgs → default). Sessizce sahiplenme YASAK.
#   - tenant_id / VARIANT_SCOPE_CANARY / generic ADMIN / client-level mapper: eklemez.
#
# NON-ATOMIC UYARI: scope create + association + scope-mapping tek transaction DEĞİL. Ara adım
# başarısız olursa kısmi state kalabilir. non-zero exit ASLA başarı değildir: token mint etmeden
# önce `--check` koş; kısmi state'i tahmin etme; UNSAFE yoksa `--apply` tekrar çalıştır (idempotent).
#
# Secret disiplini: admin password stdout/log'a yazılmaz; `set -x` / process-dump YASAK.
set -euo pipefail

MODE="${1:---check}"
REALM="${REALM:-platform-test}"
CLIENT_ID="smoke-client"
RUNTIME_SCOPE="smoke-runtime-v1"
NOTIFY_SCOPE="smoke-notify-v1"
REALM_ROLE="ENDPOINT_ADMIN"

case "$MODE" in
  --check|--apply) ;;
  *) echo "kullanım: $0 [--check|--apply]   (env: REALM, CONFIRM_PROD_SMOKE_CONTRACT)" >&2; exit 1 ;;
esac

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

WORK="$(mktemp -d "${TMPDIR:-/tmp}/.kc-a2b1.XXXXXX")"
cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT

# =====================================================================================
# Canonical audit — check / pre-mutation barrier / postcondition AYNI invariant setini kullanır.
# exit: 0=SAFE  2=MISSING(güvenli eksik)  3=UNSAFE(mutasyon yapılmaz)  1=girdi hatası
# =====================================================================================
cat > "$WORK/audit.py" <<'AUDIT_PY'
import json
import os
import sys

# Token yüzeyini etkileyen config alanları. Raw JSON equality YASAK — KC `id`/server-default ekler.
# `multivalued`/`aggregate.attrs` (Codex P1): jsonType.label=String tek başına SCALAR garantisi DEĞİL —
# multivalued=true, userId/org_id claim'ini string LİSTESİNE çevirir ve token kontratının
# `userId='987654'` / `org_id='default'` skaler varsayımını sessizce bozar.
CONFIG_KEYS = (
    "user.attribute", "claim.name", "jsonType.label",
    "access.token.claim", "id.token.claim", "userinfo.token.claim",
    "multivalued", "aggregate.attrs",
    "included.custom.audience", "included.client.audience",
)


def load(d, name, default=None):
    p = os.path.join(d, name)
    if not os.path.exists(p):
        return default
    with open(p) as f:
        raw = f.read().strip()
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return "__PARSE_ERROR__"


def norm_mappers(ms):
    """→ (dict, duplicate_names). Duplicate isim (Codex P1): dict son mapper'ı tutar; ilkini gizler.
    Gizlenen duplicate token üretiminde ÇALIŞMAYA devam eder ve aynı claim'i farklı biçimde yazabilir
    → çağıran duplicate'i UNSAFE saymalı. (Repo precedent: setup-m365-broker.sh aynı ismi FAIL sayar.)"""
    out, seen, dups = {}, set(), []
    for m in ms or []:
        n = m["name"]
        if n in seen:
            dups.append(n)
        seen.add(n)
        cfg = m.get("config") or {}
        out[n] = {
            "protocol": m.get("protocol"),
            "protocolMapper": m.get("protocolMapper"),
            "consentRequired": bool(m.get("consentRequired", False)),
            "config": {k: cfg.get(k) for k in CONFIG_KEYS if cfg.get(k) is not None},
        }
    return out, sorted(set(dups))


def compare_scope(desired, live):
    issues = []
    live_ms = live.get("protocolMappers") or []
    if live.get("protocol") != desired["protocol"]:
        issues.append("protocol=%r (beklenen %r)" % (live.get("protocol"), desired["protocol"]))
    for k, v in desired["attributes"].items():
        got = (live.get("attributes") or {}).get(k)
        if got != v:
            issues.append("attr %s=%r (beklenen %r)" % (k, got, v))
    d_m, _ = norm_mappers(desired["protocolMappers"])
    l_m, dups = norm_mappers(live_ms)
    if dups:
        issues.append("DUPLICATE mapper adı: %s (aynı isimde >1 mapper — biri diğerini gizler ama ikisi de "
                      "token üretiminde çalışır)" % ",".join(dups))
    if len(live_ms) != len(desired["protocolMappers"]):
        issues.append("mapper sayısı=%d (beklenen %d)" % (len(live_ms), len(desired["protocolMappers"])))
    missing = sorted(set(d_m) - set(l_m))
    extra = sorted(set(l_m) - set(d_m))
    if missing:
        issues.append("eksik mapper: %s" % ",".join(missing))
    if extra:
        issues.append("BEKLENMEYEN mapper: %s" % ",".join(extra))
    for n in sorted(set(d_m) & set(l_m)):
        if d_m[n] == l_m[n]:
            continue
        # Yalnız FARKLI alanları raporla (full-JSON dump okunamıyor + gerçek farkı gizliyor)
        parts = []
        for f in ("protocol", "protocolMapper", "consentRequired"):
            if d_m[n][f] != l_m[n][f]:
                parts.append("%s: live=%r beklenen=%r" % (f, l_m[n][f], d_m[n][f]))
        dc, lc = d_m[n]["config"], l_m[n]["config"]
        for k in sorted(set(dc) | set(lc)):
            if dc.get(k) != lc.get(k):
                parts.append("config[%s]: live=%r beklenen=%r" % (k, lc.get(k), dc.get(k)))
        issues.append("mapper %s → %s" % (n, "; ".join(parts)))
    return issues


def main():
    if len(sys.argv) != 5:
        print("kullanim: audit.py <snap-dir> <desired-runtime> <desired-notify> <realm-role>", file=sys.stderr)
        return 1
    d, f_runtime, f_notify, realm_role = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    with open(f_runtime) as f:
        des_runtime = json.load(f)
    with open(f_notify) as f:
        des_notify = json.load(f)
    RUNTIME, NOTIFY, CANARY = des_runtime["name"], des_notify["name"], "notify-canary"

    unsafe, missing, ok = [], [], []

    # 0) SNAPSHOT BÜTÜNLÜĞÜ (Codex P1) — okuma hatası "boş state" değildir.
    #    Bir GET başarısızsa collect `.unreadable` marker bırakır. Bilinmeyen state üzerinde
    #    mutasyon yapmak yerine burada fail-closed duruyoruz (postcondition'da fark etmek GEÇ olur).
    unreadable_path = os.path.join(d, ".unreadable")
    if os.path.exists(unreadable_path):
        with open(unreadable_path) as f:
            failed = [ln.strip() for ln in f if ln.strip()]
        print("  [UNSAFE] snapshot incomplete — şu kaynaklar OKUNAMADI: %s" % "; ".join(failed))
        print("           (okuma hatası 'kaynak boş' sayılmaz; bilinmeyen state üzerinde mutasyon YASAK)")
        print("VERDICT=UNSAFE:%d" % len(failed))
        return 3

    # 1) realm rolü — JSON/type exact (grep DEĞİL: eksik/null alan false-positive "OK" üretiyordu)
    role = load(d, "role.json")
    if role == "__PARSE_ERROR__" or not isinstance(role, dict):
        unsafe.append("realm rolü %s okunamadı/parse edilemedi" % realm_role)
    elif role.get("name") != realm_role:
        unsafe.append("realm rolü %s YOK (name=%r)" % (realm_role, role.get("name")))
    elif role.get("composite") is not False:
        unsafe.append("%s composite=%r — yalnız `is False` kabul (eksik/null/true/\"false\" FAIL); "
                      "composite ise child-role evreni incelenmeden apply YASAK"
                      % (realm_role, role.get("composite")))
    else:
        ok.append("%s var, composite=false (JSON-exact)" % realm_role)

    # 2) client identity + shape — EXACT (Codex P1: clients[0] YASAK)
    #    Tam bir eşleşme + clientId exact + non-empty string id şart. Aksi halde child GET'ler
    #    atlanır ve eksik snapshot "boş" sanılıp FALSE SAFE üretilirdi.
    clients = load(d, "clients.json", None)
    client = {}
    client_ok = False
    if clients == "__PARSE_ERROR__" or not isinstance(clients, list):
        unsafe.append("clients.json okunamadı/liste değil")
    else:
        hits = [x for x in clients if isinstance(x, dict) and x.get("clientId") == "smoke-client"]
        if len(hits) == 0:
            unsafe.append("smoke-client YOK (clients sorgusu eşleşme döndürmedi) — önce A2a")
        elif len(hits) > 1:
            unsafe.append("smoke-client için %d eşleşme (beklenen 1) — belirsiz identity" % len(hits))
        else:
            cid = hits[0].get("id")
            if not (isinstance(cid, str) and cid.strip()):
                unsafe.append("smoke-client nesnesinde non-empty string `id` YOK (id=%r) → client'a bağlı "
                              "mapper/scope-mapping kaynakları OKUNAMAZ; eksik child 'boş' sayılamaz" % cid)
            else:
                client, client_ok = hits[0], True
    if client_ok:
        if client.get("fullScopeAllowed") is not False:
            unsafe.append("fullScopeAllowed=%r (yalnız False kabul)" % client.get("fullScopeAllowed"))
        else:
            ok.append("fullScopeAllowed=false")
        if client.get("serviceAccountsEnabled") is not False:
            unsafe.append("serviceAccountsEnabled=%r (A2a shape bozulmuş)" % client.get("serviceAccountsEnabled"))
        else:
            ok.append("serviceAccounts=false (A2a shape korunuyor)")
        # Geçerli client var → child snapshot'lar ZORUNLU (yoksa "boş" değil, EKSİK)
        for child, label in (("client-mappers.json", "client protocol-mappers"),
                             ("client-scope-mappings.json", "client scope-mappings")):
            if not os.path.exists(os.path.join(d, child)):
                unsafe.append("geçerli smoke-client var ama %s snapshot'ı YOK (%s) — "
                              "okunmamış kaynak 'boş' sayılamaz" % (label, child))

    defaults = client.get("defaultClientScopes") or []
    optionals = client.get("optionalClientScopes") or []

    # 3) built-in `roles` default association — olmadan ENDPOINT_ADMIN token'a ÇIKMAZ
    if "roles" in defaults:
        ok.append("built-in `roles` default association'da (realm_access.roles üretimi mümkün)")
    else:
        unsafe.append("built-in `roles` default association'da DEĞİL → scope-mapping eklense bile "
                      "realm_access.roles çıkmaz; 'converged' iddiası yanlış olur")

    # 4) client-level mapper == 0 — check/barrier/postcondition AYNI invariant
    cmaps = load(d, "client-mappers.json", None)
    if cmaps is None:
        pass   # yukarıda "child snapshot YOK" olarak raporlandı (client_ok ise) — burada 0 SAYMA
    elif cmaps == "__PARSE_ERROR__" or not isinstance(cmaps, list):
        unsafe.append("client protocol-mappers okunamadı/liste değil")
    elif len(cmaps) != 0:
        unsafe.append("client-level mapper sayısı=%d (beklenen 0; mapper'lar scope-owned kalmalı). "
                      "Script bunları SİLMEZ — operatör incelemeli" % len(cmaps))
    else:
        ok.append("client-level mapper sayısı=0 (mapper'lar scope-owned)")

    # 5) association polarity EXACT — notify DEFAULT'a kaçarsa org_id capability switch olmaktan çıkar
    for name, want_default, want_optional in ((RUNTIME, True, False),
                                              (NOTIFY, False, True),
                                              (CANARY, False, False)):
        in_d, in_o = name in defaults, name in optionals
        if in_d == want_default and in_o == want_optional:
            if want_default or want_optional:
                ok.append("%s association exact (default=%s optional=%s)" % (name, in_d, in_o))
            else:
                ok.append("%s bağlı değil (shared scope'a dokunulmuyor)" % name)
            continue
        if in_d and not want_default:
            unsafe.append("%s DEFAULT association'da olmamalı (live d=%s o=%s / beklenen d=%s o=%s)"
                          % (name, in_d, in_o, want_default, want_optional))
        elif in_o and not want_optional:
            unsafe.append("%s OPTIONAL association'da olmamalı (live d=%s o=%s / beklenen d=%s o=%s)"
                          % (name, in_d, in_o, want_default, want_optional))
        elif want_default and not in_d:
            missing.append("assoc-default:%s" % name)
        elif want_optional and not in_o:
            missing.append("assoc-optional:%s" % name)

    # 6) role scope-mappings — client + iki owned scope (realm AND client tarafı)
    def check_mappings(fname, label, want_realm, required):
        sm = load(d, fname, None)
        if sm is None:
            if required:
                unsafe.append("%s mevcut ama scope-mappings snapshot'ı YOK (%s) — okunmamış kaynak "
                              "'rol taşımıyor' sayılamaz" % (label, fname))
            return
        if sm == "__PARSE_ERROR__" or not isinstance(sm, dict):
            unsafe.append("%s scope-mappings okunamadı/object değil" % label)
            return
        # Nested alan tipleri EXACT (Codex P1): `or []` / `or {}` normalizasyonu eksik/yanlış tipi gizler
        rm_raw, cm_raw = sm.get("realmMappings"), sm.get("clientMappings")
        if not isinstance(rm_raw, list):
            unsafe.append("%s realmMappings alanı eksik/yanlış tip (%r) — [] kabul edilmez" % (label, type(rm_raw).__name__))
            return
        if not isinstance(cm_raw, dict):
            unsafe.append("%s clientMappings alanı eksik/yanlış tip (%r) — {} kabul edilmez" % (label, type(cm_raw).__name__))
            return
        realm_names = sorted(x["name"] for x in rm_raw if isinstance(x, dict) and "name" in x)
        client_map = cm_raw
        if client_map:
            unsafe.append("%s CLIENT role scope-mapping taşıyor: %s (beklenen {})"
                          % (label, ",".join(sorted(client_map))))
        if realm_names == want_realm:
            if want_realm:
                ok.append("%s realm scope-mapping exact: %s" % (label, want_realm))
            else:
                ok.append("%s rol taşımıyor (realm=[] client={})" % label)
        elif not realm_names and want_realm:
            missing.append("scope-mapping:%s" % want_realm[0])
        else:
            unsafe.append("%s realm scope-mapping=%s (beklenen %s) — beklenmeyen rol token'a açılabilir"
                          % (label, realm_names, want_realm))

    check_mappings("client-scope-mappings.json", "smoke-client", [realm_role], required=client_ok)

    # 7) scope shape — protocol + protocolMapper + consentRequired + config whitelist
    scopes = load(d, "scopes.json", [])
    if scopes == "__PARSE_ERROR__":
        unsafe.append("client-scopes okunamadı")
        scopes = []
    for des, sm_file in ((des_runtime, "runtime-sm.json"), (des_notify, "notify-sm.json")):
        hits = [x for x in scopes if isinstance(x, dict) and x.get("name") == des["name"]]
        if len(hits) == 0:
            missing.append("scope:%s" % des["name"])
            continue
        if len(hits) > 1:
            unsafe.append("%s için %d scope (beklenen 1) — duplicate scope adı" % (des["name"], len(hits)))
            continue
        live = hits[0]
        sid = live.get("id")
        if not (isinstance(sid, str) and sid.strip()):
            unsafe.append("%s nesnesinde non-empty string `id` YOK (id=%r) → scope'un kendi "
                          "scope-mappings kaynağı OKUNAMAZ; eksik child 'rol taşımıyor' sayılamaz"
                          % (des["name"], sid))
            continue
        check_mappings(sm_file, des["name"], [], required=True)
        issues = compare_scope(des, live)
        if issues:
            unsafe.append("%s DRIFT → %s  [script mutate/sil ETMEZ; operatör incelemeli]"
                          % (des["name"], " | ".join(issues)))
        else:
            ok.append("%s shape exact (%d mapper)" % (des["name"], len(des["protocolMappers"])))

    for line in ok:
        print("  [OK]     %s" % line)
    for line in missing:
        print("  [MISS]   %s" % line)
    for line in unsafe:
        print("  [UNSAFE] %s" % line)

    if unsafe:
        print("VERDICT=UNSAFE:%d" % len(unsafe))
        return 3
    if missing:
        print("VERDICT=MISSING:%s" % ",".join(missing))
        return 2
    print("VERDICT=SAFE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
AUDIT_PY

kc_login() {
  local p
  p="$(docker exec "$KC_CONTAINER" sh -lc 'cat "$KEYCLOAK_ADMIN_PASSWORD_FILE"' | tr -d '\n')"
  [ -n "$p" ] || { echo "ERROR: admin password okunamadı" >&2; return 1; }
  K config credentials --server http://localhost:8080 --realm master --user admin --password "$p" >/dev/null 2>&1
  unset p
}

# ---- Desired state (tek kaynak) ----
DESIRED_AUDIENCES_CUSTOM="endpoint-admin-service permission-service variant-service notification-orchestrator auth-service"
DESIRED_AUDIENCE_CLIENT="account"

write_desired() {
  python3 - "$WORK/desired-runtime.json" "$RUNTIME_SCOPE" "$DESIRED_AUDIENCES_CUSTOM" "$DESIRED_AUDIENCE_CLIENT" <<'PY'
import json, sys
out, name, customs, client_aud = sys.argv[1], sys.argv[2], sys.argv[3].split(), sys.argv[4]
mappers = [{
    "name": "userId", "protocol": "openid-connect",
    "protocolMapper": "oidc-usermodel-attribute-mapper", "consentRequired": False,
    "config": {"user.attribute": "userId", "claim.name": "userId", "jsonType.label": "String",
               "access.token.claim": "true", "id.token.claim": "false", "userinfo.token.claim": "false",
               # scalar garanti: jsonType=String TEK BAŞINA yetmez — multivalued/aggregate claim'i
               # string listesine çevirir ve auth-service'in Long.parseLong beklentisini bozar.
               "multivalued": "false", "aggregate.attrs": "false"},
}]
for a in customs:
    mappers.append({"name": "aud-" + a, "protocol": "openid-connect",
                    "protocolMapper": "oidc-audience-mapper", "consentRequired": False,
                    "config": {"included.custom.audience": a,
                               "access.token.claim": "true", "id.token.claim": "false",
                               "userinfo.token.claim": "false"}})
mappers.append({"name": "aud-" + client_aud, "protocol": "openid-connect",
                "protocolMapper": "oidc-audience-mapper", "consentRequired": False,
                "config": {"included.client.audience": client_aud,
                           "access.token.claim": "true", "id.token.claim": "false",
                           "userinfo.token.claim": "false"}})
json.dump({"name": name,
           "description": "A2b.1 smoke-client runtime token contract (board #2476, Codex 019f6b1d v3.2)",
           "protocol": "openid-connect",
           "attributes": {"include.in.token.scope": "true", "display.on.consent.screen": "false"},
           "protocolMappers": mappers}, open(out, "w"))
PY
  python3 - "$WORK/desired-notify.json" "$NOTIFY_SCOPE" <<'PY'
import json, sys
out, name = sys.argv[1], sys.argv[2]
json.dump({"name": name,
           "description": "A2b.1 smoke-client optional org boundary claim (board #2476, Codex 019f6b1d v3.2)",
           "protocol": "openid-connect",
           "attributes": {"include.in.token.scope": "true", "display.on.consent.screen": "false"},
           "protocolMappers": [{
               "name": "org_id", "protocol": "openid-connect",
               "protocolMapper": "oidc-usermodel-attribute-mapper", "consentRequired": False,
               "config": {"user.attribute": "org_id", "claim.name": "org_id", "jsonType.label": "String",
                          "access.token.claim": "true", "id.token.claim": "false",
                          "userinfo.token.claim": "false",
                          # scalar garanti (bkz. userId): org guard tek org_id string bekler
                          "multivalued": "false", "aggregate.attrs": "false"}}]}, open(out, "w"))
PY
}

# EXACT lookup (Codex P1): generic "name VEYA clientId" seçimi YASAK — client ve scope ayrı
# identity alanları kullanır. Tam **bir** eşleşme + non-empty string `id` şart; aksi halde boş
# döner ve audit bunu UNSAFE sayar (eskiden exception `|| true` ile yutulup CID="" kalıyordu →
# child GET'ler atlanıyor → audit eksik dosyaları "boş" sanıp FALSE SAFE veriyordu).
pick_client_uuid() {  # $1=clients.json → id ("" = exact-tek-eşleşme yok)
  python3 -c '
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    print(""); raise SystemExit(0)
if not isinstance(d, list):
    print(""); raise SystemExit(0)
hits = [x for x in d if isinstance(x, dict) and x.get("clientId") == sys.argv[2]]
if len(hits) != 1:
    print(""); raise SystemExit(0)
i = hits[0].get("id")
print(i if isinstance(i, str) and i.strip() else "")' "$1" "$CLIENT_ID" 2>/dev/null || true
}

pick_scope_id() {  # $1=scopes.json  $2=scope adı → id ("" = exact-tek-eşleşme yok)
  python3 -c '
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    print(""); raise SystemExit(0)
if not isinstance(d, list):
    print(""); raise SystemExit(0)
hits = [x for x in d if isinstance(x, dict) and x.get("name") == sys.argv[2]]
if len(hits) != 1:
    print(""); raise SystemExit(0)
i = hits[0].get("id")
print(i if isinstance(i, str) and i.strip() else "")' "$1" "$2" 2>/dev/null || true
}

# ---- collect: TÜM state tek turda (fonksiyon başına tekrar kcadm çağrısı YOK → timeout'un da kökü) ----
#
# FAIL-CLOSED OKUMA (Codex P1): başarısız GET **asla** `[]`/`{}` gibi geçerli state'e çevrilmez.
# "Kaynak gerçekten boş" ile "kaynak okunamadı" AYRI state'tir. Aksi halde ör. `clients/<id>/scope-mappings`
# timeout ederse script `{}` yazar, beklenmeyen rol mapping'ini göremez ve BİLİNMEYEN canlı state üzerinde
# mutasyon yapar. Her dosya yalnız komut başarılı dönerse atomik olarak yerine konur; aksi halde
# `.unreadable` marker'ı bırakılır → audit `UNSAFE: snapshot incomplete`.
CID=""; RSID=""; NSID=""

# Sözleşme (Codex P1):
#   remote GET hatası VEYA beklenmeyen JSON shape + marker yazıldı → return 0 (collect devam eder,
#     audit "snapshot incomplete" ile UNSAFE verir)
#   LOKAL hata (mv edilemedi / marker yazılamadı)                  → return 1 (collect FATAL, exit 1)
# Not: exit 0 + non-empty YETMEZ — `{}` dönen bir protocol-mappers cevabı "0 mapper" gibi
# görünüp invariant'ı yanlışlıkla OK yapardı. Bu yüzden beklenen JSON tipi de doğrulanır.
kget_atomic() {  # $1=hedef dosya  $2=beklenen tip (list|object)  $3..=kcadm get argümanları
  local dest="$1" want="$2"; shift 2
  local tmp="$dest.part" dir; dir="$(dirname "$dest")"
  local ok=0
  if K get "$@" -r "$REALM" > "$tmp" 2>/dev/null && [ -s "$tmp" ]; then
    if python3 -c '
import json, sys
want = sys.argv[2]
try:
    with open(sys.argv[1]) as f:
        d = json.load(f)
except Exception:
    sys.exit(1)
sys.exit(0 if (isinstance(d, list) if want == "list" else isinstance(d, dict)) else 1)
' "$tmp" "$want" 2>/dev/null; then
      ok=1
    fi
  fi
  if [ "$ok" -eq 1 ]; then
    if ! mv -f "$tmp" "$dest"; then
      rm -f "$tmp"
      echo "ERROR: snapshot commit edilemedi (lokal I/O): $dest" >&2
      return 1
    fi
    return 0
  fi
  rm -f "$tmp"
  # Remote okunamadı / beklenmeyen shape → marker (audit UNSAFE sayar; "boş" DEĞİL)
  if ! printf '%s (beklenen JSON %s)\n' "$*" "$want" >> "$dir/.unreadable"; then
    echo "ERROR: snapshot unreadable marker yazılamadı (lokal I/O): $dir/.unreadable" >&2
    return 1
  fi
  return 0
}

collect() {  # return 1 = LOKAL I/O hatası (fatal) · return 0 = snapshot alındı (eksikse marker'lı)
  local d="$WORK/snap"
  rm -rf "$d" || return 1
  mkdir -p "$d" || return 1
  # roles/<role>: yoksa KC non-zero döner — bu GEÇERLİ "rol yok" bilgisi, okuma hatası DEĞİL.
  if ! K get "roles/$REALM_ROLE" -r "$REALM" > "$d/role.json.part" 2>"$d/role.err"; then
    if grep -qiE "not found|404" "$d/role.err" 2>/dev/null; then
      echo '{}' > "$d/role.json" || return 1   # gerçekten yok → audit "rol YOK" der (UNSAFE)
    else
      printf 'roles/%s (okuma hatası)\n' "$REALM_ROLE" >> "$d/.unreadable" || return 1
    fi
    rm -f "$d/role.json.part"
  else
    mv -f "$d/role.json.part" "$d/role.json" || {
      echo "ERROR: role snapshot commit edilemedi (lokal I/O)" >&2; return 1; }
  fi
  rm -f "$d/role.err"

  kget_atomic "$d/clients.json" list clients -q "clientId=$CLIENT_ID" || return 1
  CID="$(pick_client_uuid "$d/clients.json")"
  if [ -n "$CID" ]; then
    kget_atomic "$d/client-mappers.json" list "clients/$CID/protocol-mappers/models" || return 1
    kget_atomic "$d/client-scope-mappings.json" object "clients/$CID/scope-mappings" || return 1
  fi
  kget_atomic "$d/scopes.json" list client-scopes || return 1
  RSID="$(pick_scope_id "$d/scopes.json" "$RUNTIME_SCOPE")"
  NSID="$(pick_scope_id "$d/scopes.json" "$NOTIFY_SCOPE")"
  if [ -n "$RSID" ]; then
    kget_atomic "$d/runtime-sm.json" object "client-scopes/$RSID/scope-mappings" || return 1
  fi
  if [ -n "$NSID" ]; then
    kget_atomic "$d/notify-sm.json" object "client-scopes/$NSID/scope-mappings" || return 1
  fi
  return 0
}

collect_or_die() {
  collect || {
    echo "ERROR: snapshot collect tamamlanamadı (lokal I/O) — mutasyon YAPILMADI" >&2
    exit 1
  }
}

audit() {
  set +e
  python3 "$WORK/audit.py" "$WORK/snap" "$WORK/desired-runtime.json" "$WORK/desired-notify.json" "$REALM_ROLE"
  local rc=$?
  set -e
  return $rc
}

apply_missing() {  # $1 = "a,b,c"
  local items="$1" it n sid rid
  IFS=',' read -ra ITEMS <<< "$items"
  for it in "${ITEMS[@]}"; do
    case "$it" in
      "scope:$RUNTIME_SCOPE")
        KI create client-scopes -r "$REALM" -f - < "$WORK/desired-runtime.json" >/dev/null 2>&1 \
          || { echo "ERROR: $RUNTIME_SCOPE create başarısız" >&2; return 1; }
        echo "  + client-scope oluşturuldu: $RUNTIME_SCOPE" ;;
      "scope:$NOTIFY_SCOPE")
        KI create client-scopes -r "$REALM" -f - < "$WORK/desired-notify.json" >/dev/null 2>&1 \
          || { echo "ERROR: $NOTIFY_SCOPE create başarısız" >&2; return 1; }
        echo "  + client-scope oluşturuldu: $NOTIFY_SCOPE" ;;
      assoc-default:*)
        n="${it#assoc-default:}"
        sid="$(pick_scope_id "$WORK/snap/scopes.json" "$n")"
        [ -n "$sid" ] || { echo "ERROR: $n scope id bulunamadı (create bu turda mı yapıldı?)" >&2; return 1; }
        K update "clients/$CID/default-client-scopes/$sid" -r "$REALM" >/dev/null 2>&1 \
          || { echo "ERROR: $n default association başarısız" >&2; return 1; }
        echo "  + default association: $n" ;;
      assoc-optional:*)
        n="${it#assoc-optional:}"
        sid="$(pick_scope_id "$WORK/snap/scopes.json" "$n")"
        [ -n "$sid" ] || { echo "ERROR: $n scope id bulunamadı" >&2; return 1; }
        K update "clients/$CID/optional-client-scopes/$sid" -r "$REALM" >/dev/null 2>&1 \
          || { echo "ERROR: $n optional association başarısız" >&2; return 1; }
        echo "  + optional association: $n" ;;
      scope-mapping:*)
        n="${it#scope-mapping:}"
        rid="$(python3 -c 'import json,sys
print(json.load(open(sys.argv[1])).get("id",""))' "$WORK/snap/role.json")"
        [ -n "$rid" ] || { echo "ERROR: rol id alınamadı" >&2; return 1; }
        printf '[{"id":"%s","name":"%s"}]' "$rid" "$n" \
          | KI create "clients/$CID/scope-mappings/realm" -r "$REALM" -f - >/dev/null 2>&1 \
          || { echo "ERROR: scope-mapping ekleme başarısız" >&2; return 1; }
        echo "  + realm scope-mapping: $n" ;;
      *) echo "ERROR: bilinmeyen MISSING item: $it" >&2; return 1 ;;
    esac
  done
}

# ---- Main ----
kc_login || exit 1
write_desired
collect_or_die

echo ""
echo "-- audit (salt-okunur) --"
set +e
AUDIT_OUT="$(audit)"; AUDIT_RC=$?
set -e
printf '%s\n' "$AUDIT_OUT"
VERDICT="$(printf '%s' "$AUDIT_OUT" | sed -n 's/^VERDICT=//p' | tail -1)"

if [ "$MODE" = "--check" ]; then
  echo ""
  case "$AUDIT_RC" in
    0) echo "SONUÇ: converged (exit 0)"; exit 0 ;;
    2) echo "SONUÇ: güvenli eksik var — --apply yaratabilir (exit 2)"; exit 2 ;;
    3) echo "SONUÇ: UNSAFE — --apply hiçbir mutasyon yapmadan durur (exit 3)"; exit 3 ;;
    *) echo "SONUÇ: audit hatası (exit 1)"; exit 1 ;;
  esac
fi

# --apply
case "$AUDIT_RC" in
  0) echo ""; echo "SONUÇ: zaten converged — mutasyon yok (exit 0)"; exit 0 ;;
  3) echo ""
     echo "SAFETY BARRIER: UNSAFE state — HİÇBİR mutasyon yapılmadı (exit 3)."
     echo "Script drift'i silmez/düzeltmez (Codex: sessizce sahiplenme YASAK). Operatör incelemeli."
     exit 3 ;;
  2) : ;;
  *) echo "audit hatası (exit 1)"; exit 1 ;;
esac

echo ""
echo "-- apply stage 1: yalnız eksik scope'ları yarat --"
# İki aşama + ARADA YENİDEN AUDIT (Codex P1): ilk audit scope'u görmediği için shape'ini
# inceleyememiştir. Create sonrası KC kendi normalize/default'unu uygulayabilir (canlı kanıt:
# audience mapper'a `userinfo.token.claim=false` ekliyor). Bu yüzden create'ten sonra scope
# YENİDEN denetlenmeden client'a BAĞLANMAZ ve association listesi ilk (stale) audit'ten
# değil, TAZE audit çıktısından yeniden türetilir.
FIRST_PASS="${VERDICT#MISSING:}"
SCOPE_ITEMS="$(printf '%s' "$FIRST_PASS" | tr ',' '\n' | grep '^scope:' | paste -sd, - || true)"
if [ -n "$SCOPE_ITEMS" ]; then
  apply_missing "$SCOPE_ITEMS" || { echo "APPLY FAIL (scope create) — --check ile doğrula" >&2; exit 1; }
  echo ""
  echo "-- ikinci safety barrier: yeni scope'lar yeniden denetleniyor --"
  collect_or_die
  set +e
  MID_OUT="$(audit)"; MID_RC=$?
  set -e
  printf '%s\n' "$MID_OUT"
  case "$MID_RC" in
    0) echo ""; echo "SONUÇ: scope create sonrası converged — association gerekmedi (exit 0)"; exit 0 ;;
    3) echo ""
       echo "SAFETY BARRIER (stage 2): yeni oluşturulan scope UNSAFE denetimden geçemedi —"
       echo "association/scope-mapping YAPILMADI (exit 3). Scope KC tarafında oluşmuş olabilir;"
       echo "shape'i incele, gerekirse elle düzelt/sil, sonra --check ile doğrula."
       exit 3 ;;
    2) VERDICT="$(printf '%s' "$MID_OUT" | sed -n 's/^VERDICT=//p' | tail -1)" ;;
    *) echo "audit hatası (exit 1)"; exit 1 ;;
  esac
fi

REST_ITEMS="$(printf '%s' "${VERDICT#MISSING:}" | tr ',' '\n' | grep -v '^scope:' | paste -sd, - || true)"
if [ -n "$REST_ITEMS" ]; then
  echo ""
  echo "-- apply stage 2: association + scope-mapping (taze audit'ten türetildi) --"
  apply_missing "$REST_ITEMS" || { echo "APPLY FAIL (association/mapping) — --check ile doğrula" >&2; exit 1; }
fi

echo ""
echo "-- postcondition (aynı canonical audit) --"
collect_or_die
set +e
POST_OUT="$(audit)"; POST_RC=$?
set -e
printf '%s\n' "$POST_OUT"
echo ""
if [ "$POST_RC" -eq 0 ]; then
  echo "SONUÇ: APPLY PASS — token contract converged (exit 0)"
  exit 0
fi
echo "SONUÇ: POSTCONDITION FAIL (exit $POST_RC) — apply sonrası state desired değil"
exit 3
