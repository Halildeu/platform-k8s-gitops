#!/usr/bin/env bash
# Faz 25 #2526: sentetik aday -> takip -> recruiter inbox/status E2E.
# Secret/JWT/candidate token stdout veya process argumanina basılmaz.
#
# A2 MIGRATION NOTE (2026-07-21, Faz 22 Sec KC hardening #2476 A2b.2):
# `client_id=frontend` public + DAG=true — A2c cutover'da DAG=false. Bu smoke
# recruiter/operator persona token'ının `resource_access.ats-api.roles`'e
# (13 ats.* scope: application.read/status.write/citation.write/consent.write/
# dsar.write/erasure.execute/export.read/export.write/recording.write/review.read/
# review.write/transcript.read/transcription.write) bağımlı. Bu scope'lar
# frontend'de DEFAULT olarak atanmış, smoke-client'ta YOK. A2c ÖNCESİ Faz25 team
# ya (a) smoke-client'a ats.* scope'larını A2b.3 ile eklemeli (defaultClientScopes'a
# taşımalı ki tenant claim + resource_access garantili gelsin), ya (b) `ats-recruiter`
# adında dedicated ATS smoke client kurmalı. Aksi halde A2c bu smoke'u breaks eder.
set -euo pipefail

EDGE="${ATS_EDGE:-https://testai.acik.com}"
API="$EDGE/api/ats/v1"
TENANT="00000000-0000-0000-0000-000000000001"
OTHER_TENANT="t-platform-test"
T=$(mktemp -d); chmod 700 "$T"; umask 077
trap 'rm -rf "$T"; unset RT OT CA ROOT S RPW OPW' EXIT
N=0; ok(){ echo "PASS: $1"; N=$((N+1)); }; die(){ echo "FAIL: $1" >&2; exit 1; }

ROOT=$(python3 -c 'import json;print(json.load(open("/home/halil/bootstrap-drill/vault-init-test.json"))["root_token"])')
S=$(VAULT_TOKEN="$ROOT" docker exec -e VAULT_TOKEN \
  -e VAULT_ADDR=http://127.0.0.1:8200 platform-vault-test \
  vault kv get -format=json kv/platform/ats-smoke)
unset ROOT
RPW=$(printf '%s' "$S" | jq -er '.data.data.RECRUITER_PW')
OPW=$(printf '%s' "$S" | jq -er '.data.data.OPERATOR_PW')
printf '%s\n' 'data-urlencode = "grant_type=password"' 'data-urlencode = "client_id=frontend"' \
  'data-urlencode = "username=ats-recruiter-persona"' \
  "data-urlencode = \"password=$RPW\"" > "$T/recruiter-token.curl"
printf '%s\n' 'data-urlencode = "grant_type=password"' 'data-urlencode = "client_id=frontend"' \
  'data-urlencode = "username=ats-operator-persona"' \
  "data-urlencode = \"password=$OPW\"" > "$T/operator-token.curl"
unset RPW OPW S
RT=$(curl -fsS --max-time 20 --config "$T/recruiter-token.curl" \
  "$EDGE/realms/platform-test/protocol/openid-connect/token" | jq -er '.access_token')
OT=$(curl -fsS --max-time 20 --config "$T/operator-token.curl" \
  "$EDGE/realms/platform-test/protocol/openid-connect/token" | jq -er '.access_token')
