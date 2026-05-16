# Session Handoff — 2026-05-17 (Session 65) — schema-service B1 Capability Gap Sprint

> Format: D28 5-alan + sıradaki agent P0 aksiyon listesi
> Önceki handoff: `session-handoff-2026-05-16-session-64-adim-12-complete.md`
> Codex fix-plan thread: `019e32da`

---

## 1. Bağlam — bu oturumda ne yapıldı, neden bu handoff

schema-service **B1 Capability Gap Sprint**: Workcube MSSQL `sys.*` katalogundan
**otoritatif metadata extraction** ekleyen 8-PR'lık dizi. ADR-0020 truth-tier
modeli — 8 envanterin tamamı `authoritative_mssql` katmanında.

- B1-1 / B1-2 / B1-3 → önceki session'da merge edilmişti.
- Bu session: **B1-4..B1-8 + `SchemaSnapshot` builder refactor (PR-A)** tamamlandı
  → 6 PR merge.
- Ardından: B1 image'ı test cluster'a deploy + `/api/v1/schema/snapshot` canlı
  doğrulama denendi.

**Canlı doğrulama gerçek bir blocker ortaya çıkardı** (doğrulamanın işini yaptığı
an): `/api/v1/schema/snapshot` endpoint'i snapshot **kuramıyor**. Kod tarafı
(8 capability) merge + image deploy edildi; ancak uçtan uca canlı kanıt
**henüz yok**. Bu handoff blocker'ın teşhisini + düzeltme planını sıradaki
session'a aktarır.

Handoff sebebi: B1 sprint (6 PR) + deploy araştırması bu session context'ini
doldurdu. extractTables fix'i çok-PR'lık (P0+P1+Q3) ve PR ortasında kesilmeden
taze session'da koşmalı (HARD RULE — Session Otomatik Açma, tetikleyici #1
context doluluk + #4 pre-completion natural break).

---

## 2. İddia — origin/main'e MERGE edilen PR'lar

B1 sprint **8/8** + builder refactor = **9 PR**, hepsi `platform-backend`
origin/main'de. Tümü cross-AI Codex peer review (REVISE→absorb→AGREE pattern),
CI yeşil, **normal squash merge** (`--admin` yok — HARD RULE).

| PR | Commit | Kapsam |
|----|--------|--------|
| #224 | `fa3cbbd` | B1-1 / M2 — ColumnInfo 7→16 alan (identity, computed, default, sparse, ordinal...) |
| #225 | `9aa7439` | B1-2 / R1+R2 — otoritatif FK + unique constraint extraction |
| #226 | `a15eb4e` | B1-3 / M3 — check + default constraint envanteri |
| #227 | `0419ea3` | B1-4 / M4 — fiziksel (rowstore) non-PK index envanteri |
| #228 | `2f0595d` | PR-A — `SchemaSnapshot` builder refactor, legacy positional ctor'lar drop |
| #229 | `9c370a4` | B1-5 / M1 — object catalog envanteri (`sys.objects` + extended properties) |
| #230 | `b1b135a` | B1-6 / M6 — per-table storage footprint (`sys.dm_db_partition_stats`) |
| #231 | `583c74d` | B1-7 / M13 — change-data envanteri (CDC / change-tracking / temporal / replication) |
| #232 | `3e16e9d` | B1-8 / M15 — database-level options (`sys.databases` + `sys.database_files`) |

