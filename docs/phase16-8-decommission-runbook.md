# Faz 16.8 — MSSQL Source Decommission Runbook

> **Scope**: Workcube MSSQL (`10.9.193.201:1433/workcube_mikrolink`) source-read kesimi.
> **NOT in scope**: Compose stateless container retirement (auth-service-1, user-service-1, vb.) — ayrı Faz 18+.
> **Codex AGREE**: thread `019dbf24` iter-1/2 PARTIAL → iter-3 AGREE hedefi
> **Parent**: [PLAN.md §16.8](../PLAN.md) + [docs/migration/mssql-pg-data-contract.md](./migration/mssql-pg-data-contract.md)

---

## Execution Plane / Required Access

> **ÖNEMLI**: Bu runbook komutları **authoritative olarak `staging-sw` host üzerinde** çalıştırılır. Local Mac `kubectl/vault/docker` context **kullanılmaz** (drift + yanlış-cluster riski).

Gereken erişim:
- **SSH**: `ssh staging-sw` (sudo erişimi iptables için)
- **Vault prod token**: `VAULT_ADDR=http://127.0.0.1:8200 VAULT_TOKEN="${VAULT_TOKEN_PROD}"` (staging-sw host üzerinde)
- **Vault test token**: `VAULT_ADDR=http://127.0.0.1:8301 VAULT_TOKEN="${VAULT_TOKEN_TEST}"` (staging-sw host üzerinde)
- **kubectl context**: `k3d-prod` + `k3d-test` (staging-sw üzerinde `~/.kube/config`)
- **Compose files**: `/home/halil/platform/compose/.env.prod` + `.env.test`

### Shell Expansion Kontratı

**Komutlar iki execution moduna sahip:**

**Mod A (runbook operatörü local'de komut çalıştırıyor + SSH wrapper kullanıyor):**
- Operatör kendi shell'inde `export VAULT_TOKEN_PROD=<prod-token>` + `export VAULT_TOKEN_TEST=<test-token>` önceden tanımlamış olmalı
- Komut: `ssh staging-sw "VAULT_ADDR=... VAULT_TOKEN=\"${VAULT_TOKEN_PROD}\" ..."` → **double-quote = local expansion**; token local shell'de expand edilip SSH stream üzerinden remote'a gönderilir
- Trade-off: Token local shell history/env'e girer; SSH bağlantı üstünde plaintext taşınır (TLS ile korumalı)

**Mod B (staging-sw üzerinde direkt çalışıyor):**
- `ssh staging-sw` kısmını atla
- Remote shell'de `source /etc/profile.d/vault-tokens.sh` (root-owned 600-perm) sonra komutlar direkt çalışır
- Trade-off: Token remote host'ta persist; local'e hiç gitmez

**Runbook komutları Mod A format'ında yazılmıştır** (local wrapper). Mod B için `ssh staging-sw` kısmını çıkar + double-quote içindeki `\"${VAR}\"` ifadeleri `"${VAR}"` olarak değiştir.

**Güvenlik**: Mod A için geliştirici Mac session'ı kısa ömürlü (reboot'ta env silinir); production operasyon ekibi Mod B tercih edebilir.

---

## Genel Bakış

5 aşama + 1 prereq gate (A0). Canonical cadence **7+7+30 gün** soak her aşama arası. Rollback dispatcher script tek giriş noktası (`bootstrap/phase16-8-rollback.sh <subcommand>`).

**Blast radius**: En büyük user impact Aşama 1 (feature flag); en büyük reversible-risk Aşama 2 (Vault secret remove); **gerçek point-of-no-return Aşama 5** (30 gün soak sonrası driver removal + ERP cred disable).

### Test Cluster Scope

**Authoritative 16.8 = prod only**. Test cluster 16.5 cutover sonrası zaten MSSQL-off (PLAN.md §16.5.5 "Test-Authoritative Gate" zorunlu ön koşul). 16.8 aşamalarında:

- **Aşama 1 (flag flip)**: **prod only**. Test zaten MSSQL-off (16.5.5 gate).
- **Aşama 2 (Vault remove)**: prod authoritative, **test Vault/env cleanup evidence için symmetric** (yoksa legacy artifact kalır).
- **Aşama 3 (network deny)**: **prod only**. Host-level iptables kuralı tüm Docker trafiğini kapsar; test cluster'ın ek ayrı ihtiyacı yok.
- **Aşama 4 (emergency drill)**: **prod authoritative**. Test dry-run'lar pre-16.5 yapılmıştır; 16.8 sonrası prod-emergency senaryosu.
- **Aşama 5 (full decom)**: prod + ADR (repo genel).

### Örnek Takvim

| Aşama | En erken tetik | Min süre önceki aşamaya göre |
|---|---|---|
| A0 Prereq | 16.7 D29 evidence | — |
| 1 Feature flag | 16.5 cutover sırasında | — |
| 2 Vault remove | Aşama 1 + 7 gün | 7 gün |
| 3 Network deny | Aşama 2 + 7 gün | 7 gün |
| 4 Emergency dry-run | Aşama 3 + 24-72h | timed drill zorunlu |
| 5 Full decom | Aşama 3 + 30 gün | 30 gün |

