# Session Handoff — 2026-05-17 (Session 67) — extractTables Fix Chain TAMAM: Q3 (503) + Q4 (storage catalog-view) MERGED

> Format: D28 5-alan + sıradaki agent aksiyon listesi
> Önceki handoff: `session-handoff-2026-05-17-session-66-p0-p1-extracttables-fix.md`
> Codex thread'ler: Q3 `019e335c-9077-7392-ba86-b7422a1fb14c`, Q4 `019e34f9-f0a4-7dc0-9766-d3878ce66d0b`

---

## 1. Bağlam

Session 65 (PR #726) `schema-service` `extractTables` query-timeout blocker'ını
+ P0/P1/Q3 fix planını devretti. Session 66 (PR #733) **P0** (query timeout
config-ize) + **P1** (`extractTables` split) merge edip canlı doğruladı,
**Q3**'ü açık bıraktı.

Bu session (67): **Q3** (`buildSnapshot` hardening — base-extraction fail →
domain exception → HTTP 503) + **Q4** (`extractStorage` DMV → catalog view
yeniden yazımı, izin-gerektirmez) merge edildi. Ek olarak `current-state.md`
canonical truth doc'u P0+P1+Q3 LIVE state ile güncellendi (PR #740).

**`extractTables` timeout fix zinciri artık uçtan uca KAPANDI** —
P0 + P1 + Q3 + Q4 tamamı origin/main'de. Yan kazanım: Q4 `storage`
envanterindeki "DMV izni yok → boş envanter" boşluğunu **kod tarafından**
kapattı — operatör/DBA `GRANT VIEW DATABASE [PERFORMANCE] STATE` ihtiyacı
tamamen ORTADAN KALKTI (PROHIBITED action — erişim-kontrolü değişimi — yerine
catalog-view yeniden yazımı ile çözüldü).

Handoff sebebi: extractTables/storage thread'i tamamen kapandı — doğal
milestone (HARD RULE — Session Otomatik Açma, tetik #4 pre-completion natural
break). Sıradaki session yeni bir konuya taze context'le başlamalı.

**Ek bulgu (bu handoff anında):** `k3d-test` cluster'ı durmuş bulundu
(`k3d-test-server-0` container OOM-exit 137). `k3d cluster start test` ile
yeniden başlatıldı; k3s API server up ama startup-reconciliation yükü altında
settle ediyor. Recovery durumu §3 + §5 P0'da.

---

## 2. İddia — bu session MERGE edilen PR'lar

6 PR. Tümü cross-AI Codex peer review (AGREE), CI yeşil, **normal squash**
(`--admin` yok — HARD RULE), `ai-post-merge-cleanup.sh` archive tag'li.

| PR | Repo | Konu |
|----|------|------|
| #733 | platform-k8s-gitops | Session 66 handoff doc |
| #235 | platform-backend | **Q3-code** — `buildSnapshot` base-fail → `SnapshotUnavailableException` → HTTP **503**; global `@RestControllerAdvice` (`SchemaExceptionHandler`), cause sızdırmayan `{error, schema, reason}` body |
| #735 | platform-k8s-gitops | **Q3-gitops** — schema-service digest bump `sha-b9b40f7` (build run 25977247312) |
| #740 | platform-k8s-gitops | `current-state.md` — schema-service `extractTables` fix P0+P1+Q3 LIVE delta |
| #237 | platform-backend | **Q4-code** — `extractStorage` `sys.dm_db_partition_stats` DMV → `sys.partitions` + `sys.allocation_units` catalog view'ları (izin-free); `indexKb` artık türetilmiş |
| #745 | platform-k8s-gitops | **Q4-gitops** — schema-service digest bump `sha-58bc2c9` (build run 25985721556) |

Codex peer review:
- **Q3** `019e335c` — plan-time AGREE (503 tek-tip / `partial-status` ertele /
  global advice) + post-impl AGREE (must-fix yok; cause-sızdırma güvenlik
  notunun karşılandığı diff üzerinden doğrulandı).
- **Q4** `019e34f9` — plan AGREE (Option D — fan-out-safe ayrı `sys.partitions`-
  only rowCount CTE) + post-impl AGREE. Rewrite sırasında plan sorgusunda bir
  `p.rows` fan-out bug'ı yakalanıp Codex'e iletildi → Option D ile çözüldü.

---

## 3. İspatlar

**Q3 — canlı doğrulandı, canonical truth'a işlendi:**
- PR #740 `docs/state/current-state.md` "Live Delta" → schema-service
  `extractTables` fix **P0+P1+Q3 LIVE** kaydı (canonical truth doc).
- `SchemaSnapshotService.buildSnapshot` adım-1 `extractTables` artık try-catch
  sarmalı: base extraction fail → `SnapshotUnavailableException` fırlatır;
  `SchemaExceptionHandler` (`@RestControllerAdvice`) → HTTP **503**, body
  `{error, schema, reason}` (sabit `reason`; cause yalnız server-side log,
  response'a sızmaz). Başarılı snapshot response shape'i değişmedi.

**Q4 — kod + image merge, immutable digest pin:**
- `extractStorage` artık `sys.partitions` + `sys.allocation_units` catalog
  view'larını okuyor — catalog view'lar metadata-visibility ile okunur,
  `VIEW DATABASE [PERFORMANCE] STATE` grant'i GEREKMİYOR.
- SQL şekli: 2-CTE — `part_rows` (fan-out-safe rowCount, yalnız
  `sys.partitions`, `index_id IN (0,1)`) + allocation-unit `au.type`
  decomposition (1=in-row, 2=lob, 3=row-overflow). `indexKb` artık SQL
  kolonu değil — `max(0, usedKb − dataKb − lobKb − rowOverflowKb)` türev.
- Test overlay `kustomize/overlays/test/kustomization.yaml` schema-service
  pin: `digest: sha256:894e492f029c93277ee7d84c993bad2535d970995b0d2df08a48ebb23340ae26`
  (tag `sha-58bc2c9`, PR #237).

**Test:** schema-service standalone suite **202 test / 0 fail / 0 error /
0 skip** — bu handoff sırasında worktree `58bc2c9` üzerinde `mvn test` ile
yeniden doğrulandı (BUILD SUCCESS). Sayı yörüngesi: 198 (session 66 P0+P1) →
Q3 `SchemaExceptionHandlerTest` + `SchemaSnapshotServiceTest` ek → Q4
`SchemaExtractServiceStorageExtractionTest` rewrite → **202**.

**Cluster:** `k3d-test` durmuş bulundu, `k3d cluster start test` çalıştırıldı.
k3s API server up; kontrol düzlemi startup-reconciliation altında — bu handoff
yazımında henüz settle etmemişti (TLS handshake timeout, kine "Slow SQL",
Calico CNI sandbox hataları — recovery §5 P0).

---

## 4. İspatlamaz

- 🟠 **Q4 `storage` envanteri canlı `/snapshot` üzerinde YENİDEN
  doğrulanmadı.** `k3d-test` cluster bu handoff anında durmuş bulundu;
  restart sonrası API server hâlâ settle ediyor. Q4 catalog-view sorgusunun
  canlı `workcube_mikrolink` üzerinde **dolu `storage[]`** (eski boş yerine)
  döndürdüğü, cluster geri geldiğinde teyit edilmeli. Q4 kod + 202-test +
  immutable digest tarafı tamam; eksik olan tek şey canlı endpoint smoke'u.
- 🟡 **`partial-status` metadata yapılmadı.** Q3 planının (#726 §5 / Codex
  `019e335c`) en az tanımlı parçası — degrade olan envanterleri
  `SchemaSnapshot` metadata'sında işaretleme — Codex tarafından "ayrı alt-iş
  olarak ertelenebilir" verdict'iyle ertelendi. Q4 `storage`'ı izin-free
  yaptığı için aciliyeti DÜŞTÜ ama capability hâlâ açık (CDC/change-tracking
  devre dışı bir DB'de `changeData` boş kalabilir → consumer "boş mu, yok mu?"
  ayrımını yapamaz).

---

## 5. Bilinen Boşluk + Sıradaki Agent Aksiyon Listesi

### 🟠 P0 — k3d-test cluster recovery + Q4 storage canlı re-verify
- **Durum**: Cluster durmuş bulundu (`k3d-test-server-0` OOM-exit 137).
  `k3d cluster start test` çalıştırıldı; k3s API server process up ama
  startup-reconciliation yükü altında — kine datastore "Slow SQL", API
  `127.0.0.1:7443` TLS handshake timeout, client-side throttling, Calico
  CNI sandbox teardown hataları.
- **Aksiyon**:
  1. API server'ın settle etmesini bekle — `kubectl --context k3d-test
     --request-timeout=10s get nodes` yeşillenene kadar. k3s genelde startup
     backlog'unu işleyince kendiliğinden toparlar.
  2. Calico hâlâ bozuksa CLAUDE.md Pitfall #5 typha watch-cache fix:
     `kubectl -n calico-system scale deploy calico-typha --replicas=0` →
     `delete pod -l k8s-app=calico-node` → `scale --replicas=1`.
  3. schema-service pod `Running` + imageID `sha256:894e492f…` (Q4) doğrula.
  4. `GET /api/v1/schema/snapshot?schema=workcube_mikrolink` → HTTP 200 +
     **`storage[]` DOLU** — Q4 catalog-view kanıtı; eski DMV-izin boşluğunun
     kod tarafından kapandığının canlı ispatı.
  5. Deploy sonrası tarayıcı console + network kontrolü (HARD RULE — Deploy
     Sonrası Tarayıcı Console Verifikasyonu) — schema-service backend-only ama
     onu tüketen frontend (schema explorer / report builder) varsa smoke et.
- **Effort**: küçük-orta (cluster self-heal beklemesi + 1 endpoint smoke).

### 🟡 P1 — `partial-status` metadata (Q3 ertelenen alt-iş)
- **Hedef**: Degrade olan envanterleri `SchemaSnapshot` metadata'sında
  görünür kıl — consumer "envanter boş mu, yoksa toplanamadı mı?" ayrımını
  yapabilsin.
- **Plan**: Codex `019e335c` ile plan-time istişare → metadata contract
  shape netleştir → impl → cross-AI post-impl review → CI → normal squash →
  gitops digest bump → deploy → verify.
- **Effort**: orta, 1 PR (platform-backend) + gitops digest bump.

### 🔵 P2 — schema-service sonraki capability faz'ları
- **B2 / M8** — programmability gövde envanteri: `sys.sql_modules` view /
  stored-proc / function tanım metni. Kod referansları mevcut, ayrı sprint.
- **B3 / M7** — filegroup + compression envanteri. `StorageInfo` Javadoc'unda
  açık not: "Filegroup and compression are out of scope here — capability
  M7 (B3)".
- Bu faz'lar plan-time Codex istişaresi ister; ADR-0020 truth-tier modeline
  (`authoritative_mssql`) eklenecek yeni envanterler.

### 🟢 P3 — current-state.md Q4 delta
- PR #740 `current-state.md`'i P0+P1+Q3 LIVE'a kadar güncelledi; **Q4**
  (storage catalog-view) henüz current-state.md'ye işlenmedi. Sıradaki
  session küçük bir delta ile (Q4 LIVE re-verify sonrası) ekleyebilir.

---

## Sıradaki Session İçin İlk Komut

```bash
cd /Users/halilkocoglu/Documents/platform-k8s-gitops
git fetch origin main && git log origin/main --oneline -5
cat docs/session-handoff-2026-05-17-session-67-extracttables-q3-q4-complete.md   # bu doc

# P0 — cluster recovery + Q4 storage canlı re-verify
kubectl --context k3d-test --request-timeout=10s get nodes
kubectl --context k3d-test -n platform-test get pod -l app=schema-service -o wide
```
