# Session Handoff — 2026-06-03 Faz 21.1 mid-chain (multi-PR sprint in flight)

> Format: D28 5-alan + sıradaki agent action list
> Branch contamination kanıtı: AG-028 paralel session stash@{0} korunmuş
> M8 sprint scope cleanly closed; Faz 21.1 sub-faz Codex strict order chain devam ediyor.

---

## 1. Bağlam (bu oturumda ne yapıldı)

**Önceki session (M8 readiness sprint 4-PR D→B→A→C + PR-5 follow-up)**: tamamen MERGED ✅. M7 30-day stable observation harness LIVE; Faz 21 charter + ADR-0032 mühürlü; R10 mitigation harness deployable; audit-and-check.sh wrapper operasyonel; PR-5 multi-DB + test cluster dry-run evidence MERGED.

**Bu session (Faz 21.1 sub-faz cross-repo chain — Codex strict-order)**:
- platform-backend PR #391 V29 org_id compat layer MERGED (column nullable + backfill + BEFORE INSERT/UPDATE trigger; 9-assertion PG IT)
- platform-backend PR #392 V30 org_id CHECK constraint MERGED (NOT VALID + VALIDATE pattern; SQLSTATE 23514 reject; 7-assertion PG IT)
- platform-backend PR #393 PR2b-i entity foundation MERGED (7 entities × orgId field + getter/setter + getEffectiveOrgId helper; 4+3 schema/JPA flush IT)
- platform-k8s-gitops PR #1240 V29+V30 testai digest bump MERGED (sha-3bcb8ec)
- platform-backend PR #394 PR2b-ii canonical write MERGED (6 service insert sites × `setOrgId + setTenantId` same UUID; 2 canonical write PG IT)
- platform-backend PR2b-iii branch `feat/faz-21-1-pr2b-iii-be024c-repository-coalesce` open (commit 890c1f61 WIP) — 3-file skeleton DeviceGridQueryBuilder + DiffCacheBackfillService + DiffCacheBackfillWorker with canonical effective-org filter

**Paralel session koordinasyon**: AG-028 P0 catalog uninstall flags (Mavis/Codex paralel agent) lokal stash@{0}'a güvenle saklı; ag-028 branch orijinal state'e reset edildi.

---

## 2. İddia (MERGED PR'lar)

| # | Repo | PR | Title | Merged Time | Codex iter | Tests |
|---|---|---|---|---|---|---|
| 1 | k8s-gitops | #1234 | M8 PR-1 D M7 30-day stable observation harness | 06-03 ~08:30 | 5-iter AGREE | observation rules |
| 2 | k8s-gitops | #1235 | M8 PR-2 B Faz 21 charter + ADR-0032 | 06-03 ~08:35 | 3-iter AGREE | docs |
| 3 | k8s-gitops | #1236 | M8 PR-3 A R10 mitigation execution harness | 06-03 ~08:40 | 5-iter AGREE | scripts + RB + template |
| 4 | k8s-gitops | #1237 | M8 PR-4 C audit-and-check.sh operator wrapper | 06-03 ~08:45 | 1-shot AGREE | wrapper |
| 5 | k8s-gitops | #1238 | M8 PR-5 multi-DB + dry-run evidence + tenant_id drift docs | 06-03 ~08:50 | 3-iter AGREE | dry-run JSON + report |
| 6 | platform-backend | #391 | Faz 21.1 PR1 V29 org_id compat layer | 06-03 ~08:33 | 2-iter AGREE | 9 PG IT |
| 7 | platform-backend | #392 | Faz 21.1 PR2a V30 org_id CHECK constraint | 06-03 ~08:55 | 3-iter AGREE | 7 PG IT |
| 8 | platform-backend | #393 | Faz 21.1 PR2b-i entity foundation | 06-03 ~09:20 | 2-iter AGREE | 4+3 PG IT |
| 9 | k8s-gitops | #1240 | gitops V29+V30 testai digest bump sha-3bcb8ec | 06-03 ~09:25 | 1-shot AGREE | kustomize lint |
| 10 | platform-backend | #394 | Faz 21.1 PR2b-ii canonical write | 06-03 ~09:35 | 1-iter AGREE | 2 PG IT |

