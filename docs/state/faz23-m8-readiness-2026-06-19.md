# Faz 23 M8 #760 — Post-M7 Stabilite Hazırlık Raporu

**Tarih:** 2026-06-19  
**Kapsam:** M7 Trigger Gate 17-günlük (ve canonical 30-günlük) stabilite penceresi değerlendirmesi  
**Canonical kaynak:** docs/notify/milestones.md §M8, issue #760  
**Bu doküman:** READ-ONLY değerlendirme; cluster mutasyonu yok

---

## Özet (Türkçe — 3 satır)

**M7 stabilite verdict:** Observation harness aktif (PR #1234, 2026-06-03 merged); canonical M7 LIVE tarihi 2026-05-23 itibariyle 27 gün geçti, Prometheus 30-gün time gate (elapsed ≥ 2592000 s) 2026-06-22'de dolacak; live cluster Prometheus metrikleri bu remote session'dan sorgulanamadı — gap açıkça belgelendi, metric fabricate edilmedi; CI yeşil (30/30 run SUCCESS, sıfır hata).

**M8 hazır mı? HAYIR** — Canonical 30-gün penceresi 2026-06-22'de dolacak (3 gün eksik); D30 prod cutover (#1381) hâlâ operator-gated (2026-06-09 itibarıyla teyit, sonrasındaki durum belirsiz); operator-bound pre-migration audit/dry-run/per-tenant isolation test yürütülmedi; Faz 21.1 PR2b-iii BE-024c COALESCE zinciri pending.

**Sıradaki concrete adım:** D30 prod cutover (#1381) için operatör kararı → 2026-06-22 (veya sonrası) `NotifyM7StableObservationWindowReady` Prometheus alert'i doğrulanırsa `docs/scripts/m7-stable-evidence.sh` çalıştırıp evidence commit et → R10 audit-and-check.sh prod-shaped snapshot'a uygula → M8 promotion sprint başlat.

---

## 1. M7 Trigger Gate Metrikleri — 17-Günlük Pencere Analizi

### 1.1 Canonical M7 LIVE Zaman Çizelgesi

| Alan | Değer |
|---|---|
| M7 LIVE timestamp (canonical) | 2026-05-23T00:00:00Z (Web Push browser-only DELIVERED end-to-end) |
| M7 LIVE unix | 1779494400 |
| 30-gün mark (Prometheus gate) | 1782086400 = **2026-06-22T00:00:00Z** |
| Bugün (2026-06-19) itibarıyla geçen süre | **27 gün** (2592000 s gerektiriyor; ~2332800 s geçti) |
| Prometheus gate dolana kadar kalan | **~3 gün** |
| Görev notu: "M7 promoted ~2026-06-02" | Discrepancy — canonical M7 LIVE = 2026-05-23; 2026-06-02 PR #1234 (observation harness merge tarihi); canonical alındı |

> **Önemli Boşluk:** Görev tanımı "M7 was promoted ~2026-06-02; M8 promotion was gated on a 17-day stability window" diyor. Canonical recording rule'da M7 LIVE = 2026-05-23 ve 30-gün window şartı var (17 gün değil). 2026-06-02 = observation harness PR #1234'ün merge tarihidir (harness deployment başlangıcı). Bu rapor canonical 30-gün şartını esas alır.

### 1.2 Prometheus Observation Harness

Aşağıdaki kaynaklar 2026-06-03 PR #1234 ile merged; kustomize monitoring stack'e dahil:

```
kustomize/base/monitoring/notify-m7-stable-recording-rule.yaml  (5 composite predicate)
kustomize/base/monitoring/notify-m7-stable-alert-rule.yaml      (2 alert: Regression + WindowReady)
docs/scripts/m7-stable-evidence.sh                              (READ-ONLY evidence emitter)
docs/operations/RUNBOOKS/RB-faz-23-m7-30day-stable-observation.md
```

**5 Composite Predicate (stable_30d = 1 için tümü gerekli):**

| # | Predicate | Eşik | Durum (2026-06-19) |
|---|---|---|---|
| 1 | `dispatch_success_rate_30d` | ≥ 0.995 | ⚠️ Bilinmiyor — live cluster Prometheus erişilemiyor |
| 2 | `dlq_burn_max_30d` (24h window) | ≤ 1.0 | ⚠️ Bilinmiyor — live cluster Prometheus erişilemiyor |
| 3 | `critical_alert_minutes_30d` | == 0 | ⚠️ Bilinmiyor — live cluster Prometheus erişilemiyor |
| 4 | `observation_coverage_30d` | ≥ 0.99 | ⚠️ Bilinmiyor — live cluster Prometheus erişilemiyor |
| 5 | `elapsed_seconds_since_m7_live` | ≥ 2592000 (30 gün) | ❌ **HENÜZ DOLMADI** (~3 gün kaldı; 2026-06-22T00:00:00Z) |

> **Credential Gap:** Bu remote session (GitHub MCP surface only) k3d cluster Prometheus'una (`/prometheus/api/v1/query`) erişim sağlayamıyor. Live metrik değerleri (dispatch_success_rate, dlq_burn, coverage) bu raporda yer almıyor — değerler uydurulmadı. Operatör doğrulaması için `docs/scripts/m7-stable-evidence.sh` kullanılmalı. Prometheus exposer ayrıca #1468 (P1-security: Prometheus/UI anonim erişim) ile halihazırda takip ediliyor.

### 1.3 Alert Noise Tahmini — 17-Günlük Pencere (2026-06-02 → 2026-06-19)

**GitHub API surface'ten elde edilen proxy kanıtlar:**

| Kaynak | Bulgu |
|---|---|
| platform-backend CI — `ci-mvn-check.yml` runs, main, son 30 run | **30/30 SUCCESS**, sıfır failure, sıfır cancellation |
| Tarih aralığı (CI) | 2026-06-15T23:24Z → 2026-06-19T02:56Z (en son 30 run) |
| platform-k8s-gitops commits (2026-06-02→2026-06-19) | alert/rollback niteliğinde commit yok; digest bump, feature, governance commit'leri |
| Alertmanager-bridge self-watch rule | monitoring stack'te mevcut; firing evidence github history'de yok |
| `NotifyM7StableObservationRegression` alert | firing commit kanıtı YOK (geçmişte) |

**Uyarı:** Yukarıdakiler proxy kanıtlardır — Prometheus alertmanager firing timeline direkt sorgulanamadı. Sıfır regression commit = regression olmadığı kanıtı değil; ancak major alert olsaydı incident commit / hotfix pattern'i beklenir (mevcut değil).

**Sonuç:** 17-günlük GitHub-erişilebilir pencerede regression kanıtı YOK. Ancak live Prometheus doğrulaması olmaksızın 5 composite predicate'in tamamı için kesin verdict verilemez. Predicate-5 (elapsed_seconds time gate) kesin olarak DOLMADI.

**Alert-noise (GitHub proxy):** 0 tespit edilen firing, 0 unique incident commit. False-positive rate: ÖLÇÜLEMEYEN (live cluster erişimi gerekiyor).

---

## 2. Tenant Isolation Testleri — platform-backend CI Durumu

### 2.1 CI Durumu

```
Workflow: CI - Maven Build Check
Repo: halildeu/platform-backend
Branch: main
Son 5 run:
  27802537073 — SUCCESS — 2026-06-19T02:56Z — fix(remote-bridge): refresh trust on accepted consent (#715)
  27800306646 — SUCCESS — 2026-06-19T01:44Z — fix(remote-bridge): refresh peer trust on control heartbeat (#714)
  27797068384 — SUCCESS — 2026-06-19T00:07Z — fix(remote-bridge): bind operator close audit
  27789317050 — SUCCESS — 2026-06-18T21:06Z — Add approved script runner catalog (#709)
  27788194377 — SUCCESS — 2026-06-18T20:44Z — Fix remote bridge AD computer resolver fallback (#708)

Son 30 run: 30/30 SUCCESS — SIFIR FAILURE
İncelenen dönem: 2026-06-15T23:24Z → 2026-06-19T02:56Z
```

**Verdict: CI YEŞİL.** Most recent run on main = SUCCESS.

### 2.2 Tenant/Org Isolation Test Dosyaları

GitHub code search (`org_id tenant isolation test repo:halildeu/platform-backend language:java`) sonuçları:

| Dosya | Modül | Kapsam |
|---|---|---|
| `ComplianceGapRepositoryTenantIsolationPostgresIntegrationTest.java` | endpoint-admin-service | `tenant B must NOT see tenant A's RDP gap — tenant boundary fail-closed` |
| `EndpointSoftwareInventoryStateHistoryEffectiveOrgPostgresIntegrationTest.java` | endpoint-admin-service | `countQuery must respect cross-org isolation too` |
| `EndpointOutdatedSoftwareSnapshotPayloadHashAndFleetEffectiveOrgPostgresIntegrationTest.java` | endpoint-admin-service | `Fleet assertion 3: cross-org isolation` |
| `V37CacheFkOrgCompositePostgresIntegrationTest.java` | endpoint-admin-service | `no tenant-composite FK remains; org-composite FK preserves CASCADE; org isolation enforced` |
| `NotificationInboxRepositoryTest.java` | notification-orchestrator | `Cross-tenant isolation (org_id + subscriber_id filter)` |
| `MeetingRepositoryH2Test.java` | meeting-service | `cross-org isolation` (H2 + Postgres IT separate) |
| `TranscriptSegmentRepositoryH2Test.java` | transcript-service | `cross-tenant isolation, ordering, case-insensitive search` |

> **Not:** Yukarıdaki testler `org_id` / `tenant_id` boundary enforcement'i doğruluyor. M8 DoD §3'teki "per-tenant isolation test" ise Faz 21.0 pre-migration audit kapsamında ayrı bir operatör-bound test — `r10-invariant-checks.sh --inv4-verified` gate'i ile ilişkili. Bu CI testleri tamamlayıcı kanıt; M8 DoD'un pre-migration isolation kapısını kapatmıyor.

### 2.3 Son Başarısız Test Yoklaması

`ComplianceGapRepositoryTenantIsolationPostgresIntegrationTest.java` endpoint-admin-service modülünde. Son CI run (2026-06-19) endpoint-admin-service gate'ini de kapsıyor: `3137 tests, 0 failures, 1 skipped` (commit `3216a6b` PR #710 CI kanıtı). Tenant isolation testleri bu run'da GREEN.

---

## 3. M8 Promotion Planı

### 3.1 M8 DoD Teslim Edilebilirler — Güncel Durum

| # | Teslim Edilebilir | Durum | Notlar |
|---|---|---|---|
| A | M7 v1 stable ≥ 30 gün prod | ⏳ **KISMEN** (27/30 gün; 2026-06-22'de doluyor) | Canonical Prometheus time gate; D30 #1381 gate bağımlılığı |
| B | R10 mitigation plan | ✅ HAZIR | `r10-invariant-checks.sh`, `pre-migration-audit.sh`, `audit-and-check.sh` merged (PR #1236+#1237+#1238) |
| C | Pre-migration audit + dry-run | ⚠️ OPERATOR-BOUND | Testai dry-run 2026-06-03 yapıldı (docs/faz-23-evidence/2026-06-03-faz-21-dryrun-on-test-cluster.md); prod-shaped snapshot YOK |
| D | Per-tenant isolation test | ⚠️ OPERATOR-BOUND | `r10-invariant-checks.sh --inv4-verified` Inv-4 manual cross-check henüz yürütülmedi |
| E | Faz 21 charter draft | ✅ MERGED | PR #1235 (docs/faz-21/charter.md + ADR-0032) |
| F | Faz 21.1 `tenant_id → org_id` rename | 🟡 KISMEN | PR #391-394 merged (V29 compat layer + V30 CHECK + entity foundation + canonical write); PR2b-iii BE-024c COALESCE pending |

### 3.2 Spesifik Teslim Edilebilirler — Alertmanager Rules Değişiklikleri

**M8 promotion öncesi gerekli alertmanager değişikliği:** YOKTUR (observation harness halihazırda deployed). M8 promotion = `NotifyM7StableObservationWindowReady` alert firing'ini gözlemleyip evidence commit etmek, akabinde Faz 21 migration sprint'ini başlatmak. Alertmanager kuralları passive observation rolünde; flipping için kural değişikliği gerekmez.

**M8 sonrası eklenmesi gereken alertler (Faz 21 migration sırasında):**
- Per-tenant drift alert: `org_id IS NULL` satır sayısı izleme (Faz 21.1 cleanup PR sonrası)
- Migration progress recording rule: `tenant_id → org_id` rename tamamlanma yüzdesi

### 3.3 OpenFGA Model Değişiklikleri

**M8 doğrudan OpenFGA model değişikliği gerektirmiyor.** M8 = multi-tenant migration PRE-GATE (migration izin gate'i). Ancak Faz 21 kapsamında:
- `type meeting` + `type transcript` eksikliği (#1660) — Faz 24 prod-promotion blocker olabilir; M8 kapsamında değil ama paralelde takip edilmeli.
- ADR-0032 tenant model v1 merged (org_id authoritative, OpenFGA tenant-namespaced, Vault `kv/platform/tenants/<tenant>/` path).

### 3.4 Controller Flag

**M8 promotion tetikleyici = flag DEĞİL:** `r10-invariant-checks.sh --inv4-verified` komutu ile Inv-4 kanıtı + `m7-stable-evidence.sh` kanıt belgesi commit + operatör kararı. Yazılım kapatma/açma flag'i yok.

### 3.5 Rollback Planı

| Senaryo | Rollback Aksiyonu | Süre Tahmini |
|---|---|---|
| Faz 21 migration regression | `pre-migration-audit.sh` snapshot → tenant_id geri yazma migration (Flyway forward-only değil; compat layer korunacak) | 2-4 saat |
| org_id backfill hatası | V29 trigger rollback: DROP TRIGGER → tenant_id sadece path'e dön | 30 dk |
| OpenFGA tuple mismatch | Tuple delete + re-seed via permission-service catalog initializer (idempotent) | 1 saat |
| Notification drift (M7 regression) | `NotifyM7StableObservationRegression` alert → incident runbook RB-faz-23-m7-30day-stable-observation.md §4 | Anlık |
| D30 cutover geri alma | 72h warm rollback window (CLAUDE.md D30 policy) — staging-sw frozen + rollback pointer | ≤ 72 saat |

### 3.6 Acceptance Criteria — Geçer/Kalır Eşikleri

**M8 promotion GEÇER (tüm kriterler karşılanmalı):**

| Kriter | Geçer Eşiği | Kalır Eşiği |
|---|---|---|
| Prometheus `stable_30d` | == 1 (tüm 5 predicate) | Herhangi biri 0 |
| `dispatch_success_rate_30d` | ≥ 0.995 | < 0.995 |
| `dlq_burn_max_30d` | ≤ 1.0 | > 1.0 |
| `critical_alert_minutes_30d` | == 0 | > 0 |
| `observation_coverage_30d` | ≥ 0.99 | < 0.99 |
| Elapsed (natural 30-day mark) | ≥ 2026-06-22T00:00:00Z + 24h hold | Herhangi bir erken doğrulama |
| CI (platform-backend main) | Son 5 run SUCCESS | Herhangi bir FAILURE |
| Tenant isolation testleri | 0 failure (Postgres IT) | ≥ 1 failure |
| R10 Inv-4 | `--inv4-verified` flag ile exit 0 | Exit non-zero veya flag eksik |
| Pre-migration audit prod | `MOSTLY_CLEAN` verdict | `BLOCKING_ISSUES_FOUND` |
| Faz 21.1 PR2b-iii | Merged + CI GREEN | Open veya failing |

### 3.7 Codex Cross-AI Peer Review

**Codex MCP bu session'da erişilebilir değil.** Aşağıda yapılandırılmış Codex peer review prompt'u belgelendi; bir sonraki session'da `mcp__codex__codex` tool'u ile yeni thread açılarak gönderilmeli.

```
Codex Review Request — Faz 23 M8 Multi-tenant Trigger Gate Promotion Plan
Thread: yeni thread (mcp__codex__codex)
Date: 2026-06-19
Requesting session: docs/faz23-m8-readiness-2026-06-19 readiness check

Context:
- platform-k8s-gitops issue #760 (M8 Multi-tenant Trigger Gate)
- M7 v1 LIVE: 2026-05-23; 30-gün mark: 2026-06-22
- Observation harness: notify-m7-stable-recording-rule.yaml (5 composite predicates)
- Faz 21.1 zinciri: PR #391-394 merged; PR2b-iii BE-024c COALESCE pending
- D30 prod cutover (#1381): operator-gated (belirsiz)

Sorular:
1. M8 Promotion gate'ini 30 güne mi yoksa 17 güne mi kalibre etmeliyiz?
   - Canonical milestones.md §M8: "≥30 days in production"
   - Görev tanımı: "17-day stability window"
   - Önerim: 30-gün canonical (Prometheus time gate değişikliği gerektiriyor)

2. Faz 21.1 PR2b-iii (BE-024c DiffCache COALESCE) M8 DoD blocker mı yoksa
   M8 sonrası Faz 21.1 cleanup PR scope'unda mı kalmalı?

3. D30 prod cutover (#1381) M8 trigger clock için hard prerequisite mi?
   (2026-06-09 comment bunu ima ediyor ama notify platform M7 clock
    2026-05-23'ten başladı — çakışma var)

4. Pre-migration audit (pre-migration-audit.sh) test cluster üzerinde
   değil prod-shaped snapshot üzerinde yapılmalı mı? Mevcut testai
   dry-run (2026-06-03-faz-21-dryrun-on-test-cluster.md) M8 DoD §3
   için yeterli mi?

Verdict bekle: AGREE / PARTIAL / REVISE / RED
ready_for_impl: true/false
```

> **Not:** Codex thread referansı mevcut değil. Bu prompt M8 sprint başlamadan önce gönderilmeli. Mevcut Codex references: `019e8c24` (M8 sprint plan-time AGREE), `019e8c93` (PR2b-iii order), `019e8c95` (Faz 21.1 PR1 AGREE).

---

## 4. Sonraki Adım Tavsiyesi

### 4.1 Öncelik Sırası

| Öncelik | Aksiyon | Kimin | ETA |
|---|---|---|---|
| P0 | D30 prod cutover (#1381) operatör kararı | Operatör | ASAP |
| P0 | 2026-06-22 `NotifyM7StableObservationWindowReady` alert doğrula | Operatör + agent | 2026-06-22+ |
| P0 | `docs/scripts/m7-stable-evidence.sh` çalıştır + evidence commit | Agent | Alert sonrası |
| P1 | `audit-and-check.sh` prod-shaped snapshot'a uygula | Operatör + agent | M7 evidence sonrası |
| P1 | R10 Inv-4 manual cross-check (`platform-ai` repo) | Operatör | Paralelde |
| P1 | Codex review prompt gönder (yukarıdaki §3.7) | Agent | Sonraki session |
| P2 | Faz 21.1 PR2b-iii BE-024c DiffCache COALESCE | Agent | Codex AGREE sonrası |
| P2 | `#1660` OpenFGA `type meeting/transcript` live preflight | Agent | Faz 24 deploy öncesi |

### 4.2 Kritik Bağımlılık Zinciri

```
D30 prod cutover (#1381) → M7 30-gün Prometheus gate dolumu (2026-06-22)
  → m7-stable-evidence.sh kanıt commit
  → Codex peer review §3.7
  → audit-and-check.sh prod snapshot (R10 + Inv-4)
  → Faz 21.1 PR2b-iii merge
  → M8 OPEN (Faz 21 migration izin gate)
  → Faz 21 migration sprint
```

### 4.3 Şu An Bloklayan Üç Şey

1. **D30 prod cutover (#1381):** Operatör kararı; agent-doable DEĞİL — irreversible production switch.
2. **30-gün Prometheus time gate:** 2026-06-22T00:00:00Z + 24h hold; retroaktif kısaltma kuralına aykırı.
3. **Inv-4 manual cross-check:** `platform-ai` repo'da vector partition + prompt filter + embedding cache + audit label cross-check; agent autonomous yapamaz (external repo erişimi yok).

---

## Appendix A — Veri Kaynakları ve Erişim Boşlukları

| Kaynak | Durum | Not |
|---|---|---|
| GitHub issue #760 comments | ✅ Okundu | Son comment: 2026-06-09 (Blocked / #1381 gate) |
| milestones.md M7/M8 section | ✅ Okundu | M7 LIVE = 2026-05-23; M8 target = 2026-09-01 |
| notify-m7-stable-recording-rule.yaml | ✅ Okundu | 5 composite predicate + time gate |
| notify-m7-stable-alert-rule.yaml | ✅ Okundu | 2 alert: Regression + WindowReady |
| platform-backend CI runs (main) | ✅ 30/30 SUCCESS | 2026-06-15 → 2026-06-19 |
| Tenant isolation test files | ✅ Bulundu | ComplianceGapRepositoryTenantIsolationPostgresIntegrationTest + 6 diğer |
| Live Prometheus /api/v1/query | ❌ ERİŞİLEMEDİ | Remote session — cluster Prometheus erişimi yok |
| Alertmanager firing timeline | ❌ DOĞRULANAMADI | Live cluster gerekiyor |
| D30 cutover #1381 güncel durum | ⚠️ BELİRSİZ | Son bilgi 2026-06-09; issue OPEN |

---

## Appendix B — İlgili PR ve Issue Referansları

| Referans | Açıklama | Durum |
|---|---|---|
| #760 | M8 Multi-tenant Trigger Gate | OPEN (Blocked) |
| #759 | M7 v1 Closure | OPEN (🟡 In Progress) |
| #1381 | D30 atomic cutover (11 servis) | OPEN (operator-gated) |
| platform-backend PR #391-394 | Faz 21.1 org_id compat + CHECK + entity + canonical write | MERGED |
| platform-k8s-gitops PR #1234 | M7 stable observation harness | MERGED (2026-06-03) |
| platform-k8s-gitops PR #1235 | Faz 21 charter + ADR-0032 | MERGED |
| platform-k8s-gitops PR #1236-#1238 | R10 scripts + audit wrapper | MERGED |
| #1468 | Prometheus/UI public exposure (P1 security) | OPEN |
| #1660 | OpenFGA type meeting/transcript eksikliği | OPEN |

---

*Bu doküman HARD RULE No Fake Work uyumludur: live cluster metriklerine erişilemediği açıkça belgelenmiş, değer uydurulmamış, M8 verdict fabricate edilmemiştir. Codex peer review prompt §3.7'de yapılandırılmış; cross-AI review bir sonraki session'a ertelenmiştir.*
