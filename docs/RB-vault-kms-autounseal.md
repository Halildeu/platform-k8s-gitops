# RB-vault-kms-autounseal — Vault KMS Auto-Unseal Runbook (P1.10)

ID: RB-vault-kms-autounseal
Service: vault-cluster (compose stateful tier, ADR-0002 §0.5 D6)
Status: Canonical (gitops authoritative)
Owner: @team/platform

> **Provenance:** platform-ssot `docs/04-operations/RUNBOOKS/RB-vault-kms-autounseal.md` → migrated as-is (Faz 18.4 Phase 1). D8 Aşama 2 KMS autounseal hedefi için referans.

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

Prod Vault'un cloud KMS ile auto-unseal edilmesi. Shamir seal'de Vault boot'u her restart sonrası **manuel unseal** gerektirir (n-of-m key thresholds). Prod otomasyonu için bu:

- **Availability riski:** Vault restart = API down = tüm servisler secret fetch edemez.
- **Güvenlik riski:** Unseal key'lerin diskte plaintext tutulması (`vault-unseal` sidecar pattern staging'de böyle yapıyor) compliance ihlali.

Cloud KMS auto-unseal:
- Vault boot'ta KMS'ten key alır → self-unseal
- Unseal key'ler diskte yok
- Sealed durumda kalma ihtimali KMS erişim hatası (§5)

**Provider seçenekleri:**

| Provider | Ne zaman? | Maliyet | Compliance |
|---|---|:-:|:-:|
| **AWS KMS** | EC2 / ECS / EKS deploy | ~$1/ay per key + req fee | FIPS 140-2 L3 |
| **GCP KMS** | GKE / GCE deploy | ~$1/ay per key version | FIPS 140-2 L3 |
| **Azure Key Vault** | AKS / VM deploy | Standard tier | FIPS 140-2 L2 |
| **Transit (Vault)** | Multi-cloud / self-hosted HSM | Kendi cost | HSM'e bağlı |

**Öneri (fresh prod):** Deploy platform'un native KMS'ini kullan (en düşük latency, IAM tight binding, audit trail).

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

**Sorumlu ekipler:** Platform Engineering (operasyon), Security Engineering (gözetim).
**Ortamlar:** prod (primary). Stage ve test Shamir + sidecar loop ile kalır; bu runbook prod cutover içindir.
**Base:** HashiCorp Vault 1.21.4, raft storage, single node.

**İlgili dosyalar:**
- `backend/devops/vault/vault.hcl` (base config — değişmez)
- `backend/devops/vault/vault-seal-disabled.hcl` (Shamir placeholder)
- `backend/devops/vault/vault-seal-awskms.hcl`
- `backend/devops/vault/vault-seal-gcpckms.hcl`
- `backend/devops/vault/vault-seal-azurekeyvault.hcl`
- `backend/devops/vault/vault-seal-transit.hcl`
- `backend/docker-compose.yml` + `deploy/docker-compose.prod.yml` — `VAULT_SEAL_FILE` env-driven mount
- `deploy/ubuntu/deploy-backend.sh` — `VAULT_SEAL_MODE` conditional sidecar

**SLO:**
- Vault restart sonrası auto-unseal max 30 saniye.
- KMS unavailable olduğunda alert ≤ 1 dk.
- Recovery key generate operasyonu planlandığında operator threshold'u erişilebilir olmalı.

-------------------------------------------------------------------------------
3. BAŞLATMA / DURDURMA
-------------------------------------------------------------------------------

### Provider Rehearsal Matrix (AWS önerilen — ilk rehearsal)

Prod cutover öncesi staging rehearsal için aday provider karşılaştırması
(Codex Thread B analizi, 2026-04-18):

