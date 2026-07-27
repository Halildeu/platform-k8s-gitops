#!/usr/bin/env bash
# 39d-4 D29 kanıt matrisi (Codex 019f4c6c/019f50b7 adlandırmasıyla).
# aiserver'da koşar; persona şifreleri Vault'tan (stdout'a düşmez);
# token'lar yalnız bu süreçte — basılan tek şey claim ÖZETİ (redacted).
# shellcheck disable=SC2015 # ok()/bad() daima 0; bu dosyada koşullu sayaç deseni.
set -uo pipefail
EDGE="https://testai.acik.com"
VAULT_INIT_FILE="${VAULT_INIT_FILE:-/srv/platform/secrets/backup-auth/vault-init-test.json}"
KCTOK="$EDGE/realms/platform-test/protocol/openid-connect/token"
API="$EDGE/api/ats/v1/interviews/iv-smoke-1"
T=$(mktemp -d); chmod 700 "$T"; umask 077
trap 'rm -rf "$T"; unset ROOT SMOKE READER REVIEWER OPERATOR ROLELESS RT' EXIT
# Beklenen imaj digest'i — default aktivasyon kustomization pin'i ile senkron
# tutulur (pin bump PR'ı bu default'u da günceller); ad-hoc koşum için env
# override: ATS_EXPECTED_DIGEST=sha256:... ./d29-smoke.sh
PIN="${ATS_EXPECTED_DIGEST:-sha256:c3c4afdf84f36fd7bd29fc2b64fec03a0fced0151344d4b4f2b9446fc0cb839b}"
PASS=0; FAIL=0
ok(){ echo "PASS: $1"; PASS=$((PASS+1)); }
bad(){ echo "FAIL: $1"; FAIL=$((FAIL+1)); }

ROOT=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["root_token"])' "${VAULT_INIT_FILE}")
SMOKE=$(VAULT_TOKEN="$ROOT" docker exec -e VAULT_TOKEN \
  -e VAULT_ADDR=http://127.0.0.1:8200 platform-vault-test \
  vault kv get -format=json kv/platform/ats-smoke)
unset ROOT
pw(){ printf '%s' "$SMOKE" | python3 -c "import json,sys;print(json.load(sys.stdin)['data']['data']['$1'])"; }

tok(){ # $1=client $2=user $3=pwkey -> access_token (bos = fail)
  local p
  p=$(pw "$3")
  {
    printf '%s\n' 'data-urlencode = "grant_type=password"'
    printf 'data-urlencode = "client_id=%s"\n' "$1"
    printf 'data-urlencode = "username=%s"\n' "$2"
    printf 'data-urlencode = "password=%s"\n' "$p"
  } | curl -sS --max-time 15 --config - "$KCTOK" \
    | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("access_token",""))
except Exception: print("")'
  unset p
}
claims(){ # $1=token — redacted özet (aud/tenant/ats-scope-sayısı/rol-listesi)
  printf '%s' "$1" | cut -d. -f2 | python3 -c '
import base64,json,sys
p=sys.stdin.read().strip(); p+="="*(-len(p)%4)
c=json.loads(base64.urlsafe_b64decode(p))
ra=sorted(c.get("resource_access",{}).get("ats-api",{}).get("roles",[]))
sc=len([s for s in c.get("scope","").split() if s.startswith("ats.")])
print("  aud=",c.get("aud")," tenant=",c.get("tenant")," ats-scopes=",sc," roles=",ra)'
}
code(){ # $1=method $2=url $3=token(optional) $4=body(optional json)
  local cfg="$T/request.curl"
  : >"$cfg"
  [ -n "${3:-}" ] && printf 'header = "Authorization: Bearer %s"\n' "$3" >"$cfg"
  if [ -n "${4:-}" ]; then
    curl -sS --max-time 20 --config "$cfg" -o "$T/last.json" -w '%{http_code}' -X "$1" -H 'Content-Type: application/json' -d "$4" "$2"
  else
    curl -sS --max-time 20 --config "$cfg" -o "$T/last.json" -w '%{http_code}' -X "$1" "$2"
  fi
}

