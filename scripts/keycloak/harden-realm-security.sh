#!/usr/bin/env bash
#
# harden-realm-security.sh — Faz 22 Sec realm güvenlik desired-state (board #2476).
#
# Codex (OpenAI) plan-time thread 019f69f6 → REVISE ×3 absorb. Declarative,
# review-able, idempotent, recreate-deterministic realm hardening kaynağı.
# "kcadm patch + kc-export-cron backup" YETMEZ (Codex): review-able desired
# state + idempotent convergence + field-level drift + test→prod promotion
# + fail-closed rollback gerekir — hepsi bu script'te.
#
# ── Slices (desired-state modüler; sonraki PR'lar DESIRED_JSON'a ekler) ──
#   A1 — brute-force protection (failureFactor=5 + TÜM ilgili param converge,
#        bruteForceStrategy + maxTemporaryLockouts dahil — Codex REVISE-2)
#   A2 — ROPC migrasyon + frontend.directAccessGrants=false   [sonraki PR]
#   A2-obs — login event logging (eventsEnabled + 7g retention). A2c'nin
#        (frontend.directAccessGrants=false) önündeki engel bir "ekip karari"
#        degil, VERI YOKLUGU idi: events kapali oldugu icin `frontend` uzerinden
#        ROPC kullanan kalmis mi kimse bilmiyordu. Bu iki alan acildiginda karar
#        olculebilir hale gelir: N gun boyunca clientId=frontend +
#        grant_type=password event'i YOKSA A2c guvenle uygulanir; VARSA hangi
#        tuketicinin tasinmasi gerektigi de ayni kayittan cikar.
#        (Not: `frontend` public client + directAccessGrants=true, yani parola
#        grant'i client kimlik dogrulamasi olmadan calisiyor — A2c'nin kapatmak
#        istedigi risk tam olarak bu.)
#   A2-obs2 — yonetici islem kaydi (adminEventsEnabled). A2-obs GIRIS
#        event'lerini acti ama admin REST tarafi kapali kaldi. 2026-08-01: bir
#        hesabin OTP credential'i kayboldu ve KIMIN sildigi cevaplanamadi.
#        Ayrim onemli — kullanici-tarafi silme REMOVE_TOTP / REMOVE_CREDENTIAL
#        user-event'i uretir (olcum: credential'in tum omrunu kapsayan pencerede
#        ikisi de 0, yani kullanici silmedi), admin API silmesi ise YALNIZ admin
#        event uretir; o kapali oldugu icin hicbir iz kalmadi. Kimlik bilgisine
#        dokunan her admin cagrisi iz birakmali, aksi halde "kim sildi" sorusu
#        kanit yoklugundan cevapsiz kalir.
#        adminEventsDetailsEnabled bilerek false: detay modu istek GOVDESINI
#        saklar (parola sifirlama govdesi, client secret) — denetim izi ugruna
#        secret kalicilastirmayiz. Kim/ne zaman/hangi kaynak yolu sorusu icin
#        govde zaten gerekmiyor.
#   A3 — redirectUri + webOrigins narrowing. CANLIDA uygulanmış ama BU SCRIPT
#        yönetemez: alanlar `clients/*` üzerinde ve liste tipinde; engine tek
#        kaynak (`realms/$REALM`) + skaler varsayıyor, `--rollback` de realm
#        snapshot doğruluyor. Repo yüzeyi ayrıca makine-zorunlu:
#        tests/operations/test_keycloak_client_origin_invariant.py (PR #2982).
#   B  — conditional-OTP privileged. Akis `browser-privileged-mfa` VAR ve davranisi
#        2026-07-27 kanitlandi (rol yokken OTP yok / rol varken CONFIGURE_TOTP).
#        Realm'e BAGLANDI, sonra AYNI GUN GERI ALINDI ve `browserFlow` bu desired
#        state'ten CIKARILDI. Sebep: baglamanin "kimseyi etkilemedigi" olcumu YANLISTI.
#        `roles/requires-mfa/users` yalniz DOGRUDAN atamalari dondurur; rol asil olarak
#        COMPOSITE uzerinden dagitiliyor ve ters yon hic sorulmamisti:
#          requires-mfa'yi iceren roller: MEETING_ADMIN, ENDPOINT_ADMIN, TRANSCRIPT_ADMIN,
#          ethics-manager, remote-bridge-approver, remote-bridge-operator
#          efektif tasiyan: 34 TEKIL kullanici (admin hesabi + gercek kisiler dahil);
#          orneklenenlerin neredeyse hicbirinde OTP kayitli DEGIL -> sonraki tarayici
#          girisinde TOTP kurulumuna zorlanirlardi.
#        Yani bu bir "dormant" degisiklik DEGILDI. Yeniden baglamak once (a) kimlerin
#        etkilendigi listesinin owner'la netlesmesini, (b) OTP kayit penceresini,
#        (c) tercihen `requires-mfa`nin composite'lerden cikarilip hedefli atanmasini
#        gerektirir. Bagladiktan sonra `browserFlow`u desired state'e geri koymak sart
#        (aksi halde canli/desired drift kalir) — ama once (a)-(c).
# Bu sürüm: A1 + A2-obs + A2-obs2 + B(browserFlow bağlaması).
#
# ── Modes ──
#   --check                read-only drift raporu (MUTASYON YOK).
#                          exit 0 = converged, 2 = drift var.
#   --apply                pre-state snapshot → converge → postcondition assert.
#   --rollback <snap.json> FAIL-CLOSED: snapshot realm-guard + full-key + type
#                          + semantic-domain validate → pre-rollback snapshot →
#                          geri yaz → read-back snapshot değerleriyle assert.
#
# ── Realm → container ──
#   platform-test → platform-kc-test   (TEST — agent-otonom, HARD RULE ortam-kapsam)
#   serban        → platform-kc-prod   (PROD — CONFIRM_PROD_HARDEN=serban intent-gate;
#                                        gerçek owner onayı dış workflow/board'da)
#
# ── Usage ──
#   ssh halil@staging-sw 'REALM=platform-test bash -s -- --check' < <bu-script>
#   ssh halil@staging-sw 'REALM=platform-test bash -s -- --apply' < <bu-script>
#   ssh halil@staging-sw 'REALM=platform-test bash -s -- --rollback <snap>' < <bu-script>
#
# ── Exit codes ──
#   0  OK / converged      1  ERROR (input/login/guard/type/domain/realm-mismatch)
#   2  DRIFT (--check)      3  POSTCONDITION_FAILED (read-back assertion)
#
# HARD RULE: hiçbir secret stdout/log'a YAZILMAZ. Admin password kcadm config
# credentials sırasında kısa süre process argv'de taşınır (setup-m365 ile aynı);
# `set -x` / process-dump / komut-satırı gözlemi bu script'te YASAK. Idempotent.
# Operator login-credential'a DOKUNMAZ. Realm YARATMAZ (mevcut realm precondition;
# yoksa fail-closed). permanentLockout=false → kalıcı hesap kaybı yok.
#
set -euo pipefail
umask 077   # tüm dosya oluşturma 0600/0700 (snapshot secret-adjacent)

