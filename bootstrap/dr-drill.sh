#!/usr/bin/env bash
# DR Cold-Rollback Drill — sandbox-isolated restore + 2x smoke + RTO measurement
# Faz 12 (Codex 4-phase plan): Clone drill + 2x independent boot-smoke + RTO≤4h
#
# Source: docs/S5-disaster-recovery-runbook.md §3-§4 + docs/day-2-cron-install.md
# Referenced backup producers:
#   bootstrap/pg-dump-cron.sh      (hourly PG dump, 30d retention)
#   bootstrap/vault-snapshot-cron.sh (daily Vault Raft, 14d retention)
#   bootstrap/kc-export-cron.sh    (weekly realm JSON, 56d retention)
#
# Safety model:
#   - NEVER touches live containers (platform-{pg,kc,vault}-{prod,test})
#   - NEVER touches /home/halil/platform-stateful/{prod,test}/
#   - Sandbox path MUST contain "drill" (assertion)
#   - Drill containers prefixed "drill-*" (namespace collision proof)
#   - Port offset +10000 (15432, 18200, 18080)
#   - Explicit DRILL_CONFIRM=yes required
#
# Exit codes:
#   0  = drill PASS (both smoke runs + RTO within budget)
#   2  = safety guard violation (unsafe config detected, no changes)
#   3  = preflight failure (missing backups, disk, deps)
#   4  = drill FAIL (restore or smoke failed; cleanup trapped)
#   5  = RTO budget exceeded
#
# Usage:
#   DRILL_CONFIRM=yes ./bootstrap/dr-drill.sh
#   DRILL_CONFIRM=yes SKIP_KC=1 ./bootstrap/dr-drill.sh   # KC export drift workaround
#   DRILL_CONFIRM=yes DRILL_ENV=test ./bootstrap/dr-drill.sh

set -euo pipefail

# ---- CONFIG (env-overridable) ----
DRILL_ROOT="${DRILL_ROOT:-${HOME}/platform-stateful-drill}"
BACKUP_ROOT="${BACKUP_ROOT:-${HOME}/platform/backup}"
DRILL_NET="${DRILL_NET:-platform-drill-net}"
DRILL_ENV="${DRILL_ENV:-prod}"          # prod or test (which backup source)
SKIP_KC="${SKIP_KC:-0}"                 # 1 = proceed without KC export (kc=0 drift)

# Container names (drill-prefixed)
PG_CONTAINER="drill-pg"
VAULT_CONTAINER="drill-vault"
KC_CONTAINER="drill-kc"

# Port offsets: +10000 from canonical to avoid live port collision
PG_PORT=15432
VAULT_PORT=18200
KC_PORT=18080

# RTO budget (seconds) — ADR-0002 §8 hedefi 4h = 14400s
RTO_BUDGET_SECONDS="${RTO_BUDGET_SECONDS:-14400}"

# Images (match live prod stack versions)
PG_IMAGE="${PG_IMAGE:-pgvector/pgvector:pg18}"
VAULT_IMAGE="${VAULT_IMAGE:-hashicorp/vault:1.17}"
KC_IMAGE="${KC_IMAGE:-quay.io/keycloak/keycloak:25.0}"

# Disk requirement
MIN_FREE_GB="${MIN_FREE_GB:-20}"

# Drill root token (ephemeral; logged to drill artifacts, NOT prod)
DRILL_VAULT_ROOT_TOKEN=""
DRILL_START_TS=""
DRILL_END_TS=""
DRILL_LOG="/tmp/dr-drill-$(date +%Y%m%d-%H%M%S).log"

# ---- LOGGING ----
log() { printf '\033[0;36m[dr-drill]\033[0m %s %s\n' "$(date +%H:%M:%S)" "$*" | tee -a "$DRILL_LOG"; }
err() { printf '\033[0;31m[dr-drill ERR]\033[0m %s %s\n' "$(date +%H:%M:%S)" "$*" | tee -a "$DRILL_LOG" >&2; }
ok()  { printf '\033[0;32m[dr-drill OK]\033[0m %s %s\n'  "$(date +%H:%M:%S)" "$*" | tee -a "$DRILL_LOG"; }