| Provider | Ön-yapılandırma | Rotation | Süre | Rehearsal Maliyeti | Notlar |
|---|---|---|:-:|---|---|
| **AWS KMS** (önerilen) | CMK `alias/vault-unseal-prod`, IAM role `vault-unseal-stage`, policy `kms:Encrypt/Decrypt/DescribeKey` | `enable-key-rotation` 180-365 gün | 45-60 dk | `~$1/key/month` + req fee `$0.03/10k` (free tier 20k/month) | FIPS 140-2 L3, IAM model en anlaşılır, key deletion 7-30 gün recover window |
| GCP KMS | Key ring `vault-unseal`, key `vault-unseal-prod`, SA `vault-unseal@erp-platform-prod`, role `cloudkms.cryptoKeyEncrypterDecrypter` | 90 gün auto | 45-60 dk | `$0.06/key-version/month` + op fee `$0.03/10k` | FIPS 140-2 L3, workload identity (GKE), key destroy 24h scheduled |
| Azure Key Vault | Vault `erp-prod-kv`, key `vault-unseal-prod`, MI/SP + `Key Vault Crypto User` | Policy `Rotate P18M + Notify P30D + Expiry P2Y` | 50-70 dk | Standard tier + scheduled rotation ek ücret | FIPS 140-2 L2, soft-delete + purge-protection ZORUNLU |
| Transit (Vault) | Ayrı bağımsız Vault + transit engine + periodic orphan token | Transit key rotate + token renewal runbook | 60-90 dk | Public KMS fee yok; 2. Vault control-plane maliyeti | **Recursive failure riski** — ancak gerçek bağımsız control-plane varsa düşün |

**Tavsiye:**
- **İlk rehearsal: AWS KMS.** Prod platform seçimi AWS ise birincil tercih.
- Prod platform kararı açık ise önce compute platform (k8s cluster
  provider), sonra native KMS.
- Transit sadece gerçek bağımsız ikinci Vault control-plane varsa;
  aksi halde break-glass'i sadeleştirmez, karmaşıklaştırır.

### Tek-host staging-sw reframe (2026-04-18, Codex verdict)

User direktifi "external cloud (AWS/GCP/Azure) yasak, tek host staging-sw"
altında OI-04'ün pratik prod-grade rehearsal yapması **mümkün değil**:

- **Seçenek A (Same-Vault self-referential transit)**: Teknik olarak
  imkansız — sealed Vault kendi `transit/` mount'una erişip decrypt
  yapamaz (chicken-and-egg bootstrap problemi). HashiCorp dokümantasyonu
  bu pattern'i desteklemez.
- **Seçenek B (2nd Vault container same-host)**: Config wiring ve auto-unseal
  akışı için sinyal üretir ama aynı host, aynı kernel, aynı disk, aynı
  Docker network = aynı failure domain. Prod-grade KMS dayanıklılığı
  kanıtlamaz; "same-host wiring drill" diye etiketlenirse dürüst,
  "KMS rehearsal" diye sunulursa security theater.
- **Seçenek C (honest reframing, bu runbook yolu)**: Staging-sw'da Shamir
  pattern korunur. Transit cutover **prod cutover öncesi explicit prereq
  olan ayrı iş paketi** olur. Bu prereq:
  - **Independent host** (ayrı failure domain — başka VM/zone/region) VEYA
  - **User-approved cloud KMS provider** (AWS/GCP/Azure — user açık izni + IAM/role bind).
  - Transit veya cloud KMS path seçildikten sonra gerçek rehearsal §3
    Ortak Dry-Run Checklist Step A-F'ye göre yürütülür.

**OI-04 staging-sw-only kapsamı:**
- Dokümantasyon ve runbook parity (bu §).
- `RB-vault-approle-setup-stage.md` runbook'u AppRole kalıcı setup için.
- Recovery key escrow drill §5.5 — simulated (prod Vault fresh init yok,
  kavramsal akış doğrulaması).
- Break-glass decision tree §5.1 — simulated (IAM restore dry-run yok).
- **Gerçek KMS rehearsal ve escrow drill icra yok** — prod cutover
  gate'inde ayrı story açılacak (independent host veya cloud KMS user
  onayı sonrası).

### Ortak Dry-Run Checklist (her provider için)

- Step A — Provider key + identity binding + rotation policy (aynı oturumda aktif)
- Step B — `VAULT_SEAL_MODE`, `VAULT_SEAL_FILE`, provider env'leri set et
- Step C — Fresh init — **5 recovery share / threshold 3** (key shares 1/1,
  KMS seal altında unseal share fiilen kullanılmaz):
   ```bash
   docker exec platform-vault-1 vault operator init \
     -recovery-shares=5 -recovery-threshold=3 \
     -key-shares=1 -key-threshold=1
   ```