Örnek: Aşama 1 `24 Nisan 2026` PASS → Aşama 2 ≥ `1 Mayıs` → Aşama 3 ≥ `8 Mayıs` → Aşama 5 ≥ `7 Haziran`.

---

## A0 — Prereq Gate (zorunlu ön koşul)

**Tetik**: 16.5 cutover öncesi evidence check

**Gate Checklist**:
- [ ] 16.0 Data Contract **SEALED** (`docs/migration/mssql-pg-data-contract.md` status `SEALED`, DRAFT değil)
- [ ] 16.1 annex 2A `report-source-annex.yaml` seal (zero `pending_annex`, 8 sourceQuery manual_validated=true)
- [ ] 16.1 annex 2B `schema-introspection-annex.yaml` seal
- [ ] `docs/migration/schema-service-parity-adr.md` karar mühürlü (Option A veya B)
- [ ] 16.5 cutover test-authoritative PASS (testai.acik.com MSSQL-off functional smoke)
- [ ] 16.7 D29 3-katman evidence (Up + Functional + Zanzibar-ready; synthetic authoritative)
- [ ] **Flag truth-table** dokümante: hangi servis hangi flag, hangi config surface (K8s ConfigMap vs compose env vs Vault ES)
- [ ] **Execution plane ready**: `ssh staging-sw` erişim doğrulandı, prod+test Vault token hazır, authoritative `k3d-prod`+`k3d-test` kube context test edildi
- [ ] Backup evidence: MSSQL full backup + SHA256 (retention 30 gün min, Aşama 5 soak penceresi)

**Truth closure**: `docs/state/current-state.md` §A0 deltası (gate PASS evidence).

**Go/No-Go**: Tüm gate item `[x]` → Aşama 1'e geç. Herhangi biri `[ ]` → 16.8 başlama, blockerları kapat.

### Flag Truth-Table (ÖRNEK — A0 gate'te mühürlenir)

> **Codex iter-1 bulgu**: K8s manifest'lerinde `*_MSSQL_ENABLED` **görünmüyor**; deployment `envFrom: configMap+secret`. Flag surface'ı 16.5 cutover'dan önce netleşmeli.

| Servis | Flag | Surface | Change method | Rollback method |
|---|---|---|---|---|
| report-service (prod) | `REPORT_MSSQL_ENABLED=false` | K8s ConfigMap `report-service-config` | kustomize patch + ArgoCD sync | ConfigMap patch revert + rollout restart |
| report-service (test) | aynı | overlays/test patch | Kustomize | aynı |
| schema-service (prod) | `SCHEMA_MSSQL_ENABLED=false` | **Parity Option A**: flag YOK (code-level datasource switch) / **Option B**: ConfigMap `schema-service-config` | Option A: image digest update (platform-ssot PR) / Option B: ConfigMap patch | Option A: image rollback / Option B: ConfigMap revert |
| schema-service (test) | aynı | aynı | aynı | aynı |

