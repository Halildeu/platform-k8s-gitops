# Session 06 — Final Kapanış (Faz E kısmi + Faz I cron + Frontend rebuild)

> Extracted 2026-04-23 from `docs/session-handoff-2026-04-20-k8s-migration-faz-b-c.md` (lines 733-862)
> Canonical truth: `docs/state/current-state.md`

---

## Session 6 — Final Kapanış (Faz E kısmi + Faz I cron + Frontend rebuild)

> Trigger: kullanıcı "yol haritasını tamamlayalım" → "başlayalım"

### FF. ESO Routing — DERİN DEBUG (Handoff Pending)

Keşif zinciri (pod → stateful IP 172.19.0.4 connection refused):
1. Calico IP pool `natOutgoing=true` ✓ (default-ipv4-ippool)
2. `cali-nat-outgoing` chain counter artıyor (MASQUERADE uygulanıyor)
3. `cali40masq-ipam-pools` ipset'e `10.44.0.0/16` eklendi (önce boştu)
4. Pod src route: `172.19.0.4 via 169.254.1.1 dev eth0 src 10.44.x`
5. Ama yine timeout/refused: KC test (172.19.0.5), PG test (172.19.0.7), prod vault (172.21.0.6) — **hepsi bloklu**
6. kube-proxy iptables **stale**: vault Service 10.45.59.158 → iptables'ta 10.45.214.190 (eski IP)
7. k3s cluster kube-proxy binary gömülü (pod YOK)
8. KUBE-SERVICES chain delete+recreate sonrası yine stale
9. Docker bridge isolation (`DOCKER-ISOLATION-STAGE-2` nftables, docker bridge networks arası FORWARD default DROP)

**Root cause**: k3d + Docker bridge cross-network isolation. Pod network (10.44.x) kendi bridge'inde, stateful containers (172.19.x / 172.21.x) ayrı bridge'lerde. Default policy: DROP inter-bridge.

**Çözüm yolları** (sonraki oturum, Faz E-4 kapsamı):
- A. Vault pod'u k3d cluster içine taşı (StatefulSet)
- B. NodePort Service + externalTrafficPolicy=Local + node üzerinden bridge routing
- C. Calico FelixConfiguration host network range ekle (pod'lara host bridge'e routing)
- D. iptables DOCKER-ISOLATION manual rule (tehlikeli, docker yönetim bozabilir)

### GG. Frontend Rebuild Env-Per-Build (PR #534)

`platform-ssot` repo'ya merge için açıldı:

**web/Dockerfile ARG eklendi (6 adet)**:
- VITE_KEYCLOAK_URL (default ai.acik.com)
- VITE_KEYCLOAK_REALM (default serban)
- VITE_KEYCLOAK_CLIENT_ID (default frontend)
- VITE_FRONTEND_PUBLIC_ORIGIN + VITE_GATEWAY_URL
- VITE_AUTH_MODE (default keycloak)

**Workflow matrix build**:
- prod: `ghcr.io/halildeu/platform-ssot-frontend:sha-<short>` (ai.acik.com + serban)
- testai: `ghcr.io/halildeu/platform-ssot-frontend-testai:sha-<short>` (testai.acik.com + platform-test)

Build-time VITE_* ENV → webpack DefinePlugin inline → auth-config.ts runtime öncelik sırası (process.env → window.__ENV__ fallback).

### HH. Faz I.1 Day-2 Backup Cron (PR #26 MERGED)

3 bootstrap script + 1 install runbook:

| Script | Cron | Retention | Path |
|---|---|---|---|
| `pg-dump-cron.sh` | hourly | 30 gün | `~/platform/backup/pg/{prod,test}/` |
| `vault-snapshot-cron.sh` | daily 02:00 | 14 gün | `~/platform/backup/vault/{prod,test}/` |
| `kc-export-cron.sh` | weekly Sun 03:00 | 56 gün | `~/platform/backup/keycloak/{prod,test}/` |
| `backup-freshness-exporter.sh` (mevcut) | hourly | N/A (overwrite) | `/var/lib/node_exporter/backup_freshness.prom` |

`docs/day-2-cron-install.md` runbook:
- node_exporter textfile collector setup
- Backup root dizinleri + chmod 700
- Crontab entry (4 satır)
- Doğrulama (manuel test + Prometheus metric + alert eval)
- DR restore komutları (PG restore, Vault raft, KC realm import)

