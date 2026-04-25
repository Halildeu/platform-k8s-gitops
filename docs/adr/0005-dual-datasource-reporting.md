# ADR-0005: Dual DataSource Reporting (PG platform + Workcube MSSQL read-only live)

**Status**: Accepted (2026-04-24, post-Faz-19.8)
**Superseded by**: —
**Date**: 2026-04-24
**Context owner**: Faz 19 Reports canonical truth + User direktifi "daha birçok rapor yapacağız kalıcı uzun vadeli"
**Codex review**: thread `019dc10b` AGREE (Option B confirmed, D19 Service+Endpoints pattern)

---

## Context

### User mandate (2026-04-24)
> "daha birçok rapor yapacağız kalıcı uzun vadeli olan hangisi"

User, aktif raporlama geliştirmesi devam edecek ve Workcube Mikrolink ERP'nin authoritative data kaynağı olarak **değişmeyeceğini** bildiriyor. Raporların **live ERP verisi** göstermesi gerekiyor; snapshot/stale kabul edilemez.

### Mevcut durum (Faz 19.7 sonrası)

- **report-service** K8s platform-prod ns'de deployed, PG'ye işaret ediyor (`jdbc:postgresql://postgres:5432/reports_db`)
- **Workcube MSSQL** (10.9.193.201:1433) authoritative ERP data kaynağı (user bizim ekosistem değil)
- **Faz 16 MSSQL→PG data contract** DRAFT (44 tablo, `pending_manual_validation`, Flyway V16 plan)
- **Frontend** mfe-reporting + mfe-shell/reports (ReportBuilderWizard + DashboardBuilder) kaynak platform-web'de; K8s deployment'ında erişilebilir (200 response, ama backing data bridge yok)

### Repo'da zaten yorumlu kontrat (Codex tespiti)

- `kv/platform/mssql-external` Vault path dokümante
- `REPORT_MSSQL_ENABLED`, `SCHEMA_MSSQL_ENABLED` feature flags planlı
- `kustomize/base/apps/{report,schema}-service/ops/externalsecret.yaml` yorumlu ama hazır
- NetPol default-deny (`kustomize/base/netpol/default-deny.yaml`); 1433 allowlist yok
- Mevcut D19 pattern (`kustomize/base/host-services/`: postgres-svc, keycloak-svc, vault-svc)

---

## Decision

**Dual DataSource Reporting mimari kabul edildi:**