**Toplam**: 10 PR MERGED, 23+25=48 PG IT pass, 8 Codex consult thread.

---

## 3. İspatlar

### Cross-AI peer review (Codex thread audit)
- 019e8c24 — M8 sprint plan order D→B→A→C
- 019e8c3e — Faz 21 charter strategic GO
- 019e8c85 — PR-5 follow-up sıralama
- 019e8c95 — PR1+PR2a compat-safe split planı
- 019e8ca1 — PR2a V30 NOT VALID + VALIDATE pattern
- 019e8cac — PR2b plan-time strict order (PR2b-i entity foundation → PR2b-ii canonical write → PR2b-iii repository COALESCE)
- 019e8cc2 — PR2b-ii Option A inline canonical write (Codex AGREE 1-iter)
- 019e8cd4 — PR2b-iii BE-024c repository slice plan-time AGREE (parenthesized OR pattern + cache out-of-scope + 4+2 assertion tests)

### Live cluster
- testai k3d-test cluster pod imageID sha-3bcb8ec live (PR1+PR2a V29+V30 deploy edildi)
- V29 + V30 Flyway runs at pod startup; trigger active; CHECK constraint validated 7 tables

### Repo state (canonical truth)
- main HEAD: 909accef (PR #394 PR2b-ii canonical write)
- Faz 21 charter: `docs/faz-21/charter.md` MERGED in k8s-gitops PR #1235
- ADR-0032: `docs/adr/0032-faz-21-tenant-model.md` MERGED
- Audit script: `docs/scripts/faz-21/audit-and-check.sh` operasyonel + multi-DB
- Dry-run evidence: `docs/faz-23-evidence/2026-06-03-faz-21-dryrun-on-test-cluster.md` MERGED

---

## 4. İspatlamaz

### Operator-bound (sprint scope dışı — HARD RULE: agent autonomously yapmaz)
- [ ] **M7 v1 30-day stable observation evidence** — natural mark 2026-06-22T00:00:00Z + 24h hold. Operator audit-and-check.sh ile evidence script çalıştırır.
- [ ] **Inv-4 manual cross-check** `platform-ai` repo (vector partition + prompt filter + embedding cache + audit label)
- [ ] **Prod-shaped snapshot R10 audit** — audit-and-check.sh multi-DB invocation
- [ ] **D30 atomic cutover** — irreversible, user decision gate

### Agent-doable / in-flight
- [ ] **PR #394 image build retry**: Maven Central transient 403 on first attempt; rerun triggered. Yeni digest beklenmekte → gitops bump için gerek.
- [ ] **PR2b-iii branch** `feat/faz-21-1-pr2b-iii-be024c-repository-coalesce` (commit 890c1f61 WIP):
  - 3-file skeleton implementation tamamlandı (DeviceGridQueryBuilder + DiffCacheBackfillService + DiffCacheBackfillWorker)
  - Bilinen test fail: `DeviceGridQueryBuilderTest.basePage_isSchemaQualified_withLateralJoins_tieBreaker_andOverfetch` — hard-coded expected SQL string. 35 diğer DeviceGridQueryBuilder testi pass. DiffCacheConstraintsPostgresIntegrationTest 9/9 pass.
- [ ] **PR2b-iii dedicated test class** yazma: Codex 019e8cd4 önerisi 4 + 2 assertion (canonical row read + legacy null row read + cross-tenant negative + existing BE-024c regression + null-org fixture pre-assert + LEFT JOIN miss/wrong-attach negative)
- [ ] **PR2b-iii final merge gate** per Codex: PR #394 image build + gitops digest bump + testai apply + runtime evidence required

---

## 5. Bilinen Boşluk + Sıradaki Agent için P0 Aksiyon Listesi

### P0 (hemen sıradaki — agent autonomous)

1. **PR #394 image build retry sonucu kontrol** — Maven Central transient 403; retry'a verildi.
   - `gh run list --branch main --workflow="CI - Image Build + GHCR Push" --limit 3`
   - SUCCESS ise yeni digest al: `gh run view <run_id> --log | grep "Expected Digest.*endpoint-admin"`
   - FAIL ise yine retry ve devam

2. **Gitops digest bump PR** (PR2b-i + PR2b-ii deploy için)
   - branch: feat/faz-21-1-pr2b-i-pr2b-ii-entity-canonical-deploy
   - kustomize/overlays/test/kustomization.yaml endpoint-admin-service pin update
   - Yeni digest = PR #394 image build sonrası (commit 909accef veya yeni HEAD)
   - PR aç + CI green + merge

3. **PR2b-iii test fail absorb** (DeviceGridQueryBuilderTest expected SQL update)
   - File: `endpoint-admin-service/src/test/java/com/example/endpointadmin/grid/DeviceGridQueryBuilderTest.java`
   - Test methodu: `basePage_isSchemaQualified_withLateralJoins_tieBreaker_andOverfetch`
   - Expected SQL string'inde `WHERE d.tenant_id = :tenantId` → `WHERE (d.org_id = :orgId OR (d.org_id IS NULL AND d.tenant_id = :orgId))` parantezli pattern
   - Plus expected param name değişimi: `:tenantId` → `:orgId`
   - Diğer 35 DeviceGridQueryBuilder testi şu an pass — kontrol et + gerekirse benzer pattern update

4. **PR2b-iii dedicated test class** (Codex 019e8cd4 4+2 assertion)
   - File: `endpoint-admin-service/src/test/java/com/example/endpointadmin/grid/DeviceGridCanonicalOrgIdFilterPostgresIntegrationTest.java` (yeni)
   - Test 1: canonical row (org_id + tenant_id eşit) → filter match
   - Test 2: legacy null fixture (`UPDATE ... SET org_id = NULL`) → filter match via tenant_id fallback
   - Pre-assert: legacy fixture INSERT sonrası org_id NULL kalıp kalmadığı
   - Test 3: cross-tenant negative (orgA filter orgB rows döndürmemeli)
   - Test 4: existing BE-024c integration regression
   - Test 5: LEFT JOIN cache miss (device cache yokken düşürmüyor)
   - Test 6: LEFT JOIN cache wrong-attach negative (yanlış tenant cache row attach etmiyor)

5. **PR2b-iii Codex iter chain + PR open + merge**
   - `gh pr create --title "feat(endpoint-admin Faz 21.1 PR2b-iii): BE-024c repository COALESCE..."` 
   - Codex thread 019e8cd4 reply ile post-impl review
   - Iter chain → AGREE → squash merge + cleanup

### P1 (sıralı — agent autonomous, P0 sonrası)

6. PR2b-iii image build + 2. gitops digest bump
7. Testai cluster apply verify (kubectl rollout + Flyway V29+V30 verify)
8. Live evidence collect (post-rollout smoke): `psql -c "SELECT count(*) FROM endpoint_devices WHERE org_id IS NULL"` → 0

### P2 (sonraki sprint scope — agent organize edebilir ama önceliği değil)

9. PR2b-iv: kalan repository/service/controller/DTO surface (bounded domain PR'ları)
10. PR2c: cache tables canonicalize (endpoint_software_diff_cache + endpoint_outdated_software_diff_cache → org_id ekle)
11. Cleanup PR: DROP COLUMN tenant_id (deploy/rollback window + mismatch=0 evidence + Codex strict 3-koşul)

### Branch state (next session başlangıcı için)

```bash
cd ~/Documents/platform-backend
git checkout feat/faz-21-1-pr2b-iii-be024c-repository-coalesce
# 890c1f61 WIP commit: 3 service file edits
# DeviceGridQueryBuilder, DiffCacheBackfillService, DiffCacheBackfillWorker
# main 909accef PR2b-ii MERGED'dan branched
```

Repo'daki stash listesi (paralel session koordinasyonu — UNUNUTULMASIN):
- stash@{0}: AG-028 P0 catalog uninstall flags — parallel Mavis/Codex agent çalışıyor; belongs to feat/ag-028-* branch
- stash@{1-7}: eski WIP'ler (önceki PR çalışmaları)

### Mavis CLI durum (Continuous Autonomous Mode HARD RULE)

`__MAVIS_PARENT_SESSION_ID` env yoktu bu session; multi-session koordinasyon için kullanıcı session ID gerektirir. AG-028 collision tespit edildi ama Mavis send yapılmadı (session ID yoktu). Sonraki session bu paralel akışı kontrol etmeli.

### Codex thread audit referansları (tüm AGREE chain)

```
019e8c24 → M8 sprint plan
019e8c3e → Faz 21 charter strategic
019e8c85 → PR-5 follow-up
019e8c95 → V29+V30 split
019e8ca1 → V30 NOT VALID+VALIDATE
019e8cac → PR2b strict order
019e8cc2 → PR2b-ii Option A inline
019e8cd4 → PR2b-iii BE-024c parenthesized OR
```

Tüm thread'ler aktif; sonraki session'da `mcp__codex__codex-reply` ile devam edilebilir (özellikle 019e8cd4 PR2b-iii iter cycle için).

---

## 6. Anti-pattern guards (KALICI — sonraki session uygular)

- Bare `OR tenant_id = ?` YASAK; her zaman parantezli `(org_id = ? OR (org_id IS NULL AND tenant_id = ?))`
- Repository derived `findByOrgIdOrTenantId(...)` YASAK; explicit `@Query` ile `findByEffectiveOrgId` / `findVisibleToOrg`
- DTO/API contract `orgId` surfacing YASAK PR2b-iii scope'unda (PR2b-iv veya post-window-evidence PR)
- Cache tables (endpoint_software_diff_cache + endpoint_outdated_software_diff_cache) canonicalize YASAK PR2b-iii'te (PR2c scope)
- LATERAL JOIN ON-clause inner predicates tenant_id ile kalır; sadece outer WHERE canonical OR pattern olur
- `DROP COLUMN tenant_id` YASAK PR2b-iii'te (cleanup PR scope, deploy/rollback window + mismatch=0 evidence sonrası)
- V29 trigger'ı "silent compensation" olarak kullanmak YASAK — testler null-org fixture ile explicit kanıt
- `SecurityContext` re-read YASAK; local variable kullan (PR2b-ii pattern carry)
- M8 DoD "done" dili YASAK; 10 PR MERGED sadece source-side ilerleme

---

## 7. Operator-bound DoD chain (M8 closure için)

- [ ] M7 30-day stable evidence (natural mark 2026-06-22)
- [ ] Inv-4 manual cross-check platform-ai
- [ ] Prod-shaped snapshot audit
- [ ] Faz 21.1 cleanup PR (DROP tenant_id) merged
- [ ] D30 atomic cutover

Operator-bound; agent organize eder + chip oluşturur ama autonomously tetiklemez (HARD RULE — Tam Otonom Önerme + Yürütme).

---

## 8. Sonraki Session Açılış Komut Çerçevesi

```bash
# 1. State check
cd ~/Documents/platform-backend
git fetch origin main
git log --oneline origin/main -5
gh pr list --repo Halildeu/platform-backend --state open --limit 10

# 2. PR #394 image build retry sonucu (Maven Central transient 403 sonrası)
gh run list --branch main --workflow="CI - Image Build + GHCR Push" --limit 3
# success ise digest al → gitops bump branch
# fail ise tekrar retry veya cluster pin değişmeden devam

# 3. PR2b-iii branch'i çek + WIP'ten devam
git checkout feat/faz-21-1-pr2b-iii-be024c-repository-coalesce
git log -2 --oneline  # 890c1f61 WIP commit

# 4. DeviceGridQueryBuilderTest expected SQL absorb
# Adım 4: testi oku + 1 fail method'u canonical pattern'e güncelle
# Adım 5: 4+2 assertion dedicated PG IT class yaz
# Adım 6: Codex iter chain submit (019e8cd4 reply)
# Adım 7: PR open + merge
```

### Sonraki session açılışı için kısa context

Session 41/42 — Faz 21.1 sub-faz mid-chain. M8 sprint kapandı. PR2b-iii BE-024c repository COALESCE 3-file WIP commit branched. Bilinen test fail expected SQL hard-coded; iki ek test class write + Codex iter chain + PR open + merge.

Plus image build retry sonucu kontrol + gitops 2. digest bump (entity foundation + canonical write).

Paralel session AG-028 koordinasyonu için Mavis CLI session ID gerek (kullanıcı sağlar).