MODE="${1:---check}"
REALM="${REALM:-platform-test}"
SNAP_DIR="${SNAP_DIR:-$HOME/.kc-harden-snapshots}"

# ─── realm → container + prod intent-gate ──────────────────────────────────
case "$REALM" in
  platform-test) KC_CONTAINER="platform-kc-test"; ENV="test" ;;
  serban|platform-prod)
    KC_CONTAINER="platform-kc-prod"; ENV="prod"; REALM="serban"
    if [ "${CONFIRM_PROD_HARDEN:-}" != "serban" ]; then
      echo "ERROR: prod realm (serban) için CONFIRM_PROD_HARDEN=serban env gerekli" >&2
      echo "       (bu yalnız intent-guard; gerçek owner onayı dış workflow/board'da)" >&2
      exit 1
    fi ;;
  *) echo "ERROR: bilinmeyen realm '$REALM' (beklenen: platform-test, serban)" >&2; exit 1 ;;
esac

KC="docker exec ${KC_CONTAINER} /opt/keycloak/bin/kcadm.sh"

# ─── A1 brute-force desired state — TEK KAYNAK (valid JSON, type-anlamlı) ──
# Değerler canlı KC 26.5.5'ten doğrulandı (bruteForceStrategy=MULTIPLE default;
# maxTemporaryLockouts=0 permanentLockout=false ile tutarlı — Codex REVISE-2).
DESIRED_JSON='{
  "bruteForceProtected": true,
  "bruteForceStrategy": "MULTIPLE",
  "failureFactor": 5,
  "permanentLockout": false,
  "maxTemporaryLockouts": 0,
  "waitIncrementSeconds": 60,
  "maxFailureWaitSeconds": 900,
  "minimumQuickLoginWaitSeconds": 60,
  "quickLoginCheckMilliSeconds": 1000,
  "maxDeltaTimeSeconds": 43200,
  "eventsEnabled": true,
  "eventsExpiration": 604800,
  "adminEventsEnabled": true,
  "adminEventsDetailsEnabled": false
}'

