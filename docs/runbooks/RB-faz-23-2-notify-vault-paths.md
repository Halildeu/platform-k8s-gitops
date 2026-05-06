# RB-faz-23-2-notify-vault-paths — notification-orchestrator Vault path setup

> **Status**: ACTIVE (Faz 23.2 PR-D.3 ESO setup operasyon runbook)
> **ADR**: ADR-0013-notification-orchestration
> **Vault**: kv/platform/notify

Bu runbook ESO ExternalSecret'in Vault'tan okuduğu path'lerin **operatör tarafından
manuel kurulumunu** anlatır. Path olmadan ExternalSecret SecretSyncedError verir
ve pod boot stub Secret değerleriyle (dev sentinels) çalışır — production posture
broken.

---

## Tetikleyici

- ilk PR-D.3 deploy (test veya prod cluster)
- Vault re-init / disaster recovery
- Secret rotation (webhook signing key, redaction pepper, authz API key)
- Faz 23.3.1 SMS adapter aktivasyonu (NetGSM): `kv/platform/notify/sms/netgsm`
  path'ine username/password/msgheader yazımı (operatör — credential-write
  boundary). Aşağıda "Adım 4 — SMS NetGSM aktivasyonu" detayı.

## Ön-koşul

- Vault server erişilebilir (`vault status`)
- Vault token: `vault login` ROOT veya `kv/platform/*` write yetkisi
- ESO ClusterSecretStore `vault-platform-gitops` healthy (mevcut)

## Adımlar

### 1. Vault path setup (ilk deploy)

```bash
# DEV/TEST cluster — daha gevşek değerler kabul edilebilir
vault kv put kv/platform/notify \
  db_username='platform' \
  db_password='<test-db-password>' \
  redaction_pepper='<32-byte random hex>' \
  webhook_signing_secret='<32-byte random hex>' \
  webhook_signing_secret_next='' \
  webhook_active_kid='kid-1' \
  authz_internal_api_key='<32-byte random>'

# PROD cluster — strict secret hygiene
# Tüm değerler operatör tarafından üretilmiş (openssl rand -hex 32) +
# Vault'ta bir kere yazılır + access audited.
vault kv put kv/platform/notify \
  db_username='platform' \
  db_password="$(vault kv get -field=password kv/platform/postgres-platform-user)" \
  redaction_pepper="$(openssl rand -hex 32)" \
  webhook_signing_secret="$(openssl rand -hex 32)" \
  webhook_signing_secret_next='' \
  webhook_active_kid='kid-1' \
  authz_internal_api_key="$(openssl rand -hex 32)"
```

### 2. ExternalSecret apply

ESO bu Secret değişimini 1h refresh interval ile pickup eder; manuel hızlandırma:

```bash
# Test overlay (canonical apply target — base/apps/...ops/ASA path tek-kaynak
# DEĞİL; test cluster'da overlay'in notify/eso dizini reconciliation hedefi):
kubectl --context k3d-test apply -k kustomize/overlays/test/eso/notify
kubectl --context k3d-test -n platform-test get externalsecret notification-orchestrator-secrets

# Sync zorla (annotation rolldown):
kubectl --context k3d-test -n platform-test annotate externalsecret \
  notification-orchestrator-secrets force-sync=$(date +%s) --overwrite
```

### 3. Verification

```bash
# Secret synced status
kubectl --context k3d-test -n platform-test get externalsecret \
  notification-orchestrator-secrets -o jsonpath='{.status.conditions}'

# Beklenen: type=Ready status=True reason=SecretSynced

# Secret data keys (sadece anahtar varlığı, değer YAZMA):
kubectl --context k3d-test -n platform-test get secret \
  notification-orchestrator-secrets -o jsonpath='{.data}' | jq 'keys'

# IMPORTANT (envFrom semantics): çalışan pod env'i Secret update'ten
# etkilenmez. Yeni env var'ları görmek için rolling restart + status wait:
kubectl --context k3d-test -n platform-test rollout restart deploy/notification-orchestrator
kubectl --context k3d-test -n platform-test rollout status deploy/notification-orchestrator

# YENİ pod'da env doğrulama (sadece anahtar varlığı, değer asla print etme):
kubectl --context k3d-test -n platform-test exec deploy/notification-orchestrator -- \
  printenv | grep -oE '^(SPRING_DATASOURCE_USERNAME|NOTIFY_REDACTION_PEPPER)='
```

### 4. SMS NetGSM aktivasyonu (Faz 23.3.1)

NetGSM REST v2 SMS provider için Vault path setup.

**ÖNEMLİ — pre-merge zorunluluk** (Codex review iter-1 P1 absorb):
ExternalSecret `data[].remoteRef` reconcile zamanında zorunlu. Vault path
**hiç yok** ise mevcut `Synced` status `Ready=False` (SecretSyncedError) olur
ve diğer 11 secret key reconcile'ı da bozar. Çözüm: PR merge **öncesinde**
operatör Vault path'ini en azından placeholder değerlerle yaratır. Boş
string seed pattern güvenlidir — adapter username empty olduğu için fail-closed
davranır (DELIVERED yok, FAILED("netgsm credentials missing")), runtime SMS
yok ama ESO sync OK + diğer key'ler hâlâ Ready=True.

