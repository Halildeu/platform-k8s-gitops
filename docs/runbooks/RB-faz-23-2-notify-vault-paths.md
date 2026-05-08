# RB-faz-23-2-notify-vault-paths — notification-orchestrator Vault path setup

> **Status**: ACTIVE (Faz 23.9 Step D rewrite — Codex thread `019e08df`
> REVISE absorb)
> **ADR**: ADR-0013-notification-orchestration
> **Vault path**: `kv/platform/notification-orchestrator` (flat, single-path
> convention; matches auth-service / user-service)

Bu runbook ESO ExternalSecret'in Vault'tan okuduğu path'in **operatör tarafından
manuel kurulumunu** anlatır. Path olmadan ExternalSecret SecretSyncedError
verir ve pod boot stub Secret değerleriyle (dev sentinels) çalışır —
ProductionConfigValidator fail-closed.

> **Migration note (2026-05-08, Faz 23.9 Step D)**: Faz 23.2 PR-D.3 split path
> `kv/platform/notify/{db,redaction,webhook,authz,smtp,slack}` over-engineered
> for SMTP/Slack channels not yet wired. Test ExternalSecret stayed in
> `SecretSyncedError` from 2026-05-07 to 2026-05-08. This runbook now reflects
> the flat single-path convention. Existing test/prod Vault data migrated by
> writing to the new path; old split path remains in Vault for one-cycle
> safety, deletion deferred to follow-up rotation PR.

---

## Tetikleyici

- ilk Step D deploy (test veya prod cluster)
- Vault re-init / disaster recovery
- Secret rotation (webhook signing key, redaction pepper, authz API key)

## Ön-koşul

- Vault server erişilebilir (`vault status`)
- Vault token: `vault login` ROOT veya `kv/platform/notification-orchestrator`
  write yetkisi (bootstrap-writer policy)
- ESO ClusterSecretStore `vault-platform-gitops` healthy
- ESO AppRole `eso-runtime` policy includes
  `kv/data/platform/notification-orchestrator` read
  (`bootstrap/vault-policies/common/eso-runtime.hcl`)

## Adımlar

### 1. Vault path setup (ilk deploy)

```bash
# DEV/TEST cluster
docker exec -e VAULT_TOKEN="$ROOT_TOKEN" platform-vault-test \
  vault kv put kv/platform/notification-orchestrator \
    db_username='platform' \
    db_password='<test-db-password>' \
    redaction_pepper="$(openssl rand -hex 32)" \
    webhook_signing_secret="$(openssl rand -hex 32)" \
    authz_internal_api_key="$(openssl rand -hex 32)"

# PROD cluster — strict secret hygiene
docker exec -e VAULT_TOKEN="$ROOT_TOKEN" platform-vault-prod \
  vault kv put kv/platform/notification-orchestrator \
    db_username='platform' \
    db_password="$(vault kv get -field=password kv/platform/postgres-platform-user)" \
    redaction_pepper="$(openssl rand -hex 32)" \
    webhook_signing_secret="$(openssl rand -hex 32)" \
    authz_internal_api_key="$(openssl rand -hex 32)"
```

### 2. ExternalSecret apply (selective, D17 koruma)

ESO bu Secret değişimini 1h refresh interval ile pickup eder; selective apply:

```bash
# Test cluster
kubectl --context k3d-test apply -f kustomize/overlays/test/eso/notify/externalsecret-notify.yaml

# Prod cluster
kubectl --context k3d-prod apply -f kustomize/overlays/prod/eso/notify/externalsecret-notify.yaml

# Verify
kubectl --context k3d-test -n platform-test get externalsecret notification-orchestrator-secrets
# Beklenen: STATUS=SecretSynced READY=True LAST SYNC=<seconds>
```

> **D17 koruma**: `kubectl apply -k overlays/{env}/eso` YASAK — tüm ESO
> ExternalSecret'leri re-apply eder. Tek manifest selective apply yeterli.

### 3. Verification

```bash
# Secret synced status
kubectl --context k3d-test -n platform-test get externalsecret \
  notification-orchestrator-secrets -o jsonpath='{.status.conditions}'
# Beklenen: type=Ready status=True reason=SecretSynced

# Secret ownership (must be ExternalSecret-owned, not direct kubectl)
kubectl --context k3d-test -n platform-test get secret \
  notification-orchestrator-secrets -o jsonpath='{.metadata.ownerReferences}'
# Beklenen: kind=ExternalSecret, name=notification-orchestrator-secrets

# Pod env injection (rolling restart sonrası — yeni pod boot eder)
kubectl --context k3d-test -n platform-test rollout restart deploy/notification-orchestrator
kubectl --context k3d-test -n platform-test exec deploy/notification-orchestrator -- \
  printenv | grep -E 'SPRING_DATASOURCE_USERNAME|NOTIFY_REDACTION_PEPPER' | head -3
```

### 4. Webhook key rotation (Faz 23.7 follow-up)

Rotation runbook (`*_NEXT` + `ACTIVE_KID` registry) henüz bu PR'da yok.
Activation şartı: prod webhook traffic > 0 + receiver registry hazır.
Detay: ayrı `RB-notify-webhook-rotation.md` (TODO). Bu runbook tek-key
state'i kurar; rotation extension follow-up PR ile gelir.

## Rollback

ExternalSecret manifest revert + pod restart:

```bash
# ExternalSecret silersek stub Secret tekrar geçerli olur (dev sentinels);
# pod boot olur ama ProductionConfigValidator fail-closed yakalar
kubectl --context k3d-test -n platform-test delete externalsecret \
  notification-orchestrator-secrets
kubectl --context k3d-test -n platform-test rollout restart deploy/notification-orchestrator
```

> **Live recovery (2026-05-08 deneyim)**: prod cutover'da Vault setup
> deferred edildi → direct `kubectl create secret` ile bootstrap yapıldı.
> Step D ESO migration sırasında ESO `creationPolicy=Owner` byte-identical
> içerikle ownership aldı, pod restart gerek olmadı. Aynı pattern recovery
> için kullanılabilir.

## Audit

Vault audit log her path access kaydeder:
```bash
vault read -format=json sys/audit | jq '.data.audit_devices'
# Audit cevap: vault.audit.log içinde notification-orchestrator ESO read'leri
```

## Yasaklar

- Vault token'ı git'e commit etmek **YASAK**
- Stub Secret değerlerini production'da tutmak **YASAK**
  (ProductionConfigValidator fail-closed yakalar)
- Webhook key rotation'ı sıralı yapmamak **YASAK** (downtime'a neden olur)
- Eski split path (`kv/platform/notify/*`) yazmaya devam etmek **YASAK**
  (Faz 23.9 Step D itibarıyla deprecated)

## Referans

- `kustomize/overlays/prod/eso/notify/externalsecret-notify.yaml` (prod manifest)
- `kustomize/overlays/test/eso/notify/externalsecret-notify.yaml` (test manifest)
- `kustomize/base/apps/notification-orchestrator/secret-stub.yaml` (bootstrap stub)
- `bootstrap/vault-policies/common/eso-runtime.hcl` (`kv/data/platform/notification-orchestrator` read policy)
- ADR-0013-notification-orchestration §6 (security)
- Codex thread `019e08df` (REVISE absorb — flat path consolidation)
