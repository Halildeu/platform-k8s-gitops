# S5 Disaster Recovery Runbook — Backup + Restore Drill

> **Source:** K8s-6 S5 (post-cutover stabil workload için DR hazırlık)
> **Prereq:** D32 prod cutover PASS + T+72h warm rollback window kapanmış
> **Kapsam:** PostgreSQL + Keycloak realm + Vault KV + K8s manifest
> **RPO hedefi (D23):** 24 saat
> **RTO hedefi (D23):** 4 saat
> **Codex yedek iş önerisi — post-D32 scope, pre-cutover kritik değil**

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
docker exec platform-postgres pg_dumpall -U postgres \
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

docker exec platform-keycloak /opt/keycloak/bin/kc.sh export \
  --realm serban \
  --users realm_file \
  --file "/tmp/serban-${DATE}.json"

docker cp "platform-keycloak:/tmp/serban-${DATE}.json" \
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

```bash
# 1. Compose PG durdur + volume temizle (DIKKAT destructive)
docker compose -f host-compose/data/docker-compose.yml stop postgres
docker compose -f host-compose/data/docker-compose.yml rm -f postgres
docker volume rm host-compose_postgres-data

# 2. Compose PG baştan başlat (boş volume)
docker compose -f host-compose/data/docker-compose.yml up -d postgres
sleep 30   # init time

# 3. Restore (backup'tan)
gunzip -c /home/halil/platform/backup/pg/pg_dumpall_<DATE>.sql.gz | \
  docker exec -i platform-postgres psql -U postgres

# 4. Doğrula (DB listesi + tablo sayısı)
docker exec platform-postgres psql -U postgres -c '\l'
# Beklenen: auth_db, user_db, variant_db, core_db, report_db, schema_db,
#           permission_db, openfga_db, keycloak
```

### 3.2 Keycloak realm restore

**Süre:** ~10 dk

```bash
# KC config dir'e realm JSON kopya
docker cp /home/halil/platform/backup/keycloak/serban-<DATE>.json.gz \
  platform-keycloak:/tmp/

docker exec platform-keycloak gunzip /tmp/serban-<DATE>.json.gz

docker exec platform-keycloak /opt/keycloak/bin/kc.sh import \
  --file /tmp/serban-<DATE>.json

# KC restart (import sonrası)
docker compose -f host-compose/data/docker-compose.yml restart keycloak
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
- `host-compose/data/docker-compose.yml` (PG + KC + Vault compose config)