- Step D — Restart × 3 dry-run, her adımda:
   ```bash
   docker restart platform-vault-1 && sleep 20
   docker exec platform-vault-1 vault status -format=json \
     | jq '{sealed, seal_type, recovery_seal_type}'
   # Beklenen: {"sealed": false, "seal_type": "awskms", "recovery_seal_type": "shamir"}
   ```
- Step E — CLI JSON alan isimleri build'e göre değişirse fallback:
   ```bash
   docker exec platform-vault-1 vault status  # table output
   curl -s http://127.0.0.1:8200/v1/sys/seal-status | jq
   ```
- Step F — Fail durumunda provider-specific log + `kms describe-key` ile
  root-cause sınıflandır; rehearsal'ı PASS yazma.

### Evidence paths

- Kalıcı doküman: `docs/04-operations/DRILLS/vault-kms-rehearsal-<provider>-YYYYMMDD.md`
- Geçici makina kanıtı: `.cache/reports/vault-kms-rehearsal/<provider>/status.json`
- Format: `environment`, `provider`, `key_id`, `identity_principal`,
  `restart_1/2/3_outputs`, `seal_status_evidence`, `operator`,
  `started_at`, `completed_at`, `verdict`

### AWS KMS

**Ön hazırlık:**
- KMS key oluştur (symmetric, usage=ENCRYPT_DECRYPT):
   ```bash
   aws kms create-key --description "Vault auto-unseal prod" \
     --key-usage ENCRYPT_DECRYPT --key-spec SYMMETRIC_DEFAULT
   aws kms create-alias --alias-name alias/vault-unseal-prod \
     --target-key-id <KEY_ID>
   ```
- IAM policy (minimum):
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [{
       "Sid": "VaultAutoUnseal",
       "Effect": "Allow",
       "Action": ["kms:Encrypt", "kms:Decrypt", "kms:DescribeKey"],
       "Resource": "arn:aws:kms:<region>:<acct>:key/<KEY_ID>"
     }]
   }
   ```
- IAM rolü EC2 instance / ECS task'a bağla (instance profile).

**Prod deploy env** (HashiCorp-documented env vars passed into the Vault container):
```bash
VAULT_SEAL_MODE=awskms
VAULT_SEAL_FILE=./devops/vault/vault-seal-awskms.hcl
VAULT_AWSKMS_SEAL_KEY_ID=alias/vault-unseal-prod
AWS_REGION=eu-central-1
# Credentials: EC2 instance profile (no AWS_ACCESS_KEY_ID/_SECRET needed).
# Fallback: AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY env vars.
```
Ref: https://developer.hashicorp.com/vault/docs/configuration/seal/awskms

### GCP KMS

**Ön hazırlık:**
```bash
gcloud kms keyrings create vault-unseal --location global
gcloud kms keys create vault-unseal-prod \
  --keyring vault-unseal --location global \
  --purpose encryption
gcloud kms keys add-iam-policy-binding vault-unseal-prod \
  --keyring vault-unseal --location global \
  --member "serviceAccount:vault-unseal@<PROJECT>.iam.gserviceaccount.com" \
  --role roles/cloudkms.cryptoKeyEncrypterDecrypter
```

**Prod deploy env** (HashiCorp-documented env vars):
```bash
VAULT_SEAL_MODE=gcpckms
VAULT_SEAL_FILE=./devops/vault/vault-seal-gcpckms.hcl
GOOGLE_PROJECT=erp-platform-prod
GOOGLE_REGION=global
VAULT_GCPCKMS_SEAL_KEY_RING=vault-unseal
VAULT_GCPCKMS_SEAL_CRYPTO_KEY=vault-unseal-prod
# Credentials: Workload Identity (GKE, preferred — no file mount) or
# GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json (bare-metal fallback).
```
Ref: https://developer.hashicorp.com/vault/docs/configuration/seal/gcpckms

### Azure Key Vault

**Ön hazırlık:**
```bash
az keyvault create --name vault-unseal-kv --resource-group <rg> \
  --location westeurope --enable-soft-delete true --enable-purge-protection true
az keyvault key create --vault-name vault-unseal-kv \
  --name vault-unseal-prod --kty RSA --size 2048 --ops wrapKey unwrapKey
az role assignment create --role "Key Vault Crypto User" \
  --assignee <MI_OBJECT_ID> \
  --scope /subscriptions/<SUB>/resourceGroups/<rg>/providers/Microsoft.KeyVault/vaults/vault-unseal-kv
