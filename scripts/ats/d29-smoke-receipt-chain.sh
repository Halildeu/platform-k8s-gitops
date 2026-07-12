#!/usr/bin/env bash
# 39d-8..11 canlı receipt/artifact/replay/repair smoke'u (RB-ats-39d ek-matrisi).
# staging-sw'de koşar; d29-smoke.sh desenini izler: persona şifreleri Vault'tan
# (stdout'a DÜŞMEZ), token'lar yalnız bu süreçte. iv-smoke-2 kullanılır
# (iv-smoke-1'in 39d-4 state'i kirletilmez). Ledger doğrulamaları platform-pg-test
# üzerinden salt-okuma psql'dir (mutasyon YOK — WORM'a dokunulmaz).
# Kapsam notu: repair'in 200-REPAIRED yolu app-boot E2E'de kanıtlı; CANLIDA
# yalnız onay-kapısı (rolsüz 403) doğrulanır — canlı R4 fixture'ı state bozar.
set -uo pipefail
EDGE="https://testai.acik.com"
KCTOK="$EDGE/realms/platform-test/protocol/openid-connect/token"
IV="iv-smoke-2"
API="$EDGE/api/ats/v1/interviews/$IV"
PASS=0; FAIL=0
ok(){ echo "PASS: $1"; PASS=$((PASS+1)); }
bad(){ echo "FAIL: $1"; FAIL=$((FAIL+1)); }

ROOT=$(python3 -c 'import json;print(json.load(open("/home/halil/bootstrap-drill/vault-init-test.json"))["root_token"])')
SMOKE=$(docker exec -e VAULT_TOKEN="$ROOT" -e VAULT_ADDR=http://127.0.0.1:8200 platform-vault-test vault kv get -format=json kv/platform/ats-smoke)
pw(){ printf '%s' "$SMOKE" | python3 -c "import json,sys;print(json.load(sys.stdin)['data']['data']['$1'])"; }
tok(){
  curl -sk --max-time 15 -d "grant_type=password&client_id=$1&username=$2&password=$(pw "$3")" "$KCTOK" \
    | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("access_token",""))
except Exception: print("")'
}
code(){ # $1=method $2=url $3=token(optional) $4=body(optional json) — cevap /tmp/rc-last.json
  local h=(); [ -n "${3:-}" ] && h=(-H "Authorization: Bearer $3")
  if [ -n "${4:-}" ]; then
    curl -sk --max-time 30 -o /tmp/rc-last.json -w '%{http_code}' -X "$1" "${h[@]}" -H 'Content-Type: application/json' -d "$4" "$2"
  else
    curl -sk --max-time 30 -o /tmp/rc-last.json -w '%{http_code}' -X "$1" "${h[@]}" "$2"
  fi
}
jfield(){ python3 -c "import json;d=json.load(open('/tmp/rc-last.json'));print(d.get('$1',''))" 2>/dev/null; }
hdr(){ # $1=method $2=url $3=token — header'ları /tmp/rc-hdr'a, status stdout'a
  curl -sk --max-time 30 -D /tmp/rc-hdr -o /tmp/rc-last.json -w '%{http_code}' -X "$1" -H "Authorization: Bearer $3" "$2"
}
psq(){ docker exec platform-pg-test psql -U postgres -d ats -tAc "$1"; }

OPERATOR=$(tok frontend ats-operator-persona OPERATOR_PW)
READER=$(tok frontend ats-reader-persona READER_PW)
[ -n "$OPERATOR" ] || { echo "FATAL: operator token alınamadı"; exit 1; }
[ -n "$READER" ] || { echo "FATAL: reader token alınamadı"; exit 1; }

# --- fixture: consent → upload → transcribe → citation → review → finalize ---
python3 - <<'WAVEOF'
import wave
w = wave.open('/tmp/rc-sentetik.wav', 'w')
w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000)
w.writeframes(b'\x00\x00' * 800)
w.close()
WAVEOF
C=$(code PUT "$API/recording-consent" "$OPERATOR" '{"subjectRef":"sub-smoke-2","state":"GRANTED"}')
[ "${C:0:1}" = "2" ] || { bad "consent -> $C"; }
UP=$(curl -sk --max-time 30 -o /tmp/rc-last.json -w '%{http_code}' -X POST "$API/recordings" \
  -H "Authorization: Bearer $OPERATOR" -H "Content-Type: audio/wav" \
  -H "X-ATS-Filename: rc-sentetik.wav" --data-binary @/tmp/rc-sentetik.wav)