rm -f "$T/recruiter-token.curl" "$T/operator-token.curl"
[ -n "$RT" ] || die "recruiter token"
[ -n "$OT" ] || die "operator token"
CLAIMS=$(printf '%s' "$RT" | cut -d. -f2 | python3 -c 'import base64,json,sys;p=sys.stdin.read().strip();p+="="*(-len(p)%4);d=json.loads(base64.urlsafe_b64decode(p));print((d.get("tenant") or "")+"|"+",".join(sorted(d.get("resource_access",{}).get("ats-api",{}).get("roles",[]))))')
[ "$CLAIMS" = "$TENANT|ats.application.read,ats.application.status.write" ] || die "tenant/rol exact-set"
ok "recruiter tenant + least-privilege rol exact-set"
printf 'header = "Authorization: Bearer %s"\n' "$RT" > "$T/recruiter.curl"
OP_CLAIMS=$(printf '%s' "$OT" | cut -d. -f2 | python3 -c 'import base64,json,sys;p=sys.stdin.read().strip();p+="="*(-len(p)%4);d=json.loads(base64.urlsafe_b64decode(p));print((d.get("tenant") or "")+"|"+",".join(sorted(d.get("resource_access",{}).get("ats-api",{}).get("roles",[]))))')
EXPECTED_OPERATOR="$OTHER_TENANT|ats.application.read,ats.application.status.write,ats.citation.write,ats.consent.write,ats.dsar.write,ats.erasure.execute,ats.export.read,ats.export.write,ats.recording.write,ats.review.read,ats.review.write,ats.transcript.read,ats.transcription.write"
[ "$OP_CLAIMS" = "$EXPECTED_OPERATOR" ] || die "operator tenant/rol exact-set"
printf 'header = "Authorization: Bearer %s"\n' "$OT" > "$T/operator.curl"

CA=$(openssl rand 32 | base64 | tr '+/' '-_' | tr -d '=\n')
[ "${#CA}" -eq 43 ] || die "candidate token formati"
ID="faz25-$(openssl rand -hex 16)"
printf '%s\n' 'header = "Content-Type: application/json"' \
  "header = \"X-ATS-Idempotency-Key: $ID\"" "header = \"X-ATS-Candidate-Access: $CA\"" > "$T/submit.curl"
printf 'header = "X-ATS-Candidate-Access: %s"\n' "$CA" > "$T/candidate.curl"

C=$(curl -fsS --max-time 20 -o "$T/jobs" -w '%{http_code}' "$API/jobs")
if [ "$C" != 200 ] || ! jq -e 'any(.[]; .slug=="product-designer")' "$T/jobs" >/dev/null; then
  die "public jobs"
fi
ok "public jobs katalogu"

NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ); X=$(openssl rand -hex 6)
printf '{"fullName":"Sentetik Aday %s","email":"aday-%s@example.test","phone":"+12025550123","city":"Istanbul","linkedIn":"https://linkedin.example.test/sentetik","portfolio":"https://portfolio.example.test/sentetik","summary":"Sentetik urun tasarimi ve arastirma ozeti","experience":"Sentetik urun deneyimi kaydi","education":"Sentetik lisans egitimi","skills":["Urun Tasarimi","Arastirma"],"note":"Faz 25 sentetik canli kabul","noticeVersion":"kvkk-application-v1","noticeAcceptedAt":"%s","accuracyConfirmedAt":"%s"}' "$X" "$X" "$NOW" "$NOW" > "$T/body"
C=$(curl -sS --max-time 20 --config "$T/submit.curl" -D "$T/h1" -o "$T/r1" \
  -w '%{http_code}' --data-binary @"$T/body" "$API/jobs/product-designer/applications")
[ "$C" = 201 ] || die "submit HTTP $C"
REF=$(jq -er 'select(.status=="SUBMITTED" and .version==0 and .replayed==false)|.publicRef' "$T/r1")
[[ "$REF" == app_* ]] || die "receipt"
ok "sentetik basvuru -> 201 SUBMITTED"

C=$(curl -sS --max-time 20 --config "$T/submit.curl" -D "$T/hr" -o "$T/rr" \
  -w '%{http_code}' --data-binary @"$T/body" "$API/jobs/product-designer/applications")
if [ "$C" != 200 ] || ! grep -Eiq '^X-ATS-Replay:[[:space:]]*true' "$T/hr" \
  || [ "$(jq -r .publicRef "$T/rr")" != "$REF" ]; then
  die "idempotent replay"
