# Vault Policy — eso-runtime
# ExternalSecrets Operator AppRole için okuma yetkisi.
# Apply: vault policy write eso-runtime bootstrap/vault-policies/eso-runtime.hcl
#
# Prereq: Vault KV v2 mount 'kv' aktif (vault secrets enable -version=2 -path=kv kv)
# AppRole: vault write auth/approle/role/eso-runtime token_policies=eso-runtime
#
# Docs: docs/S2-B1-vault-property-matrix.md (tüm path + property tablosu)

# --- Platform servis secret'ları (ESO per-service ExternalSecret'ler) ---
path "kv/data/platform/auth-service" {
  capabilities = ["read"]
}

path "kv/data/platform/user-service" {
  capabilities = ["read"]
}

path "kv/data/platform/variant-service" {
  capabilities = ["read"]
}

path "kv/data/platform/core-data-service" {
  capabilities = ["read"]
}

path "kv/data/platform/report-service" {
  capabilities = ["read"]
}

path "kv/data/platform/schema-service" {
  capabilities = ["read"]
}

path "kv/data/platform/permission-service" {
  capabilities = ["read"]
}

# --- Faz 22.1.1b BE-001 endpoint-admin-service (missing-policy hot-fix 2026-05-10) ---
# Service introduced 2026-04-29 (Faz 22.1.1b BE-001) but the eso-runtime policy
# was never updated to grant ESO read access to its kv/data/platform path. The
# omission caused a silent 11-day outage: ESO sync returned 403 since first
# deploy, the K8s Secret never landed, the pod entered CrashLoopBackOff every
# time it was restarted (most recently during the 2026-05-09 cluster operations).
# Same shape as auth-service / report-service / etc. — single flat path, 4 keys
# (db_username, db_password, enrollment_token_pepper, device_secret_encryption_key).
# Live patch applied to vault-test 2026-05-10T17:30Z; this file makes the change
# canonical so the next vault-bootstrap drill cannot regress.
path "kv/data/platform/endpoint-admin-service" {
  capabilities = ["read"]
}

# --- Faz 22.6 endpoint-admin-remote-bridge activation path ---
# Dedicated broker-scoped secret path for the outbound mTLS remote-ops broker.
# Consumed by kustomize/overlays/test/activation/endpoint-admin-remote-bridge.
# This is deliberately separate from endpoint-admin-service because the broker
# receives only least-priv DB/OpenFGA/PKI/attestation/step-up/signing material,
# not the primary endpoint-admin service's enrollment/admin secrets.
path "kv/data/platform/endpoint-admin-remote-bridge" {
  capabilities = ["read"]
}

# --- Faz 24 #410/#1615 meeting-service (foundation deploy 2026-06-17) ---
# ExternalSecret reads kv/platform/meeting-service with 2 keys (db_username,
# db_password). Same flat-path convention as endpoint-admin/auth/report.
# Without this grant ESO sync returns 403 → K8s Secret never lands →
# pod stuck ContainerCreating (envFrom optional:false). Live patch applied
# to vault-test alongside; this file keeps it canonical (bootstrap-drill safe).
path "kv/data/platform/meeting-service" {
  capabilities = ["read"]
}

# --- Faz 24 #411/#1615 transcript-service (foundation deploy 2026-06-17) ---
# ExternalSecret reads kv/platform/transcript-service with 2 keys (db_username,
# db_password). Same flat-path convention as meeting/endpoint-admin/auth/report.
# Without this grant ESO sync returns 403 → K8s Secret never lands →
# pod stuck ContainerCreating (envFrom optional:false). Live patch applied
# to vault-test alongside; this file keeps it canonical (bootstrap-drill safe).
path "kv/data/platform/transcript-service" {
  capabilities = ["read"]
}

# --- Faz 24 #1249/#1615 audit-event-consumer-service (KVKK audit pipeline) ---
# ExternalSecret reads kv/platform/audit-event-consumer-service with 3 keys
# (db_username, db_password, redis_password — same flat-path convention as
# meeting/transcript/endpoint-admin/auth). redis_password matches the
# host-compose/redis-streams requirepass (the audio-gateway producer uses the
# same value via kv/platform/audio-gateway-service). Without this grant ESO sync
# returns 403 → K8s Secret never lands → pod stuck ContainerCreating
# (envFrom optional:false). Live patch applied to vault-test alongside; this
# file keeps it canonical (bootstrap-drill safe).
path "kv/data/platform/audit-event-consumer-service" {
  capabilities = ["read"]
}