OBJ=$(jfield objectKey)
[ "${UP:0:1}" = "2" ] && [ -n "$OBJ" ] || bad "upload -> $UP obj=$OBJ"
C=$(code POST "$API/transcribe" "$OPERATOR" "{\"sourceObjectKey\":\"$OBJ\"}")
TK=$(jfield transcriptKey)
[ "${C:0:1}" = "2" ] && [ -n "$TK" ] || bad "transcribe -> $C tk=$TK"
C=$(code POST "$API/citations" "$OPERATOR" "{\"transcriptKey\":\"$TK\",\"claim\":\"sentetik smoke iddiasi rc-2\"}")
CIT=$(jfield citationKey); CIT_EV=$(jfield evidenceId)
[ "$C" = "201" ] && [ -n "$CIT" ] || bad "citation -> $C"
C=$(code POST "$API/review-cases" "$OPERATOR" "{\"sourceEvidenceRefs\":[\"$CIT\"],\"aiOutputVersionRef\":\"ai-v1\"}")
CASE=$(jfield caseKey)
[ "${C:0:1}" = "2" ] && [ -n "$CASE" ] || bad "review open -> $C"
for T in "{\"caseKey\":\"$CASE\",\"action\":\"START\",\"oversightRoleRef\":\"role-smoke\"}" \
         "{\"caseKey\":\"$CASE\",\"action\":\"REVIEWED_NO_CHANGE\"}" \
         "{\"caseKey\":\"$CASE\",\"action\":\"RATIONALE\",\"ref\":\"rationale-smoke-1\"}"; do
  C=$(code POST "$API/review-case/transition" "$OPERATOR" "$T")
  [ "${C:0:1}" = "2" ] || bad "transition -> $C"
done
C=$(code POST "$API/review-case/finalize" "$OPERATOR" "{\"caseKey\":\"$CASE\",\"decisionOutcomeRef\":\"karar-smoke-1\"}")
[ "${C:0:1}" = "2" ] || bad "finalize -> $C"

SCHEMA_DIGEST=$(printf '0%.0s' {1..64})
EXPORT_BODY="{\"caseKey\":\"$CASE\",\"citationKeys\":[\"$CIT\"],\"context\":{\"generatorVersionRef\":\"gen-v1\",\"locale\":\"tr-TR\",\"timezone\":\"Europe/Istanbul\",\"aiAssistanceDisclosureRef\":\"disclosure-v1\",\"consentRefs\":[\"consent-smoke-1\"],\"rubricVersionRef\":\"rubric-v1\",\"criteria\":[{\"criterionId\":\"c-comm\",\"jobRelatednessRationaleRef\":\"jr-v1\"}],\"citationCriterion\":{\"$CIT\":\"c-comm\"},\"wormChainRefs\":[\"$CIT_EV\"],\"redactionPolicyRef\":\"red-pol-v1\",\"redactionRunRef\":\"red-run-1\",\"retentionPolicyRef\":\"ret-pol-v1\",\"schemaDigest\":\"$SCHEMA_DIGEST\",\"signatureRef\":\"sig-1\"}}"
WORM_BEFORE=$(psq "SELECT count(*) FROM worm_ledger WHERE tenant_id='t-platform-test' AND event_type='evidence_packet.exported' AND payload->>'case_key'='$CASE'")
C=$(code POST "$API/export" "$OPERATOR" "$EXPORT_BODY")
ART=$(jfield artifactKey); PDIG=$(jfield packetDigest)
[ "$C" = "201" ] && [ -n "$ART" ] && ok "export 201 (yeni üretim)" || bad "export -> $C ($(head -c 200 /tmp/rc-last.json))"
CASE_ENC=$(python3 -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1],safe=''))" "$CASE")

echo "== A) receipt: 200 COMPLETED + no-store; reader 403; anon 401 =="
S=$(hdr GET "$API/export/receipt?caseKey=$CASE_ENC" "$OPERATOR")
TS=$(jfield transitionStatus)
[ "$S" = "200" ] && [ "$TS" = "COMPLETED" ] && ok "receipt 200 COMPLETED" || bad "receipt -> $S/$TS"
grep -qi '^cache-control:.*no-store' /tmp/rc-hdr && ok "receipt no-store" || bad "receipt no-store yok"
S=$(hdr GET "$API/export/receipt?caseKey=$CASE_ENC" "$READER")
[ "$S" = "403" ] && ok "reader(export.read'siz) receipt -> 403" || bad "reader receipt -> $S"
S=$(code GET "$API/export/receipt?caseKey=$CASE_ENC")
[ "$S" = "401" ] && ok "anon receipt -> 401" || bad "anon receipt -> $S"

