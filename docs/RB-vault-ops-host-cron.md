# RB — Vault Ops Host Cron (staging-sw)

**Scope:** Faz 18.4 Vault Ops Replacement.
**Replaces:** compose sidecar'lar `platform-vault-snapshot-1` (24h loop) + `platform-vault-audit-init-1` (one-shot).
**Target host:** staging-sw (Ubuntu, root token file `/home/halil/bootstrap-drill/vault-init-prod.json`).
**Topology:** tek `platform-vault-1` container (D6 stateful tier, ADR-0002 §0.5).
**Codex AGREE:** thread `019dc04d` (guardrail: flock + unique temp + idempotent ensure).

---

## Tetik

- Faz 18.3 (service-manager retire) MERGED.
- Faz 18.4 Phase 1 PR merged → host'ta cron install.

## Önkoşul

```bash
# Staging-sw host üzerinde, halil kullanıcısı
test -f /home/halil/bootstrap-drill/vault-init-prod.json  # root token JSON
docker ps --filter name=platform-vault-1 --filter status=running | grep -q platform-vault-1
test -x /home/halil/platform-k8s-gitops/bootstrap/vault-snapshot-cron.sh
test -x /home/halil/platform-k8s-gitops/bootstrap/vault-audit-init-cron.sh
```

## Adımlar

### 1. Repo pull (staging-sw)

```bash
cd /home/halil/platform-k8s-gitops
git pull origin main  # Faz 18.4 Phase 1 merge sonrası
ls -l bootstrap/vault-snapshot-cron.sh bootstrap/vault-audit-init-cron.sh  # +x permission
```

**Beklenen:** iki dosya `-rwxr-xr-x`, en son commit Faz 18.4 Phase 1.
**Fail sinyali:** dosya yok → PR merge değil veya pull yapılmadı.

### 2. Manual smoke — snapshot

```bash
sudo -u halil bash /home/halil/platform-k8s-gitops/bootstrap/vault-snapshot-cron.sh
```

**Beklenen (~5sn):**
```
[vault-snapshot] SNAPSHOT → /home/halil/platform/backup/vault/vault-snapshot-YYYYMMDD-HHMM.snap (tmp=/tmp/snap-<pid>-...)
[vault-snapshot] OK size=XM
[vault-snapshot] DONE YYYYMMDD-HHMM
```

**Doğrulama:**
```bash
ls -lh /home/halil/platform/backup/vault/
du -h /home/halil/platform/backup/vault/vault-snapshot-*.snap | tail -1
# Beklenen: size > 100K (Vault state küçük ama empty değil)
```

**Fail sinyali:**
- `FAIL: no token file` → token file yok veya permission kötü.
- `FAIL snapshot save/cp` → Vault sealed veya token invalid.

### 3. Manual smoke — audit-init

```bash
sudo -u halil bash /home/halil/platform-k8s-gitops/bootstrap/vault-audit-init-cron.sh
```

**Beklenen:**
```
[vault-audit-init] OK: audit device file/ already enabled
```
(compose sidecar zaten enable etmiş olduğu için idempotent ensure `already enabled` döner — bu **başarı**.)

### 4. Cron install

```bash
sudo -u halil crontab -l > /tmp/cron-backup-$(date +%s).txt  # safety backup
sudo -u halil crontab -e
```

Ekle:
```cron
# Faz 18.4 Vault Ops (replace compose vault-snapshot-1 + vault-audit-init-1)
# Codex AGREE thread 019dc04d
0 2 * * * /home/halil/platform-k8s-gitops/bootstrap/vault-snapshot-cron.sh >> /home/halil/platform/logs/vault-snapshot-cron.log 2>&1
15 2 * * * /home/halil/platform-k8s-gitops/bootstrap/vault-audit-init-cron.sh >> /home/halil/platform/logs/vault-audit-init-cron.log 2>&1
```

**Not:**
- Snapshot 02:00, audit-init 02:15 → compose sidecar cadence'inden offset (race koruma).
- flock script-level mevcut (paralel fail-safe).

### 5. Doğrulama — crontab

```bash
sudo -u halil crontab -l | grep vault
```

**Beklenen:** iki satır üstteki gibi.

### 6. Log dizini

```bash
sudo -u halil mkdir -p /home/halil/platform/logs/
sudo -u halil touch /home/halil/platform/logs/vault-snapshot-cron.log
sudo -u halil touch /home/halil/platform/logs/vault-audit-init-cron.log
```

### 7. Backup freshness exporter entegrasyonu (isteğe bağlı, Phase 2+)

`bootstrap/backup-freshness-exporter.sh` zaten `vault-snapshot-*.snap` scan ediyor (`bootstrap/backup-freshness-exporter.sh:44`). Host cron ilk tick sonrası Prometheus'ta:

```promql
time() - backup_last_success_seconds{kind="vault"}  # < 90000 (25h) = GREEN
```

**PrometheusRule kontrol:** `docs/monitoring-ops.md` altında `VaultBackupStale` alert (eğer yoksa Phase 2'de eklenecek).

## Rollback

Cron entry'sini kaldır:

```bash
sudo -u halil crontab -e  # vault satırlarını sil
```

Compose sidecar hâlâ ayakta (Phase 4'e kadar dokunulmadı) — otomatik backup devam eder.

## Devam eşiği

- Phase 1 PR merge PASS ✓
- Manuel smoke (snapshot + audit-init) PASS ✓
- 1 cron tick başarı (02:00 ertesi gün) → Phase 4 eligible

## Referans

- PLAN.md §Faz 18.4 (lines 1240-1245)
- Codex thread `019dc04d` AGREE
- ADR-0002 §0.5 D6 stateful tier + §3.7 compose retention
- docs/S5-vault-audit-retention.md (idempotent ensure pattern)
- docs/day-2-cron-install.md (PG/KC/vault cron trilogy)
- bootstrap/vault-snapshot-cron.sh
- bootstrap/vault-audit-init-cron.sh
- bootstrap/backup-freshness-exporter.sh (node_exporter textfile)