# --- Faz 23.9 Step D notification-orchestrator (flat path; auth-service convention) ---
# Codex thread 019e08df REVISE absorb: ExternalSecret reads kv/platform/notification-
# orchestrator with 5 keys (db_username, db_password, webhook_signing_secret,
# authz_internal_api_key, redaction_pepper). Future SMTP/Slack additions extend the
# same path with extra properties; no need to split until rotation policies diverge.
path "kv/data/platform/notification-orchestrator" {
  capabilities = ["read"]
}

# --- Faz 23.2.D T1.4 D43 outage fallback (Codex 019e0dea iter-2 AGREE-with-revisions) ---
# notification-orchestrator down olduğunda Alertmanager bunu Slack/SMTP'ye direct
# göndersin diye AYRI credential set. Orchestrator path'i ile aynı SMTP server, ama
# AYRI SMTP user (alertmanager-fallback@) — bağımsız rotation. Orchestrator path
# compromise olsa bile fallback kanalı sağ kalır (security defense-in-depth).
#
# 5 keys (operator init):
#   SLACK_WEBHOOK_URL — Alertmanager direct slack receiver
#   SMTP_HOST — fallback SMTP server (orchestrator ile aynı server)
#   SMTP_PORT — 587 (orchestrator ile aynı)
#   SMTP_USER — alertmanager-fallback@... (AYRI kullanıcı)
#   SMTP_PASSWORD — fallback user'a ait şifre
#
# ESO ExternalSecret: kustomize/overlays/{test,prod}/eso/alertmanager/
#   externalsecret-alertmanager-fallback.yaml
# Mount: alertmanagerSpec.secrets[] → /etc/alertmanager/secrets/alertmanager-
#   fallback-secrets/<key>
#
# Codex iter-2 absorb: ayrı `alertmanager-runtime` policy DEĞİL — eso-runtime
# extend daha temiz (MVP). Ayrı AppRole/CSS gelecek SoD hardening (T1.4 scope dışı).
path "kv/data/platform/alertmanager-fallback" {
  capabilities = ["read"]
}

# --- V2.1 Ops-A — Perf alert receiver (A2 isolation path; ADR-0029 Hibrit D Teams primary) ---
# ADR-0029 Hibrit D 2026-05-27 — Microsoft Teams Power Automate workflow primary
# canlı path (kullanıcı kararı "Slack altyapısını bozma + Teams kullan"; Codex
# `019e6b24` REVISE→AGREE strategic chain absorb). Slack pattern dormant
# asset-preserved (multi-tenant başka tenants için reactivation chain).
#
# Original: Codex `019e2772` post-impl peer review iter-3 P0 blocker absorb:
# ESO `perf-alertmanager-teams-secrets` ExternalSecret bu path'i okuyor;
# policy genişletilmeden owner Vault write tek başına yeterli olmaz (403).
#
# Vault path: kv/platform/perf-alertmanager
#   TEAMS_WEBHOOK_URL — Microsoft Teams Power Automate workflow webhook (active; ADR-0029 D1)
#   SLACK_WEBHOOK_URL — multi-tenant başka tenants için dormant (ADR-0029 D2; RB-perf-alerts-slack-reactivation-chain.md)
#
# ESO ExternalSecret: kustomize/overlays/{test,prod}/eso/alertmanager/
#   externalsecret-perf-alertmanager-teams.yaml (active Teams)
#   externalsecret-perf-alertmanager.yaml.disabled.template (dormant Slack)
# Mount: alertmanagerSpec.secrets[] → /etc/alertmanager/secrets/perf-
#   alertmanager-teams-secrets/TEAMS_WEBHOOK_URL
#
# D43 fallback (ADR-0027 Hibrit C — SMTP-only primary + Teams dormant) ile AYRI
# infrastructure (kv/platform/alertmanager-fallback vs kv/platform/perf-alertmanager).
# Spike Codex `019e267a` A2 isolation tercih + V2.1 Ops-A impl prep PR
# Codex `019e2772` post-impl P0 fix absorb + ADR-0029 Hibrit D pivot Codex
# `019e6b24` REVISE→AGREE chain (4-iter peer review).
path "kv/data/platform/perf-alertmanager" {
  capabilities = ["read"]
}