# sentetik WAV (RIFF header + 0.1sn sessizlik — tamamen sentetik; PII yok)
WAV="$T/sentetik.wav" python3 - <<'WAVEOF'
import os, struct, wave
w = wave.open(os.environ['WAV'], 'w')
w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000)
w.writeframes(b'\x00\x00' * 800)
w.close()
WAVEOF

echo "== D29: Up + Immutable =="
POD=$(kubectl --context k3d-test -n platform-test get pod -l app=ats-interview-evidence -o jsonpath='{.items[0].status.phase}/{.items[0].status.containerStatuses[0].ready}')
IMG=$(kubectl --context k3d-test -n platform-test get pod -l app=ats-interview-evidence -o jsonpath='{.items[0].status.containerStatuses[0].imageID}')
[ "$POD" = "Running/true" ] && ok "pod Running/ready" || bad "pod=$POD"
case "$IMG" in *"$PIN"*) ok "imageID == pinned digest (D30)";; *) bad "imageID=$IMG beklenen=$PIN";; esac
PROVIDER=$(kubectl --context k3d-test -n platform-test get configmap ats-interview-evidence-config -o jsonpath='{.data.ATS_AI_PROVIDER}')
[ "$PROVIDER" = "live-stt" ] && ok "provider config == live-stt (fail-closed)" || bad "provider=$PROVIDER"

echo "== D29: Edge + Authn deny =="
C=$(code GET "$API/transcripts"); [ "$C" = "401" ] && ok "no-token GET transcripts -> 401" || bad "no-token -> $C"
C=$(code GET "$EDGE/api/ats/healthz"); [ "$C" != "200" ] && ok "healthz DISARI kapali ($C)" || bad "healthz disari acik!"
RT=$(tok admin-cli ats-reader-persona READER_PW)
if [ -n "$RT" ]; then C=$(code GET "$API/transcripts" "$RT"); [ "$C" = "401" ] && ok "audience'siz (admin-cli) token -> 401" || bad "audience'siz -> $C"; else echo "SKIP: admin-cli token alinamadi"; fi

echo "== Persona tokenlari (frontend client) =="
READER=$(tok frontend ats-reader-persona READER_PW)
REVIEWER=$(tok frontend ats-reviewer-persona REVIEWER_PW)
OPERATOR=$(tok frontend ats-operator-persona OPERATOR_PW)
ROLELESS=$(tok frontend ats-roleless-persona ROLELESS_PW)
for n in READER REVIEWER OPERATOR ROLELESS; do
  v=$(eval "printf '%s' \"\$$n\"")
  [ -n "$v" ] && { echo "$n token OK:"; claims "$v"; } || bad "$n token alinamadi"
done
printf 'header = "Authorization: Bearer %s"\n' "$REVIEWER" >"$T/reviewer.curl"

echo "== D29: Authz allow/deny matrisi =="
C=$(code GET "$API/transcripts" "$READER"); [ "$C" = "200" ] && ok "reader GET transcripts -> 200" || bad "reader read -> $C"
C=$(code PUT "$API/recording-consent" "$READER" '{"subjectRef":"sub-smoke-1","state":"GRANTED"}'); [ "$C" = "403" ] && ok "reader consent-write -> 403" || bad "reader write -> $C"
C=$(code GET "$API/transcripts" "$ROLELESS"); [ "$C" = "403" ] && ok "ROLSUZ (scope'lu) -> 403 [ROL-KAPISI CANLI]" || bad "roleless -> $C"

echo "== D29: Functional — live-STT fail-closed (reviewer zinciri) =="
C=$(code PUT "$API/recording-consent" "$REVIEWER" '{"subjectRef":"sub-smoke-1","state":"GRANTED"}')
[ "${C:0:1}" = "2" ] && ok "consent GRANTED -> $C" || { bad "consent -> $C"; head -c 200 "$T/last.json" 2>/dev/null; echo; }
UP=$(curl -sS --max-time 30 --config "$T/reviewer.curl" -o "$T/up.json" -w '%{http_code}' -X POST "$API/recordings" \
  -H "Content-Type: audio/wav" -H "X-ATS-Filename: d29-sentetik.wav" --data-binary @"$T/sentetik.wav")
