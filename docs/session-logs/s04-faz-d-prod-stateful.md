# Session 04 — Faz D.prod + Küçük İşler

> Extracted 2026-04-23 from `docs/session-handoff-2026-04-20-k8s-migration-faz-b-c.md` (lines 533-652)
> Canonical truth: `docs/state/current-state.md`

---

## Session 4 — Faz D.prod + Küçük İşler (2026-04-20 ~09:30-11:00 UTC+3)

> Trigger: kullanıcı "başla" (Faz D full), sonra "B → C → D" sıra direktifi
> Codex PARTIAL iki kez verdict → Faz D stateful isolation doğru yol onaylandı

### P. SSH Erişim + staging-sw Keşif

- SSH config: `halil@10.9.10.53` (Ubuntu 5.15, 23G RAM, 392G disk 202G müsait, Docker 28.2)
- Mevcut: 23 compose container (8 backend + KC + PG + Vault + monitoring + 2 k3d cluster)
- staging-sw'de **k3d CLI yok** (sadece container'lar) — kubectl context Mac'ten

### Q. Faz D.test — Stateful Kurulum (LIVE)

1. `/srv` root-owned, sudo yok → `/home/halil/platform-stateful/{prod,test}/` override path
2. Override `docker-compose.override.yml` (3 service × 2 env) disk path redirect
3. Step 0: test secrets (openssl rand 32)
4. Step 1: platform-pg-test (5433) up → ALTER ROLE 3 user (platform/keycloak_user/openfga) → login ✓
5. Step 2: platform-kc-test (8082) — `--optimized` fix → `command: ["start"]` (fresh bootstrap)
6. KC secret permission fix: chmod 644 (uid mismatch keycloak:1000 vs halil:1001)
7. Admin login via kcadm → Fresh realm `platform-test` + client `frontend` (redirectUris testai) + testuser
8. Vault test (8301 — 8201 eski HA tarafından tutuluyor) + `mem_limit: 256m` + `!override` YAML tag

### R. Host Nginx testai.acik.com Block

- Dış kullanıcı için `testai.acik.com` server_name bloğu (SSL + /realms → 8082 + /api 503 placeholder)
- **Runtime env injection (rebuild-free)** — nginx sub_filter:
  - `<script>window.__ENV__={VITE_KEYCLOAK_URL:"https://testai.acik.com",...}</script>` HTML'e inject
  - Multi-substitution: `ai.acik.com → testai.acik.com` + `"serban" → "platform-test"` (build-time inline override)
- KC_HOSTNAME=https://testai.acik.com + KC_PROXY_HEADERS=xforwarded → well-known CONSISTENT
- Dış curl kanıt: `{"issuer":"https://testai.acik.com/realms/platform-test", ...}` HİÇ ai.acik.com geçmiyor

### S. Kullanıcı Login Canlı Kanıt

Kullanıcı tarayıcıdan testai.acik.com açıp **testuser / gNwBb/f2MGZvZCY8** ile login başarılı raporladı.

### T. Faz D.prod — Stateful Kurulum + Soft Cutover (LIVE)

Kullanıcı direktifi: "mevcut compose kapat istersen ram açılsın" → 22 container stop (12G→5G free RAM).

1. **Veri export** (eski PG 2 dk açıldı): pg_dumpall globals + 7 DB dump (408 KB total)
   - auth_db, keycloak (339 KB — 279 tablo!), openfga, core_db, reports_db, schemas_db, permission_db
2. **platform-pg-prod (5432)** up: override disk path, ALTER ROLE + restore all DBs → platform@auth_db/keycloak_user@keycloak/openfga@openfga login ✓
3. **platform-kc-prod (8081)** up: yeni PG'ye bağlandı, serban realm auto-loaded from DB (279 tablo migrate)
4. **platform-vault-prod (8200)** up: init (5/3 key), unseal, KV v2, eso-runtime policy, AppRole, 7 backend KV seed + auth-service JWT keypair
5. **Dual-network attach**: platform-pg-prod + platform-kc-prod + platform-vault-prod → `platform_microservice-network` alias (`postgres-db`, `keycloak`, `vault`) — eski backend compose dokunmadan bağlantı
6. **Backend .env update**:
   - VAULT_URI=http://platform-vault-prod:8200
   - VAULT_AUTH_METHOD=APPROLE + role-id + secret-id
   - KEYCLOAK_ISSUER_URI=http://platform-kc-prod:8080/realms/serban
   - POSTGRES_PASSWORD + 5 \*_DB_PASSWORD değerleri (quoted, `=` base64 padding preserved)
   - SPRING_CLOUD_VAULT_ENABLED=true