# --- Credential consolidation Faz A — shared `platform` PG role canonical path ---
# docs/architecture/runtime/credential-consolidation-plan.md §4-§5 (Codex 019e3386).
# 7 platform-role services (auth / user / core-data / variant / permission /
# notification-orchestrator / endpoint-admin) will repoint SPRING_DATASOURCE_
# USERNAME/PASSWORD to this single canonical path, eliminating the per-service
# db_password drift class that caused the D1.1c auth-service silent outage.
# P0 precondition (plan §5): without this allowlist entry ESO gets a 403 on the
# canonical path → Secret sync fail. Added in PR-0 BEFORE any service repoint
# (plan §6 sequencing: policy gate first, runtime repoint = separate sprint).
# Service-specific secrets (JWT keys, keycloak_client_secret, peppers, internal
# API keys) stay on the existing kv/data/platform/<svc> paths — unchanged.
path "kv/data/platform/pg-platform-role" {
  capabilities = ["read"]
}

# --- OpenFGA Store + Model ID (D-008 runtime kontrat) ---
path "kv/data/platform/openfga" {
  capabilities = ["read"]
}

# --- D31 opsiyonel MSSQL external (report/schema yorumlu ES) ---
path "kv/data/platform/mssql-external" {
  capabilities = ["read"]
}

# --- S2-B3 smoke-client bearer token (blackbox allow probe) ---
path "kv/data/platform/keycloak/smoke-client" {
  capabilities = ["read"]
}

# --- GHCR pull token (ghcr-pull ExternalSecret) ---
path "kv/data/gitops/ghcr-token" {
  capabilities = ["read"]
}

# --- Faz 24 audio-gateway-service (Aşama-2 staging — platform-ai#151, gitops#1447) ---
# SPRING_DATA_REDIS_PASSWORD (host-compose/redis-streams requirepass ile aynı;
# seed: docs/runbooks/redis-streams-staging-sw.md §1)
path "kv/data/platform/audio-gateway-service" {
  capabilities = ["read"]
}

# --- remote-write-bridge basic auth (gitops#1459) ---
# Test Prometheus remoteWrite basicAuth credential'ı (username/password;
# host-compose/remote-write-bridge htpasswd ile aynı parola — seed README §1).
# Tüketici: monitoring ns ExternalSecret remote-write-bridge-auth
# (kustomize/base/monitoring-test-only).
path "kv/data/platform/remote-write-bridge" {
  capabilities = ["read"]
}

# --- redis-streams-exporter read-only ACL user (gitops#1457) ---
# Exporter'ın ayrı read-only Redis user'ı (username=exporter + password;
# host-compose/redis-streams aclfile ile aynı parola). audio-gateway'in
# default-user parolasından bağımsız rotation. Tüketici: platform-test ns
# ExternalSecret redis-streams-exporter-secrets.
path "kv/data/platform/redis-streams-exporter" {
  capabilities = ["read"]
}

# --- Faz 24 #1250 audit-retention-worker (audit-archive 7yr WORM — ADR-0042) ---
# ExternalSecret audit-retention-worker-secrets reads kv/platform/audit-retention-worker
# (minio_access_key + minio_secret_key — least-privilege MinIO svcacct for the
# audit-archive bucket; non-secret endpoint/bucket/region carried alongside).
# Same flat-path convention as audit-event-consumer / redis-streams-exporter.
# Without this grant ESO sync returns 403 → Secret never lands → the C-slice
# audit-retention-worker CronJob can't start. Live patch applied to vault-test
# alongside; this file keeps it canonical (bootstrap-drill safe).
path "kv/data/platform/audit-retention-worker" {
  capabilities = ["read"]
}

# --- Faz 24 PR-obs-02 audit-archive-exporter (ADR-0042 durable metrics) ---
# ExternalSecret audit-archive-exporter-secrets reads
# kv/platform/audit-archive-exporter (db_username + db_password) for the
# dedicated read-only Postgres exporter role. Without this grant ESO sync
# returns 403 -> Secret never lands -> audit-archive-exporter remains
# CreateContainerConfigError/Degraded.
path "kv/data/platform/audit-archive-exporter" {
  capabilities = ["read"]
}

# --- Metadata read (versioned KV v2 list/describe) ---
path "kv/metadata/platform/*" {
  capabilities = ["list"]
}

path "kv/metadata/gitops/*" {
  capabilities = ["list"]
}