```

**Prod deploy env** (HashiCorp-documented env vars):
```bash
VAULT_SEAL_MODE=azurekeyvault
VAULT_SEAL_FILE=./devops/vault/vault-seal-azurekeyvault.hcl
AZURE_TENANT_ID=<tenant>
VAULT_AZUREKEYVAULT_VAULT_NAME=vault-unseal-kv
VAULT_AZUREKEYVAULT_KEY_NAME=vault-unseal-prod
# Credentials: Managed Identity (preferred — no CLIENT_ID/_SECRET needed).
# Service Principal fallback:
#   AZURE_CLIENT_ID
#   AZURE_CLIENT_SECRET
```
Ref: https://developer.hashicorp.com/vault/docs/configuration/seal/azurekeyvault

### Transit (External Vault)

**Ön hazırlık (transit Vault):**
```bash
vault secrets enable transit
vault write -f transit/keys/autounseal-prod
vault policy write autounseal-prod - <<EOF
path "transit/encrypt/autounseal-prod" { capabilities = ["update"] }
path "transit/decrypt/autounseal-prod" { capabilities = ["update"] }
EOF
vault token create -policy=autounseal-prod -period=720h
# → token'ı secure-store et
```

**Prod deploy env** (HashiCorp-documented env vars):
```bash
VAULT_SEAL_MODE=transit
VAULT_SEAL_FILE=./devops/vault/vault-seal-transit.hcl
VAULT_ADDR=https://vault-kms.internal:8200
VAULT_TOKEN=<periodic-token>
VAULT_TRANSIT_SEAL_MOUNT_PATH=transit/
VAULT_TRANSIT_SEAL_KEY_NAME=autounseal-prod
# Optional: VAULT_SKIP_VERIFY=true (dev only)
```
**NOTE:** `VAULT_ADDR` / `VAULT_TOKEN` here point at the **external transit Vault**, not this Vault. If container healthchecks or CLI commands need to talk to this Vault's own API, pass explicit flags (`-address`, `-token`) or unset these envs in the health script context.

Ref: https://developer.hashicorp.com/vault/docs/configuration/seal/transit

### Init ve Recovery Keys

KMS-seal mode'da `vault operator init`:

```bash
docker exec -it platform-vault-1 vault operator init \
  -recovery-shares=5 -recovery-threshold=3 -key-shares=1 -key-threshold=1
```

**Çıktı:**
- 5 **Recovery Key** (KMS unavailable olunca root token generation için)
- **Initial Root Token** (ilk admin işlemler)

**KRİTİK — Recovery Key Escrow:**
- 1Password / Bitwarden vault (operator team shared)
- AWS Secrets Manager (ayrı account, cross-account IAM)
- GCP Secret Manager / Azure Key Vault (ayrı subscription)
- Print + locked safe (compliance gerekli ise)

**Minimum redundancy:** En az **2 farklı lokasyon** (cloud vault + offline). Recovery threshold (3) kurtarma için yeterli sayıda operator erişiminde olmalı.

**Initial root token:** Boot sonrası AppRole / userpass kurup bu token'ı **revoke et** (`vault token revoke <token>`). Gerektiğinde recovery keys ile yeniden generate edilir (§5).

### Audit-Init ve Snapshot Job Bootstrap

`vault-audit-init` ve `vault-raft-snapshot` sidecar'ları `/vault-keys/root-token` dosyasından token okuyor (bkz. `backend/devops/vault/vault-init-audit.sh:28`, `vault-raft-snapshot.sh:33`). Shamir mode'da bu dosya `/home/halil/platform/state/vault/` içinde bind mount'la veriliyor; KMS mode'da aynı path'i sağlamak gerek ama root token yerine **dedicated AppRole token** daha güvenli.

**Önerilen akış (KMS fresh init sonrası):**

- Initial root token ile audit-ops AppRole oluştur:
   ```bash
   vault auth enable approle
   vault policy write vault-audit - <<'EOF'
   path "sys/audit" { capabilities = ["read", "list"] }
   path "sys/audit/*" { capabilities = ["create", "update", "sudo"] }
   path "sys/storage/raft/snapshot" { capabilities = ["read"] }
   EOF
   vault write auth/approle/role/vault-audit \
     token_policies=vault-audit \
     token_ttl=24h token_max_ttl=720h
   ROLE_ID=$(vault read -field=role_id auth/approle/role/vault-audit/role-id)
   SECRET_ID=$(vault write -field=secret_id -f auth/approle/role/vault-audit/secret-id)
   ```

- Script'lerin beklediği path'e token üret ve yerleştir:
   ```bash
   VAULT_TOKEN=$(vault write -field=token auth/approle/login \
     role_id=$ROLE_ID secret_id=$SECRET_ID)
   echo "$VAULT_TOKEN" > /home/halil/platform/state/vault/root-token
   chmod 600 /home/halil/platform/state/vault/root-token
   ```

- Initial root token'ı revoke et (§3.5).

- Token rotation için cron / systemd timer (TTL < max_ttl).

**Alternatif (daha basit ama daha güvensiz):** Initial root token'ı kalıcı tut ve `/vault-keys/root-token` olarak yerleştir. Audit logging ve snapshot çalışır ama root token compromise durumunda etki büyük. Prod için AppRole path tercih edilmeli.

### Durdurma / Rollback

**Planlı durdurma:**
```bash
docker stop platform-vault-1
# KMS auto-unseal mode'da restart sonrası otomatik açılır.
```

**KMS → Shamir rollback:** KMS'ten Shamir'e migration Vault dokümanına göre desteklenir (`unseal -migrate` flag ile, KMS erişilebilir durumda). §6 migration appendix.

-------------------------------------------------------------------------------
4. GÖZLEMLEME / LOG / METRİKLER
-------------------------------------------------------------------------------

### Post-Init Verification

```bash
# Container healthy?
docker exec platform-vault-1 vault status
# Expected: Sealed=false, HA Enabled=false, Recovery Seal Type=<kms-type>