`SchemaSnapshot` artık 15 record bileşeni: `version, metadata, tables,
relationships, foreignKeys, uniqueConstraints, checkConstraints,
defaultConstraints, indexes, objects, storage, changeData, databaseOptions,
domains, analysis`. Her envanter additive — `report-service` mirror'ı
`@JsonIgnoreProperties(ignoreUnknown=true)` ile kod değişimsiz tolere ediyor
(sadece mirror test JSON'u güncellendi).

---

## 3. İspatlar

- **9 PR origin/main'de** — doğrulama: `git log origin/main --oneline` →
  `fa3cbbd..3e16e9d` 9 squash commit; `git branch -r --contains 3e16e9d` →
  `origin/main`.
- **schema-service standalone test suite**: 191 test, 0 fail (Maven local run +
  CI "schema-service standalone build" check her PR'da yeşil).
- **Codex cross-AI peer review**: her PR ayrı thread, AGREE verdict.
  B1-4 / B1-5 / PR-A / B1-6 / B1-7 / B1-8 hepsi REVISE×1 absorb→AGREE.
- **CI**: her PR'da "schema-service standalone build" + "CI - Image Build +
  GHCR Push" yeşil; normal squash.
- **Image deploy + canlı verify — BU SESSION**: test cluster pod
  `schema-service-6bdd76574f-jqqjg`, image `sha-3e16e9d` /
  digest `sha256:2e631bedf2c56c705fef7dd27f241fe0acb7e7ce2181c345ec3c7b31b723b5fa`,
  Running 1/1 gözlendi; `/api/v1/schema/snapshot` çağrısı + pod log timeout
  kanıtı (§4) bu session'da alındı. k3d-test cluster **handoff anında**
  unreachable oldu (`127.0.0.1:7443 connection refused`) — sıradaki session
  işe başlamadan pod state'ini yeniden doğrulamalı.

---

## 4. İspatlamaz

- 🔴 **`/api/v1/schema/snapshot` uçtan uca ÇALIŞMIYOR.** Pod log kanıtı:
  `org.springframework.dao.QueryTimeoutException` /
  `com.microsoft.sqlserver.jdbc.SQLServerException: The query has timed out`.
  `extractTables` SQL'i canlı Workcube MSSQL'e (`workcube_mikrolink`:
  1509 tablo, 26240 kolon) karşı ~60 sn'de timeout oluyor.
- 🔴 **8 B1 envanteri canlı snapshot'ta hiç dolmadı.** `extractTables`,
  `buildSnapshot` adım-1 ve try-catch ile sarılı **DEĞİL** (tek arıza noktası)
  → tüm snapshot 500 dönüyor, 8 B1 extraction'a hiç ulaşılmıyor.
- 🟠 **cluster pod state handoff anında re-verify EDİLEMEDİ** — cluster handoff
  sırasında unreachable oldu. Pod bu session erken aşamada `sha-3e16e9d`
  Running 1/1 gözlenmişti; sıradaki session işe başlamadan tazece doğrulamalı.
- Sonuç: B1 kod **MERGED**, image **DEPLOYED**, blocker bu session **canlı
  gözlendi**, ama 8 B1 capability'sinin **uçtan uca çalıştığına dair canlı
  kanıt YOK** (D29 disiplini: Up ≠ Functional).

---

## 5. Bilinen Boşluk + Sıradaki Agent P0 Aksiyon Listesi

Codex teşhis + fix planı: thread **`019e32da`**.

### 🔴 P0 — extractTables query timeout (BLOKER, en yüksek öncelik)
- **Kök neden**: `schema-service/src/main/java/com/example/schema/config/MssqlConfig.java:17`
  — hard-coded `template.getJdbcTemplate().setQueryTimeout(60)`.
- **Fix tek bir kod satırı DEĞİL — tam runtime config yüzeyi**:
  1. `MssqlConfig.java` — timeout'u property'ye al
     (örn. `@Value("${schema.mssql.query-timeout-seconds:60}")`), default 60.
  2. **test overlay ConfigMap/env** — `schema-service-config` ConfigMap'e
     (platform-k8s-gitops `kustomize`) `SCHEMA_MSSQL_QUERY_TIMEOUT_SECONDS=180`
     (veya 300) ekle + pod rollout restart. ⚠️ Bu adım atlanırsa kod PR'ı
     merge olsa bile canlı timeout **hâlâ 60 sn** kalır (property default
     değişmedi).
  3. **image rebuild** (platform-backend CI) → **GitOps overlay digest bump**
     (`kustomization.yaml:637`).
- Effort: küçük kod PR'ı (platform-backend) + overlay PR'ı (platform-k8s-gitops).

### 🔴 P1 — extractTables split (base + enrichment)
- `SchemaExtractService.extractTables` tek dev JOIN sorgusu → ikiye böl:
  - `extractBaseTables` — tablo + kolon temel alanlar (zorunlu, fatal).
  - `enrichTables` — identity / default / computed zenginleştirme; ayrı
    sorgular, non-fatal, Java tarafında `object_id + column_id` ile merge.
- Effort: orta, 1 PR.

### 🟠 Q3 — buildSnapshot hardening
- `SchemaSnapshotService.buildSnapshot` adım-1 `extractTables` try-catch'siz →
  base extraction fatal kalsın AMA generic 500 yerine domain exception →
  **503/504**; B1-1 enrichment'ları non-fatal; partial-status görünürlüğü.
- Effort: orta, 1 PR (P1 ile birleşebilir).

### 🟠 Re-deploy + re-verify — her satır AYRI kanıtlanır (D29: Up ≠ Functional)
- [ ] `origin/main` — extractTables fix commit'i merge edildi
- [ ] GHCR — fix image digest build edildi (`sha-<commit>`)
- [ ] GitOps overlay — `kustomization.yaml:637` schema-service digest = build edilen digest
- [ ] cluster — pod `imageID` == overlay digest (D30 immutable artifact)
- [ ] `schema-service-config` ConfigMap `SCHEMA_MSSQL_QUERY_TIMEOUT_SECONDS` yeni
      değerde + pod rollout restart edildi
- [ ] `GET /api/v1/schema/snapshot?schema=workcube_mikrolink` → HTTP 200, timeout YOK
- [ ] response JSON — B1 envanter alanları (`foreignKeys` / `uniqueConstraints` /
      `checkConstraints` / `defaultConstraints` / `indexes` / `objects` /
      `storage` / `changeData` / `databaseOptions`) DOLU döndü

### 🟠 GitOps overlay digest drift
- `platform-k8s-gitops` `kustomize/overlays/test/kustomization.yaml:637`
  schema-service `digest: sha256:387ad01af0cc9e3c2cacb6b9a88d3ed7d9d3a402f94366d71d8b97a48d2e3311`
  = **PR #220 (pre-B1)**. Cluster `sha-3e16e9d` (B1-8) koşuyor → overlay DRIFT.
- ⚠️ **Latent risk**: şu an `kubectl apply -k overlays/test` schema-service'i
  pre-B1 `387ad01` image'ına GERİ DÖNDÜRÜR.
- Fix: extractTables fix image'ı build edilince digest'i bir kez bump et.

### 🟡 Temizlik artıkları (düşük öncelik)
- `~/Documents/.pb-worktrees/` altında 6 leftover worktree:
  `b1-4 b1-5 b1-6 b1-7 b1-8 snapshot-builder` — `ai-post-merge-cleanup.sh`
  kaldırmamış. `git worktree remove` ile temizle.
- `~/Documents/platform-backend` ana checkout `#223`'te stale (detached HEAD)
  — yeni iş taze worktree'den (origin/main) açılmalı; ana repo `git fetch` ister.
- k3d-test cluster bu session'da unreachable (`127.0.0.1:7443 connection
  refused`) — cluster ops `ssh halil@staging-sw` üzerinden veya tunnel ile.

---

## Yeni Session İçin İlk Komut

```bash
# 1. Bu handoff'u oku
cat docs/session-handoff-2026-05-17-session-65-schema-b1-capability-sprint.md

# 2. extractTables fix için taze izole worktree (platform-backend origin/main)
cd ~/Documents/platform-backend && git fetch origin
git worktree add ~/Documents/.pb-worktrees/schema-timeout-fix origin/main

# 3. Codex fix-plan thread'ine devam (veya yeni thread — 019e32da expire olabilir)
#    P0 → MssqlConfig.java:17 setQueryTimeout(60) → property + bump
#    P1 → extractTables split (base + enrichment)
#    Q3 → buildSnapshot hardening
```

İlk iş: **P0 — `MssqlConfig.java:17` query timeout config-ize + bump.**
Codex review → CI yeşil → squash merge → P1 → Q3 → re-deploy → re-verify →
overlay digest bump.
