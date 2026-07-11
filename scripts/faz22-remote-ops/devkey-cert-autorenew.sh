#!/bin/bash
# Faz 22.6 device-key session cert DURABLE auto-renew (staging-sw cron bridge).
# Codex 019f515c REVISE absorb: flock single-flight; TIME-BASED threshold (renew only
# when last successful renew > INTERVAL hours ago — locale-independent, robust); one-time
# short-TTL enrollment token; token via env inside EncodedCommand (NOT plaintext argv) —
# one-time+short-TTL mitigates residual; agent-restart + stream verify; failure marker.
#
# The device-key session cert (denetim PC C:\ProgramData\EndpointAgent\tpm-client-cert.pem)
# is Vault pki_int (device CA) issued with a 24h TTL and has NO in-agent auto-renew yet.
# This cron renews it BEFORE expiry (every ~16h → ≥8h margin) so the device-key VIEW_ONLY
# session never breaks. PERMANENT fix (separate agent feature, filed): agent-side auto-renew
# (SPIFFE-style) + `--enrollment-token-stdin`. This bridge holds until that ships.
set -uo pipefail

RENEW_INTERVAL_HOURS="${RENEW_INTERVAL_HOURS:-16}"      # 24h TTL → renew every 16h (≥8h margin)
FORCE="${FORCE:-0}"                                     # FORCE=1 → skip interval check
REALM="platform-test"; KC="http://127.0.0.1:8082"; GW="https://testai.acik.com"
PERSONA="${PERSONA:-c5persona-admin-9001}"
DENSSH="ssh -F /home/runner/faz22-6-denetim-ssh/config -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=8 denetim-pc"
LOG=/home/halil/platform/logs/devkey-cert-autorenew.log
LOCK=/home/halil/platform/locks/devkey-cert-autorenew.lock
MARK=/home/halil/platform/state/devkey-cert-autorenew.epoch     # last successful renew epoch
STATUS=/home/halil/platform/state/devkey-cert-autorenew.status
mkdir -p "$(dirname "$LOG")" "$(dirname "$LOCK")" "$(dirname "$MARK")"
exec >>"$LOG" 2>&1
say() { echo "[$(date -u +%FT%TZ)] $*"; }

exec 9>"$LOCK"
if ! flock -n 9; then say "another run holds the lock, skip"; exit 0; fi

NOW=$(date -u +%s)
LAST=$(cat "$MARK" 2>/dev/null || echo 0); [[ "$LAST" =~ ^[0-9]+$ ]] || LAST=0
AGE_H=$(( (NOW - LAST) / 3600 ))
say "=== autorenew start (interval=${RENEW_INTERVAL_HOURS}h; lastRenew ${AGE_H}h ago) ==="
if [ "$FORCE" != "1" ] && [ "$LAST" -gt 0 ] && [ "$AGE_H" -lt "$RENEW_INTERVAL_HOURS" ]; then
  say "son renew ${AGE_H}h < ${RENEW_INTERVAL_HOURS}h → renew GEREKMİYOR, skip"
  echo "$(date -u +%FT%TZ) OK skip age=${AGE_H}h" > "$STATUS"; exit 0
fi

# --- MANAGER token + one-time short-TTL enrollment ---
KCADM=$(docker exec platform-kc-test sh -c 'cat /run/secrets/kc_admin_password' 2>/dev/null | tr -d '\r\n')
[ -z "$KCADM" ] && { say "FAIL kc-admin-pass"; echo "$(date -u +%FT%TZ) FAIL kc-admin-pass" > "$STATUS"; exit 1; }
ADMTOK=$(curl -sS -X POST "$KC/realms/master/protocol/openid-connect/token" \
  --data-urlencode grant_type=password --data-urlencode client_id=admin-cli \
  --data-urlencode username=admin --data-urlencode "password=$KCADM" | jq -r '.access_token // empty')