# Beklenen -s arg sayısı (alan × 2). count-assert için (Codex REVISE-3).
NKEYS=$(DESIRED_JSON="$DESIRED_JSON" python3 -c 'import json,os; print(len(json.loads(os.environ["DESIRED_JSON"])))')
EXPECTED_ARGS=$(( NKEYS * 2 ))

# ─── type + semantic-domain engine (Codex REVISE-2/3: fail-closed, atomik) ──
# bool ↔ int ayrımı: Python'da bool int alt-sınıfı → type(v) is int.
# applyargs/rollbackargs: ÖNCE tümünü validate (biriktir), SONRA bas — kısmi
# çıktı yok. Bash tarafı ayrıca exit-status'u tmpfile ile ölçer (mapfile
# process-substitution status'u yutar — REVISE-3 P0).
PYENGINE='
import json, os, sys
DESIRED = json.loads(os.environ["DESIRED_JSON"])
BOOL_KEYS = {"bruteForceProtected", "permanentLockout", "eventsEnabled",
             "adminEventsEnabled", "adminEventsDetailsEnabled"}
STR_KEYS  = {"bruteForceStrategy"}
INT_KEYS  = set(DESIRED) - BOOL_KEYS - STR_KEYS
# KC 26.5.5 BruteForceStrategy enum (canli dogrulandi: MULTIPLE; LINEAR digeri).
BF_STRATEGY_ENUM = {"MULTIPLE", "LINEAR"}
# failureFactor > 0 zorunlu; diger sure/sayac alanlari >= 0.
POSITIVE_KEYS = {"failureFactor"}

def canon(k, v):
    """desired/snapshot degerini kcadm -s icin canonical str; type+domain fail-closed."""
    if k in BOOL_KEYS:
        if not isinstance(v, bool):
            raise SystemExit(f"TYPE_ERR: {k} bool bekleniyordu, {type(v).__name__} geldi")
        return "true" if v else "false"
    if k in STR_KEYS:
        if not isinstance(v, str) or not v:
            raise SystemExit(f"TYPE_ERR: {k} non-empty str bekleniyordu")
        if k == "bruteForceStrategy" and v not in BF_STRATEGY_ENUM:
            raise SystemExit(f"DOMAIN_ERR: bruteForceStrategy {v!r} KC enum degil {sorted(BF_STRATEGY_ENUM)}")
        return v
    # INT — bool int alt-sinifi oldugu icin once bool ele
    if isinstance(v, bool) or type(v) is not int:
        raise SystemExit(f"TYPE_ERR: {k} int bekleniyordu, {type(v).__name__} geldi")
    if k in POSITIVE_KEYS and v <= 0:
        raise SystemExit(f"DOMAIN_ERR: {k} > 0 olmali, {v} geldi")
    if v < 0:
        raise SystemExit(f"DOMAIN_ERR: {k} negatif olamaz, {v} geldi")
    return str(v)

def build_args(source):
    """TUM alanlari validate edip -s/key=val listesi dondurur (atomik: hata=bos donmez, exception atar)."""
    out = []
    for k in DESIRED:
        if k not in source:
            raise SystemExit(f"MISSING: yonetilen alan {k} kaynakta yok (fail-closed)")
        out.append("-s")
        out.append(f"{k}={canon(k, source[k])}")
    return out

cmd = sys.argv[1]

if cmd == "diff":
    cur = json.load(open(sys.argv[2]))
    drift = 0
    for k in DESIRED:
        c = cur.get(k); d = DESIRED[k]
        m = (c == d)
        print(f"  {k}: current={json.dumps(c)} desired={json.dumps(d)} " + ("MATCH" if m else "DRIFT"))
        if not m:
            drift += 1
    print(f"DRIFT_COUNT={drift}")

