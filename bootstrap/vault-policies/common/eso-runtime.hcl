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

# --- V2.1 Ops-A — Perf alert receiver (A2 isolation path) ---
# Codex `019e2772` post-impl peer review iter-3 P0 blocker absorb:
# ESO `perf-alertmanager-secrets` ExternalSecret bu path'i okuyor;
# policy genişletilmeden owner Vault write tek başına yeterli olmaz (403).
#
# Vault path: kv/platform/perf-alertmanager
#   SLACK_WEBHOOK_URL — #perf-alerts Slack channel incoming webhook
#
# ESO ExternalSecret: kustomize/overlays/{test,prod}/eso/alertmanager/
#   externalsecret-perf-alertmanager.yaml
# Mount: alertmanagerSpec.secrets[] → /etc/alertmanager/secrets/perf-
#   alertmanager-secrets/SLACK_WEBHOOK_URL
#
# D43 fallback ile AYRI Slack kanalı (#perf-alerts vs #alerts-d43-drill).
# Spike Codex `019e267a` A2 isolation tercih + V2.1 Ops-A impl prep PR
# Codex `019e2772` post-impl P0 fix absorb.
path "kv/data/platform/perf-alertmanager" {
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

# --- Metadata read (versioned KV v2 list/describe) ---
path "kv/metadata/platform/*" {
  capabilities = ["list"]
}

path "kv/metadata/gitops/*" {
  capabilities = ["list"]
}
