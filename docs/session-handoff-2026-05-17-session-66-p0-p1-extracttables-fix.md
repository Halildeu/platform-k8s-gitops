# Session Handoff — 2026-05-17 (Session 66) — extractTables Timeout Fix: P0+P1 LIVE, Q3 kaldı

> Format: D28 5-alan + sıradaki agent Q3 aksiyon planı
> Önceki handoff: `session-handoff-2026-05-17-session-65-schema-b1-capability-sprint.md`
> Codex fix-plan: thread `019e32da`. P0 review: `019e32fc`. P1 review: `019e3317`.

---

## 1. Bağlam

Session 65 handoff'u (PR #726) `schema-service` `extractTables` query-timeout
blocker'ını + P0/P1/Q3 fix planını devretti: `/api/v1/schema/snapshot`
`extractTables` ~60s'de timeout olup 500 dönüyordu (`workcube_mikrolink`
1509+ tablo).

Bu session (66): **P0** (query timeout config-ize) + **P1** (`extractTables`
split) merge edildi ve **canlı test cluster'da uçtan uca doğrulandı**
(live-kanıtlı). **Q3** (`buildSnapshot` hardening) açık — iş devam ediyor;
bu handoff Q3'ü sıradaki session'a aktarır.

Handoff sebebi: bu session 6 PR + 2 deploy + 2 uzun canlı snapshot
doğrulaması yaptı; P0+P1 verified-live doğal bir milestone. Q3 tam bir PR
döngüsü (kod + Codex + CI + merge + deploy + verify) — taze session'da
kesintisiz koşmalı (HARD RULE — Session Otomatik Açma, tetik #1 context +
#4 pre-completion natural break).

---

## 2. İddia — bu session MERGE edilen PR'lar

Tümü cross-AI Codex peer review (AGREE), CI yeşil, **normal squash** (`--admin`
yok), `ai-post-merge-cleanup.sh` archive tag'li.

| PR | Repo | Konu |
|----|------|------|
| #726 | platform-k8s-gitops | Session 65 handoff doc |
| #233 | platform-backend | **P0-code** — `MssqlConfig` query timeout property-driven (`schema.mssql.query-timeout-seconds`, default 60) |
| #728 | platform-k8s-gitops | **P0-gitops** — test overlay `SCHEMA_MSSQL_QUERY_TIMEOUT_SECONDS=300` ConfigMap env + schema-service digest bump (pre-B1 → B1+P0) |
| #234 | platform-backend | **P1-code** — `extractTables` → `extractBaseTables` (fatal) + `enrichTables` (3 bağımsız non-fatal sorgu) split |
| #730 | platform-k8s-gitops | **P1-gitops** — schema-service digest bump (⚠ yanlış digest pinledi) |
| #732 | platform-k8s-gitops | **P1-gitops düzeltme** — doğru schema-service digest `sha256:7aad3043` (çok-servisli build'de #730 başka servisin digest'ini almıştı) |

Codex thread: P0 `019e32fc` (AGREE), P1 `019e3317` (plan + post-impl + her iki
gitops PR — hepsi AGREE).

---

## 3. İspatlar

**P0 — canlı doğrulandı (bu session):**
- `GET /api/v1/schema/snapshot?schema=workcube_mikrolink` → **HTTP 200**, build
  **88.9s** (eski 60s timeout'un üstünde — teşhis birebir doğru).
- Pod env `SCHEMA_MSSQL_QUERY_TIMEOUT_SECONDS=300` doğrulandı.
- 8 B1 capability canlı çalıştı: foreignKeys 10, uniqueConstraints 3,
  defaultConstraints 607, indexes 1834, objects 1524, databaseOptions
  (compat 110 / SIMPLE). checkConstraints 0 + changeData 0 gerçek-boş.
  storage [] — `VIEW DATABASE STATE` izni yok (bkz. §4).

**P1 — canlı doğrulandı (bu session):**
- Pod log split kodunu kanıtlıyor: `Extracting base tables` →
  `Extracted 1513 base tables, 26333 columns` (`extractBaseTables`) +
  `Column enrichment for schema 'workcube_mikrolink': 1378 identity,
  607 default, 0 computed` (`enrichTables` 3 bağımsız sorgu) →
  `Snapshot built in 40860ms`.
- `/snapshot` HTTP 200; çıktı P0 ile **birebir eşdeğer** (1513 tablo /
  26333 kolon / 1787 ilişki / 16 domain).
- Cluster pod `schema-service-dc6cc4dbb-zzmbh` imageID `sha256:7aad3043`
  (P1 image), overlay #732 ile hizalı.

**Test:** schema-service standalone suite **198 test, 0 fail** (191 baseline
→ P0 `MssqlConfigTest` +2 → P1 `SchemaExtractServiceTableExtractionTest` +5).

---

## 4. İspatlamaz

- 🟠 **Q3 yapılmadı.** `SchemaSnapshotService.buildSnapshot` adım-1
  `extractService.extractTables(schema)` hâlâ try-catch'siz. Base extraction
  fail ederse → exception propagate → generic **HTTP 500** (domain exception
  → 503/504 DEĞİL). P0/P1 sonrası bu pratikte tetiklenmiyor (timeout 300s,
  query 88s/40s'de bitiyor) ama hardening eksik.
- 🟡 **`storage` envanteri canlıda boş.** `extractStorage`
  (`sys.dm_db_partition_stats` DMV) `VIEW DATABASE STATE` izni istiyor;
  MSSQL `AlUser_App` hesabında yok → non-fatal fail (B1-6 tasarımı bunu
  öngörüyordu, snapshot çökmedi). Operatör/DBA izin grant'i gerek — kod işi
  değil.

---

## 5. Bilinen Boşluk + Sıradaki Agent Q3 Aksiyon Planı

Codex fix planı: handoff #726 §5 / thread `019e32da`.

### 🟠 Q3 — buildSnapshot hardening (tek kalan handoff item'i)
- **Hedef**: `SchemaSnapshotService.buildSnapshot` adım-1 `extractTables`
  try-catch'siz → base-extraction fail'i generic 500 yerine graceful
  503/504'e çevir.
- **Plan**:
  1. Domain exception (örn. `SnapshotUnavailableException`).
  2. `buildSnapshot` — adım-1 `extractTables` çağrısını sar; base extraction
     fail → `SnapshotUnavailableException` fırlat. (P1 sonrası `extractTables`
     yalnız base-fail'de throw eder; enrichment içte non-fatal.)
  3. `SchemaController` veya `@RestControllerAdvice` —
     `SnapshotUnavailableException` → HTTP **503** (veya 504), net JSON body.
  4. Partial-status görünürlüğü — degrade olan envanterleri (örn. storage)
     snapshot metadata'sında işaretle. Scope'u Codex ile netleştir (bu
     bölüm #726 §5'te en az tanımlı kısım; ayrı alt-iş olarak ertelenebilir).
- **Kabul kriterleri** (sıradaki agent + Codex plan-time'da kesinleştirir):
  - HTTP kodu: base-extraction fail → **503** (Service Unavailable — snapshot
    şu an kurulamıyor); neden spesifik query-timeout ise **504**. Kesin
    503/504 ayrımı Codex plan-time onayına bağlı.
  - Error response JSON: ör. `{"error":"snapshot_unavailable",
    "schema":"<ad>","reason":"<kısa mesaj>"}` — generic Spring 500 sayfası
    değil; mevcut başarılı snapshot response shape'i etkilenmez.
  - Test: `SchemaSnapshotServiceTest` — `extractTables` (base) throw →
    `SnapshotUnavailableException` doğrulaması; controller/advice testi —
    exception → 503/504 + body shape.
  - Partial-status: degrade envanter alanı snapshot metadata contract'ında
    tanımlanmalı; shape Codex plan-time'da netleşir.
- **Effort**: orta, 1 PR (platform-backend) + sonra gitops digest bump +
  deploy + verify.
- **Akış**: Codex plan-time istişare → impl → cross-AI post-impl review →
  CI yeşil → normal squash → gitops digest bump → deploy → re-verify.

### 🟡 Canonical truth güncelle (sıradaki session erken adım)
- `docs/state/current-state.md` ~2026-05-15'te kalmış (stale). Sıradaki
  session `current-state.md`'i P0+P1 live state ile güncellemeli:
  schema-service `7aad3043` image / `extractTables` split / query timeout
  300s. Q3 öncesi veya Q3 PR'ıyla birlikte yapılabilir.

### 🟡 Storage permission (düşük öncelik — operatör/DBA, kod değil)
- MSSQL `AlUser_App` hesabına `GRANT VIEW DATABASE STATE` → `storage`
  envanteri (`sys.dm_db_partition_stats`) canlıda dolar. Kod değişikliği yok.

### 🟡 Temizlik artıkları (düşük öncelik)
- `~/Documents/.pb-worktrees/` altında leftover worktree'ler: `b1-4..b1-8`,
  `snapshot-builder`, `schema-timeout-fix`. `git worktree remove` ile temizle.

---

## Yeni Session İçin İlk Komut

```bash
# 1. Bu handoff'u oku
cat docs/session-handoff-2026-05-17-session-66-p0-p1-extracttables-fix.md

# 2. Q3 için taze izole worktree (platform-backend origin/main)
cd ~/Documents/platform-backend && git fetch origin
git worktree add ~/Documents/.pb-worktrees/q3-buildsnapshot origin/main

# 3. Q3 — SchemaSnapshotService.buildSnapshot adım-1 hardening
#    domain exception SnapshotUnavailableException → HTTP 503/504
#    Codex plan-time istişare (019e32da referans veya yeni thread)
```

İlk iş: **Q3 — `buildSnapshot` adım-1 hardening + domain exception → 503/504.**
Codex plan-time AGREE → impl → cross-AI review → CI → squash merge → gitops
digest bump → deploy → re-verify. Q3, extractTables timeout fix zincirinin
(P0+P1+Q3) son halkası — sıradaki session onu sürdürür.
