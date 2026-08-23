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

VAULT_INIT_FILE_DEFAULT="/srv/platform/secrets/backup-auth/vault-init-test.json"
# Host 53->15 tasinmasinda dosya yol DEGISTIRDI (silinmedi): eski konum
# ~/bootstrap-drill, yenisi /srv/platform/secrets/backup-auth (ACL ile
# script kullanicisina r--). Ikisini sirayla dene; ilk okunabilir kazanir.
[ -r "$VAULT_INIT_FILE_DEFAULT" ] || VAULT_INIT_FILE_DEFAULT="$HOME/bootstrap-drill/vault-init-test.json"
VAULT_INIT_FILE="${VAULT_INIT_FILE:-$VAULT_INIT_FILE_DEFAULT}"

RENEW_INTERVAL_HOURS="${RENEW_INTERVAL_HOURS:-16}"      # 24h TTL → renew every 16h (≥8h margin)
FORCE="${FORCE:-0}"                                     # FORCE=1 → skip interval check
REALM="platform-test"; KC="http://127.0.0.1:8082"; GW="https://testai.acik.com"
PERSONA="${PERSONA:-c5persona-admin-9001}"
# Host 53->15: the old staging-sw runner's SSH config and /home/halil state
# dirs did not survive the migration — this bridge silently stopped with them
# and the device cert sat expired for 12 days (found 2026-08-15; the device
# still showed ONLINE because ordinary heartbeats ride HMAC, not this cert).
# Prefer the legacy config when it exists; otherwise go direct over WireGuard
# (the aiserver key for denetimpc@10.99.0.2 is provisioned). State lives under
# the invoking user's HOME so the script owns no other user's paths.
DEN_SSH_CONFIG="/home/runner/faz22-6-denetim-ssh/config"
if [ -r "$DEN_SSH_CONFIG" ]; then
  DENSSH="ssh -F $DEN_SSH_CONFIG -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=8 denetim-pc"
else
  DENSSH="ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=8 ${DENETIM_SSH_TARGET:-denetimpc@10.99.0.2}"
fi
STATE_ROOT="${STATE_ROOT:-$HOME/platform}"
LOG=$STATE_ROOT/logs/devkey-cert-autorenew.log
LOCK=$STATE_ROOT/locks/devkey-cert-autorenew.lock
MARK=$STATE_ROOT/state/devkey-cert-autorenew.epoch     # last successful renew epoch
STATUS=$STATE_ROOT/state/devkey-cert-autorenew.status
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
# A2b.2 (2026-07-21): confidential smoke-client ROPC (client_id=frontend + DAG=false, A2c cutover).
# Vault kv/platform/keycloak/smoke-client (A2a); persona=c5persona-admin-9001 smoke-runtime-v1 scope OK.
VT=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["root_token"])' "$VAULT_INIT_FILE" 2>/dev/null || echo "")
SMOKE_SEC=$(docker exec -e VAULT_TOKEN="$VT" platform-vault-test \
  vault kv get -field=client_secret kv/platform/keycloak/smoke-client 2>/dev/null || echo "")
[ -z "$SMOKE_SEC" ] && { say "FAIL smoke-client-secret (kv/platform/keycloak/smoke-client — A2a seed?)"; echo "$(date -u +%FT%TZ) FAIL smoke-client-secret" > "$STATUS"; exit 1; }
VT=""
PTOK=$(curl -sS -X POST "$KC/realms/$REALM/protocol/openid-connect/token" \
  --data-urlencode grant_type=password --data-urlencode client_id=smoke-client \
  --data-urlencode "client_secret=$SMOKE_SEC" \
  --data-urlencode username=$PERSONA --data-urlencode "password=$PPASS" | jq -r '.access_token // empty')
SMOKE_SEC=""
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
# Success = the persisted cert is genuinely fresh (>20h of its 24h TTL left)
# and the service is back up. The old check grepped the log for "harness
# started", but that line only appears when the remote-bridge lane is enabled —
# measured 2026-08-15 with the bridge config-disabled, a successful renew would
# have WARNed forever. The cert's own NotAfter is deterministic either way; the
# stream line is reported as a bonus when the bridge happens to be on.
# EncodedCommand, like the mint step above — and for the same reason. The
# endpoint's SSH login shell is PowerShell, so an inline -Command string is
# parsed TWICE: the login shell interpolates $c (to empty) before the inner
# powershell ever runs, and the verify silently returns nothing. Measured
# 2026-08-23: eight days of "WARN unverified (certExp=?)", the MARK never
# advancing, and the cron re-minting every 8h instead of every 16h — 61 certs
# in the ledger where ~12 would do. DateTimeOffset avoids the PS5.1
# `-UFormat %s` local-time shift as well.
VERIFY_PS='$c=New-Object Security.Cryptography.X509Certificates.X509Certificate2("C:\ProgramData\EndpointAgent\tpm-client-cert.pem"); [System.DateTimeOffset]::new($c.NotAfter.ToUniversalTime(),[TimeSpan]::Zero).ToUnixTimeSeconds()'
VERIFY_B64=$(printf '%s' "$VERIFY_PS" | iconv -f UTF-8 -t UTF-16LE | base64 -w0)
CERT_EXP=$($DENSSH "powershell -NoProfile -EncodedCommand $VERIFY_B64" 2>/dev/null | tr -dc '0-9')
SVC=$($DENSSH 'powershell -NoProfile -Command "(Get-Service EndpointAgent).Status"' 2>/dev/null | tr -d '\r\n')
STREAM=$($DENSSH 'powershell -NoProfile -Command "Get-Content C:\ProgramData\EndpointAgent\logs\endpoint-agent.log -Tail 25"' 2>/dev/null | grep -aE "harness started" | tail -1)
if [ -n "$CERT_EXP" ] && [ "$CERT_EXP" -gt $((NOW + 20*3600)) ] && [ "$SVC" = "Running" ]; then
  say "=== RENEW OK: cert fresh (expires in $(( (CERT_EXP-NOW)/3600 ))h) + service Running${STREAM:+ + device-key stream up}"
  echo "$NOW" > "$MARK"
  echo "$(date -u +%FT%TZ) OK renewed" > "$STATUS"
else
  say "WARN: renew ran but not verified (certExp=${CERT_EXP:-?} svc=${SVC:-?})"
  echo "$(date -u +%FT%TZ) WARN unverified" > "$STATUS"
fi