```bash
# A) Pre-merge placeholder seed (path olduğunu garantilemek):
vault kv put kv/platform/notify/sms/netgsm \
  username='' \
  password='' \
  msgheader='Notify'

# B) Production aktivasyon (real creds):
# DEV/TEST cluster — NetGSM test/staging account
vault kv put kv/platform/notify/sms/netgsm \
  username='<netgsm-test-username>' \
  password='<netgsm-test-password>' \
  msgheader='Notify'

# PROD cluster — NetGSM production account (operatör credential-write)
vault kv put kv/platform/notify/sms/netgsm \
  username='<netgsm-prod-username>' \
  password='<netgsm-prod-password>' \
  msgheader='<approved sender ID — IYS registered>'
```

ESO sync + verification (envFrom-aware sıra):

```bash
# 1) ESO force-sync (refresh interval beklemeden Vault'tan oku)
kubectl --context k3d-test -n platform-test annotate externalsecret \
  notification-orchestrator-secrets force-sync=$(date +%s) --overwrite

# 2) ExternalSecret status Ready=True doğrula
kubectl --context k3d-test -n platform-test get externalsecret \
  notification-orchestrator-secrets -o jsonpath='{.status.conditions}'

# 3) Secret data keys redacted check (yeni 3 NetGSM anahtarı eklenmiş mi)
kubectl --context k3d-test -n platform-test get secret \
  notification-orchestrator-secrets -o jsonpath='{.data}' | \
  jq 'keys[] | select(test("NOTIFY_ADAPTERS_SMS_NETGSM"))'

# 4) Rolling restart + status wait (envFrom Secret pickup container start'ta)
kubectl --context k3d-test -n platform-test rollout restart deploy/notification-orchestrator
kubectl --context k3d-test -n platform-test rollout status deploy/notification-orchestrator

# 5) YENİ pod'da env injection doğrula (anahtar varlığı, değer print ETME)
kubectl --context k3d-test -n platform-test exec deploy/notification-orchestrator -- \
  printenv | grep -oE '^NOTIFY_ADAPTERS_SMS_NETGSM_(USERNAME|MSGHEADER)='
# Beklenen: USERNAME ve MSGHEADER satırları görünür (PASSWORD print edilmez)
```

**Not (KVKK + IYS uyum)**:
- `msgheader` (sender ID) NetGSM hesabında **kayıtlı + onaylı** olmalı; kayıtsız
  sender ID code 40 (provider FAILED) döner.
- IYS opt-out (consent reddetmiş alıcı) provider code 70 (FAILED) ile döner;
  audit row'da görünür. Pre-send IYS check (Faz 23.3.2) henüz yok — KVKK
  full compliance closure değil; provider-side IYS gate + post-send code 70
  audit izleme bu PR scope'unda yeterli operasyonel posture sayılır.

### 5. Webhook key rotation (operasyon disiplini)

PR-A kid-aware HMAC registry: rotation `webhook_signing_secret_next` ekle, sonra
`webhook_active_kid` bump. ESO refresh + pod restart bağımsız.

```bash
# 1. Yeni key Vault'a write (next slot)
vault kv patch kv/platform/notify webhook_signing_secret_next="$(openssl rand -hex 32)"

# 2. ESO sync + pod restart (next key load; both old + new active for grace)
kubectl annotate externalsecret notification-orchestrator-secrets force-sync=$(date +%s) --overwrite
kubectl rollout restart deploy/notification-orchestrator

# 3. 24h grace sonrası: active kid bump (old key drop, next promote to active)
vault kv patch kv/platform/notify \
  webhook_active_kid=kid-2 \
  webhook_signing_secret="$(vault kv get -field=webhook_signing_secret_next kv/platform/notify)" \
  webhook_signing_secret_next=''

# 4. Final pod restart
kubectl annotate externalsecret notification-orchestrator-secrets force-sync=$(date +%s) --overwrite
kubectl rollout restart deploy/notification-orchestrator
```

## Rollback

ExternalSecret manifest revert + pod restart:

```bash
# ExternalSecret silersek stub Secret tekrar geçerli olur (dev sentinels);
# pod boot olur ama production posture degraded
kubectl --context k3d-test -n platform-test delete externalsecret notification-orchestrator-secrets
kubectl --context k3d-test -n platform-test rollout restart deploy/notification-orchestrator
```

## Audit

Vault audit log her path access kaydeder:
```bash
vault read -format=json sys/audit | jq '.data.audit_devices'
# Audit cevap: vault.audit.log içinde notification-orchestrator ESO read'leri
```

## Yasaklar

- Vault token'ı git'e commit etmek **YASAK**
- Stub Secret değerlerini production'da tutmak **YASAK**
  (ProductionConfigValidator fail-closed yakalar — `dev-only-pepper-not-for-production`
  whitespace check raise eder)
- Webhook key rotation'ı sıralı yapmamak **YASAK** (downtime'a neden olur:
  receivers eski key'le validate eder, biz yeni key ile imzalıyorsak)

## Referans

- **Test overlay** (canonical apply target): `kustomize/overlays/test/eso/notify/externalsecret-notify.yaml`
  (notification-orchestrator-secrets ExternalSecret, 12 data entries: db × 2,
  smtp × 3, redaction × 1, webhook × 1, slack × 1, authz × 1, sms/netgsm × 3 —
  Faz 23.3.1: 9 → 12 transition, +3 NetGSM SMS keys)
- Base secret-stub (pod-startup safety net): `kustomize/base/apps/notification-orchestrator/secret-stub.yaml`
- Base older-pattern ExternalSecret (legacy ops/ dir, not canonical): `kustomize/base/apps/notification-orchestrator/ops/externalsecret.yaml`
- ADR-0013-notification-orchestration §6 (security)
- Vault AppRole + ESO ClusterSecretStore: `kustomize/base/eso/clustersecretstore.yaml`
- NetGSM SMS adapter (Faz 23.3.1): `Halildeu/platform-backend#77`