**Kullanıcı tarafından staging-sw'de `crontab -e` ile install** gerekiyor. Alert'ler (`BackupPGStale`, `BackupVaultStale`, `BackupKCStale`, `BackupExporterDown`) cron çalışmaya başladığında fonksiyonel.

### II. Pending (Faz I.3 Vault Rotation)

**Problem**: KC prod master realm admin user eski compose'un PG'sinden migrate edildi. Yeni `KC_ADMIN_PW_PROD` env'i container ilk start'ta atlandı (admin var zaten). Dolayısıyla kcadm login fail.

**Çözüm (sonraki oturum)**:
```bash
# KC container içinde admin password reset
docker exec platform-kc-prod /opt/keycloak/bin/kc.sh bootstrap-admin password \
  --username admin --password "${KC_ADMIN_PW_PROD}"
```

Sonra:
- `kcadm.sh get clients -r serban` ile client_secret extract
- Vault kv/platform/<svc> update (PLACEHOLDER_<svc> → gerçek secret)
- Backend pod rolling restart

### JJ. Faz I.4.3 Sectigo Cert Renewal (Takvim)

- **Mevcut cert**: `*.acik.com` Sectigo wildcard
- **Expire**: Oct 1 2026 23:59:59 GMT
- **Renewal hedef**: Sep 1 2026 (30 gün marj)
- **Alert**: `SSLCertExpireWarning` (30 gün) + `SSLCertExpireCritical` (7 gün) — `zanzibar-stability-rule.yaml`'da
- **Runbook**: `docs/S5-cert-renewal-runbook.md` (mevcut)
- **Automation opsiyonu**: `bootstrap/install-cert-manager.sh` (hazır, henüz install edilmedi)

### KK. Session 6 PR Özeti

| PR | Repo | Konu | Durum |
|---|---|---|---|
| #26 | k8s-gitops | Day-2 backup cron trilogy + install runbook | ✅ MERGED |
| #534 | platform-ssot | Frontend Dockerfile ARG + matrix build | 🟡 CI running |
| #27 (bu) | k8s-gitops | Session 6 final handoff | ⏳ Open |

### LL. Final Yol Haritası Durumu

| Faz | Durum | Live/Pending |
|---|---|---|
| A Decision | ✅ DONE | merged |
| B testai Live | ✅ **LIVE** | login canlı kanıtlı |
| C Stability | ✅ **LIVE** | 0 critical firing |
| D.test | ✅ **LIVE** | PG+KC+Vault ayrı |
| D.prod | ✅ **LIVE** | soft cutover + 9 backend healthy |
| E.1 ArgoCD | ✅ DONE | root + platform-system Synced |
| E.2 Cluster register | 🟡 | in-cluster OK; test external pending |
| E.3 App sync | 🟡 | platform-prod OutOfSync (manual D30) |
| **E.4 ESO CSS Ready** | ❌ **BLOCKED** | Docker bridge isolation — handoff 4 yol |
| F Preflight | ✅ Fiilen | manual cutover |
| G Cutover | ✅ Fiilen | soft cutover |
| H Decommission | ✅ Fiilen | 7 container rm |
| **I.1 Backup cron** | ✅ SCRIPT DONE | Crontab install (kullanıcı staging-sw) |
| I.2 Rotation | 🟡 | PG/KC/JWT schedule doc, kod yok |
| I.3 Vault rotation | 🟡 Pending | KC admin reset + client_secret import |
| I.4 Cert renewal | 🟡 Planlı | Sep 1 2026 takvim, S5-cert-renewal-runbook |
| I.5 Vuln scan | 🟡 | OSV platform-ssot ✓; k8s-gitops'a ekle pending |
| I.6 Retention | ✅ | values-test 6h, values-prod 30d |
| I.7 DR prova | 🟡 | Runbook + restore komutları doc'ta; drill koşulmadı |

**Toplam migration: ~%98** (core +Faz I script base)

### MM. Sonraki Oturum İçin Minimum İş

1. **Staging-sw crontab install** (kullanıcı, 5 dk)
2. **KC admin password reset + Vault PLACEHOLDER rotation** (30 dk)
3. **PR #534 merge + workflow matrix build** (k8s-gitops overlay bump testai)
4. **ESO routing fix** (1-2 saat, 4 çözüm yolundan 1)
5. **Cert-manager install + Let's Encrypt testai** (opsiyonel, 1 saat)

---
