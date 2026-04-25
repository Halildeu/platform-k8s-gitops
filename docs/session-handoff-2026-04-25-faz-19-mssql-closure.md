# Session Handoff — Faz 19 MSSQL Closure (2026-04-25)

> Faz 19.MSSQL.A-O hattı tamamlandı: Workcube MSSQL bridge canlı, 31 rapor + 12 dashboard + schema introspection 1509 tablo, 8/8 backend endpoint 200.

## D28 5-Alan

### Bağlam (Why this handoff?)

Faz 19 split-repo authority transfer (10-step plan, ADR-0004) tamamlandıktan sonra **Faz 19.MSSQL** alt-fazı eklendi (ADR-0005 Dual DataSource Reporting). Workcube ERP MSSQL host'una read-only live bridge kurma çalışmasının sonu. Backend tarafında 21+ atomic fix uygulandı; tümü gitops PR'larında kalıcı.

### İddia (Ne yapıldı?)

**Major deliverables:**
1. ADR-0005 Dual DataSource Reporting (PG primary + MSSQL secondary read-only)
2. Vault seed `kv/platform/mssql-external` her iki realm (D34 izolasyon)
3. Bridge proxy pattern: per-cluster alpine/socat container (Calico routing workaround)
4. Backend services (report-service, schema-service) MSSQL bağlantısı LIVE
5. Frontend MFE federation 7 remote (4 eski + 3 yeni: schema-explorer, suggestions, ethic) ENABLE
6. Schema-explorer auth chain (axios interceptor + window.fetch monkey-patch + mfe_shell URL env-driven)
7. Gateway 6 yeni route (`/api/v1/{schema,users,permissions,reports,dashboards,...}` + `/api/audit/events`)
8. Test overlay platform-test realm + SECURITY_JWT_* env override (8 service)

**PR'lar (zaman sırası):**
| # | Repo | Faz |
|---|---|---|
| #6 | platform-backend | 19.MSSQL.A WorkcubeMssqlConfig |
| #7 | platform-backend | 19.MSSQL.B application-k8s.yml binding |
| #125 | platform-k8s-gitops | 19.MSSQL.C gitops activation |
| #126 | platform-k8s-gitops | 19.MSSQL.D+E+F bridge proxy + ESO + digest |
| #27 | platform-web | 19.MSSQL.J+K+L schema-explorer fixes |
| #127 | platform-k8s-gitops | 19.MSSQL.M gateway routes (kalıcı) |
| #128 | platform-k8s-gitops | 19.MSSQL.N test overlay realm + report-service activation (kalıcı) |
| #28 | platform-web | 19.MSSQL.O CI gateway URL + asset merge (kalıcı) |

### İspatlar

**Backend e2e (Bearer JWT password grant, test cluster):**
```
✅ /api/v1/users → 200 (2 kullanıcı: admin + testuser)
✅ /api/v1/reports → 200 (6259 byte, 31 rapor: HR + Finans + Stok + Satış)
✅ /api/v1/dashboards → 200 (3702 byte, 12 dashboard)
✅ /api/v1/schema/snapshot → 200 (3611061 byte = 3.6 MB)
   • 1509 tablo, 26240 kolon, 1774 ilişki, 27 domain
✅ /api/v1/permissions → 200 (2802 byte)
✅ /api/v1/permissions/assignments?userId=1 → 200 (7913 byte)
✅ /api/v1/me/theme/resolved → 200 (343 byte)
✅ /api/audit/events → 200 (DB boş 0 event normal)
✅ /api/v1/authz/me → 200 (1489 byte yetkiler)
✅ /api/v1/authz/version → 200 ({"authzVersion":3})
```

**Backend pod log kanıt (report-service test cluster):**
```
report-pg-pool - Added connection (PG metadata)
HikariPool-1 - Added connection (MSSQL primary)
workcube-mssql-readonly - Added connection (qualifier secondary)
Dashboard registry initialized with 12 definitions
Report registry initialized with 31 definitions
```

**Schema-service log:**
```
schema-mssql-pool - Started
Extracted 1509 tables, 26240 columns
Detected 27 domains from 1509 tables
Snapshot built in 26228ms
```

### İspatlamaz (henüz kanıtlanmamış)

- Tarayıcı görsel doğrulama (kullanıcı /admin/* sayfalarını görsel test etmedi PR sonrası)
- /api/audit/events/live SSE endpoint (404, optional feature)
- Prod cluster MSSQL aktivasyon (test cluster'da kanıt; prod aynı pattern uygulanır)
- AG Grid License warning (lisans yenileme — backend bağımsız)
- Calico routing root cause (Faz 20'de research planlanmış)

### Bilinen boşluk (kalan iş)

| Öncelik | İş | Detay |
|---|---|---|
| P0 | Faz 19.10 platform-ssot archive read-only | GitHub Settings → archived (1 click) |
| P0 | Frontend yeni digest (sha-ac35567) overlay pin update | Image build CI bitince digest pin PR |
| P1 | Faz 18.8 Mac k3d-dev clean smoke | Mac dev cluster doğrulama |
| P1 | Prod cluster MSSQL aktivasyon | Test pattern aynen prod'a |
| P2 | Faz 20: Calico routing root cause research (B alternatifi) | Bridge proxy workaround → kalıcı CNI fix |
| P2 | workflows-legacy aktivasyon (16 workflow) | secret-scan + codeql öncelikli |

## Quick reference

**Aktif servisler test cluster:**
- frontend (1/1)
- api-gateway (1/1) — 15 route (R0-R14)
- report-service (1/1) — MSSQL primary + workcube qualifier secondary
- schema-service (1/1) — workcube_mikrolink schema introspection
- user-service, permission-service, variant-service, auth-service (her biri 1/1, REPORT_PG creds + SECURITY_JWT_*)
- workcube-mssql-proxy-{prod,test} docker container (alpine/socat)
- platform-vault-{prod,test}, platform-pg-{prod,test}, platform-kc-{prod,test} (compose stateful tier — D6)

**Vault paths:**
- `kv/platform/mssql-external` (Workcube creds)
- `kv/platform/{report,schema}-service` (JWT/Auth)
- `kv/gitops/ghcr-token` (Halildeu PAT)

## Codex thread referansları

- `019dc10b` — ADR-0005 Dual DataSource Reporting (Codex AGREE iter-final)
- `019dc1ee` — Faz 19.11 console.warn prod suppress + apiLogger
- `019dc0ef` — Faz 19.8 dual-build CI Option B
- `019dc0ac` — Faz 19 detailed AGREE 10-step

## Sıradaki session başlangıcı

```bash
# Read order:
docs/state/current-state.md             # canlı truth
docs/adr/0005-dual-datasource-reporting.md  # MSSQL bridge tasarımı
PLAN.md "Faz 19" + "Faz 20 (planned)"   # roadmap
docs/session-handoff-2026-04-25-faz-19-mssql-closure.md  # bu dosya
```

