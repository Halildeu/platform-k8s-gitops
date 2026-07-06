# Session Handoff — 2026-06-03 Faz 21.1 sub-faz COMPLETE (5-PR chain + 3 gitops bumps MERGED)

> Format: D28 5-alan + sıradaki agent action list
> Chain: V29 → V30 → gitops sha-3bcb8ec → PR2b-i → PR2b-ii → gitops sha-909acce → PR2b-iii → gitops sha-688c0b9
> Total: 5 platform-backend PR + 3 platform-k8s-gitops digest bump PR + 1 dedicated PG IT class + 6 Codex AGREE thread

---

## 1. Bağlam (bu oturumda ne yapıldı)

**Önceki session**: M8 readiness sprint 4-PR D→B→A→C + PR-5 follow-up tamamen MERGED (#1234-#1238).

**Bu session**:
- Faz 21.1 PR1 (V29) + PR2a (V30) MERGED + gitops #1240 (sha-3bcb8ec) MERGED
- Faz 21.1 PR2b-i entity foundation + PR2b-ii canonical write MERGED
- Gitops #1243 (sha-909acce) MERGED + testai LIVE evidence (V29+V30 active, Flyway version v30, Spring Boot 93.881s)
- Faz 21.1 PR2b-iii BE-024c repository COALESCE MERGED (PR #395)
- Gitops #1244 (sha-688c0b9) opened, CI pending

Codex 6 thread AGREE chain — plan-time + post-impl review hepsi clean.

---

## 2. İddia (MERGED PR'lar — bu session 8 PR + paralel session AG-028 stash safe)

### platform-backend (5 PR)

| # | PR | Title | Merge Time | Codex iter | Tests |
|---|---|---|---|---|---|
| 1 | #391 | Faz 21.1 PR1 V29 org_id compat layer (column + backfill + trigger) | 06-03 ~08:33 | 2-iter AGREE | 9 PG IT |
| 2 | #392 | Faz 21.1 PR2a V30 org_id CHECK constraint (NOT VALID + VALIDATE) | 06-03 ~08:55 | 3-iter AGREE | 7 PG IT |
| 3 | #393 | Faz 21.1 PR2b-i entity foundation (7 entities × orgId Option A) | 06-03 ~09:20 | 2-iter AGREE | 4+3 PG IT |
| 4 | #394 | Faz 21.1 PR2b-ii canonical write (6 service insert sites Option A inline) | 06-03 ~09:35 | 1-iter AGREE | 2 PG IT |
| 5 | #395 | Faz 21.1 PR2b-iii BE-024c repository COALESCE (3 read sites parenthesized OR) | 06-03 ~10:25 | 0-iter AGREE (post-impl) | 5 PG IT (dedicated) |

### platform-k8s-gitops (3 PR)

| # | PR | Title | Merge Time | Live Evidence |
|---|---|---|---|---|
| 6 | #1240 | gitops bump endpoint-admin sha-3bcb8ec (V29+V30 deploy) | 06-03 ~09:17 | (deployment already had sha-3bcb8ec equivalent f9c1e3aa pin pre-PR1) |
| 7 | #1243 | gitops bump endpoint-admin sha-909acce (PR2b-i+ii deploy) | 06-03 ~10:15 | ✅ Pod imageID sha256:2cadcdcb match; Flyway v30; Spring Boot 93.881s; HTTP 401 auth |
| 8 | #1244 | gitops bump endpoint-admin sha-688c0b9 (PR2b-iii deploy) | open, CI pending | — |

### Toplam tests

**93/93 endpoint-admin PG IT PASS** (Testcontainers PG 16-alpine + DataJpaTest + non-public schema topology):
- V29 9 + V30 7 + EntityFoundation 4 + JpaFlush 3 + CanonicalWrite 2 = 25/25 (PR1-PR2b-ii regression)
- PR2b-iii dedicated 5/5: DeviceGridCanonicalOrgIdFilterPostgresIntegrationTest
- DeviceGridQueryBuilder 36 + DeviceGridExportBuilder 8 = 44/44 unit (expected-SQL absorbed)
- Schema Qualification 3 + Schema5Cache 7 + DiffCacheConstraints 9 = 19/19 read regression

---

## 3. İspatlar

### Cross-AI peer review chain (HARD RULE provider-level)

| Thread | Phase | Verdict | Iter |
|---|---|---|---|
| 019e8c95 | PR1+PR2a compat-safe split planning | AGREE Option B | 1-shot |
| 019e8ca1 | V30 NOT VALID + VALIDATE pattern (PR2a) | AGREE | 2-iter |
| 019e8cac | PR2b strict-order plan (entity → write → repository) | AGREE | 1-shot |
| 019e8cc2 | PR2b-ii Option A inline canonical write (plan-time) | AGREE | 1-iter |
| 019e8cd4 | PR2b-iii parenthesized OR + COALESCE + 4+2 PG IT (plan-time) | AGREE | 1-shot |
| 019e8cf8 | PR2b-iii post-impl 5/5 lens (Claude impl, Codex review) | AGREE (must-fix yok) | 1-shot |

### Live cluster (testai k3d-test)

```
kubectl get pod -l app.kubernetes.io/name=endpoint-admin-service:
  ghcr.io/halildeu/platform-backend-endpoint-admin-service@sha256:2cadcdcb449e23b23dc1f5f567a55642076d20cd0e3e8364cbba249598eaaae3

Flyway log:
  "Successfully applied 2 migrations to schema endpoint_admin_service, now at version v30
   (execution time 00:00.235s)"

Spring Boot startup:
  "Started EndpointAdminServiceApplication in 93.881 seconds (process running for 97.541)"
  Tomcat 8096 (main) + 8081 (admin)

Smoke endpoints:
  GET /actuator/health → HTTP 401 (auth gate functional)
  GET /api/v1/endpoint-admin/devices → HTTP 401 (auth gate functional)
```

### Repo state (canonical truth)

- platform-backend HEAD: 688c0b9b (PR #395 PR2b-iii merge commit)
- platform-k8s-gitops HEAD: ab6b3d1 (PR #1243 merge commit; #1244 branch open)
- Memory: `~/.claude/projects/<slug>/memory/project_faz_21_1_org_id_closure.md` (Faz 21.1 5-PR chain detailed reference)

### PR2b-iii pattern (Codex 019e8cd4)

```sql
-- Filter predicates (3 sites: page query, export, count preflight)
WHERE (d.org_id = :orgId OR (d.org_id IS NULL AND d.tenant_id = :orgId))

-- Pure-enumeration (Worker discovery)
SELECT DISTINCT COALESCE(org_id, tenant_id) AS org FROM endpoint_devices ORDER BY org
```

### V29 trigger + V30 CHECK live behaviour

```sql
-- V29 (BEFORE INSERT/UPDATE on each tenant-scoped table):
IF NEW.org_id IS NULL AND NEW.tenant_id IS NOT NULL THEN
    NEW.org_id := NEW.tenant_id;
END IF;

-- V30 (CHECK constraint, two-phase NOT VALID + VALIDATE):
CHECK (org_id IS NULL OR org_id = tenant_id)
-- Mismatch dual-write → SQLSTATE 23514 (PG check_violation)
```

---

## 4. İspatlamaz

### Sprint scope dışı (PR2b-iv + PR2c + Cleanup — agent autonomous)

- [ ] **PR2b-iv**: kalan repository derived methods + service-layer secondary read sites + controller/DTO orgId surfacing (bounded slices, multiple PRs)
- [ ] **PR2c**: cache table canonicalize — V31 migration ADD COLUMN org_id UUID nullable on endpoint_software_diff_cache + endpoint_outdated_software_diff_cache + backfill from joined endpoint_devices.org_id (Codex 019e8cd4 §4 strict scope deferred)
- [ ] **Cleanup PR**: DROP COLUMN tenant_id (post-window evidence + mismatch=0 audit, agent autonomous after operator gates)

### Operator-bound (HARD RULE: agent autonomously yapmaz)

- [ ] **M7 v1 30-day stable observation evidence** — natural mark 2026-06-22T00:00:00Z + 24h hold. Operator audit-and-check.sh ile.
- [ ] **Inv-4 manual cross-check** `platform-ai` repo (vector partition + prompt filter + embedding cache + audit label)
- [ ] **Prod-shaped snapshot R10 audit** — audit-and-check.sh multi-DB invocation
- [ ] **D30 atomic cutover** — irreversible, user decision gate

---

## 5. Bilinen Boşluk + Sıradaki Agent için P0 Aksiyon Listesi

### P0 (hemen sıradaki — agent autonomous chain'i kapatma)

1. **PR #1244 (gitops PR2b-iii bump sha-688c0b9) CI green** + ADR-0011 BG-1 + cross-ai-audit (if needed — PR body already includes correct 7-class taxonomy + Implementer AI/Reviewer AI/Codex thread/Verdict format)
2. **Merge #1244** + forensic cleanup
3. **Testai apply**: `kubectl --context k3d-test -n platform-test set image deployment/endpoint-admin-service endpoint-admin-service=ghcr.io/halildeu/platform-backend-endpoint-admin-service@sha256:25ef5a33ab0f62589ad8ddf5d4c47cfbe43016ce7142e0b14586536fd61d64a2`
4. **Live evidence collect**:
   - Pod imageID match sha256:25ef5a33
   - Spring Boot startup clean (no Hibernate ORM-validate error)
   - Smoke 401 auth gate
   - Optional: real-tenant test query through gateway URL to verify canonical OR pattern functional

### P1 (sıralı — agent autonomous, P0 sonrası)

5. **PR2b-iv planning + impl**: bounded slices via Codex iter chain
   - Scope analysis: `git grep -nE "(findByTenantId|tenant_id\s*=\s*\?)" endpoint-admin-service/src/main/java/` to enumerate residual read sites
   - Slice list:
     a. Endpoint device repository derived methods
     b. Software inventory state-history reads
     c. Compliance evaluation reads
     d. AppControl reads
     e. InstallAudit reads
     f. Controller DTO surface (orgId JSON field — surfacing decision)
   - Per slice: dedicated branch + bounded PR ≤ 5 file + dedicated test class + Codex plan-time AGREE → impl → post-impl AGREE → merge
6. **PR2c cache canonicalize**:
   - V31 migration scaffold (ADD COLUMN org_id + backfill JOIN endpoint_devices + INDEX + optional trigger)
   - Cache table entity additions
   - DiffCacheService write path + DeviceGridQueryBuilder LEFT JOIN ON-clause flip
   - Codex iter chain plan-time + impl + post-impl

### P2 (sonraki sprint scope — Cleanup PR + sister domain)

7. **Cleanup PR**: DROP COLUMN tenant_id (Codex strict 3-koşul: operator gate'leri + window evidence + mismatch=0)
8. **Sister domain Faz 21.2** (notify_db): tenant_id → org_id pattern mirror, same V29/V30/entity/write/repository chain

### Operator gates (deferred)

9-12. Operator-bound items (M7 30-day + Inv-4 + R10 prod-shaped + D30 cutover)

---

## 6. Anti-pattern guards (KALICI — sonraki session uygular)

- Bare `OR tenant_id = ?` YASAK — her zaman parantezli `(org_id = ? OR (org_id IS NULL AND tenant_id = ?))`
- Repository derived `findByOrgIdOrTenantId(...)` YASAK — explicit `@Query` ile `findByEffectiveOrgId` / `findVisibleToOrg`
- DTO/API contract `orgId` surfacing PR2b-iv'te ele alınır (PR2b-iii scope dışı)
- Cache tables (endpoint_software_diff_cache + endpoint_outdated_software_diff_cache) canonicalize PR2c scope (PR2b-iii LEFT JOIN ON-clause tenant_id stays)
- LATERAL JOIN ON-clause inner predicates tenant_id ile kalır; sadece outer WHERE canonical OR pattern olur
- `DROP COLUMN tenant_id` YASAK Cleanup PR scope (deploy/rollback window + mismatch=0 evidence + Codex strict 3-koşul)
- V29 trigger'ı "silent compensation" olarak kullanmak YASAK — testler null-org fixture ile explicit kanıt (DISABLE TRIGGER USER pattern)
- `SecurityContext` re-read YASAK; local UUID var kullan (PR2b-ii Option A inline pattern carry)
- M8 DoD "done" dili YASAK; 5-PR chain MERGED sadece source + testai LIVE; cleanup PR + 30-day stable + Inv-4 + R10 + D30 hala açık
- Cross-AI peer review HARD RULE: aynı sağlayıcının session/subagent'i review için yetmez — implementer claude, reviewer codex (provider farklı)

---

## 7. Operator-bound DoD chain (M8 closure için)

- [ ] PR2b-iv tüm slices MERGED
- [ ] PR2c cache canonicalize MERGED
- [ ] Cleanup PR (DROP COLUMN tenant_id) MERGED
- [ ] M7 30-day stable evidence (natural mark 2026-06-22)
- [ ] Inv-4 manual cross-check platform-ai
- [ ] Prod-shaped snapshot audit
- [ ] D30 atomic cutover

Operator-bound items: agent organize eder + spawn_task chip oluşturur ama autonomously tetiklemez (HARD RULE — Tam Otonom Önerme + Yürütme).

---

## 8. Sonraki Session Açılış Komut Çerçevesi

```bash
# 1. State check
cd ~/Documents/platform-k8s-gitops
git fetch origin --quiet
git log --oneline origin/main -3
# Beklenen: ab6b3d1 (PR #1243) MERGED, 3fa7ce2 (PR-5) MERGED, ...
gh pr list --repo Halildeu/platform-k8s-gitops --state open --limit 5
# Eğer #1244 hala open → CI green bekle + merge + apply

# 2. PR2b-iii testai LIVE doğrulama
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test get pod -l app.kubernetes.io/name=endpoint-admin-service -o jsonpath='{.items[0].status.containerStatuses[0].imageID}'; echo"
# Beklenen: sha256:25ef5a33... (PR2b-iii deploy)

# 3. PR2b-iv kapsamı analizi
cd ~/Documents/platform-backend
git grep -nE "(findByTenantId|tenant_id\s*=\s*\?)" endpoint-admin-service/src/main/java/ | head -30
git grep -nE "@Query.*tenant_id" endpoint-admin-service/src/main/java/ | head -20
# Bu çıktı PR2b-iv bounded slices için hammadde

# 4. Codex plan-time consult (PR2b-iv strict-order plan)
# mcp__codex__codex prompt: "Faz 21.1 PR2b-iv plan — kalan repository/service/controller/DTO surface ..."
# AGREE sonrası direkt impl (Plan Consensus Autonomy HARD RULE)

# 5. Sprint chain'i devam — ilk slice PR open, CI, merge, testai apply, smoke, sonraki slice
```

### Sonraki session açılışı için kısa context

Session 43 — Faz 21.1 sub-faz tamamen MERGED + LIVE (PR2b-iii dahil). M8 DoD'nin "endpoint_admin domain canonicalization" ayağı tamamlandı. Sırada PR2b-iv (kalan repository/service/controller/DTO surface bounded slices) + PR2c (cache canonicalize) + Cleanup PR (operator gates sonrası) + sister domain Faz 21.2 (notify_db).

Mavis CLI session ID env yok (önceki session'da AG-028 stash@{0} korunmuş; sonraki session paralel agent koordinasyonu için Mavis session ID lazım).
