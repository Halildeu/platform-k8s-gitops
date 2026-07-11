#!/usr/bin/env bash
# 39d-4 D29 kanıt matrisi (Codex 019f4c6c/019f50b7 adlandırmasıyla).
# staging-sw'de koşar; persona şifreleri Vault'tan (stdout'a düşmez);
# token'lar yalnız bu süreçte — basılan tek şey claim ÖZETİ (redacted).
set -uo pipefail
EDGE="https://testai.acik.com"
KCTOK="$EDGE/realms/platform-test/protocol/openid-connect/token"
API="$EDGE/api/ats/v1/interviews/iv-smoke-1"
PASS=0; FAIL=0
ok(){ echo "PASS: $1"; PASS=$((PASS+1)); }
bad(){ echo "FAIL: $1"; FAIL=$((FAIL+1)); }

ROOT=$(python3 -c 'import json;print(json.load(open("/home/halil/bootstrap-drill/vault-init-test.json"))["root_token"])')
SMOKE=$(docker exec -e VAULT_TOKEN="$ROOT" -e VAULT_ADDR=http://127.0.0.1:8200 platform-vault-test vault kv get -format=json kv/platform/ats-smoke)
pw(){ printf '%s' "$SMOKE" | python3 -c "import json,sys;print(json.load(sys.stdin)['data']['data']['$1'])"; }

tok(){ # $1=client $2=user $3=pwkey -> access_token (bos = fail)
  curl -sk --max-time 15 -d "grant_type=password&client_id=$1&username=$2&password=$(pw "$3")" "$KCTOK" \
    | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("access_token",""))
except Exception: print("")'
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
  local h=(); [ -n "${3:-}" ] && h=(-H "Authorization: Bearer $3")
  if [ -n "${4:-}" ]; then
    curl -sk --max-time 20 -o /tmp/d29-last.json -w '%{http_code}' -X "$1" "${h[@]}" -H 'Content-Type: application/json' -d "$4" "$2"
  else
    curl -sk --max-time 20 -o /tmp/d29-last.json -w '%{http_code}' -X "$1" "${h[@]}" "$2"
  fi
}

# sentetik WAV (RIFF header + 0.1sn sessizlik — tamamen sentetik; PII yok)
python3 - <<'WAVEOF'
import struct, wave
w = wave.open('/tmp/d29-sentetik.wav', 'w')
w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000)
w.writeframes(b'\x00\x00' * 800)
w.close()
WAVEOF

echo "== D29: Up + Immutable =="
POD=$(kubectl --context k3d-test -n platform-test get pod -l app=ats-interview-evidence -o jsonpath='{.items[0].status.phase}/{.items[0].status.containerStatuses[0].ready}')
IMG=$(kubectl --context k3d-test -n platform-test get pod -l app=ats-interview-evidence -o jsonpath='{.items[0].status.containerStatuses[0].imageID}')
[ "$POD" = "Running/true" ] && ok "pod Running/ready" || bad "pod=$POD"
case "$IMG" in *c2dcc1da2e169d676fec21a1acc60d6fd6be2b108e73ce705b0aa813010432b1*) ok "imageID == pinned digest (D30)";; *) bad "imageID=$IMG";; esac

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

echo "== D29: Authz allow/deny matrisi =="
C=$(code GET "$API/transcripts" "$READER"); [ "$C" = "200" ] && ok "reader GET transcripts -> 200" || bad "reader read -> $C"
C=$(code PUT "$API/recording-consent" "$READER" '{"subjectRef":"sub-smoke-1","state":"GRANTED"}'); [ "$C" = "403" ] && ok "reader consent-write -> 403" || bad "reader write -> $C"
C=$(code GET "$API/transcripts" "$ROLELESS"); [ "$C" = "403" ] && ok "ROLSUZ (scope'lu) -> 403 [ROL-KAPISI CANLI]" || bad "roleless -> $C"

echo "== D29: Functional — stubbed AI (reviewer zinciri) =="
C=$(code PUT "$API/recording-consent" "$REVIEWER" '{"subjectRef":"sub-smoke-1","state":"GRANTED"}')
[ "${C:0:1}" = "2" ] && ok "consent GRANTED -> $C" || { bad "consent -> $C"; cat /tmp/d29-last.json 2>/dev/null | head -c 200; echo; }
UP=$(curl -sk --max-time 30 -o /tmp/d29-up.json -w '%{http_code}' -X POST "$API/recordings" \
  -H "Authorization: Bearer $REVIEWER" -H "Content-Type: audio/wav" \
  -H "X-ATS-Filename: d29-sentetik.wav" --data-binary @/tmp/d29-sentetik.wav)
[ "${UP:0:1}" = "2" ] && ok "upload sentetik wav -> $UP" || { bad "upload -> $UP"; head -c 300 /tmp/d29-up.json; echo; }
EV=$(python3 -c 'import json;d=json.load(open("/tmp/d29-up.json"));print(d.get("objectKey") or d.get("evidenceId") or "")' 2>/dev/null)
echo "  upload cevap ozet: $(head -c 200 /tmp/d29-up.json 2>/dev/null)"
if [ -n "$EV" ]; then
  TR=$(curl -sk --max-time 60 -o /tmp/d29-tr.json -w '%{http_code}' -X POST "$API/transcribe" \
    -H "Authorization: Bearer $REVIEWER" -H 'Content-Type: application/json' \
    -d "{\"sourceObjectKey\":\"$EV\"}")
  [ "${TR:0:1}" = "2" ] && ok "transcribe (stub) -> $TR" || { bad "transcribe -> $TR"; head -c 300 /tmp/d29-tr.json; echo; }
  echo "  transcribe cevap ozet: $(head -c 240 /tmp/d29-tr.json 2>/dev/null)"
fi
TK=$(python3 -c 'import json;d=json.load(open("/tmp/d29-tr.json"));print(d.get("transcriptKey") or d.get("key") or "")' 2>/dev/null)
if [ -n "$TK" ]; then
  C=$(code GET "$API/transcript?key=$TK" "$REVIEWER"); [ "$C" = "200" ] && ok "read-back transcript?key -> 200" || bad "read-back -> $C"
else
  bad "transcriptKey cevaptan cikarilamadi"
fi
grep -q "test-stub" /tmp/d29-last.json 2>/dev/null && ok "stub-provenance ('test-stub') read-back'te" || echo "NOT: read-back'te test-stub izi yok (transcribe listesine bagli)"

echo "== Operator allow / reviewer deny (DSAR) =="
C=$(code POST "$API/dsar" "$REVIEWER" '{"subjectRef":"sub-smoke-1","reasonCode":"r-kvkk"}'); [ "$C" = "403" ] && ok "reviewer dsar -> 403" || bad "reviewer dsar -> $C"
C=$(code POST "$API/dsar" "$OPERATOR" '{"subjectRef":"sub-smoke-1","reasonCode":"r-kvkk"}'); [ "${C:0:1}" = "2" ] && ok "operator dsar intake -> $C" || bad "operator dsar -> $C ($(head -c 160 /tmp/d29-last.json 2>/dev/null))"

echo; echo "SONUC: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
