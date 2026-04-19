# S5 Vault Audit Log Retention — Day-2 Ops

> ⚠ **ADR-0002 UPDATE** (2026-04-19): Container env-specific ayrıldı: `platform-vault-prod` + `platform-vault-test`.
> Bu doküman prod context; test instance için komut container adını `platform-vault-test`, port `8201` olarak değiştir.
> İlişkili: [`day-2-governance.md`](./day-2-governance.md) §1.3 Vault Backup.

> **Source:** K8s-6 S5 day-2 ops (Codex iter-8 non-blocking öneri)
> **Kapsam:** Vault audit backend + log rotation + retention policy + review rutini
> **Frekans:** Haftalık review (ops), aylık archive, yıllık purge

---

## 1. Vault Audit Backend Aktif

### 1.1 File Audit Backend Enable

```bash
export VAULT_ADDR=http://<vault-host>:8200
vault login <admin-token>

# File audit backend aktif (idempotent)
vault audit list | grep file_audit || \
vault audit enable -path=file_audit file \
  file_path=/vault/logs/audit.log \
  log_raw=false \
  hmac_accessor=true

# Doğrula
vault audit list
# Beklenen: file_audit/    file    file_path=/vault/logs/audit.log...
```

### 1.2 Docker Compose Volume Mount

```yaml
# host-compose/vault/prod/docker-compose.yml
services:
  vault:
    image: hashicorp/vault:1.15
    volumes:
      - vault-data:/vault/data
      - vault-logs:/vault/logs      # yeni — audit log persist
    # ...

volumes:
  vault-data:
  vault-logs:                        # yeni
```

---

## 2. Log Rotation (logrotate)

### 2.1 Config

```bash
# /etc/logrotate.d/vault
cat <<'EOF' | sudo tee /etc/logrotate.d/vault
/var/lib/docker/volumes/host-compose_vault-logs/_data/audit.log {
    daily
    rotate 90             # 90 gün retention
    compress
    delaycompress
    missingok
    notifempty
    postrotate
        docker exec platform-vault-prod kill -SIGHUP 1 2>/dev/null || true
    endscript
}
EOF

# Test (dry-run)
sudo logrotate -d /etc/logrotate.d/vault

# Manuel force rotation (test)
sudo logrotate -f /etc/logrotate.d/vault
```

### 2.2 Retention Matrisi

| Dönem | Lokasyon | Format | Erişim |
|---|---|---|---|
| **0-90 gün** | Host disk (logrotate) | JSON (her satır event) | Ops direkt |
| **91-365 gün** | Haftalık archive (tar.gz) | Sıkıştırılmış | Arşiv query gerekli |
| **365+ gün** | Purge | — | — |

---

## 3. Haftalık Review Rutini

### 3.1 Audit Log Query Örnekleri

```bash
# Son 7 gün failed auth denemeleri
tail -n 100000 /var/lib/docker/volumes/host-compose_vault-logs/_data/audit.log \
  | jq 'select(.request.operation == "update" and .response.error != null) | {time, path: .request.path, error: .response.error}' \
  | head -50

# AppRole login başarı sayısı (son 24h)
tail -n 100000 audit.log \
  | jq -r 'select(.request.path == "auth/approle/login") | .time' \
  | awk -F'T' '$1 == "'$(date -u +%Y-%m-%d)'" {n++} END {print n" AppRole login bugün"}'

# KV read per servis (son 7 gün)
tail -n 500000 audit.log \
  | jq -r 'select(.request.path | startswith("kv/data/platform/")) | .request.path' \
  | sort | uniq -c | sort -rn
# Beklenen: permission-service + auth-service + diğer 5 servis read dağılımı
```

### 3.2 Review Checklist (haftalık)

- [ ] **Failed auth:** `.response.error != null` → şüpheli IP/pattern var mı?
- [ ] **Unexpected path:** `kv/data/platform/*` dışı path read → policy sızıntı
- [ ] **Token usage anomaly:** Token kullanıcısı bilinmeyen bir path'e ulaştı mı?
- [ ] **Policy change:** `sys/policies/acl/*` update/delete → yetkili ops mı?
- [ ] **Secret create/update:** `kv/data/*` create → beklenen ops iş mi?

### 3.3 Aylık Archive

```bash
#!/usr/bin/env bash
# /home/halil/platform/backup/vault-audit-archive.sh
# Cron: 0 3 1 * *  (her ayın 1'i, 03:00)
set -euo pipefail

ARCHIVE_DIR="/home/halil/platform/backup/vault-audit"
MONTH=$(date -d "1 month ago" +%Y-%m)

mkdir -p "${ARCHIVE_DIR}"

# Son ayın logları topla
tar -czf "${ARCHIVE_DIR}/audit-${MONTH}.tar.gz" \
  /var/lib/docker/volumes/host-compose_vault-logs/_data/audit.log.*.gz 2>/dev/null || true

echo "✓ Archive: ${ARCHIVE_DIR}/audit-${MONTH}.tar.gz"

# 12+ ay eski archive purge
find "${ARCHIVE_DIR}" -name "audit-*.tar.gz" -mtime +365 -delete
```

---

## 4. Alert & Monitoring

### 4.1 Vault Audit Log Exporter (node_exporter textfile veya Promtail)

**Opsiyon A (minimal):** Promtail (mevcut logs-traces stack) `/var/lib/docker/volumes/host-compose_vault-logs/_data/audit.log` dosyasını tail eder → Loki'ye gönderir.

**Opsiyon B (detay):** Custom exporter — audit log'tan metric üretir (failed auth rate, path access count, policy change count).

### 4.2 PrometheusRule (opsiyonel ileri iş)

```yaml
# Eğer custom exporter ile metric üretilirse:
- alert: VaultFailedAuthSpike
  expr: rate(vault_audit_failed_auth_total[5m]) > 0.5
  for: 10m
  labels:
    severity: critical
```

---

## 5. Compliance & İleri İş

- **Audit backend değişmez kuralı:** File backend tek başına yeterli değil compliance için. **Syslog** veya **Socket** ikinci backend eklenebilir (remote log host).
- **Tamper detection:** Log dosyası hash zinciri (append-only guarantee). Vault'un kendisi tamper-resistance sağlamaz — dış immutable storage (S3 Object Lock veya WORM NAS) gerekir compliance için.
- **PII/secret masking:** `log_raw=false` default — secret değerler hash'lenir. `hmac_accessor=true` → accessor ID'ler de hash'lenir.

---

## 6. Referanslar

- Vault docs: <admin-panel> (ops erişim)
- `host-compose/vault/prod/docker-compose.yml` — Vault service + volumes
- `helm-values/loki/values.yaml` — Loki retention (logs-traces stack)
- `helm-values/promtail/values.yaml` — Promtail config
- `docs/S5-disaster-recovery-runbook.md` — Vault snapshot backup referansı
- `bootstrap/vault-policies/README.md` — Policy + AppRole yönetimi