[ "${UP:0:1}" = "2" ] && ok "upload sentetik wav -> $UP" || { bad "upload -> $UP"; head -c 300 "$T/up.json"; echo; }
EV=$(python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));print(d.get("objectKey") or d.get("evidenceId") or "")' "$T/up.json" 2>/dev/null)
echo "  upload cevap ozet: $(head -c 200 "$T/up.json" 2>/dev/null)"
if [ -n "$EV" ]; then
  TR=$(curl -sS --max-time 60 --config "$T/reviewer.curl" -o "$T/tr.json" -w '%{http_code}' -X POST "$API/transcribe" \
    -H 'Content-Type: application/json' \
    -d "{\"sourceObjectKey\":\"$EV\"}")
  [ "${TR:0:1}" = "2" ] && ok "transcribe (live-STT) -> $TR" || { bad "transcribe -> $TR"; head -c 300 "$T/tr.json"; echo; }
  echo "  transcribe cevap ozet: $(head -c 240 "$T/tr.json" 2>/dev/null)"
fi
TK=$(python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));print(d.get("transcriptKey") or d.get("key") or "")' "$T/tr.json" 2>/dev/null)
if [ -n "$TK" ]; then
  C=$(code GET "$API/transcript?key=$TK" "$REVIEWER"); [ "$C" = "200" ] && ok "read-back transcript?key -> 200" || bad "read-back -> $C"
else
  bad "transcriptKey cevaptan cikarilamadi"
fi
if [ "$C" = "200" ] && [ -s "$T/last.json" ] && ! grep -q "test-stub" "$T/last.json"; then
  ok "live-stt read-back dolu; test-stub izi yok"
else
  bad "live-stt read-back/provenance dogrulamasi"
fi

# Faz 25 #2441: backend screening imaji + KC scope'lari birlikte pinlendikten sonra
# explicit acilir. Default 0 mevcut smoke'u eski pin uzerinde bozmaz;
# acceptance kosumu ATS_SCREENING_EXPECTED=1 ile fail-closed ek 8 kontrol yapar.
if [ "${ATS_SCREENING_EXPECTED:-0}" = "1" ]; then
  echo "== Faz 25: Screening pointer/replay + split authority =="
  if [ -z "$TK" ]; then
    bad "screening icin transcriptKey yok"
  else
    SCREEN_KEY="scrq_$(python3 -c 'import uuid; print(uuid.uuid4())')"
    SCREEN_BODY="{\"sourceKind\":\"TRANSCRIPT_SEGMENT\",\"transcriptKey\":\"$TK\",\"segmentIndex\":0}"
    SCREEN_CODE=$(curl -sS --max-time 30 -D "$T/d29-screen-create.headers" \
      -o "$T/d29-screen-create.json" -w '%{http_code}' -X POST "$API/screenings" \
      -H "Authorization: Bearer $REVIEWER" -H 'Content-Type: application/json' \
      -H "X-ATS-Idempotency-Key: $SCREEN_KEY" -d "$SCREEN_BODY")
    [ "$SCREEN_CODE" = "201" ] && ok "reviewer screening create -> 201" || bad "reviewer screening create -> $SCREEN_CODE"
    if grep -qi '^cache-control: no-store' "$T/d29-screen-create.headers" \
      && grep -qi '^x-ats-replay: false' "$T/d29-screen-create.headers"; then
      ok "screening create no-store + X-ATS-Replay:false"
    else
      bad "screening create cache/replay header kontrati"
    fi
    if python3 - "$T/d29-screen-create.json" <<'PY'
import json
import sys