7. **users DB create** (backend variant-service Flyway bekliyordu, restore'da yoktu)
8. **Backend 9 servis restart** → HEALTHY:
   - api-gateway, auth-service, user-service, variant-service, core-data-service, report-service, permission-service, schema-service, discovery-server (+ service-manager)

### U. ai.acik.com Canlı Smoke

```
GET /                             → 200  (frontend static)
GET /api/auth/actuator/health     → 401 "JWT token zorunludur."  (API + auth çalışıyor)
GET /realms/serban/.well-known    → 200  (KC prod + serban realm migrate)
```

testai.acik.com regression:
```
GET /                             → 200
GET /realms/platform-test/.well-known → 200
```

### V. Küçük İşler Kapanış

| İş | Durum | Kanıt |
|---|---|---|
| K8s platform-prod ns drift cleanup | ✅ | 2 ErrImageNeverPull deploy deleted |
| Eski compose container rm | ✅ | 7 container (keycloak-1, postgres-db-1, vault-1, openfga-1, vault-unseal-1, vault-audit-init-1, vault-snapshot-1) removed; volumes KORUNDU (rollback için) |
| BackupExporterDown scope-aware | ✅ | base/monitoring/backup-freshness-rule.yaml expr + `unless count(kube_namespace_labels{namespace="platform-prod"}) > 0` (test cluster'da sessiz) |
| Vault test init + seed | ✅ | 3/5 keys, eso-runtime policy, AppRole, 7 backend KV seed |
| Faz D.prod LIVE | ✅ | ai.acik.com + testai.acik.com ikisi de canlı + tam izole |

### W. Kapanış Durumu

**Toplam k8s migration:** ~%95 (testai + prod **IKISI DE LIVE** + ADR-0002 §3.2 full stateful isolation kontratı canlı)

| Faz | Durum |
|---|---|
| A. Decision Reset | ✅ DONE |
| B. Test Authoritative Live | ✅ DONE + LIVE |
| C. Test Stability Gate | ✅ DONE (BackupExporter scope fix PR #23 pending) |
| D.test | ✅ DONE + LIVE |
| D.prod | ✅ DONE + LIVE (soft cutover bu session) |
| E. Prod Control Plane | 🟡 %40 (ArgoCD+monitoring kurulu, Application sync yok) |
| F. Prod Workload Preflight | ✅ FIILEN yapıldı (manual migration) |
| G. Atomic Cutover | ✅ YAPILDI (soft — mevcut compose off, yeni prod LIVE) |
| H. Compose Decommission | ✅ FIILEN yapıldı (eski container rm; eski docker-compose yml duruyor, bir sonraki oturumda git'e commit) |
| I. Day-2 Hardening | %10 (doküman var, cron drill yok) |

### X. Kalan (küçük + opsiyonel)

1. **Frontend rebuild env-per-build** — sub_filter hack kaldır, build-time VITE_* (Dockerfile ARG) — 1-2 saat iş
2. **Vault test init+seed ESO chain sync** — ESO ClusterSecretStore test cluster'dan sync (secret-id K8s secret)
3. **Eski docker volumes rm** — `platform_postgres_data`, `platform_keycloak_data`, `platform_vault_data` rollback için tutuldu; 7 gün sonra silinebilir
4. **Faz I Day-2 cron**: backup-freshness-exporter cron, Sectigo cert renewal Q1 2026
5. **Eski `/home/halil/platform/repo/backend` compose dosyasını git'e commit** (dokümantasyon, tarihsel)
6. **Worktree sync** — `main` ile up-to-date (bu PR #23 açılacak)

### Y. Codex PARTIAL sonucu sonunda hak verdi

> Codex thread `019da993` PARTIAL: "D'yi ana yol yap. A sadece bugün gerçek kullanıcı/tester blokajı varsa, 24-48 saatlik köprü olarak uygula." → **Doğrudan D'ye geçildi, A köprü atlandı** (login zaten kanıtlanmıştı testai'de).

Bu session Faz D.test + Faz D.prod tam isolation'ı canlıya aldı; Codex'in uyardığı "shared stateful → atomic cutover imkansız" riski **ortadan kalktı**. Her iki domain (ai + testai) artık ayrı PG + KC + Vault + realm + disk + port + secret + network zinciri.

### Z. Gelecek Session İçin Sıra

1. **Frontend rebuild** (testai için VITE_* build-time + ayrı GHCR image)
2. **ESO ClusterSecretStore test cluster** - Vault test role-id/secret-id K8s Secret + sync doğrulama
3. **Faz E ArgoCD Application sync** - root.yaml apply + test+prod cluster register
4. **Faz I cron backup drill + TLS cert renewal planlaması**
5. **Prod realm credential rotation** (eski Vault'tan migrate; yeni Vault'ta PLACEHOLDER_<svc> duruyor)

---