(Kesin table A0 gate'te 16.0 SEAL + 16.5 PASS evidence ile doldurulur — bu runbook içinde placeholder.)

---

## Aşama 1 — Feature Flag Kill Switch

**Tetik**: 16.5 cutover adım 4 (feature flag flip — runbook §16.5.5)
**Süre**: 15 dk (Kustomize patch + ArgoCD sync + rollout — iki servis paralel)

### Komutlar

**report-service** (her zaman flag tabanlı, **prod only**):

```bash
ssh staging-sw "kubectl --context k3d-prod apply -f - <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: report-service-config
  namespace: platform-prod
data:
  REPORT_MSSQL_ENABLED: 'false'
EOF"

ssh staging-sw "kubectl --context k3d-prod -n platform-prod rollout restart deploy/report-service && \
  kubectl --context k3d-prod -n platform-prod rollout status deploy/report-service --timeout=180s"
```

**schema-service** (parity ADR'ye göre dal, **prod only**):

```bash
# === Parity Option B (ConfigMap flag tabanlı) ===
ssh staging-sw "kubectl --context k3d-prod apply -f - <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: schema-service-config
  namespace: platform-prod
data:
  SCHEMA_MSSQL_ENABLED: 'false'
EOF"
ssh staging-sw "kubectl --context k3d-prod -n platform-prod rollout restart deploy/schema-service"

# === Parity Option A (image digest hattı, flag YOK) ===
# Bu Aşama 1 flag-flip için no-op. Değişim 16.5 cutover sırasında image digest
# update olarak gerçekleşir:
#   - ssot PR (MSSQL-free code + test) merged → GHCR `sha-<new>`
#   - Bu repo `overlays/prod/kustomization.yaml images:` block `newTag: sha-<new>`
#   - ArgoCD sync → schema-service pod yeni digest ile başlar, MSSQL sınıf classpath'te yok
# Aşama 1 akışında sadece report-service patch'i uygulanır; schema-service için
# **"Option A: N/A"** olarak işaretlenir ve digest update evidence A0 gate'te
# 16.5 PASS kanıtıyla birlikte check edilir.
```

> **Test cluster notu**: Test 16.5.5 gate ile zaten MSSQL-off. Aşama 1 flag flip prod authoritative; test'te legacy flag varsa (nadir) ayrı cleanup PR'ı (bu runbook scope dışı).

### Verify (gerçek read-path kanıt, `theme-registry` değil)

```bash
# 1. Gerçek report render (MSSQL-off proof)
# Gateway path — admin token'lı gerçek rapor execute
TOKEN=$(curl -s -X POST https://ai.acik.com/realms/serban/protocol/openid-connect/token \
  -d "client_id=admin-cli" -d "username=admin@example.com" -d "password=<pw>" \
  -d "grant_type=password" | jq -r .access_token)

curl -s -H "Authorization: Bearer ${TOKEN}" \
  https://ai.acik.com/reports/fin-faturalar/execute?year=2026 | jq '.data | length'
# Beklenen: >0 (PG'den render; MSSQL-off canlı kanıt)

# 2. Schema explorer smoke
curl -s -H "Authorization: Bearer ${TOKEN}" \
  https://ai.acik.com/schemas/explore?schema=workcube_mikrolink_1 | jq '.tables | length'
# Beklenen: >0 (parity Option A: PG catalog; Option B: snapshot table)

# 3. Log taraması — MSSQL connection attempt?
ssh staging-sw "kubectl --context k3d-prod -n platform-prod logs deploy/report-service --tail=200 | grep -iE 'mssql|10.9.193.201' | wc -l"
# Beklenen: 0

ssh staging-sw "kubectl --context k3d-prod -n platform-prod logs deploy/schema-service --tail=200 | grep -iE 'mssql|10.9.193.201' | wc -l"
# Beklenen: 0
```

### Fail Sinyali

- Report render 500/NPE → PG veri eksik (ETL reconciliation fail)
- Schema explorer timeout/empty → parity Option B snapshot boş veya stale
- Log'da `MssqlException`, `Caused by: MSSQL connection refused` → flag pickup olmadı

### Rollback

`bootstrap/phase16-8-rollback.sh re-enable-flags`:
- ConfigMap patch revert (`REPORT_MSSQL_ENABLED=true` + `SCHEMA_MSSQL_ENABLED=true` — Option B only)
- Her iki servis rollout restart
- < 10 dk SLA

### Evidence

- `kubectl get cm report-service-config schema-service-config -o yaml` (flag değerleri)
- ArgoCD Application `OutOfSync` → `Synced` transition
- Rapor render + schema explore screenshot (PG-backed)
- Error log grep zero MSSQL (son 1 saat + 1 hafta spot checks)

### Truth Closure

`docs/state/current-state.md` Aşama 1 PASS delta + `docs/phase16-8-evidence/aşama-1-YYYYMMDD.md`

### Go/No-Go

PASS evidence (her iki servis + gerçek render + zero log) → **7 gün soak başlar**. Herhangi fail → rollback + cutover ertele.

---

## Aşama 2 — Vault Secret Remove + Compose Env Clean

**Tetik**: Aşama 1 PASS + **7 gün gözlem** (error rate <0.1%, zero MSSQL fallback log 7 gün boyunca)
**Süre**: 30-45 dk

**Canonical Vault Path** (Codex iter-1 absorb): `kv/platform/mssql-external` (ortak, servis-bazlı değil).

### Backup (SİLMEDEN ÖNCE ZORUNLU)

```bash
ssh staging-sw "mkdir -p /tmp/phase16-8-backup-$(date +%Y%m%d)"
BACKUP_DIR=/tmp/phase16-8-backup-$(date +%Y%m%d)

# === PROD Vault backup (two-layer: envelope + data-only payload) ===
ssh staging-sw "VAULT_ADDR=http://127.0.0.1:8200 VAULT_TOKEN=\"${VAULT_TOKEN_PROD}\" \
  vault kv get -format=json kv/platform/mssql-external > ${BACKUP_DIR}/mssql-prod.envelope.json"

# Restore-ready payload (data.data only; vault kv put bunu bekler)
ssh staging-sw "jq '.data.data' ${BACKUP_DIR}/mssql-prod.envelope.json > ${BACKUP_DIR}/mssql-prod.data.json"
ssh staging-sw "sha256sum ${BACKUP_DIR}/mssql-prod.data.json > ${BACKUP_DIR}/mssql-prod.data.json.sha256"

# === TEST Vault backup (prod ile simetrik) ===
ssh staging-sw "VAULT_ADDR=http://127.0.0.1:8301 VAULT_TOKEN=\"${VAULT_TOKEN_TEST}\" \
  vault kv get -format=json kv/platform/mssql-external > ${BACKUP_DIR}/mssql-test.envelope.json"
ssh staging-sw "jq '.data.data' ${BACKUP_DIR}/mssql-test.envelope.json > ${BACKUP_DIR}/mssql-test.data.json"
ssh staging-sw "sha256sum ${BACKUP_DIR}/mssql-test.data.json > ${BACKUP_DIR}/mssql-test.data.json.sha256"

# === Compose env backup (prod + test simetrik) ===
ssh staging-sw "cp /home/halil/platform/compose/.env.prod ${BACKUP_DIR}/env.prod.backup"
ssh staging-sw "cp /home/halil/platform/compose/.env.test ${BACKUP_DIR}/env.test.backup"
ssh staging-sw "sha256sum ${BACKUP_DIR}/env.prod.backup > ${BACKUP_DIR}/env.prod.backup.sha256"
ssh staging-sw "sha256sum ${BACKUP_DIR}/env.test.backup > ${BACKUP_DIR}/env.test.backup.sha256"

# === Backup verification (dispatcher script 'verify-backup' subcommand bu mantığı tekrarlar) ===
ssh staging-sw "cd ${BACKUP_DIR} && sha256sum -c mssql-prod.data.json.sha256 mssql-test.data.json.sha256 env.prod.backup.sha256 env.test.backup.sha256"
# Tüm satırlar "OK" olmalı
```

### ES CR Teyit (delete öncesi)

```bash
# Aktif `*-mssql-secrets` External Secret var mı?
ssh staging-sw "kubectl --context k3d-prod get externalsecret -A | grep -i mssql"
ssh staging-sw "kubectl --context k3d-test get externalsecret -A | grep -i mssql"
# Beklenen: zero match (annex 2A MSSQL kapalı sonrası kalmamalı) veya yorumlu ES placeholder
```

### Delete (backup + verify sonrası)

```bash
# === PROD Vault delete ===
ssh staging-sw "VAULT_ADDR=http://127.0.0.1:8200 VAULT_TOKEN=\"${VAULT_TOKEN_PROD}\" \
  vault kv metadata delete kv/platform/mssql-external"

# === TEST Vault delete ===
ssh staging-sw "VAULT_ADDR=http://127.0.0.1:8301 VAULT_TOKEN=\"${VAULT_TOKEN_TEST}\" \
  vault kv metadata delete kv/platform/mssql-external"

# === Compose .env clean ===
ssh staging-sw "sed -i '/^MSSQL_/d' /home/halil/platform/compose/.env.prod"
ssh staging-sw "sed -i '/^MSSQL_/d' /home/halil/platform/compose/.env.test"
ssh staging-sw "grep -c '^MSSQL_' /home/halil/platform/compose/.env.prod /home/halil/platform/compose/.env.test || echo 'zero match OK'"
```

### ESO ExternalSecret Manifest Clean (bu repo)

```bash
# Yorumlu mssql_* satırları kalıcı sil (report-service + schema-service ES)
# kustomize/base/apps/report-service/ops/externalsecret.yaml
# kustomize/base/apps/schema-service/ops/externalsecret.yaml
# — bu PR kapsamı (Aşama 2 ile birlikte bu repo change)
```

### Verify

```bash
# Vault listeleri boş
ssh staging-sw "VAULT_ADDR=http://127.0.0.1:8200 VAULT_TOKEN=\"${VAULT_TOKEN_PROD}\" \
  vault kv list kv/platform/ | grep -i mssql"
# Beklenen: zero match

ssh staging-sw "VAULT_ADDR=http://127.0.0.1:8301 VAULT_TOKEN=\"${VAULT_TOKEN_TEST}\" \
  vault kv list kv/platform/ | grep -i mssql"

# Pod startup OK (zero "Secret key missing")
ssh staging-sw "kubectl --context k3d-prod -n platform-prod rollout restart deploy/report-service deploy/schema-service"
ssh staging-sw "kubectl --context k3d-prod -n platform-prod rollout status deploy/report-service deploy/schema-service --timeout=180s"
```

### Fail Sinyali

- `CreateContainerConfigError` (ES sync fail → yorumlu referans hâlâ aktif)
- Backup SHA256 verify fail (kritik — Aşama 4 drill restore güvenilmez)
- Pod log: `MssqlException: No datasource available` (ES/flag asenkron)

### Rollback

`bootstrap/phase16-8-rollback.sh restore-mssql-secret`:

```bash
# Prod restore (data.data payload)
ssh staging-sw "VAULT_ADDR=http://127.0.0.1:8200 VAULT_TOKEN=\"${VAULT_TOKEN_PROD}\" \
  vault kv put kv/platform/mssql-external @${BACKUP_DIR}/mssql-prod.data.json"

# Test restore
ssh staging-sw "VAULT_ADDR=http://127.0.0.1:8301 VAULT_TOKEN=\"${VAULT_TOKEN_TEST}\" \
  vault kv put kv/platform/mssql-external @${BACKUP_DIR}/mssql-test.data.json"

# Compose env restore (backup dosyadan, git checkout değil)
ssh staging-sw "cp ${BACKUP_DIR}/env.prod.backup /home/halil/platform/compose/.env.prod"
ssh staging-sw "cp ${BACKUP_DIR}/env.test.backup /home/halil/platform/compose/.env.test"

# Pod rollout (ES sync + flag pickup)
ssh staging-sw "kubectl --context k3d-prod annotate externalsecret report-service-secrets -n platform-prod force-sync=$(date +%s) --overwrite"
ssh staging-sw "kubectl --context k3d-prod -n platform-prod rollout restart deploy/report-service deploy/schema-service"
```

### Evidence

- Backup artifact bundle: `${BACKUP_DIR}/{mssql-prod,mssql-test}.{envelope,data}.json + .sha256` + `env.{prod,test}.backup + .sha256`
- `vault kv list kv/platform/` post-delete screenshot (prod + test simetrik)
- Compose `.env.{prod,test}` diff (pre/post, git commit)
- Pod restart success log (prod + test her iki servis)

### Truth Closure

current-state Aşama 2 delta + `docs/phase16-8-evidence/aşama-2-YYYYMMDD.md` (SHA256 manifest + backup path audit).

### Go/No-Go

Backup + sha256 verify ✓ + delete + verify ✓ → **7 gün soak başlar**.

---

## Aşama 3 — Network Deny (DOCKER-USER chain)

**Tetik**: Aşama 2 PASS + **7 gün gözlem**
**Süre**: 15 dk

**Codex iter-1 bulgu**: `iptables OUTPUT` **yanlış katman** — Docker/k3d trafiği `FORWARD/DOCKER-USER` chain'lerinden geçer. Canonical deny `DOCKER-USER` zincirinde.

### Komutlar (idempotent)

```bash
# 1. Primary: DOCKER-USER chain DROP (Docker/k3d container deny)
# -C (check) + -I (insert) idempotent pattern
ssh staging-sw 'sudo iptables -C DOCKER-USER -d 10.9.193.201 -p tcp --dport 1433 -j DROP 2>/dev/null || \
  sudo iptables -I DOCKER-USER 1 -d 10.9.193.201 -p tcp --dport 1433 -j DROP'

# 2. Secondary (opsiyonel): host OUTPUT chain (host shell/curl için ek koruma)
ssh staging-sw 'sudo iptables -C OUTPUT -d 10.9.193.201 -p tcp --dport 1433 -j DROP 2>/dev/null || \
  sudo iptables -I OUTPUT 1 -d 10.9.193.201 -p tcp --dport 1433 -j DROP'

# 3. Kalıcı kaydet (reboot'a dayanıklı)
ssh staging-sw 'sudo iptables-save > /etc/iptables/rules.v4'

# 4. Rule position verify
ssh staging-sw 'sudo iptables -L DOCKER-USER -n --line-numbers | head -5'
# DROP rule line 1'de olmalı (earlier ACCEPT altında kalırsa deny etkisiz)
```

### Verify

```bash
# Host-side test
ssh staging-sw 'nc -zv 10.9.193.201 1433'
# Beklenen: "connection timed out" veya "no route"

# Container-side test (staging-sw üzerinden, docker exec)
ssh staging-sw 'docker exec platform-report-service-1 nc -zv 10.9.193.201 1433 2>&1 | head -3'
# Beklenen: timeout/refused

# K8s pod-side test
ssh staging-sw 'kubectl --context k3d-prod -n platform-prod exec -it deploy/report-service -- nc -zv 10.9.193.201 1433 2>&1 | head -3'
# Beklenen: timeout/refused
```

**NOT**: K8s NetworkPolicy aşaması **EKLENMEZ** — base `netpol/default-deny.yaml` zaten egress deny, `netpol/allow-egress-dns-and-host.yaml` allowlist'inde `1433` zaten yok (sadece 5432/8080/8200). Codex iter-1 evidence.

### Fail Sinyali

- `nc` hâlâ bağlanırsa → rule position kontrol (`-A` yerine `-I 1` doğru)
- App log'da yeni "connection refused" (beklenen değil — Aşama 1'den beri bağlantı kurulmamalı)

### Rollback

`bootstrap/phase16-8-rollback.sh remove-network-deny`:

```bash
ssh staging-sw 'sudo iptables -D DOCKER-USER -d 10.9.193.201 -p tcp --dport 1433 -j DROP 2>/dev/null || true'
ssh staging-sw 'sudo iptables -D OUTPUT -d 10.9.193.201 -p tcp --dport 1433 -j DROP 2>/dev/null || true'
ssh staging-sw 'sudo iptables-save > /etc/iptables/rules.v4'
ssh staging-sw 'nc -zv 10.9.193.201 1433'   # bağlantı OK beklenir (ERP canlı)
```

### Evidence

- `sudo iptables -L DOCKER-USER -n --line-numbers | head -5` screenshot (rule 1'de)
- `iptables-save` dump pre/post diff
- `nc -zv` timeout kanıt (host + container + K8s pod)
- App health smoke PASS

### Go/No-Go

Connection deny evidence ✓ → **Aşama 4 timed drill (24-72h içinde) + 30 gün soak başlar**.

---

## Aşama 4 — Emergency Re-Access Timed Drill

**Tetik**: Aşama 3 PASS + **24-72 saat içinde** (Codex iter-1: SLA iddiası canlı drill gerektirir)

**Codex iter-2 clarification**: SLA "emergency request → functional re-access sağlandığı an" durur. **Post-drill cleanup SLA DIŞI** (ayrı +15-30 dk).

### Prosedür (simulated emergency: ERP admin "acil data restore" ister)

```bash
# T+0 — Start timer (functional re-access hedefi)
T0=$(date +%s)

# T+2dk — DOCKER-USER rule remove
ssh staging-sw 'sudo iptables -D DOCKER-USER -d 10.9.193.201 -p tcp --dport 1433 -j DROP'
ssh staging-sw 'sudo iptables -D OUTPUT -d 10.9.193.201 -p tcp --dport 1433 -j DROP || true'

# T+5dk — Vault secret restore (backup'tan, **prod only** — test Aşama 2'de cleanup edilmiş legacy artifact)
ssh staging-sw "VAULT_ADDR=http://127.0.0.1:8200 VAULT_TOKEN=\"${VAULT_TOKEN_PROD}\" \
  vault kv put kv/platform/mssql-external @${BACKUP_DIR}/mssql-prod.data.json"

# T+10dk — Compose env restore (prod only, drill kapsamı)
ssh staging-sw "cp ${BACKUP_DIR}/env.prod.backup /home/halil/platform/compose/.env.prod"

# T+12dk — ESO sync + pod restart (prod only, report + schema)
ssh staging-sw "kubectl --context k3d-prod annotate externalsecret -n platform-prod \
  report-service-secrets schema-service-secrets force-sync=$(date +%s) --overwrite"
ssh staging-sw "kubectl --context k3d-prod -n platform-prod rollout restart \
  deploy/report-service deploy/schema-service"

# T+20dk — Feature flag re-enable (prod only, parity ADR'ye göre)

# report-service (her zaman flag):
ssh staging-sw "kubectl --context k3d-prod apply -f - <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: report-service-config
  namespace: platform-prod
data:
  REPORT_MSSQL_ENABLED: 'true'
EOF"

# schema-service:
#   Option B (flag tabanlı): ConfigMap patch
ssh staging-sw "kubectl --context k3d-prod apply -f - <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: schema-service-config
  namespace: platform-prod
data:
  SCHEMA_MSSQL_ENABLED: 'true'
EOF"
#   Option A (image digest hattı): **image rollback** gereklidir — ssot önceki
#   MSSQL-ready digest (`sha-<pre-decom>`) ile rollout (drill süresince geçici).
#   A0 truth-table Option A seçimi varsa bu komut blok `kubectl set image deploy/schema-service \
#     schema-service=ghcr.io/halildeu/platform-ssot-schema-service:sha-<pre-decom>` ile değiştirilir.
#   Drill sonu cleanup'ta yeni MSSQL-free digest'e geri dönülür.

ssh staging-sw "kubectl --context k3d-prod -n platform-prod rollout restart deploy/report-service deploy/schema-service"
ssh staging-sw "kubectl --context k3d-prod -n platform-prod rollout status deploy/report-service deploy/schema-service --timeout=180s"

# T+25dk — Functional re-access test (MSSQL connection OK)
ssh staging-sw 'docker exec platform-report-service-1 nc -zv 10.9.193.201 1433'
# Beklenen: connected

# T+<=30dk — Drill END
T1=$(date +%s)
DURATION=$((T1-T0))
echo "Drill duration: ${DURATION}s (target <1800s / 30 dk)"

if [ ${DURATION} -le 1800 ]; then
  echo "SLA PASS"
else
  echo "SLA FAIL — runbook revize"
fi
```

### Post-Drill Cleanup (SLA DIŞI)

```bash
# Canlı state'i Aşama 3 seviyesine geri getir
# (bu kısmın süresi SLA'ya dahil DEĞİL — Codex iter-2 absorb)

# 1. Feature flag tekrar off (prod only, parity ADR'ye göre)
#    report-service: ConfigMap REPORT_MSSQL_ENABLED='false'
#    schema-service Option B: ConfigMap SCHEMA_MSSQL_ENABLED='false'
#    schema-service Option A: image digest tekrar MSSQL-free sha-<post-decom>

# 2. Vault secret tekrar delete (prod only — drill geri getirdi, test Aşama 2'den beri temiz)
ssh staging-sw "VAULT_ADDR=http://127.0.0.1:8200 VAULT_TOKEN=\"${VAULT_TOKEN_PROD}\" \
  vault kv metadata delete kv/platform/mssql-external"

# 3. Compose env tekrar clean (prod only)
ssh staging-sw "sed -i '/^MSSQL_/d' /home/halil/platform/compose/.env.prod"

# 4. DOCKER-USER rule tekrar ekle (idempotent)
ssh staging-sw 'sudo iptables -C DOCKER-USER -d 10.9.193.201 -p tcp --dport 1433 -j DROP 2>/dev/null || \
  sudo iptables -I DOCKER-USER 1 -d 10.9.193.201 -p tcp --dport 1433 -j DROP'
```

### Evidence

- `docs/phase16-8-evidence/aşama-4-drill-YYYYMMDD.md` — T+X timestamps + duration + PASS/FAIL
- Kullanıcı (ERP admin simulator) sign-off: "emergency SLA acceptable"
- Post-drill cleanup success log (state Aşama 3 seviyesine restore)

### Go/No-Go

Drill PASS (duration ≤ 30 dk `functional re-access`) → **Aşama 5 30 gün soak başlar**.
Fail → runbook revize + re-drill.

**Re-drill koşulu**: Aşama 5 90+ gün ertelenirse (örn. dış paydaş sebebiyle) Aşama 4 drill yeniden koşulur (Codex iter-1).

---

## Aşama 5 — Full Decommission (Point of No Return)

**Tetik**: Aşama 3 PASS + **30 gün gözlem** + Aşama 4 drill PASS
**Süre**: 2 saat hands-on ops time; **uçtan uca 0.5-2 iş günü** (ssot PR review + digest publish + 3-paydaş sign-off süresi dahil)

### 5.0 — Final Go/No-Go Gate (ZORUNLU)

> **Irreversible öncesi son kapı** — 4 gate item `[x]` olmadan 5.1+ başlamaz.

- [ ] **Aşama 4 drill PASS** (duration ≤ 30 dk, evidence `docs/phase16-8-evidence/aşama-4-drill-YYYYMMDD.md`)
- [ ] **30 gün soak PASS** (zero MSSQL fallback log 30 gün boyunca + rapor/schema smoke weekly)
- [ ] **ssot MSSQL-free image digest verified**:
  - `platform-ssot` PR merged (5.1 altı)
  - GHCR image `sha-<new>` pushed
  - `grep -r mssql <ssot>/backend` → zero code-level reference (sadece tarihsel docs)
- [ ] **Written sign-off** (üç paydaş):
  - Backend lead: kod review MSSQL-free
  - Ops engineer: 30g soak evidence review
  - Workcube admin: ERP tarafında "platform artık bağlanmıyor" teyit

**Truth closure**: `docs/phase16-8-evidence/aşama-5-gate-YYYYMMDD.md` — 4 gate evidence + sign-off.

**Go/No-Go**: 4 gate item `[x]` → 5.1'e geç. Herhangi biri `[ ]` → beklemeye al, eksikleri kapat.

---

### 5.1 — platform-ssot cross-repo PR (ssot team)

- `pom.xml` → `mssql-jdbc` dependency remove
- `application-k8s.yml` → MSSQL datasource block delete
- `MssqlConfig.java` delete
- `SchemaExtractService.java` → parity decision Option A kod rewrite (MSSQL reference sıfır) [Option B: metadata_snapshot table read]
- Integration test: "no MSSQL class in classpath" assertion
- Merge sonrası GHCR digest: `sha-<new>`

### 5.2 — Bu repo digest update (Aşama 5 PR)

- `kustomize/overlays/test/kustomization.yaml` + `overlays/prod/kustomization.yaml` `images:` block → `newTag: sha-<new>` (MSSQL-free)
- ArgoCD sync
- Pod imageID verify: `kubectl describe pod` yeni digest

### 5.3 — ADR Addendum

- `docs/adr/0004-mssql-source-decommissioned.md` (yeni) — tarih + evidence + superseded impacts
- `docs/adr/README.md` ADR listesi güncellenir
- ADR-0002 D31 (PG primary, MSSQL secondary) → status "Secondary option removed (ADR-0004)"

### 5.4 — ERP Credential Disable (Workcube admin)

- ERP tarafında `platform-reader` account **disable** veya rotate (credentials artık kullanılmıyor)
- Audit log: MSSQL tarafında "last login from platform" timestamp (30g+ önce olmalı)
- Workcube admin sign-off: "platform erişimi kapatıldı"

### 5.5 — PLAN.md status closure

- §16 "Faz 16 COMPLETE" marker
- `docs/state/current-state.md` delta: "Faz 16 decommission FINAL"
- `docs/session-handoff-<date>.md` (Faz 16 kapanış handoff)

### Beklenen (final state)

- `grep -r mssql platform-ssot/backend` → zero code-level (sadece tarihsel git history + migration docs)
- `kubectl describe deploy report-service -n platform-prod` → image digest yeni, MSSQL driver yok
- ADR-0004 merged, ADR-0002 D31 status güncel
- ERP credential disabled (audit evidence)

### Rollback

**YOK**. Point of no return. Fail durumunda yeni ETL pipeline (MSSQL tekrar source) günler-hafta gerektirir.

### Evidence

- `docs/phase16-8-evidence/aşama-5-gate-YYYYMMDD.md` (5.0 Final Go/No-Go)
- platform-ssot PR URL + merge commit SHA
- Bu repo digest update PR
- ADR-0004 file
- ERP admin sign-off artifact (cred disabled + audit last-login)
- current-state Faz 16 COMPLETE delta

### Truth Closure

Faz 16 kapanış handoff (`docs/session-handoff-<date>-faz-16-complete.md`).

---

## Rollback Dispatcher Script

`bootstrap/phase16-8-rollback.sh <subcommand>` (tek giriş noktası):

```bash
#!/usr/bin/env bash
# Faz 16.8 rollback dispatcher. Per-aşama rollback logic.
#
# Subcommands:
#   re-enable-flags       — Aşama 1 revert (feature flag re-enable, prod only — report + schema)
#   restore-mssql-secret  — Aşama 2 revert (Vault kv restore from backup; prod only for drill;
#                             test cleanup-only Aşama 2 run'da yapıldı)
#   remove-network-deny   — Aşama 3 revert (iptables DOCKER-USER + OUTPUT rule remove)
#   emergency-reaccess    — Aşama 4 drill (combined 1+2+3 revert, 30 dk SLA, timed, prod authoritative)
#   verify-backup         — Backup integrity check (SHA256 verify, prod+test, envelope+data+env)
#   status                — mevcut aşama rapor (hangi state'deyiz?)

set -euo pipefail

SUBCMD="${1:-status}"
BACKUP_DIR="${BACKUP_DIR:-/tmp/phase16-8-backup-latest}"

case "${SUBCMD}" in
  re-enable-flags)
    # (yukarıdaki Aşama 1 rollback komutları)
    ;;
  restore-mssql-secret)
    # Verify backup first (Codex iter-2 verify-backup absorb)
    "${0}" verify-backup || { echo "FATAL: backup integrity fail"; exit 3; }
    # (yukarıdaki Aşama 2 rollback komutları)
    ;;
  remove-network-deny)
    # (yukarıdaki Aşama 3 rollback komutları)
    ;;
  emergency-reaccess)
    # (yukarıdaki Aşama 4 timed drill prosedürü)
    ;;
  verify-backup)
    # Integrity check (Codex iter-2 bulgu 1 absorb — en kritik risk otomatik kontrol)
    cd "${BACKUP_DIR}"
    sha256sum -c mssql-prod.data.json.sha256 || exit 4
    sha256sum -c mssql-test.data.json.sha256 || exit 4
    sha256sum -c env.prod.backup.sha256 || exit 4
    sha256sum -c env.test.backup.sha256 || exit 4
    echo "Backup integrity: OK (prod+test, envelope+data+env)"
    ;;
  status)
    # (mevcut aşama detection: Vault kv, compose env, iptables state)
    ;;
  *) echo "bilinmeyen subcommand"; exit 2 ;;