UID_=$(curl -sS -H "Authorization: Bearer $ADMTOK" "$KC/admin/realms/$REALM/users?username=$PERSONA&exact=true" | jq -r '.[0].id // empty')
[ -z "$UID_" ] && { say "FAIL persona-not-found $PERSONA"; echo "$(date -u +%FT%TZ) FAIL persona" > "$STATUS"; exit 1; }
PPASS=$(openssl rand -base64 24 | tr -d '\n')
curl -sS -o /dev/null -X PUT -H "Authorization: Bearer $ADMTOK" -H "Content-Type: application/json" \
  "$KC/admin/realms/$REALM/users/$UID_/reset-password" -d "$(jq -n --arg v "$PPASS" '{type:"password",value:$v,temporary:false}')"
PTOK=$(curl -sS -X POST "$KC/realms/$REALM/protocol/openid-connect/token" \
  --data-urlencode grant_type=password --data-urlencode client_id=frontend \
  --data-urlencode username=$PERSONA --data-urlencode "password=$PPASS" | jq -r '.access_token // empty')
[ -z "$PTOK" ] && { say "FAIL persona-token"; echo "$(date -u +%FT%TZ) FAIL persona-token" > "$STATUS"; exit 1; }
ERESP=$(curl -sS -X POST -H "Authorization: Bearer $PTOK" -H "Content-Type: application/json" \
  "$GW/api/v1/endpoint-admin/endpoint-enrollments" -d '{"expiresInMinutes":10,"note":"device-key autorenew cron"}')
ETOK=$(jq -r '.token // empty' <<<"$ERESP")
[ -z "$ETOK" ] && { say "FAIL enrollment: $(head -c 160 <<<"$ERESP")"; echo "$(date -u +%FT%TZ) FAIL enrollment" > "$STATUS"; exit 1; }
say "enrollment OK (one-time, 10min TTL)"

# --- agent -auto-enroll-tpm (env token inside EncodedCommand; transcript off) ---
OUTF='C:\ProgramData\EndpointAgent\autorenew.out'
PS='$ErrorActionPreference="Continue"; try{Stop-Transcript|Out-Null}catch{};
$env:ENDPOINT_AGENT_ENROLLMENT_TOKEN="__ETOK__";
$env:ENDPOINT_AGENT_AUTO_ENROLL_CERT_SAN_URI_PREFIX="adcomputer:";
& "C:\Program Files\EndpointAgent\endpoint-agent.exe" -auto-enroll-tpm --api-url "https://testai.acik.com/api/v1/endpoint-agent" *>&1 | Tee-Object -FilePath "__OUTF__";
"EXITCODE=" + $LASTEXITCODE | Add-Content "__OUTF__";
$env:ENDPOINT_AGENT_ENROLLMENT_TOKEN=""; Get-Content "__OUTF__"; Remove-Item "__OUTF__" -Force -EA SilentlyContinue'
PS=${PS//__ETOK__/$ETOK}; PS=${PS//__OUTF__/$OUTF}
B64=$(printf '%s' "$PS" | iconv -f UTF-8 -t UTF-16LE | base64 -w0)
ENOUT=$($DENSSH "powershell -NoProfile -EncodedCommand $B64" 2>&1 | grep -aE "success|EXITCODE|error|refused" | head -3)
say "enroll: $ENOUT"
echo "$ENOUT" | grep -q "EXITCODE=0" || { say "FAIL agent-enroll"; echo "$(date -u +%FT%TZ) FAIL agent-enroll" > "$STATUS"; exit 1; }

# --- restart agent + verify device-key stream started (fresh cert loaded) ---
$DENSSH 'powershell -NoProfile -Command "Restart-Service EndpointAgent -Force"' >/dev/null 2>&1
sleep 12
STREAM=$($DENSSH 'powershell -NoProfile -Command "Get-Content C:\ProgramData\EndpointAgent\logs\endpoint-agent.log -Tail 25"' 2>/dev/null | grep -aE "harness started|device cert expired" | tail -1)
if echo "$STREAM" | grep -qi "harness started" && ! echo "$STREAM" | grep -qi "expired"; then
  say "=== RENEW OK: fresh cert + device-key session started ==="
  echo "$NOW" > "$MARK"
  echo "$(date -u +%FT%TZ) OK renewed" > "$STATUS"
else
  say "WARN: renew yapıldı ama stream doğrulanamadı [$STREAM]"
  echo "$(date -u +%FT%TZ) WARN stream-unverified" > "$STATUS"
fi