fi
ok "idempotent retry ayni receipt"

C=$(curl -sS --max-time 20 --config "$T/candidate.curl" -o "$T/c1" -w '%{http_code}' \
  "$API/candidate/applications/$REF")
if [ "$C" != 200 ] || ! jq -e '.status=="SUBMITTED" and .version==0 and
  ([has("fullName"),has("email"),has("phone"),has("candidateAccessToken")]|any|not)' "$T/c1" >/dev/null; then
  die "candidate minimal status"
fi
ok "candidate session-token status PII-free"

C=$(curl -sS --max-time 20 --config "$T/recruiter.curl" -o "$T/inbox" -w '%{http_code}' \
  "$API/recruiter/applications?jobSlug=product-designer&status=SUBMITTED&page=0&size=50")
if [ "$C" != 200 ] || ! jq -e --arg r "$REF" \
  'any(.items[]; .publicRef==$r and .status=="SUBMITTED")' "$T/inbox" >/dev/null; then
  die "recruiter inbox"
fi
ok "tenant-scoped recruiter inbox"

C=$(curl -sS --max-time 20 --config "$T/operator.curl" -o "$T/other-inbox" -w '%{http_code}' \
  "$API/recruiter/applications?jobSlug=product-designer&status=SUBMITTED&page=0&size=50")
if [ "$C" != 200 ] || ! jq -e --arg r "$REF" \
  'all(.items[]; .publicRef!=$r)' "$T/other-inbox" >/dev/null; then
  die "cross-tenant application isolation"
fi
printf '{"expectedVersion":0,"toStatus":"UNDER_REVIEW"}' > "$T/other-s1"
C=$(curl -sS --max-time 20 --config "$T/operator.curl" -H 'Content-Type: application/json' \
  -X PUT --data-binary @"$T/other-s1" -o "$T/other-o1" -w '%{http_code}' \
  "$API/recruiter/applications/$REF/status")
[ "$C" = 404 ] || die "cross-tenant status mutation HTTP $C (404 bekleniyor)"
ok "ayni rollerle baska tenant listeleyemez ve basvuruyu degistiremez"

printf '{"expectedVersion":0,"toStatus":"UNDER_REVIEW"}' > "$T/s1"
C=$(curl -sS --max-time 20 --config "$T/recruiter.curl" -H 'Content-Type: application/json' \
  -X PUT --data-binary @"$T/s1" -o "$T/o1" -w '%{http_code}' "$API/recruiter/applications/$REF/status")
if [ "$C" != 200 ] || ! jq -e '.status=="UNDER_REVIEW" and .version==1' "$T/o1" >/dev/null; then
  die "UNDER_REVIEW"
fi
ok "SUBMITTED -> UNDER_REVIEW"

C=$(curl -sS --max-time 20 --config "$T/candidate.curl" -o "$T/c2" -w '%{http_code}' \
  "$API/candidate/applications/$REF")
if [ "$C" != 200 ] || ! jq -e '.status=="UNDER_REVIEW" and .version==1' "$T/c2" >/dev/null; then
  die "candidate updated status"
fi
ok "candidate guncel durumu goruyor"

printf '{"expectedVersion":1,"toStatus":"INTERVIEW_PENDING"}' > "$T/s2"
C=$(curl -sS --max-time 20 --config "$T/recruiter.curl" -H 'Content-Type: application/json' \
  -X PUT --data-binary @"$T/s2" -o "$T/o2" -w '%{http_code}' "$API/recruiter/applications/$REF/status")
if [ "$C" != 200 ] || ! jq -e '.status=="INTERVIEW_PENDING" and .version==2' "$T/o2" >/dev/null; then
  die "INTERVIEW_PENDING"
fi
ok "UNDER_REVIEW -> INTERVIEW_PENDING"

echo "SONUC: $N/10 PASS publicRef=$REF (sentetik; token/PII redacted)"
[ "$N" -eq 10 ]
