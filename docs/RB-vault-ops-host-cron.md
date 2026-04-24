# RB — Vault Ops Host Cron (staging-sw)

**Scope:** Faz 18.4 Vault Ops Replacement.
**Replaces:** compose sidecar'lar `platform-vault-snapshot-1` + `platform-vault-audit-init-1` (2026-04-24 Faz 18.4 Phase 2 kanıt: iki container ZOMBIE, `sleep infinity` — host cron zaten authoritative Apr 20'den beri).
**Target host:** staging-sw (Ubuntu, root token files per-env).
**Topology (live):** **iki ayrı vault container** `platform-vault-prod` + `platform-vault-test` (D6 stateful tier, ADR-0002 §0.5 + D34 per-realm izolasyon).
**Token files:** `/home/halil/bootstrap-drill/vault-init-prod.json` + `vault-init-test.json`.
**Codex AGREE:** thread `019dc04d` (guardrail: flock + unique temp + idempotent ensure).

---

## Tetik

- Faz 18.3 (service-manager retire) MERGED.
- Faz 18.4 Phase 1 PR merged → host cron install / hotfix tetikler.

## Önkoşul

```bash
# Staging-sw host üzerinde, halil kullanıcısı
test -f /home/halil/bootstrap-drill/vault-init-prod.json
test -f /home/halil/bootstrap-drill/vault-init-test.json
docker ps --filter name=platform-vault-prod --filter status=running | grep -q platform-vault-prod
docker ps --filter name=platform-vault-test --filter status=running | grep -q platform-vault-test
test -x /home/halil/platform-k8s-gitops/bootstrap/vault-snapshot-cron.sh
test -x /home/halil/platform-k8s-gitops/bootstrap/vault-audit-init-cron.sh
```

## Adımlar

### 1. Repo pull (staging-sw)

```bash
cd /home/halil/platform-k8s-gitops
git pull origin main
ls -l bootstrap/vault-snapshot-cron.sh bootstrap/vault-audit-init-cron.sh  # +x permission
```

**Beklenen:** iki dosya `-rwxrwxr-x`, en son commit Faz 18.4 Phase 1 (veya hotfix).
**Fail sinyali:** dosya yok → PR merge değil veya pull yapılmadı.

### 2. Manual smoke — snapshot (prod + test per-env)

```bash
bash /home/halil/platform-k8s-gitops/bootstrap/vault-snapshot-cron.sh
```

**Beklenen (~10sn):**
```
[vault-snapshot] SNAPSHOT prod → /home/halil/platform/backup/vault/prod/vault-snapshot-YYYYMMDD-HHMM.snap (tmp=...)
[vault-snapshot] OK prod size=XK
[vault-snapshot] SNAPSHOT test → /home/halil/platform/backup/vault/test/vault-snapshot-YYYYMMDD-HHMM.snap (tmp=...)
[vault-snapshot] OK test size=YK
[vault-snapshot] DONE YYYYMMDD-HHMM
```

**Doğrulama:**
```bash
ls -lh /home/halil/platform/backup/vault/prod/ | tail -2
ls -lh /home/halil/platform/backup/vault/test/ | tail -2
# Beklenen: 2 env'de size > 20K (Vault state küçük ama empty değil)
```

**Fail sinyali:**
- `SKIP ${env}: no token file` → token file yok.
- `FAIL ${env}` → Vault sealed veya token invalid.

### 3. Manual smoke — audit-init (prod + test)

```bash
bash /home/halil/platform-k8s-gitops/bootstrap/vault-audit-init-cron.sh
```

**Beklenen:**
```
[vault-audit-init] OK prod: audit device file/ already enabled
[vault-audit-init] OK test: audit device file/ already enabled
```

Idempotent ensure: halihazırda enable olduğu için `already enabled` döner — **başarı**.

### 4. Cron install (zaten mevcut 2026-04-20'den)

**Mevcut staging-sw crontab** (Apr 20 install):
```cron
0 2 * * *   /home/halil/platform-k8s-gitops/bootstrap/vault-snapshot-cron.sh >> /home/halil/platform-backup-vault-snapshot.log 2>&1
```

**Audit-init ekleme** (Faz 18.4 Phase 2):
```bash
crontab -e
# Ekle:
15 2 * * *  /home/halil/platform-k8s-gitops/bootstrap/vault-audit-init-cron.sh >> /home/halil/platform-backup-vault-audit-init.log 2>&1
```

**Not:**
- Snapshot 02:00, audit-init 02:15 offset (race koruma).
- flock script-level mevcut (paralel fail-safe).

### 5. Doğrulama — crontab

```bash
crontab -l | grep vault
```

**Beklenen:** snapshot + audit-init iki satır.

### 6. Backup freshness exporter (mevcut)

`bootstrap/backup-freshness-exporter.sh` zaten `vault-snapshot-*.snap` scan ediyor (prod + test subdir). Prometheus:

```promql
time() - backup_last_success_seconds{kind="vault"}  # < 90000 (25h) = GREEN
```

## Rollback

Cron entry'sini kaldır:

```bash
crontab -e  # vault satırlarını sil
```

Compose sidecar'lar zaten zombie (`sleep infinity`) — backup kesintisi OLMAZ (host cron tek authoritative). Rollback için bile compose sidecar "re-activate" edilemez; alternatif sadece farklı host ile snapshot almak.

## Devam eşiği

- Phase 1 PR merge PASS ✓ (veya hotfix PR merge)
- Manuel smoke prod + test 2 env'de PASS ✓
- Zaten aktif cron (Apr 20 install) + 4 gün başarılı tick kanıtı (`/home/halil/platform-backup-vault-snapshot.log` Apr 21-24 "OK prod/test" satırları)

## Referans

- PLAN.md §Faz 18.4 (lines 1240-1245)
- Codex thread `019dc04d` AGREE
- ADR-0002 §0.5 D6 stateful tier + §3.6 vault-policies env-split
- docs/S5-vault-audit-retention.md (idempotent ensure pattern)
- docs/day-2-cron-install.md (PG/KC/vault cron trilogy)
- bootstrap/vault-snapshot-cron.sh (multi-vault loop)
- bootstrap/vault-audit-init-cron.sh (multi-vault idempotent)
- bootstrap/backup-freshness-exporter.sh (node_exporter textfile)