# Seal type doğru mu?
docker exec platform-vault-1 vault status -format=json | jq '.seal_type'
# Expected: "awskms" / "gcpckms" / "azurekeyvault" / "transit"

# KMS roundtrip testi (Vault restart sonrası auto-unseal)
docker restart platform-vault-1
sleep 20
docker exec platform-vault-1 vault status -format=json | jq '.sealed'
# Expected: false (KMS unsealed automatically)

# doctor-infra integration
bash backend/scripts/doctor-infra.sh --quick
# Expected: vault healthy + sealed=false
```

### Prometheus Metrics (vault_* namespace)

- `vault_core_unsealed` (1 = unsealed, 0 = sealed) — **kritik**
- `vault_seal_*` (KMS provider-specific)
- `vault_audit_log_request_failure` (KMS fail → audit log fail)

**Alert önerisi:**
- `vault_core_unsealed == 0` 5 dk+ → **P0 oncall page**
- `vault_seal_storage_fail_total` > 0 → **Warn** (KMS flapping)

### Log Filter

```bash
docker logs platform-vault-1 | grep -iE "unseal|seal|kms|transit" | grep -v DEBUG
```

-------------------------------------------------------------------------------
5. ARIZA DURUMLARI VE ADIMLAR
-------------------------------------------------------------------------------

### KMS Erişim Hatası (Vault Sealed) — Break-Glass Decision Tree

**Belirti:** Vault restart sonrası `vault status` → `sealed=true`. KMS unavailable (IAM revoke / key disabled / network egress block).

> ⚠️ **KRİTİK:** Recovery keys KMS seal altında **manual unseal için geçerli DEĞİLDİR** (recovery share sadece `generate-root` akışı için). Primary recovery path IAM/key restore'dur.

**İlk 45 dakika decision tree (Codex Thread B tasarımı):**

| Dakika | Faz | Aksiyon | Authority |
|---|---|---|---|
| 0-5 | Incident ack | On-call acknowledge, `vault_core_unsealed == 0` alert doğrulama, `vault status` evidence | On-call |
| 5-15 | Severity + path seçimi | Prod sealed + secret-fetch etkileniyorsa SEV-1; staging rehearsal SEV-3. Primary restore path: IAM/key | Platform Eng Lead (commander) |
| 15-30 | IAM/key restore + restart | `attach-role-policy` / `enable-key` / network egress unblock + `docker restart platform-vault-1` + seal-status doğrulama | Security Lead (IAM rollback şahidi) |
| 30-45 | Post-restore smoke | `{sealed: false, seal_type: <provider>}` + secret fetch services sağlık check + stakeholder update | Platform Eng Lead |
| 45+ | Fresh-init contingency | Eski seal erişilemez durumunda (key destroyed, irrecoverable): war room aç, fresh-init + secret re-inject. **"Migration" değil — cross-provider migration eski seal erişilebilirken çalışır.** | Platform + Security + Mgmt approval |

**Ortak imza gereken işler:**
- Recovery share çıkarma (quarterly escrow drill dışında)
- Root token generation
- Destructive KMS action rollback
- Fresh-init contingency

**Communication template:**

```text
Subject: [SEV-1] Vault sealed after KMS access failure - <env> - <YYYY-MM-DD HH:MM UTC>

