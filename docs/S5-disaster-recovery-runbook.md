# S5 Disaster Recovery Runbook — Backup + Restore Drill

> ⚠ **ADR-0002 UPDATE** (2026-04-19): D32 supersede edildi. Container isimleri güncel:
> - `platform-pg-prod` → `platform-pg-{prod,test}` (env-specific)
> - `platform-kc-prod` → `platform-kc-{prod,test}`
> - `platform-vault-prod` → `platform-vault-{prod,test}`
>
> Bu dokümandaki komutları uygularken env suffix ekleyin (örn. `platform-pg-prod`).
> Canonical runbook: [`docs/prod-cutover-runbook-v2.md`](./prod-cutover-runbook-v2.md) + [`day-2-governance.md`](./day-2-governance.md) §1 Backup/Restore Drill.

> **Source:** K8s-6 S5 (post-cutover stabil workload için DR hazırlık)
> **Prereq:** ADR-0002 prod cutover PASS + T+72h warm rollback window kapanmış
> **Kapsam:** PostgreSQL + Keycloak realm + Vault KV + K8s manifest
> **RPO hedefi (D23):** 24 saat
> **RTO hedefi (D23):** 4 saat

---

## 1. Backup Envanteri

### 1.1 State kaynakları (staging-sw-2 prod host, D32 sonrası)

| Kaynak | Konum | Backup frekansı | Retention |
|---|---|---|---|
| **PostgreSQL** (7+ DB: auth_db, user_db, variant_db, core_db, report_db, schema_db, permission_db, openfga_db, keycloak) | host compose `postgres` container | Günlük pg_dumpall + haftalık base backup | 14 gün günlük + 4 hafta base |
| **Keycloak realm** (serban) | host compose `keycloak` container (PG bağlı) + realm JSON export | Haftalık realm export + PG bağımlı | 4 hafta |
| **Vault KV data** | host compose `vault` container (Raft backend) | Günlük snapshot | 14 gün |
| **K8s manifest** | Git (platform-k8s-gitops) | Commit'te versioned | Git tarih boyunca |
| **Docker volumes** | `/var/lib/docker/volumes/` | Haftalık tar.gz | 4 hafta |
| **Host nginx config** | `/home/halil/platform/web/nginx/` | Git + haftalık tar | 4 hafta |

### 1.2 Stateless (backup GEREKMEZ)