esac
```

**6 subcommand** (Codex iter-2 `verify-backup` ekleme absorb): `re-enable-flags` / `restore-mssql-secret` / `remove-network-deny` / `emergency-reaccess` / `verify-backup` / `status`.

**Tek script gerekçesi** (Codex iter-1): 5 ayrı script gereksiz; tek monolitik script tehlikeli (yanlış tıklama); dispatcher pattern açık + güvenli.

---

## Accelerated Simulation Lane (Appendix, canonical DEĞİL)

Canonical cadence **7+7+30 gün** (yukarıda). Simulation/DR test için accelerated:

| Aşama | Canonical | Accelerated |
|---|---|---|
| Aşama 2 tetik | A1 + 7 gün | A1 + 3 gün |
| Aşama 3 tetik | A2 + 7 gün | A2 + 3 gün |
| Aşama 5 tetik | A3 + 30 gün | A3 + 15 gün |

Accelerated **yalnız simulation/DR drill için** kullanılır; prod canlı 16.8 akışı canonical takvime uyar.

---

## Truth Closure Markers

Her aşama sonunda:
1. Evidence artifact (`docs/phase16-8-evidence/aşama-X-YYYYMMDD.md`)
2. `docs/state/current-state.md` delta (yeni Session block)
3. Go/No-Go verdict yazılı (backend lead + ops + Workcube admin)
4. PLAN.md §16.8 status update (Aşama 1-5 complete)

Faz 16 COMPLETE (Aşama 5 merge) → `docs/session-handoff-<final>-faz-16-complete.md` final handoff.

---

## Hidden Risks (Codex iter-1/2 bulgularından)

1. **A0 flag truth-table eksiksiz değilse** → 16.5 cutover'da flag flip belirsiz (K8s ConfigMap'te flag yok, Codex evidence)
2. **Aşama 2 backup SHA256 doğrulanmazsa** → Aşama 4 drill restore fail (irreversible data loss riski)
3. **Aşama 2 envelope vs data format karışıklığı** → `vault kv put @envelope.json` fail; restore payload `.data.data` olmalı (jq extract)
4. **Aşama 2 prod/test Vault context karışırsa** → yanlış Vault'a restore (VAULT_ADDR/TOKEN her komutta explicit)
5. **Aşama 3 iptables OUTPUT kullanırsa** → Docker/k3d trafiği geçer (yanlış katman — DOCKER-USER canonical)
6. **Aşama 3 rule position `-A` sona** → earlier ACCEPT altında kalırsa deny etkisiz (`-I 1` zorunlu)
7. **Aşama 4 drill doc-only kalırsa** → 30 dk SLA kanıtsız; Aşama 5 point-of-no-return öncesi emergency kapasitesi belirsiz
8. **Aşama 4 report/schema asimetrisi** → tek servis restart PASS ama diğer MSSQL'siz kalır (iki servis paralel zorunlu)
9. **Aşama 5 cross-repo koordinasyonu yoksa** → ssot PR + bu repo ADR asenkron; ERP cred disable unutulursa audit trail drift
10. **Aşama 5 Final Go/No-Go atlanırsa** → irreversible adımlar parçalı ilerler (4 gate zorunlu)
11. **Compose stateless retirement 16.8 scope'a girerse** (yanlışlıkla) → 16.8 timeline bozulur, compose stateless ≠ MSSQL source. Ayrı Faz 18+ zorunlu.

---

## İlişkili

- [PLAN.md §16.8](../PLAN.md) — parent roadmap
- [docs/migration/mssql-pg-data-contract.md](./migration/mssql-pg-data-contract.md) — 16.0 Data Contract
- [docs/S2-B1-vault-property-matrix.md](./S2-B1-vault-property-matrix.md) — Vault path `kv/platform/mssql-external`
- [kustomize/base/netpol/default-deny.yaml](../kustomize/base/netpol/default-deny.yaml) — egress policy (1433 zaten deny)
- [docs/prod-cutover-runbook-v2.md](./prod-cutover-runbook-v2.md) — format standart (Tetik/Süre/Komut/Beklenen/Fail/Go-No-Go)
- [docs/adr/0002-single-host-dual-cluster.md](./adr/0002-single-host-dual-cluster.md) — D31 PG primary
- Codex thread `019dbf24` — iter-1 VERDICT + iter-2 PARTIAL + iter-3 AGREE hedefi
- Future ADR-0004 (Aşama 5 deliverable) — "MSSQL source decommissioned"