echo "== B) artifact: 200 verbatim (sha256==ledger.artifact_digest) + HEAD 403 =="
S=$(hdr GET "$API/export/artifact?caseKey=$CASE_ENC" "$OPERATOR")
[ "$S" = "200" ] && ok "artifact 200" || bad "artifact -> $S"
grep -qi '^content-type:.*application/json' /tmp/rc-hdr && ok "artifact Content-Type json" || bad "artifact content-type"
grep -qi '^cache-control:.*no-store' /tmp/rc-hdr && ok "artifact 200 no-store" || bad "artifact 200 no-store yok"
LDIG=$(psq "SELECT payload->>'artifact_digest' FROM worm_ledger WHERE tenant_id='t-platform-test' AND event_type='evidence_packet.exported' AND payload->>'case_key'='$CASE'")
BDIG=$(python3 -c "import hashlib;print(hashlib.sha256(open('/tmp/rc-last.json','rb').read()).hexdigest())")
[ -n "$LDIG" ] && [ "$LDIG" = "$BDIG" ] && ok "VERBATIM: sha256(gövde)==ledger.artifact_digest" || bad "verbatim: ledger=$LDIG gövde=$BDIG"
S=$(curl -sk --max-time 20 -o /dev/null -w '%{http_code}' -I -H "Authorization: Bearer $OPERATOR" "$API/export/artifact?caseKey=$CASE_ENC")
[ "$S" = "403" ] && ok "HEAD artifact -> 403 (bilinçli kapalı)" || bad "HEAD artifact -> $S"

echo "== C) replay: aynı gövde 200 + X-ATS-Replay + WORM sabit; değişik gövde 400 =="
S=$(curl -sk --max-time 30 -D /tmp/rc-hdr -o /tmp/rc-last.json -w '%{http_code}' -X POST \
  -H "Authorization: Bearer $OPERATOR" -H 'Content-Type: application/json' -d "$EXPORT_BODY" "$API/export")
[ "$S" = "200" ] && ok "replay 200" || bad "replay -> $S ($(head -c 200 /tmp/rc-last.json))"
grep -qi '^x-ats-replay: *true' /tmp/rc-hdr && ok "X-ATS-Replay: true" || bad "replay header yok"
[ "$(jfield artifactKey)" = "$ART" ] && ok "replay makbuzu birebir (artifactKey)" || bad "replay artifactKey farklı"
WORM_AFTER=$(psq "SELECT count(*) FROM worm_ledger WHERE tenant_id='t-platform-test' AND event_type='evidence_packet.exported' AND payload->>'case_key'='$CASE'")
[ "$WORM_BEFORE" = "0" ] && [ "$WORM_AFTER" = "1" ] && ok "case-scoped WORM: 0→1 (yalnız ilk export; replay yazmadı)" || bad "case-scoped WORM: önce=$WORM_BEFORE sonra=$WORM_AFTER (0→1 bekleniyor)"
S=$(code POST "$API/export" "$OPERATOR" "${EXPORT_BODY/sig-1/sig-BASKA}")
[ "$S" = "400" ] && ok "değişik gövde -> 400 conflict (makbuz sızmadı)" || bad "conflict -> $S"

echo "== D) repair onay-kapısı: rolsüz(operator) 403 =="
S=$(curl -sk --max-time 20 -o /tmp/rc-last.json -w '%{http_code}' -X POST -H "Authorization: Bearer $OPERATOR" -H 'Content-Type: application/json' -d "{\"caseKey\":\"$CASE\"}" "$API/export/repair")
[ "$S" = "403" ] && ok "operator(repair-rolsüz) repair -> 403 (onay-kapısı)" || bad "repair kapısı -> $S"

echo "== E) erasure-sonrası: artifact 404, receipt hâlâ 200 COMPLETED =="
C=$(code POST "$API/dsar" "$OPERATOR" '{"subjectRef":"sub-smoke-2","reasonCode":"r-kvkk"}')
DSAR=$(jfield dsarKey)
[ "${C:0:1}" = "2" ] && [ -n "$DSAR" ] || bad "dsar -> $C"
C=$(code POST "$API/dsar/erasure" "$OPERATOR" "{\"dsarKey\":\"$DSAR\",\"scope\":{\"exportArtifactKeys\":[\"$ART\"]}}")
[ "$C" = "200" ] && ok "erasure (artifact content-plane) -> 200" || bad "erasure -> $C ($(head -c 200 /tmp/rc-last.json))"
S=$(hdr GET "$API/export/artifact?caseKey=$CASE_ENC" "$OPERATOR")
[ "$S" = "404" ] && ok "erasure-sonrası artifact -> 404 (API-kanıtı)" || bad "post-erasure artifact -> $S"
grep -qi '^cache-control:.*no-store' /tmp/rc-hdr && ok "404 cevabı da no-store" || bad "404 no-store yok"
S=$(hdr GET "$API/export/receipt?caseKey=$CASE_ENC" "$OPERATOR")
TS=$(jfield transitionStatus)
[ "$S" = "200" ] && [ "$TS" = "COMPLETED" ] && ok "WORM makbuzu erasure'dan sağ çıktı (200 COMPLETED)" || bad "post-erasure receipt -> $S/$TS"

echo; echo "SONUC: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