- K8s ReplicaSet/Deployment (ArgoCD sync'ten gelir, state Git)
- Pod secret/configmap (ESO ile Vault'tan gelir, state Vault)
- Container image cache (GHCR'dan yeniden pull)

---

## 2. Backup Scripts (örnek pattern)

### 2.1 PostgreSQL günlük dump

```bash
#!/usr/bin/env bash
# /home/halil/platform/backup/pg-daily-backup.sh
# Cron: 0 2 * * *  (her gece 02:00)
set -euo pipefail

BACKUP_DIR="/home/halil/platform/backup/pg"
RETENTION_DAYS=14
DATE=$(date +%Y%m%d-%H%M%S)

mkdir -p "${BACKUP_DIR}"

# pg_dumpall — tüm DB + role + tablespace
# --clean --if-exists: restore duplicate-object safe (DROP IF EXISTS + CREATE)
# ADR-0002 DR akışında init SQL ile çakışma önler
docker exec platform-pg-prod pg_dumpall -U postgres --clean --if-exists \
  | gzip > "${BACKUP_DIR}/pg_dumpall_${DATE}.sql.gz"

# Retention (14 gün eski dosyaları sil)
find "${BACKUP_DIR}" -name "pg_dumpall_*.sql.gz" -mtime +${RETENTION_DAYS} -delete

echo "✓ PG backup: ${BACKUP_DIR}/pg_dumpall_${DATE}.sql.gz ($(du -h "${BACKUP_DIR}/pg_dumpall_${DATE}.sql.gz" | cut -f1))"
```

### 2.2 Keycloak realm export (haftalık)

```bash
#!/usr/bin/env bash
# /home/halil/platform/backup/kc-weekly-export.sh
# Cron: 0 3 * * 0  (Pazar 03:00)
set -euo pipefail

BACKUP_DIR="/home/halil/platform/backup/keycloak"
DATE=$(date +%Y%m%d)

mkdir -p "${BACKUP_DIR}"

docker exec platform-kc-prod /opt/keycloak/bin/kc.sh export \
  --realm serban \
  --users realm_file \
  --file "/tmp/serban-${DATE}.json"

docker cp "platform-kc-prod:/tmp/serban-${DATE}.json" \
  "${BACKUP_DIR}/serban-${DATE}.json"

gzip "${BACKUP_DIR}/serban-${DATE}.json"

echo "✓ KC realm export: ${BACKUP_DIR}/serban-${DATE}.json.gz"
```

### 2.3 Vault snapshot günlük

```bash
#!/usr/bin/env bash
# /home/halil/platform/backup/vault-daily-snapshot.sh
# Cron: 0 2 * * *  (her gece 02:00 PG ile aynı anda)
set -euo pipefail

BACKUP_DIR="/home/halil/platform/backup/vault"
RETENTION_DAYS=14
DATE=$(date +%Y%m%d-%H%M%S)

mkdir -p "${BACKUP_DIR}"

# Vault Raft snapshot (tüm KV + auth + policy)
VAULT_TOKEN="<root-or-admin>" vault operator raft snapshot save \
  "${BACKUP_DIR}/vault-snapshot-${DATE}.snap"

find "${BACKUP_DIR}" -name "vault-snapshot-*.snap" -mtime +${RETENTION_DAYS} -delete

echo "✓ Vault snapshot: ${BACKUP_DIR}/vault-snapshot-${DATE}.snap"
```

---

## 3. Restore Senaryoları (drill)

### 3.1 PG tam restore (fresh host veya corrupted data)

**Süre:** ~30 dk (dump boyutuna göre)

**DİKKAT (ADR-0002 init SQL çakışması):** Fresh PG start init SQL script'i çalıştırır (role + DB yaratır). `pg_dumpall` restore ise aynı object'leri tekrar yaratmaya çalışır → duplicate-object hataları. 2 çözüm: (A) Init dizinini geçici kaldır, (B) `--clean --if-exists` dump kullan.

```bash
# 1. Compose PG durdur + bind-mount dizin temizle (DİKKAT destructive)
docker compose -f host-compose/postgres/prod/docker-compose.yml stop postgres
docker compose -f host-compose/postgres/prod/docker-compose.yml rm -f postgres

# ADR-0002 bind-mount (named volume değil):
sudo rm -rf /srv/platform/stateful/prod/postgres/*
sudo chown -R 999:999 /srv/platform/stateful/prod/postgres

# 2a. (ÖNERİLEN) Init script'i geçici bir yere taşı — restore çakışma önleme
mv host-compose/postgres/prod/init host-compose/postgres/prod/init.disabled

# 2b. Compose PG baştan başlat (boş dizin; init SQL ÇALIŞMAZ çünkü init/ yok)
docker compose -f host-compose/postgres/prod/docker-compose.yml up -d postgres
until docker exec platform-pg-prod pg_isready -U postgres; do sleep 2; done

# 3. Restore (dump zaten role + DB + grant içerir)
gunzip -c /home/halil/platform/backup/pg/pg_dumpall_<DATE>.sql.gz | \
  docker exec -i platform-pg-prod psql -U postgres

# 4. Init script'i geri koy (gelecekteki fresh restart için)
mv host-compose/postgres/prod/init.disabled host-compose/postgres/prod/init

# 5. Doğrula (DB listesi)
docker exec platform-pg-prod psql -U postgres -c '\l'
# Beklenen: auth_db, users_db, variants_db, core_db, reports_db, schemas_db,
#           permission_db, openfga, keycloak
```

**Alternatif (B):** Backup'ta `pg_dumpall --clean --if-exists` flag kullanılmışsa init SQL çalıştırılabilir; `DROP IF EXISTS` + `CREATE` pattern ile duplicate-safe. Backup script'i o flagi içeriyorsa 2a adımı skip edilebilir.

### 3.2 Keycloak realm restore

**Süre:** ~10 dk

```bash
# KC config dir'e realm JSON kopya
docker cp /home/halil/platform/backup/keycloak/serban-<DATE>.json.gz \
  platform-kc-prod:/tmp/

docker exec platform-kc-prod gunzip /tmp/serban-<DATE>.json.gz

docker exec platform-kc-prod /opt/keycloak/bin/kc.sh import \
  --file /tmp/serban-<DATE>.json

# KC restart (import sonrası)
docker compose -f host-compose/keycloak/prod/docker-compose.yml restart keycloak
```

### 3.3 Vault KV restore

**Süre:** ~5 dk

```bash
# Vault zaten çalışıyorsa önce seal (opsiyonel, restore sırasında)
VAULT_TOKEN="<admin>" vault operator raft snapshot restore \
  /home/halil/platform/backup/vault/vault-snapshot-<DATE>.snap

# Doğrula
VAULT_TOKEN="<admin>" vault kv get kv/gitops/ghcr-token
VAULT_TOKEN="<admin>" vault policy list
# Beklenen: eso-runtime policy + AppRole role-id + KV data
```

### 3.4 K8s full rebuild (nuclear)

**Süre:** ~45 dk

Eğer k3d-prod cluster tam bozulduysa (nadir senaryo):

```bash
# 1. Cluster delete + recreate (volume clean)
k3d cluster delete prod
k3d cluster create prod --config bootstrap/k3d-prod.yaml

# 2. Calico CNI install
bash bootstrap/install-calico.sh prod

# 3. ESO + overlay apply
bash bootstrap/install-eso-helm.sh prod
# AppRole secret-id manuel + overlays/prod/eso apply

# 4. ArgoCD install + root.yaml apply
bash bootstrap/install-argocd.sh prod
kubectl --context k3d-prod apply -f argocd/applications/root.yaml

# 5. ArgoCD sync platform-prod Application (manuel — D30 atomic)
argocd app sync platform-prod

# 6. Smoke (docs/S1-S2-acceptance-smoke-runbook.md 3 katman D29)
```

### 3.5 Post-restore reconcile (intent-level, hand-applied prod state)

**Süre:** ~5 dk. **Ne zaman:** her restore sonrası; özellikle §3.4 nuclear
(fresh/from-migration rebuild) sonrası — o yol `kc_subject=NULL` ve realm
manuel değişiklikleri olmadan başlar. §3.1 (pg_dumpall) ve §3.2 (KC realm
export) çoğu state'i byte-level geri getirir; bu adım **intent-level** olanı
kapatır: hangi hand-applied prod değişikliği kasıtlıydı.

Canonical kayıt: [`docs/state/serban-realm-live-state-ledger.md`](state/serban-realm-live-state-ledger.md).

```bash
# 1) users_db.kc_subject reconcile (idempotent, dry-run default).
#    Impersonation target-subject resolution kc_subject'e bağlı (NULL -> 422).
#    Önce dry-run — ne değişeceğini gör:
bash scripts/keycloak/reconcile-kc-subject-backfill.sh prod            # dry-run
# Persist (owner-gated):
RECONCILE_PROD_CONFIRM=yes bash scripts/keycloak/reconcile-kc-subject-backfill.sh prod --apply
#    NOT: kalan NULL satırlar KC identity'si olmayan legacy ERP kullanıcıları
#    (Workcube import) — alarm DEĞİL. --apply prod'da id 1201/1203/1204 admin
#    için beklenen UUID'lere karşı EXACT assert yapar (mismatch -> exit 4);
#    ayrıca yazımdan önce duplicate-email + kc_subject conflict precheck'i
#    abort eder.

# 2) serban 'frontend' client protocol mapper set doğrulaması.
#    Ledger §1 tablosuyla karşılaştır. `auth-service-audience` mapper'ı
#    OWNER kararına bağlı (keep-normalize vs revert) — ledger §1.1 +
#    docs/runbooks/RB-serban-audience-mapper-decision.md. Restore edilen
#    export bu mapper'ı içerebilir; owner accept etmediyse revert path uygula.
docker exec platform-pg-prod psql -U postgres -d keycloak -c "
  SELECT pm.name, cfg.name, cfg.value
  FROM protocol_mapper pm
  JOIN client c ON c.id=pm.client_id JOIN realm r ON r.id=c.realm_id
  LEFT JOIN protocol_mapper_config cfg ON cfg.protocol_mapper_id=pm.id
  WHERE r.name='serban' AND c.client_id='frontend' ORDER BY pm.name, cfg.name;"
```

---

## 4. DR Drill Checklist (çeyrek yılda bir)

- [ ] **Full restore drill:** PG dump + Vault snapshot + KC export → staging veya ayrı test host'ta
- [ ] **Restore süresi ölç:** RTO 4h hedefi ile karşılaştır
- [ ] **Restore sonrası smoke:** S1-S2 acceptance smoke runbook
- [ ] **Data integrity:** DB row count + referential integrity check
- [ ] **Retention temizlik:** 14d/4w sınırlarına uyum
- [ ] **Runbook update:** değişen backup path/komut varsa revize

---

## 5. Kaynak Ayrımı (D23)

| Veri | Host | Backup hedef (ayrı host) |
|---|---|---|
| PG + KC + Vault | staging-sw-2 (D32 prod) | staging-sw (eski, compose artık yok, backup target olabilir) |
| Git manifest | GitHub | Local workstation + GitHub arşiv |
| Docker image | GHCR (halildeu/platform-ssot-*) | CI rebuild her zaman mümkün (immutable digest) |

**DR hedefi:** Prod host toplam kayıp senaryosunda 4h içinde fresh host kurumu + restore + smoke PASS.

---

## 6. Referanslar

- PLAN.md D23 DR/RPO/RTO (RPO 24h + RTO 4h hedefler)
- `docs/D32-bootstrap-runbook.md` F1-F9 (fresh host build)
- `docs/S1-S2-acceptance-smoke-runbook.md` (restore sonrası smoke)
- `bootstrap/vault-policies/README.md` (Vault policy + AppRole yeniden yaratma)
- `host-compose/{postgres,keycloak,vault}/prod/docker-compose.yml` (ADR-0002 per-service compose)