Impact:
Vault sealed since <time>. Secret-backed services may fail startup or secret refresh.

Current status:
Primary restore path in progress: IAM/key access restoration.
Manual unseal is not available in KMS seal mode.
Next update in 15 minutes.

Owner:
Platform Eng Lead: <name>
Security Lead: <name>
```

```text
Status page:
We are investigating degraded secret-management availability affecting backend
service startup and secret access. Next update in 15 minutes.
```

**Audit trail:**
- Kalıcı: `docs/04-operations/DRILLS/vault-breakglass-kms-YYYYMMDD.md`
- Alarm kanıtı: `.cache/reports/vault-breakglass/alert.json`
- Format: `detected_at`, `ack_at`, `severity`, `provider`, `principal_revoked`,
  `restart_time`, `sealed_observed`, `restore_action`, `restore_completed_at`,
  `stakeholder_updates_sent`, `postmortem_required`

**Kontrol listesi (§3.1 restore aksiyonları sıra):**
- Cloud KMS servisini doğrula (console veya CLI ile key describe)
- IAM rolü hâlâ attached mi? (EC2 instance metadata / GKE workload identity)
- Network egress: Vault container KMS endpoint'e ulaşabiliyor mu?
   ```bash
   docker exec platform-vault-1 sh -c 'nc -zv kms.<region>.amazonaws.com 443'
   ```
- Vault log:
   ```bash
   docker logs --tail 100 platform-vault-1 | grep -iE "seal|kms|unseal"
   ```

**Geçici kurtarma (KMS düzelene kadar):**
- Vault DOWN → tüm secret-fetching servisler fail.
- **Öncelik: KMS erişimini geri getir** (IAM revert, network unblock, key re-enable). KMS tekrar erişilebilir olunca Vault container restart otomatik self-unseal eder (`docker restart platform-vault-1`).

> ⚠️ **Recovery keys seal'i migrate ETMEZ.** Vault docs (https://developer.hashicorp.com/vault/docs/concepts/seal): recovery keys yalnızca KMS erişilebilirken root token generate etmek için kullanılır, root key'i decrypt etmez. `vault operator unseal -migrate` ancak **eski seal erişilebilirken** çalışır (Shamir→KMS veya KMS→Shamir transition). KMS permanent kayıp ise bu komut işe yaramaz.

**KMS permanent kayıp (worst case — data loss senaryosu):**

- Vault data snapshot'ı eski seal ile şifreli. KMS key silinmiş ise snapshot restore edilse bile unseal edilemez.
- Tek kurtarma yolu: **fresh init** (yeni KMS key) + secret'ları operational kaynaklardan yeniden ingest (app AppRole'leri regenerate, KV secret'ları manual re-write). Outage = saat/gün.
- **Önleme (hayati):**
  - AWS KMS: key deletion 7-30 günlük pending window; `DisableKey` durumunda bile restore edilebilir.
  - Azure Key Vault: `--enable-soft-delete` + `--enable-purge-protection` açık olmalı (3.3 komut setinde dahil).
  - GCP KMS: key version `DESTROY_SCHEDULED` state 24h window; key destroy'u audit log'a düşer.
  - Transit: transit Vault'un kendi backup'ı + raft snapshot cross-region.
  - Her provider için disable/destroy audit alarm'ı gerek.

### Recovery Keys Kaybı

**Durum:** KMS + recovery keys ikisi de kayıp.

**Kurtarma:** MÜMKÜN DEĞİL. Vault data + secrets kalıcı şifreli. Tek yol:
- Vault backup'tan (snapshot) restore — ama unseal için KMS hâlâ gerekli
- Sıfırdan init + tüm secret'ları yeniden inject (outage boyu saat/gün)

**Önleme (critical):** Recovery keys **minimum 2 farklı lokasyon**, compliance gerekiyorsa **offline print + locked safe**.

### Root Token Kaybı

**Durum:** Initial root token silindi ve admin AppRole/userpass kurulmadı.

**Kurtarma (KMS erişilebilir durumda):**
```bash
docker exec -it platform-vault-1 vault operator generate-root -init
# → nonce + otp üretir
# Recovery keys ile:
docker exec -it platform-vault-1 vault operator generate-root -nonce=<N>
# 3 kere recovery key gir
# Yeni root token üretir
```

Yeni token ile admin AppRole / userpass kur + yeni token'ı revoke et.

### Recovery Key Escrow Drill (Quarterly — ZORUNLU)

**Amaç:** AC-0320 Senaryo 5 operasyonel kanıtı. Root-token regeneration
akışının quarterly kontrollü drill'i.

**Ön-koşullar:**
- Prod veya prod-benzeri fresh-init Vault instance
- 1Password `Team Platform` vault iki kişilik erişim
- Fiziksel offsite safe erişimi
- En az 3 recovery key holder aynı pencere içinde hazır

> ⚠️ Bu drill KMS seal altında **"unseal" değil**, **`generate-root via recovery keys`** drill'idir. Tek-seal tasarımında recovery keys manuel unseal yapamaz.

**Checklist:**

- **Adım A — Fresh init (KMS modunda):**
  ```bash
  docker exec -e VAULT_ADDR=http://127.0.0.1:8200 -it platform-vault-1 \
    vault operator init -recovery-shares=5 -recovery-threshold=3 \
    -key-shares=1 -key-threshold=1
  ```
  Beklenen: `Recovery Key 1..5` ve `Initial Root Token`.
  Fail path: `Vault is already initialized` — drill ayrı scratch instance'ta.

- **Adım B — Escrow split:**
  - `Key 1-3` → 1Password Team Platform
  - `Key 4-5` → print + sealed envelope + offsite safe
  - 1Password erişim modeli tek kişide ise drill FAIL (policy gap).

- **Adım C — `generate-root -init`:**
  ```bash
  docker exec -e VAULT_ADDR=http://127.0.0.1:8200 -it platform-vault-1 \
    vault operator generate-root -init
  ```
  Beklenen: `Nonce`, `OTP`, `Started=true`, `Progress=0/3`.
  Fail path: eski attempt varsa `vault operator generate-root -cancel`.

- **Adım D — 3 holder sequential key girişi (TTY prompt, shell history riski):**
  ```bash
  docker exec -e VAULT_ADDR=http://127.0.0.1:8200 -it platform-vault-1 \
    vault operator generate-root -nonce=<NONCE>
  ```
  Her holder kendi key'ini TTY prompt'a girsin (positional arg DEĞİL).
  Beklenen: Progress 1/3, 2/3, 3/3 + `Complete=true` + `Encoded Token`.

- **Adım E — Decode:**
  ```bash
  docker exec -e VAULT_ADDR=http://127.0.0.1:8200 -it platform-vault-1 \
    vault operator generate-root -decode=<ENCODED_TOKEN> -otp=<OTP>
  ```
  Beklenen: `hvs.` prefix'li yeni root token.

- **Adım F — Critical op + self-revoke:**
  ```bash
  export VAULT_TOKEN=<NEW_ROOT_TOKEN>
  vault policy read default
  vault audit list
  vault token revoke -self
  ```
  Revoke unutulursa drill PASS sayılmamalı ("open exposure" kaydı).

- **Adım G — Quarterly cadence kayıt:**
  - `docs/04-operations/DRILLS/vault-drill-YYYY-QN.md`
  - Fields: `date`, `env`, `seal provider`, `attendees`, `holders_present`,
    `nonce_last6`, `otp_recorded=yes/no`, `encoded_token_generated=yes/no`,
    `critical_ops_tested`, `revoke_self_at`, `outcome`, `followups`
  - Çeyrek atlanırsa sonraki change window öncesi bloklayıcı risk.

**Operatör-zaman:** Hazırlık 15-20 dk + icra 15-20 dk + evidence 10-15 dk = **40-55 dk total**.

**Risk matrisi:**

| Risk | Olasılık | Etki | Azaltma |
|---|---|---|---|
| Recovery key shell history / recording ile sızar | Orta | Çok yüksek | TTY prompt only, recording kapalı, clipboard retention kapalı |
| 1Password erişimi tek kişi | Orta | Yüksek | Access review + drill öncesi witness |
| Fiziksel safe kopyaları güncel değil | Düşük | Çok yüksek | Her init/rekey sonrası sealed envelope re-issuance + checksum |
| Root token revoke unutulur | Orta | Yüksek | Checklist PASS şartı olarak `revoke-self` zorunlu |

### Periodic Transit Token Expired (Sadece Transit Seal)

**Durum:** `VAULT_TOKEN` (transit Vault'a karşı) expired → Vault restart sonrası unseal fail.

**Kurtarma:** Transit Vault'tan yeni periodic token üret:
```bash
# Transit Vault'ta:
vault token create -policy=autounseal-prod -period=720h
# Yeni token'ı prod deploy env'ine update et + Vault container restart
```

-------------------------------------------------------------------------------
6. ÖZET
-------------------------------------------------------------------------------

- Prod Vault auto-unseal için 4 cloud seçeneği (AWS KMS / GCP KMS / Azure Key Vault / Transit).
- Base `vault.hcl` değişmez, seçilen provider'a göre ek seal stanza template'i `${VAULT_SEAL_FILE}` env ile mount edilir.
- Staging/local davranışı korunur: default disabled placeholder = Shamir + `vault-unseal` sidecar loop.
- Recovery keys escrow minimum 2 lokasyon + compliance gerekiyorsa offline print.
- KMS permanent kayıp = data loss; hazırlık (soft-delete + audit alarm) kritik.
- Migration appendix (Shamir → KMS) gelecekteki bir geçiş için referans.

### Migration Appendix — Shamir → KMS (Future)

**Ne zaman gerekli:** Prod Vault zaten var ve Shamir seal'de, KMS'e geçmek için.

**Adımlar:**

- **Backup:** `vault operator raft snapshot save <path>` + offsite copy
- **Seal config update:** Base `vault.hcl`'e ilave seal stanza mount et (`VAULT_SEAL_FILE=./devops/vault/vault-seal-awskms.hcl`)
- **Restart Vault:** `docker restart platform-vault-1`
- **Migrate seal:**
   ```bash
   docker exec -it platform-vault-1 vault operator unseal -migrate
   # Shamir threshold kadar unseal key gir (3-of-5)
   ```
- **Verify:** `vault status` → `Recovery Seal Type=awskms`, `Sealed=false`
- **Revoke old unseal keys** (team-shared location'dan sil)
- **Generate recovery keys:** `vault operator generate-root` ile yeni set
- **Escrow recovery keys** (minimum 2 lokasyon)

**Rollback path:** Backup'tan restore + seal stanza kaldır + Shamir rekey.

### Test Plan (Pre-Prod Acceptance)

Staging KMS deploy rehearsal (önerilen, prod cutover öncesi):

- AWS/GCP/Azure test hesabında KMS key oluştur
- Staging compose override ile KMS config yükle
- Fresh init + recovery keys
- Vault restart × 3 kere → auto-unseal doğrula
- KMS key revoke simülasyonu → sealed=true → recovery key path doğrula
- Final: recovery keys escrow doğrulaması
- Transit modu seçilecekse: `VAULT_ADDR` / `VAULT_TOKEN` çakışma testi (container healthcheck Vault CLI kendi endpoint'ine explicit flag ile bağlanabilmeli).

-------------------------------------------------------------------------------
7. LİNKLER (İSTEĞE BAĞLI)
-------------------------------------------------------------------------------

- Decision registry: `decisions/topics/zanzibar-openfga.v1.json` (Vault indirekt Zanzibar secret store)
- `backend/infra/vault/README.md` — AppRole policies
- `backend/scripts/vault/bootstrap-backend-deploy-approle.sh`
- HashiCorp: https://developer.hashicorp.com/vault/docs/configuration/seal
- HashiCorp seal concepts / recovery keys: https://developer.hashicorp.com/vault/docs/concepts/seal

## Değişiklik Logu

- **2026-04-17 (P1.10):** İlk sürüm. 4 provider template + deploy wiring + runbook.