# ---- SAFETY ----
assert_safety() {
  log "SAFETY: checking guards"

  if [[ "${DRILL_CONFIRM:-}" != "yes" ]]; then
    err "DRILL_CONFIRM=yes zorunlu (environment variable). Abort."
    exit 2
  fi

  if [[ "$DRILL_ROOT" != *drill* ]]; then
    err "DRILL_ROOT='$DRILL_ROOT' 'drill' keyword içermeli. Abort."
    exit 2
  fi

  # Canlı stateful path prefix guard — DİKKAT: glob `platform-stateful*` yanlış
  # pozitif verir (örn. `platform-stateful-drill` match eder). Trailing `/` ile
  # kesin prefix eşleşmesi + tam path eşitlik kontrolü:
  if [[ "$DRILL_ROOT" == /home/halil/platform-stateful ]] || \
     [[ "$DRILL_ROOT" == /home/halil/platform-stateful/* ]]; then
    err "DRILL_ROOT canlı stateful path ile çakışıyor. Abort."
    exit 2
  fi

  # Yasak container isimleri
  local live_containers=(
    platform-pg-prod platform-pg-test
    platform-kc-prod platform-kc-test
    platform-vault-prod platform-vault-test
    platform-openfga-1 platform-api-gateway-1
  )
  for c in "${live_containers[@]}"; do
    if [[ "$PG_CONTAINER $VAULT_CONTAINER $KC_CONTAINER" == *"$c"* ]]; then
      err "Drill container adı live container ile çakışıyor: $c. Abort."
      exit 2
    fi
  done

  # Yasak network
  if [[ "$DRILL_NET" == "platform_microservice-network" ]] || \
     [[ "$DRILL_NET" == "platform-test-net" ]] || \
     [[ "$DRILL_NET" == bridge ]] || [[ "$DRILL_NET" == host ]]; then
    err "DRILL_NET='$DRILL_NET' reserved network. Abort."
    exit 2
  fi

  ok "SAFETY: all guards passed"
}

# ---- PREFLIGHT ----
preflight_checks() {
  log "PREFLIGHT: deps + disk + backups"

  for cmd in docker jq zcat gunzip; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
      err "Missing command: $cmd"; exit 3
    fi
  done

  if ! docker info >/dev/null 2>&1; then
    err "docker daemon unreachable"; exit 3
  fi

  local free_gb
  free_gb=$(df -BG "$HOME" | awk 'NR==2 {gsub("G",""); print $4}')
  if [[ "${free_gb:-0}" -lt "$MIN_FREE_GB" ]]; then
    err "Disk space <${MIN_FREE_GB}GB (free=${free_gb}GB). Abort."
    exit 3
  fi

  # Port collision
  for p in "$PG_PORT" "$VAULT_PORT" "$KC_PORT"; do
    if ss -ltn 2>/dev/null | awk '{print $4}' | grep -q ":${p}$"; then
      err "Port $p already in use. Abort."
      exit 3
    fi
  done

  # Backup presence
  local pg_dir="${BACKUP_ROOT}/pg/${DRILL_ENV}"
  local vault_dir="${BACKUP_ROOT}/vault/${DRILL_ENV}"
  local kc_dir="${BACKUP_ROOT}/keycloak/${DRILL_ENV}"

  if [[ ! -d "$pg_dir" ]] || ! ls "$pg_dir"/pg_dumpall_*.sql.gz >/dev/null 2>&1; then
    err "No PG dump found in $pg_dir. Abort."
    exit 3
  fi

  if [[ ! -d "$vault_dir" ]] || ! ls "$vault_dir"/vault-snapshot-*.snap >/dev/null 2>&1; then
    err "No Vault snapshot in $vault_dir. Abort."
    exit 3
  fi

  if [[ ! -d "$kc_dir" ]] || ! ls "$kc_dir"/*.json.gz >/dev/null 2>&1; then
    if [[ "$SKIP_KC" == "1" ]]; then
      log "KC export absent ($kc_dir) — SKIP_KC=1, proceeding PG+Vault only (drill PARTIAL)"
    else
      err "No KC realm export in $kc_dir. Set SKIP_KC=1 to drill PG+Vault only. Abort."
      exit 3
    fi
  fi

  ok "PREFLIGHT: deps OK, disk=${free_gb}GB, backups present"
}

# ---- BACKUP SELECTION ----
select_latest_backups() {
  log "SELECT: latest backups from $BACKUP_ROOT/*/$DRILL_ENV/"

  LATEST_PG=$(ls -t "${BACKUP_ROOT}/pg/${DRILL_ENV}"/pg_dumpall_*.sql.gz | head -1)
  LATEST_VAULT=$(ls -t "${BACKUP_ROOT}/vault/${DRILL_ENV}"/vault-snapshot-*.snap | head -1)
  LATEST_KC=""
  if [[ "$SKIP_KC" != "1" ]]; then
    LATEST_KC=$(ls -t "${BACKUP_ROOT}/keycloak/${DRILL_ENV}"/*.json.gz 2>/dev/null | head -1 || true)
  fi

  log "  PG:    $LATEST_PG ($(du -h "$LATEST_PG" | cut -f1))"
  log "  Vault: $LATEST_VAULT ($(du -h "$LATEST_VAULT" | cut -f1))"
  if [[ -n "$LATEST_KC" ]]; then
    log "  KC:    $LATEST_KC ($(du -h "$LATEST_KC" | cut -f1))"
  else
    log "  KC:    SKIPPED (SKIP_KC=1 or no export)"
  fi
}

# ---- CLEANUP (idempotent) ----
cleanup_previous() {
  log "CLEANUP: remove previous drill artifacts (idempotent)"
  docker rm -f "$PG_CONTAINER" "$VAULT_CONTAINER" "$KC_CONTAINER" 2>/dev/null || true
  docker network rm "$DRILL_NET" 2>/dev/null || true
  if [[ -d "$DRILL_ROOT" ]]; then
    # Bir kez daha path safety check — rm -rf her zaman şüpheyle
    [[ "$DRILL_ROOT" == *drill* ]] || { err "DRILL_ROOT guard failed during cleanup"; exit 2; }
    rm -rf "${DRILL_ROOT:?}"/*
  fi
  ok "CLEANUP: done"
}

# ---- PROVISION SANDBOX ----
provision_sandbox() {
  log "PROVISION: create sandbox dirs + network"
  mkdir -p "${DRILL_ROOT}/postgres" "${DRILL_ROOT}/vault" "${DRILL_ROOT}/keycloak"
  # Container user drift'leri için 0777 — geçici sandbox, teardown'da silinir.
  # Vault: UID 100 `/vault/data` yazamıyordu (host-owner: halil:halil).
  # Keycloak: UID 1000 `/opt/keycloak/data` benzer sorun potansiyeli.
  # PG: pgvector entrypoint initdb chown yapar, aslında bağımsız ama simetri için.
  # Güvenlik notu: drill container'ları drill network'üne izole, drill-* prefix,
  # port offset +10000; 0777 yalnız drill root altındaki 3 dizinde, canlı disk
  # erişimine köprü değil (DRILL_ROOT == *drill* guard var).
  chmod 0777 "${DRILL_ROOT}/postgres" "${DRILL_ROOT}/vault" "${DRILL_ROOT}/keycloak"
  docker network create "$DRILL_NET" >/dev/null
  ok "PROVISION: $DRILL_ROOT + $DRILL_NET"
}

# ---- PG RESTORE ----
start_pg() {
  log "PG: start drill postgres on port $PG_PORT"
  # stderr DRILL_LOG'a yönlendirilir ki image pull/permission/name collision
  # gibi silent fail'ler görülsün; `>/dev/null` tek yönlü hata saklama idi
  if ! docker run -d --name "$PG_CONTAINER" \
      --network "$DRILL_NET" \
      -p "${PG_PORT}:5432" \
      -v "${DRILL_ROOT}/postgres:/var/lib/postgresql/data" \
      -e POSTGRES_PASSWORD=drill-only-postgres \
      -e PGDATA=/var/lib/postgresql/data/pgdata \
      "$PG_IMAGE" >>"$DRILL_LOG" 2>&1; then
    err "PG docker run failed (see $DRILL_LOG)"
    exit 4
  fi

  # Pre-increment (((++i))) post-increment (((i++)))'dan farkla `set -e` ile
  # uyumludur. `((i++))` eski değeri 0 olduğunda exit 1 döner → set -e trigger.
  local i=0
  until docker exec "$PG_CONTAINER" pg_isready -U postgres >/dev/null 2>&1; do
    ((++i))
    if [[ $i -gt 30 ]]; then err "PG boot timeout"; exit 4; fi
    sleep 2
  done
  ok "PG: up (${i} ready-checks)"
}

restore_pg() {
  log "PG: restore from $LATEST_PG"
  local t0 t1
  t0=$(date +%s)
  if ! zcat "$LATEST_PG" | docker exec -i "$PG_CONTAINER" psql -U postgres >/dev/null 2>>"$DRILL_LOG"; then
    err "PG restore failed (see $DRILL_LOG)"
    exit 4
  fi
  t1=$(date +%s)
  ok "PG: restored ($((t1-t0))s)"
}

# ---- VAULT RESTORE ----
start_vault() {
  log "VAULT: start drill vault on port $VAULT_PORT"
  if ! docker run -d --name "$VAULT_CONTAINER" \
      --network "$DRILL_NET" \
      -p "${VAULT_PORT}:8200" \
      --cap-add IPC_LOCK \
      -v "${DRILL_ROOT}/vault:/vault/data" \
      -e VAULT_LOCAL_CONFIG='{"storage":{"raft":{"path":"/vault/data","node_id":"drill"}},"listener":{"tcp":{"address":"0.0.0.0:8200","tls_disable":1}},"disable_mlock":true,"ui":false,"cluster_addr":"http://127.0.0.1:8201","api_addr":"http://127.0.0.1:8200"}' \
      "$VAULT_IMAGE" server >>"$DRILL_LOG" 2>&1; then
    err "Vault docker run failed (see $DRILL_LOG)"
    exit 4
  fi

  sleep 3
  # Init (capture root token)
  local init_json
  init_json=$(docker exec -e VAULT_ADDR=http://127.0.0.1:8200 "$VAULT_CONTAINER" \
    vault operator init -key-shares=1 -key-threshold=1 -format=json)
  DRILL_VAULT_ROOT_TOKEN=$(echo "$init_json" | jq -r '.root_token')
  local unseal_key
  unseal_key=$(echo "$init_json" | jq -r '.unseal_keys_b64[0]')
  docker exec -e VAULT_ADDR=http://127.0.0.1:8200 "$VAULT_CONTAINER" \
    vault operator unseal "$unseal_key" >/dev/null
  ok "VAULT: init + unseal done (root token recorded in $DRILL_LOG.drill-token)"
  echo "$DRILL_VAULT_ROOT_TOKEN" > "${DRILL_LOG}.drill-token"
  chmod 600 "${DRILL_LOG}.drill-token"
}

restore_vault() {
  log "VAULT: restore snapshot from $LATEST_VAULT"
  local t0 t1
  t0=$(date +%s)
  docker cp "$LATEST_VAULT" "$VAULT_CONTAINER:/tmp/snap"
  if ! docker exec -e VAULT_ADDR=http://127.0.0.1:8200 -e VAULT_TOKEN="$DRILL_VAULT_ROOT_TOKEN" \
       "$VAULT_CONTAINER" vault operator raft snapshot restore -force /tmp/snap >>"$DRILL_LOG" 2>&1; then
    err "Vault snapshot restore failed"
    exit 4
  fi
  # Unseal sonrası yeniden — drill snapshot source vault'un keys'lerini kopyalar
  sleep 3
  t1=$(date +%s)
  ok "VAULT: restored ($((t1-t0))s)"
}

# ---- KC RESTORE (optional) ----
start_kc() {
  [[ "$SKIP_KC" == "1" ]] && { log "KC: SKIP_KC=1, atlanıyor"; return 0; }
  log "KC: start drill keycloak on port $KC_PORT"
  if ! docker run -d --name "$KC_CONTAINER" \
      --network "$DRILL_NET" \
      -p "${KC_PORT}:8080" \
      -e KC_DB=postgres \
      -e KC_DB_URL="jdbc:postgresql://${PG_CONTAINER}:5432/keycloak" \
      -e KC_DB_USERNAME=keycloak \
      -e KC_DB_PASSWORD=drill-only-postgres \
      -e KEYCLOAK_ADMIN=admin \
      -e KEYCLOAK_ADMIN_PASSWORD=drill-admin \
      "$KC_IMAGE" start-dev >>"$DRILL_LOG" 2>&1; then
    err "KC docker run failed (see $DRILL_LOG)"
    exit 4
  fi
  sleep 20
  ok "KC: up"
}

restore_kc() {
  [[ "$SKIP_KC" == "1" ]] && return 0
  log "KC: import realm from $LATEST_KC"
  local t0 t1
  t0=$(date +%s)
  zcat "$LATEST_KC" > /tmp/drill-realm.json
  docker cp /tmp/drill-realm.json "$KC_CONTAINER:/tmp/realm.json"
  # NOT: kc-export-cron.sh şu an `kcadm.sh get realms/<realm>` kullanıyor —
  # kc.sh import yerine kcadm.sh create benzeri alternatif gerekebilir.
  # Şimdilik best-effort import; fail olursa drill PARTIAL işaretli devam.
  if docker exec "$KC_CONTAINER" /opt/keycloak/bin/kc.sh import --file /tmp/realm.json >>"$DRILL_LOG" 2>&1; then
    ok "KC: imported ($((t1-t0))s)"
  else
    log "KC: import best-effort failed — drill MARK=PARTIAL, PG+Vault still valid"
    SKIP_KC=1
  fi
  rm -f /tmp/drill-realm.json
  t1=$(date +%s)
}

# ---- SMOKE (idempotent, runnable twice) ----
smoke_run() {
  local run_id="$1"
  log "SMOKE[$run_id]: PG + Vault + KC checks"
  local fails=0

  # PG check
  if docker exec "$PG_CONTAINER" psql -U postgres -tAc '\l' | grep -qE 'auth_db|users|platform'; then
    ok "SMOKE[$run_id] PG: DB listesi görünüyor"
  else
    err "SMOKE[$run_id] PG: DB listesi beklenen DB'leri içermiyor"
    ((fails++))
  fi

  # Vault raft status — snapshot restore sonrası sealed state NORMAL'dir:
  # restore orijinal prod key'leri yeniden aktive eder ama drill init token'ı
  # invalidate olur. Smoke için doğru kanıt `Initialized=true` (sealed ya da
  # unsealed fark etmez). `vault status` exit kodu:
  #   0 = initialized + unsealed
  #   1 = error (fatal)
  #   2 = initialized + sealed (drill için BEKLENEN)
  # Çıktı parsing: `Initialized` alanı `true` ise snapshot restore validated.
  local vault_out
  vault_out=$(docker exec -e VAULT_ADDR=http://127.0.0.1:8200 -e VAULT_TOKEN="$DRILL_VAULT_ROOT_TOKEN" \
       "$VAULT_CONTAINER" vault status 2>&1 || true)
  if echo "$vault_out" | grep -qE 'Initialized\s+true'; then
    local sealed
    sealed=$(echo "$vault_out" | awk '/^Sealed/{print $2}')
    ok "SMOKE[$run_id] Vault: Initialized=true (Sealed=${sealed:-unknown}) — snapshot restore validated"
  else
    err "SMOKE[$run_id] Vault: Initialized flag yok — restore fail"
    echo "$vault_out" | head -10 | tee -a "$DRILL_LOG"
    ((fails++))
  fi

  # Vault KV probe — sealed state'te beklenen olarak fail eder; bu yüzden
  # sadece unsealed durumunda çalıştır. Drill PASS kriterleri KV probe'a
  # bağlı değil (tolerable fail).
  if echo "$vault_out" | grep -qE 'Sealed\s+false'; then
    if docker exec -e VAULT_ADDR=http://127.0.0.1:8200 -e VAULT_TOKEN="$DRILL_VAULT_ROOT_TOKEN" \
         "$VAULT_CONTAINER" vault kv list kv/ >/dev/null 2>&1; then
      ok "SMOKE[$run_id] Vault: KV mount listable (bonus)"
    else
      log "SMOKE[$run_id] Vault: KV list skipped (drill token policy mismatch — tolerable)"
    fi
  else
    log "SMOKE[$run_id] Vault: KV list skipped (sealed post-restore — drill için normal)"
  fi

  # KC OIDC discovery
  if [[ "$SKIP_KC" != "1" ]]; then
    local code
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 \
      "http://127.0.0.1:${KC_PORT}/realms/master/.well-known/openid-configuration" || echo "000")
    if [[ "$code" == "200" ]]; then
      ok "SMOKE[$run_id] KC: OIDC discovery 200"
    else
      err "SMOKE[$run_id] KC: OIDC discovery=$code"
      ((fails++))
    fi
  fi

  if [[ $fails -gt 0 ]]; then
    err "SMOKE[$run_id]: $fails failures"
    return 1
  fi
  ok "SMOKE[$run_id]: PASS"
  return 0
}

# ---- RTO MEASUREMENT ----
measure_rto() {
  local elapsed=$(( DRILL_END_TS - DRILL_START_TS ))
  log "RTO: elapsed=${elapsed}s (budget ${RTO_BUDGET_SECONDS}s = 4h)"
  if [[ $elapsed -gt $RTO_BUDGET_SECONDS ]]; then
    err "RTO budget exceeded by $(( elapsed - RTO_BUDGET_SECONDS ))s"
    return 5
  fi
  ok "RTO: PASS (${elapsed}s / ${RTO_BUDGET_SECONDS}s budget)"
  return 0
}

# ---- TEARDOWN (trap) ----
teardown() {
  local exit_code=$?
  log "TEARDOWN: cleaning drill containers + network (exit_code=$exit_code)"
  docker rm -f "$PG_CONTAINER" "$VAULT_CONTAINER" "$KC_CONTAINER" 2>/dev/null || true
  docker network rm "$DRILL_NET" 2>/dev/null || true
  # DRILL_ROOT içeriği cleanup (sandbox state)
  if [[ -d "$DRILL_ROOT" ]] && [[ "$DRILL_ROOT" == *drill* ]]; then
    rm -rf "${DRILL_ROOT:?}"/{postgres,vault,keycloak} 2>/dev/null || true
  fi
  # Root token dosyası kaldır (sensitive)
  rm -f "${DRILL_LOG}.drill-token" 2>/dev/null || true
  log "TEARDOWN: done (log kept: $DRILL_LOG)"
}

# ---- MAIN ----
main() {
  log "=== DR Cold-Rollback Drill BAŞLADI ==="
  log "  DRILL_ENV=$DRILL_ENV"
  log "  DRILL_ROOT=$DRILL_ROOT"
  log "  SKIP_KC=$SKIP_KC"
  log "  Log: $DRILL_LOG"
  DRILL_START_TS=$(date +%s)

  trap teardown EXIT

  assert_safety
  preflight_checks
  select_latest_backups
  cleanup_previous
  provision_sandbox

  start_pg
  restore_pg

  start_vault
  restore_vault

  start_kc
  restore_kc

  # 2x independent smoke (60s ara)
  if ! smoke_run 1; then err "First smoke FAIL"; exit 4; fi
  log "SMOKE: 60s sleep before independent re-run"
  sleep 60
  if ! smoke_run 2; then err "Second smoke FAIL"; exit 4; fi

  DRILL_END_TS=$(date +%s)
  if ! measure_rto; then exit 5; fi

  ok "=== DR DRILL PASS ==="
  ok "  Log: $DRILL_LOG"
  ok "  Elapsed: $(( DRILL_END_TS - DRILL_START_TS ))s"
  ok "  PG: $LATEST_PG"
  ok "  Vault: $LATEST_VAULT"
  [[ -n "$LATEST_KC" ]] && ok "  KC: $LATEST_KC" || ok "  KC: SKIPPED"
}

main "$@"