1. **PG = platform-native data** authoritative:
   - `reports_db` (custom_reports Flyway V2)
   - User accounts + permissions + scoped allow + audit logs
   - Platform metadata (menu, role preset, dashboard layout)
   - Gitops kontrolünde (flyway migrations platform-backend repo'da)

2. **MSSQL = Workcube ERP data** read-only live:
   - report-service secondary DataSource (`@Qualifier("mssqlReadOnly")`)
   - Raporlar query-time canlı veri çeker (snapshot YOK)
   - Yeni rapor = yeni query (yeni migration değil)
   - Workcube tarafı authoritative (user bizim değil)

3. **Network bridge = D19 Service+Endpoints** (ExternalName değil):
   - `kustomize/base/host-services/workcube-mssql-svc.yaml` yeni (mevcut pg/kc/vault pattern)
   - Service+Endpoints `10.9.193.201:1433`
   - NetworkPolicy `allow-egress-workcube-mssql` sadece `report-service` + `schema-service` podSelector

4. **Security guardrails**:
   - Workcube admin read-only DB user (Workcube tarafında yaratılmalı — action required)
   - Vault `kv/platform/mssql-external`: username + password + JDBC URL
   - ESO ExternalSecret → Secret (report-service + schema-service mount)
   - NetPol scoped (default-deny korunur, sadece 2 servis egress 1433)
   - Query timeout + row limit (application level)
   - UI "arbitrary SQL" YOK (parametric queries only, template-based)

5. **Runtime degraded mode** (fail-fast değil):
   - MSSQL unreachable → PG-backed endpoint'ler çalışır
   - MSSQL-gerektiren raporlar 503 + retry-after
   - Health readiness'e MSSQL coupling YASAK (aksi halde pod evict/restart döngüsü)
   - MSSQL connectivity ayrı metric/indicator

6. **Schema discovery = schema-service introspection**:
   - Mevcut Faz 16.1 annex 2A crawler allowlist olarak (44 tablo whitelist)
   - UI'ya exposed schema limited
   - Caching + refresh policy

---

## Consequences

### Pozitif

- **Live data**: raporlar her sorguda taze ERP verisi (user'ın "daha birçok rapor" direktifi için doğru pattern)
- **Yeni rapor hızı**: yeni query = yeni migration değil; ERP schema'ya direkt erişim
- **Platform ↔ ERP net sınır**: PG bizim, MSSQL Workcube
- **Stale riski YOK**: Workcube ERP değişiklikleri otomatik görünür
- **Low migration cost**: Faz 16 annex 2A allowlist olarak tekrar değerli; "full migration" yükü kalkar
- **Repo hazır**: Vault path + ESO skeleton + D19 pattern zaten kontratta

### Negatif

- **Runtime ERP dependency**: Workcube MSSQL kesintisi → MSSQL-backed raporlar 503 (degraded; PG-backed normal çalışır)
- **Dual DataSource complexity**: Spring Boot `@Qualifier` routing, iki tx manager (PG transactional, MSSQL read-only)
- **Security**: Workcube tarafında read-only user yaratımı gerekli (external dependency)
- **Performance**: analytical aggregation raporları ERP'ye yük binebilir (future: CDC/ETL materialization opsiyonu)

### Nötr

- **Faz 16 data contract scope değişir**: "full migration" yerine "allowlist + curated PG dataset (opsiyonel)"
- **Annex 2A** (44 tablo) → allowlist dokümantasyonu
- **Flyway V16 plan** PG-native platform analytics için kalır (opsiyonel, baseline değil)

---

## Alternatives Considered

### Alternative A: Full Faz 16 MSSQL → PG migration

- MSSQL 44 tablo → PG one-time copy
- Flyway V16 orchestration
- **Red flag**: snapshot anından staleness (Workcube update'leri PG'ye yansımaz)
- **Red flag**: her ERP tablo değişikliği için re-migration veya CDC eklenmeli (operational overhead)
- **Red flag**: "daha birçok rapor" user direktifi için yanlış pattern

Reddedildi. Ancak sınırlı curated dataset için opsiyon olarak kalır (ör. "bu aggregation ERP'ye yük bindiriyor, günlük snapshot yeterli").

### Alternative C: ExternalName DNS bridge

- K8s Service type ExternalName → 10.9.193.201
- **Red flag**: repo D19 pattern (Service+Endpoints) ile uyumsuz
- **Red flag**: NetPol egress kuralı ExternalName ile çalışmaz (CNI selector pod→external IP gerekir, DNS resolve farklı)

Reddedildi. D19 Service+Endpoints pattern authoritative.

### Alternative D: CDC (Change Data Capture)

- SQL Server CDC/Change Tracking ERP tarafında enable
- PG'ye real-time replication (Debezium vs)
- **Red flag**: Workcube tarafında enable gerekli (operational ownership user'ın değil)
- **Red flag**: baseline için overkill; sadece analytical materialization ihtiyacı çıkarsa

Deferred. Baseline Dual DataSource sonrası performance kötüleşirse devreye girer.

---

## Implementation Status

### Faz 19.MSSQL impl (planned, post-cutover 19.9)

**Prereq**: Workcube admin read-only DB user yaratsın (scope: allowlist tablolar, SELECT only).

**Gitops tarafı:**
1. `kustomize/base/host-services/workcube-mssql-svc.yaml` (yeni, D19 pattern)
2. `kustomize/base/netpol/allow-egress-workcube-mssql.yaml` (report-service + schema-service podSelector, 1433 egress)
3. `kustomize/base/apps/report-service/ops/externalsecret.yaml` uncomment + activate
4. `kustomize/base/apps/schema-service/ops/externalsecret.yaml` uncomment + activate
5. `kustomize/overlays/{test,prod}/` secret sealer path konfig

**Vault:**
- `vault kv put kv/platform/mssql-external username=... password=... jdbc_url=jdbc:sqlserver://...`

**Backend tarafı (platform-backend repo):**
1. `report-service` secondary DataSource bean (`@Qualifier("mssqlReadOnly")`)
2. JdbcTemplate MSSQL routing
3. Query timeout + row limit
4. Health indicator ayrı (readiness coupling YOK)
5. Metric: `mssql_query_latency`, `mssql_query_errors`
6. `schema-service` introspection lane (opsiyonel) allowlist

**Frontend (platform-web):**
- mfe-reporting ReportBuilderWizard → schema-service introspection API (allowlist)
- Query param template (no arbitrary SQL)

**Exit criteria:**
- `ai.acik.com/admin/reports` rapor builder MSSQL schema görünür (allowlist)
- Canlı ERP sorgu → chart + grid renderer (user'ın beklediği eski UX)
- NetPol enforce (diğer pod'lar 1433'e erişemez)
- MSSQL kesinti smoke: health degraded, K8s restart YOK

---

## Reversal Conditions

Bu ADR supersede edilirse:
1. Workcube ERP authoritative değişir (yeni ERP sistemi gelir) → ADR revize
2. Raporlar sürekli degraded (MSSQL connectivity kararsız) → CDC eklenir (Alternative D)
3. Performance critical reports (analytical aggregation) → subset ETL + curated PG (Alternative A kısmi)

---

## Faz 20 Addendum (2026-04-25): Bridge proxy decommission + 3-realm exception

**Bridge proxy decommissioned** (PR #138 LIVE):
- Calico `containerIPForwarding=Enabled` (Faz 20 PR #136) → pod direct → 10.9.193.201:1433
- Service `port: 11433` (Vault JDBC URL backward compat) + `targetPort: 1433` (Endpoints)
- Endpoints test+prod: `10.9.193.201:1433` (her iki cluster aynı external IP)
- 2 socat container silindi: `workcube-mssql-proxy-{test,prod}`

**3-realm izolasyon exception**: Workcube MSSQL test+prod tarafından **ortak** read-only external dependency. Strict D34 izolasyon kuralı açısından bu bilinçli bir istisnadır:

| Realm | Workcube MSSQL bağımlılık |
|---|---|
| dev (Mac) | YOK (Faz 17.1 isolation hardening, vault + workcube Service kaldırıldı) |
| test (Ubuntu) | 10.9.193.201:1433 read-only (workcube_mikrolink schema crawl + reports) |
| prod (Ubuntu) | 10.9.193.201:1433 read-only (aynı external source) |

**Kalıcı hedef** (Faz 16 migration roadmap):
- PG primary, MSSQL secondary/opsiyonel
- 16.0 Data Contract (DRAFT, mevcut)
- 16.2 Flyway V16 PG canonical (DRAFT, mevcut)
- 16.3 ETL stand-alone worker (yapılacak)
- 16.5 Source-read cutover (`*_MSSQL_ENABLED=false` flag)
- 16.8 MSSQL decommission Aşama 1-5

Bu cutover sonrasında Workcube ortak external bağımlılığı son bulacak; her realm kendi PG canonical'inde self-contained olacak.

**dev realm self-containment rule** (Faz 17.1 hardening):
- `local-authn-min` overlay'inden vault + workcube-mssql Service+Endpoints `$patch: delete` ile çıkarıldı
- `dev-smoke.sh` D34 isolation gate eklendi (denylist: `10.9.10.53|10.9.193.201|ai.acik.com|testai.acik.com`)
- `zanzibar-min/full` profile'larda lokal fake fixture eklenmesi gerekir (Faz 17.5 follow-up)

---

## References

- [ADR-0002](0002-single-host-dual-cluster.md) §0.5 D6 stateful tier (PG/KC/Vault compose permanent)
- [ADR-0003](0003-inner-loop-tooling-ownership.md) inner-loop tooling
- [ADR-0004](0004-split-repo-authority-transfer.md) Faz 19 split-repo authority
- Codex thread `019dc10b` (Dual DataSource AGREE + D19 confirm)
- Codex thread `019dc0ac` (Faz 19 detaylı 10-step)
- [docs/migration/mssql-pg-data-contract.md](../migration/mssql-pg-data-contract.md) (scope revize: full → allowlist)
- [docs/migration/report-source-annex.yaml](../migration/report-source-annex.yaml) (44 tablo allowlist)
- [docs/migration/flyway-v16-plan.md](../migration/flyway-v16-plan.md) (deferred, curated PG için opsiyonel)
- `kustomize/base/apps/report-service/ops/externalsecret.yaml` (uncomment target)
- `kustomize/base/apps/schema-service/ops/externalsecret.yaml` (uncomment target)
- `kustomize/base/host-services/` (D19 pattern reference: postgres/keycloak/vault-svc.yaml)
- `kustomize/base/netpol/default-deny.yaml` (egress baseline)
- User direktifi: "daha birçok rapor yapacağız kalıcı uzun vadeli olan hangisi" (2026-04-24)