elif cmd == "applyargs":
    # ONCE hepsini validate (build), SONRA bas — kismi cikti yok.
    args = build_args(DESIRED)
    sys.stdout.write("\n".join(args) + "\n")

elif cmd == "rollbackargs":
    snap = json.load(open(sys.argv[2]))
    exp = os.environ["EXPECTED_REALM"]
    got = snap.get("realm")
    if got != exp:
        raise SystemExit(f"REALM_GUARD: snapshot .realm={got!r} != beklenen {exp!r}")
    args = build_args(snap)          # full-key + type + domain, hepsi ONCE
    sys.stdout.write("\n".join(args) + "\n")

elif cmd == "diffsnap":
    # rollback read-back: current managed alanlar snapshot ile eslesmeli.
    snap = json.load(open(sys.argv[2])); cur = json.load(open(sys.argv[3]))
    drift = 0
    for k in DESIRED:
        s = snap.get(k); c = cur.get(k)
        m = (s == c)
        print(f"  {k}: current={json.dumps(c)} snapshot={json.dumps(s)} " + ("MATCH" if m else "DRIFT"))
        if not m:
            drift += 1
    print(f"DRIFT_COUNT={drift}")

else:
    raise SystemExit(f"unknown engine cmd {cmd}")
'

# ─── validated args üretimi (fail-closed: tmpfile + exit-status + count) ────
# mapfile process-substitution Python status'unu YUTAR (Codex REVISE-3 P0) →
# çıktıyı tmpfile'a al, python exit-status'unu AYRI ölç, sonra count-assert.
GEN_ARG_FILE=""
gen_args() {
  # $1 = engine cmd (applyargs|rollbackargs), $2 = (rollback için) snapshot path.
  # başarıda GEN_ARGS[] doldurur; hata/eksik → exit 1 (mutasyon yok).
  local cmd="$1" snap="${2:-}"
  GEN_ARG_FILE="$(mktemp)"
  if [ "$cmd" = "rollbackargs" ]; then
    if ! EXPECTED_REALM="$REALM" DESIRED_JSON="$DESIRED_JSON" \
         python3 -c "$PYENGINE" rollbackargs "$snap" > "$GEN_ARG_FILE" 2>&1; then
      echo "ERROR: snapshot validation FAILED (realm-guard/full-key/type/domain) — mutasyon yok:" >&2
      cat "$GEN_ARG_FILE" >&2; rm -f "$GEN_ARG_FILE"; exit 1
    fi
  else
    if ! DESIRED_JSON="$DESIRED_JSON" \
         python3 -c "$PYENGINE" applyargs > "$GEN_ARG_FILE" 2>&1; then
      echo "ERROR: applyargs validation FAILED (type/domain) — mutasyon yok:" >&2
      cat "$GEN_ARG_FILE" >&2; rm -f "$GEN_ARG_FILE"; exit 1
    fi
  fi
  mapfile -t GEN_ARGS < "$GEN_ARG_FILE"
  rm -f "$GEN_ARG_FILE"
  [ "${#GEN_ARGS[@]}" -eq "$EXPECTED_ARGS" ] \
    || { echo "ERROR: beklenen $EXPECTED_ARGS arg alınamadı (${#GEN_ARGS[@]}) — mutasyon yok" >&2; exit 1; }
}

# ─── login (master realm; password container-secret'tan, cwd-agnostik) ─────
login() {
  local pass
  pass=$(docker exec "$KC_CONTAINER" sh -lc 'cat "$KEYCLOAK_ADMIN_PASSWORD_FILE"' 2>/dev/null | tr -d '\n')
  [ -n "$pass" ] || { echo "ERROR: KC admin password boş çözüldü" >&2; exit 1; }
  $KC config credentials --server http://localhost:8080 --realm master \
    --user admin --password "$pass" >/dev/null 2>&1 \
    || { echo "ERROR: master realm login başarısız" >&2; exit 1; }
  unset pass
}

