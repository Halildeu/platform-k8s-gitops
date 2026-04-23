# Day-2 Cron Install Runbook (Faz I)

> ADR-0002 §0.5 + `docs/day-2-governance.md` + `kustomize/base/monitoring/backup-freshness-rule.yaml`
> **Scope**: staging-sw (tek host) — cron staging-sw'deki root veya halil crontab
> **Install sonrası**: Prometheus alert'leri (`BackupPGStale`, `BackupVaultStale`, `BackupKCStale`, `BackupExporterDown`) gerçek data ile eval eder

## Hazırlık (tek seferlik)

### node_exporter textfile collector dizini
```bash
sudo mkdir -p /var/lib/node_exporter
sudo chown nobody:nogroup /var/lib/node_exporter   # node_exporter user
sudo chmod 755 /var/lib/node_exporter
```

node_exporter args'a ekle (`/etc/systemd/system/node_exporter.service` veya docker compose):
```
--collector.textfile.directory=/var/lib/node_exporter
```

### Backup root dizinleri
```bash
mkdir -p /home/halil/platform/backup/{pg,keycloak,vault}/{prod,test}
chmod 700 /home/halil/platform/backup
```

## Cron Entry (halil crontab)

`crontab -e` ile ekle:

```cron
# Faz I.1 Day-2 backup cron
# backup-freshness-exporter — her saat başı (metric fresh kalır)
0 * * * *   /home/halil/platform-k8s-gitops/bootstrap/backup-freshness-exporter.sh >> /var/log/platform-backup-freshness.log 2>&1

# PG dump — her saat başı (prod + test, pg_dumpall)
5 * * * *   /home/halil/platform-k8s-gitops/bootstrap/pg-dump-cron.sh >> /var/log/platform-pg-dump.log 2>&1

# Vault Raft snapshot — günlük 02:00
0 2 * * *   /home/halil/platform-k8s-gitops/bootstrap/vault-snapshot-cron.sh >> /var/log/platform-vault-snapshot.log 2>&1

# KC realm export — haftalık Pazar 03:00
0 3 * * 0   /home/halil/platform-k8s-gitops/bootstrap/kc-export-cron.sh >> /var/log/platform-kc-export.log 2>&1

# DR drill quarterly — her 3 ayın 1'i 03:00 (Ocak/Nisan/Temmuz/Ekim) — Faz 12 PLAN.md D23
# SKIP_KC=0 default (full drill: PG+Vault+KC). Prometheus textfile metric: dr_drill_last_run_success
0 3 1 */3 * /home/halil/platform-k8s-gitops/bootstrap/dr-drill-cron.sh >> /var/log/platform-dr-drill.log 2>&1
```

## Doğrulama

### 1. Scripts executable
```bash
chmod +x /home/halil/platform-k8s-gitops/bootstrap/*.sh
```

### 2. Manuel test (cron beklemeden)
```bash
bash /home/halil/platform-k8s-gitops/bootstrap/pg-dump-cron.sh
ls -la /home/halil/platform/backup/pg/{prod,test}/
```

### 3. Prometheus metric
```bash
# node_exporter textfile metric dosyası
cat /var/lib/node_exporter/backup_freshness.prom

# Prometheus UI query (port-forward k3d-prod monitoring):
# backup_last_success_timestamp_seconds
# Beklenen: 3 satır (pg, kc, vault) güncel Unix timestamp
```

### 4. Alert eval
```bash
# Prometheus UI: /alerts
# BackupPGStale: 24h'den eski ise warning firing
# BackupPGCritical: 48h'den eski ise critical firing
# BackupVaultStale: 24h'den eski ise warning
# BackupKCStale: 8 gün'den eski ise warning
# BackupExporterDown: metric absent ise critical (prod-only scope)
```

## Retention Özet

| Tip | Periyot | Retention | Path |
|---|---|---|---|
| PG pg_dumpall | Hourly | 30 gün (720 dosya max) | `~/platform/backup/pg/{prod,test}/` |
| Vault snapshot | Daily 02:00 | 14 gün | `~/platform/backup/vault/{prod,test}/` |
| KC realm export | Weekly Sun 03:00 | 56 gün (8 hafta) | `~/platform/backup/keycloak/{prod,test}/` |
| Freshness exporter | Hourly | N/A (overwrite) | `/var/lib/node_exporter/backup_freshness.prom` |

## Disaster Recovery Kullanım

### PG restore (eski dump'tan)
```bash
# Son dump seç
LATEST=$(ls -t ~/platform/backup/pg/prod/pg_dumpall_*.sql.gz | head -1)

# Restore
zcat "${LATEST}" | docker exec -i platform-pg-prod psql -U postgres

# Post-restore: ALTER ROLE (bootstrap-drill'den gerçek pw)
```

### Vault restore (raft snapshot)
```bash
LATEST=$(ls -t ~/platform/backup/vault/prod/vault-snapshot-*.snap | head -1)
docker cp "${LATEST}" platform-vault-prod:/tmp/restore.snap
docker exec -e VAULT_TOKEN="${ROOT_TOKEN}" platform-vault-prod vault operator raft snapshot restore /tmp/restore.snap
```

### KC realm restore
```bash
LATEST=$(ls -t ~/platform/backup/keycloak/prod/serban-*.json.gz | head -1)
zcat "${LATEST}" > /tmp/realm-import.json
# Import via kcadm.sh or Admin UI → Realm Settings → Import
```

## Referanslar
- [ADR-0002 §0.5 Kritik Blocker #3](./adr/0002-single-host-dual-cluster.md)
- [day-2-governance.md](./day-2-governance.md)
- [S5-disaster-recovery-runbook.md](./S5-disaster-recovery-runbook.md)
- [kustomize/base/monitoring/backup-freshness-rule.yaml](../kustomize/base/monitoring/backup-freshness-rule.yaml)