TOP_KEYS = {
    "findingSetRef", "runId", "policyRef", "coverage", "disposition",
    "source", "findings", "evidenceId", "schemaVersion", "occurredAt",
    "spanUnit",
}
SOURCE_KEYS = {"kind", "canonicalSourceRef", "segmentIndex"}
FINDING_KEYS = {"category", "signal", "sourceKind", "span"}
SPAN_KEYS = {"startInclusive", "endExclusive", "segmentIndex"}

with open(sys.argv[1], encoding="utf-8") as handle:
    payload = json.load(handle)
assert isinstance(payload, dict) and set(payload) == TOP_KEYS
assert isinstance(payload["source"], dict) and set(payload["source"]) == SOURCE_KEYS
assert isinstance(payload["findings"], list)
for finding in payload["findings"]:
    assert isinstance(finding, dict) and set(finding) == FINDING_KEYS
    assert isinstance(finding["span"], dict) and set(finding["span"]) == SPAN_KEYS
PY
    then
      ok "screening response pointer-only (exact allowlist semasi; ham metin/skor/karar yok)"
    else
      bad "screening response pointer-only exact sema ihlali"
    fi
    FSR=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("findingSetRef", ""))' "$T/d29-screen-create.json" 2>/dev/null)
    REPLAY_CODE=$(curl -sS --max-time 30 -D "$T/d29-screen-replay.headers" \
      -o "$T/d29-screen-replay.json" -w '%{http_code}' -X POST "$API/screenings" \
      -H "Authorization: Bearer $REVIEWER" -H 'Content-Type: application/json' \
      -H "X-ATS-Idempotency-Key: $SCREEN_KEY" -d "$SCREEN_BODY")
    if [ "$REPLAY_CODE" = "200" ] && grep -qi '^x-ats-replay: true' "$T/d29-screen-replay.headers"; then
      ok "ayni screening request -> 200 verified replay"
    else
      bad "screening replay -> $REPLAY_CODE/header"
    fi
    if [ -n "$FSR" ] && cmp -s "$T/d29-screen-create.json" "$T/d29-screen-replay.json"; then
      ok "screening replay govdesi birebir ayni"
    else
      bad "screening replay govde bagi"
    fi
    C=$(code GET "$API/screenings/$FSR" "$READER")
    [ "$C" = "200" ] && ok "reader screening.read -> 200" || bad "reader screening.read -> $C"
    READER_WRITE=$(curl -sS --max-time 20 -o "$T/d29-screen-reader-write.json" -w '%{http_code}' \
      -X POST "$API/screenings" -H "Authorization: Bearer $READER" \
      -H 'Content-Type: application/json' \
      -H "X-ATS-Idempotency-Key: scrq_$(python3 -c 'import uuid; print(uuid.uuid4())')" \
      -d "$SCREEN_BODY")
    [ "$READER_WRITE" = "403" ] && ok "reader screening.write -> 403" || bad "reader screening.write -> $READER_WRITE"
    C=$(code GET "$API/screenings/$FSR" "$ROLELESS")
    [ "$C" = "403" ] && ok "roleless screening.read -> 403" || bad "roleless screening.read -> $C"
  fi
else
  echo "NOT: screening smoke kapali (backend #168 + KC #2441 pin sonrasi ATS_SCREENING_EXPECTED=1)"
fi

echo "== Operator allow / reviewer deny (DSAR) =="
C=$(code POST "$API/dsar" "$REVIEWER" '{"subjectRef":"sub-smoke-1","reasonCode":"r-kvkk"}'); [ "$C" = "403" ] && ok "reviewer dsar -> 403" || bad "reviewer dsar -> $C"
C=$(code POST "$API/dsar" "$OPERATOR" '{"subjectRef":"sub-smoke-1","reasonCode":"r-kvkk"}'); [ "${C:0:1}" = "2" ] && ok "operator dsar intake -> $C" || bad "operator dsar -> $C ($(head -c 160 "$T/last.json" 2>/dev/null))"

echo; echo "SONUC: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