# ─── fail-closed realm guard (realm var + doğru) ───────────────────────────
guard_realm() {
  local got
  got=$($KC get "realms/$REALM" --fields realm 2>/dev/null \
    | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("realm",""))
except Exception: print("")' 2>/dev/null || echo "")
  [ "$got" = "$REALM" ] \
    || { echo "ERROR: realm guard fail (beklenen '$REALM', bulunan '$got') — script realm YARATMAZ" >&2; exit 1; }
}

# ─── fail-closed akış guard'ı (browserFlow desired'ı var olmayan bir akışı
# işaret ederse converge TÜM girişleri kırar — mutasyon öncesi doğrula) ──────
guard_browser_flow() {
  local want got
  want=$(DESIRED_JSON="$DESIRED_JSON" python3 -c \
    'import json,os; print(json.loads(os.environ["DESIRED_JSON"]).get("browserFlow",""))')
  [ -n "$want" ] || return 0   # browserFlow yönetilmiyorsa kontrol gereksiz
  got=$($KC get authentication/flows -r "$REALM" 2>/dev/null \
    | python3 -c 'import json,sys
try: print("\n".join(f.get("alias","") for f in json.load(sys.stdin)))
except Exception: pass' 2>/dev/null | grep -Fx "$want" || true)
  [ "$got" = "$want" ] \
    || { echo "ERROR: browserFlow guard fail — '$want' akışı realm '$REALM'de YOK." >&2
         echo "       Bu akış olmadan converge her girişi kırar. Script akış YARATMAZ;" >&2
         echo "       önce akışı kur (RB-kc-realm-security-hardening.md B bölümü)." >&2
         exit 1; }
}

# ─── güvenli snapshot (umask 077 + install -m700 + mktemp unique + fail-clean) ─
take_snapshot() {
  local label="${1:-snap}" ts snap
  install -d -m 700 "$SNAP_DIR" || return 1
  ts="$(date +%Y%m%dT%H%M%S)"
  snap="$(mktemp "$SNAP_DIR/realm-${REALM}-${ts}-${label}.XXXXXX.json")" || return 1
  if ! $KC get "realms/$REALM" > "$snap" 2>/dev/null || [ ! -s "$snap" ]; then
    rm -f "$snap"; return 1
  fi
  echo "$snap"
}

# ─── drift raporu helper (stdin: realm-json-file) ──────────────────────────
report_diff() {  # $1 = current json file; global DRIFT_COUNT set
  local rep
  rep=$(DESIRED_JSON="$DESIRED_JSON" python3 -c "$PYENGINE" diff "$1") \
    || { echo "ERROR: diff engine hata" >&2; exit 1; }
  echo "$rep" | grep -v '^DRIFT_COUNT='
  DRIFT_COUNT="$(echo "$rep" | sed -n 's/^DRIFT_COUNT=//p')"
}

# ═══════════════════════════════════════════════════════════════════════════
case "$MODE" in
  --check)
    echo "=== harden-realm-security --check (realm=$REALM, container=$KC_CONTAINER) ==="
    login; guard_realm; guard_browser_flow
    CUR_TMP="$(mktemp)"; trap 'rm -f "$CUR_TMP"' EXIT
    $KC get "realms/$REALM" > "$CUR_TMP" 2>/dev/null || { echo "ERROR: realm get" >&2; exit 1; }
    report_diff "$CUR_TMP"
    echo ""
    if [ "${DRIFT_COUNT:-1}" = "0" ]; then
      echo "=== CONVERGED (drift yok) ==="; exit 0
    else
      echo "=== DRIFT: $DRIFT_COUNT alan desired'a uymuyor (--apply ile converge) ==="; exit 2
    fi
    ;;

  --apply)
    echo "=== harden-realm-security --apply (realm=$REALM, container=$KC_CONTAINER) ==="
    # 1) args'ı ÖNCE üret+validate (fail-closed) — login/mutasyon öncesi
    gen_args applyargs
    login; guard_realm; guard_browser_flow

    # 2) pre-state snapshot (FULL realm rep — rollback kaynağı; güvenli oluşturma)
    SNAP="$(take_snapshot apply)" || { echo "ERROR: snapshot alınamadı" >&2; exit 1; }
    echo "✓ snapshot: $SNAP ($(wc -c < "$SNAP") bytes, mode $(stat -c '%a' "$SNAP" 2>/dev/null || echo '?'))"

    # 3) pre-apply drift (bilgi)
    PRE_TMP="$(mktemp)"; trap 'rm -f "$PRE_TMP" "${POST_TMP:-}"' EXIT
    $KC get "realms/$REALM" > "$PRE_TMP" 2>/dev/null
    echo "--- pre-apply state ---"; report_diff "$PRE_TMP"

    # 4) converge — validated canonical -s args
    $KC update "realms/$REALM" "${GEN_ARGS[@]}" >/dev/null 2>&1 \
      || { echo "ERROR: realm update başarısız (snapshot korundu: $SNAP)" >&2; exit 1; }
    echo "✓ converge uygulandı (${#GEN_ARGS[@]} arg)"

    # 5) postcondition — read-back drift=0 assert
    echo "--- postcondition (read-back) ---"
    POST_TMP="$(mktemp)"
    $KC get "realms/$REALM" > "$POST_TMP" 2>/dev/null
    report_diff "$POST_TMP"
    echo ""
    if [ "${DRIFT_COUNT:-1}" = "0" ]; then
      echo "=== APPLY PASS — desired-state converged (snapshot: $SNAP) ==="
      echo "Rollback: REALM=$REALM bash <script> --rollback $SNAP   (aynı host)"
      exit 0
    else
      echo "ERROR: POSTCONDITION FAILED — $DRIFT_COUNT alan hâlâ drift (snapshot: $SNAP)" >&2
      exit 3
    fi
    ;;

  --rollback)
    SNAP_FILE="${2:-}"
    [ -n "$SNAP_FILE" ] || { echo "ERROR: --rollback <snapshot.json> gerekli" >&2; exit 1; }
    [ -f "$SNAP_FILE" ] || { echo "ERROR: snapshot bulunamadı: $SNAP_FILE" >&2; exit 1; }
    echo "=== harden-realm-security --rollback (realm=$REALM, snap=$SNAP_FILE) ==="

    # 1) snapshot'ı TEK SEFERDE validate + canonical args üret (login öncesi
    #    fail-closed: realm-guard + full-key + type + semantic-domain). Python
    #    exit-status tmpfile ile AYRI ölçülür (mapfile status'u yutmaz) →
    #    hata=hiçbir mutasyon yok (Codex REVISE-3 P0).
    gen_args rollbackargs "$SNAP_FILE"
    RB_ARGS=("${GEN_ARGS[@]}")

    login; guard_realm

    # 2) rollback ÖNCESİ mevcut hardened state'i de snapshot'la (çift-yön)
    PRE_RB="$(take_snapshot prerollback)" || { echo "ERROR: pre-rollback snapshot alınamadı" >&2; exit 1; }
    echo "✓ pre-rollback snapshot: $PRE_RB"

    # 3) snapshot değerlerini geri yaz
    $KC update "realms/$REALM" "${RB_ARGS[@]}" >/dev/null 2>&1 \
      || { echo "ERROR: rollback update başarısız (pre-rollback snapshot: $PRE_RB)" >&2; exit 1; }
    echo "✓ rollback uygulandı (${#RB_ARGS[@]} arg)"

    # 4) read-back — current managed alanlar snapshot ile eşleşmeli
    echo "--- rollback postcondition (read-back vs snapshot) ---"
    RB_POST="$(mktemp)"; trap 'rm -f "$RB_POST"' EXIT
    $KC get "realms/$REALM" > "$RB_POST" 2>/dev/null
    RB_REP=$(DESIRED_JSON="$DESIRED_JSON" python3 -c "$PYENGINE" diffsnap "$SNAP_FILE" "$RB_POST")
    echo "$RB_REP" | grep -v '^DRIFT_COUNT='
    RB_DC="$(echo "$RB_REP" | sed -n 's/^DRIFT_COUNT=//p')"
    echo ""
    if [ "${RB_DC:-1}" = "0" ]; then
      echo "=== ROLLBACK PASS — realm managed alanlar snapshot'a döndü ==="
      exit 0
    else
      echo "ERROR: ROLLBACK POSTCONDITION FAILED — $RB_DC alan snapshot'a dönmedi" >&2
      exit 3
    fi
    ;;

  *)
    echo "ERROR: bilinmeyen mode '$MODE' (--check | --apply | --rollback <snap>)" >&2
    exit 1
    ;;
esac
