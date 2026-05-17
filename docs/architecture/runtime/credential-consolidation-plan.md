# Credential Consolidation Plan — Shared `platform` PG Role Vault Path

> **Status**: 🟡 PLAN (Codex `019e3386` plan-time review — AGREE-with-scoping); execution ayrı sprint
> **Trigger**: D1.1c Phase 3 RCA — auth-service Vault `db_password` paylaşımlı `platform` PG rolünden drift etti
> **Scope**: Vault credential topology refactor — ayrı odaklı multi-faz sprint (D1.1 dalgası dışı)
> **Cross-AI**: Codex thread `019e3386-f41e-7820-861a-0ab90255e09c`

---

## 1. Bağlam — neden

D1.1c Phase 3 RCA (`docs/d1.1c-flyway-rca-discovery-2026-05-14.md` §5.Y): auth-service DB layer'ı sessizce kırıktı — Vault `kv/platform/auth-service` `db_password` paylaşımlı `platform` PG rolünün gerçek password'ünden ayrışmıştı.

**Yapısal kök neden**: N servis tek `platform` PG rolünü paylaşır, ama her servisin Vault'ta KENDİ `kv/platform/<svc>` `db_password` kopyası var. Bir kopyanın drift'i tek servisi sessizce kırar; kopyalar arası senkron garantisi yok. Consolidation bu drift sınıfını yapısal olarak ortadan kaldırır.

## 2. Topology (2026-05-17 envanteri)

9 ExternalSecret `SPRING_DATASOURCE_PASSWORD`'ü `kv/platform/<svc>` property `db_password`'den alır:

| Servis | Vault path | Manifest | PG rolü |
|---|---|---|---|
| auth-service | `kv/platform/auth-service` | base apps | `platform` |
| user-service | `kv/platform/user-service` | base apps | `platform` |
| core-data-service | `kv/platform/core-data-service` | base apps | `platform` |
| variant-service | `kv/platform/variant-service` | base apps | `platform` |
| permission-service | `kv/platform/permission-service` | base apps | `platform` (+ ayrı `reports_db_*` → `permission_reports_writer`) |
| notification-orchestrator | `kv/platform/notification-orchestrator` | overlay eso (test+prod) | `platform` |
| endpoint-admin-service | `kv/platform/endpoint-admin-service` | overlay eso (test) | `platform` |
| report-service | `kv/platform/report-service` | base apps | `AlUser_App` |
| schema-service | `kv/platform/schema-service` | base apps | `AlUser_App` |

→ **`platform` rolü: 7 servis** · **`AlUser_App`: 2 servis** · **`permission_reports_writer`: 1** (permission-service ikinci credential) — 3 ayrı credential domain.

## 3. Fazlama (Codex Q1)

- **Faz A** — `platform` rol canonical path, 7 servis. ← bu planın ana kapsamı
- **Faz B** — `AlUser_App` canonical path, report-service + schema-service. Ayrı sub-task/PR/rollout.
- **Faz C** — long-term: per-service dedicated PG roles. Ayrı mimari/security sprint (ADR-level).

`permission_reports_writer` (üçüncü credential domain) bu refactor'a karıştırılmaz.

## 4. Canonical path tasarımı (Codex Q2)

- **Faz A**: `kv/platform/pg-platform-role` — `db_username` (=`platform`) + `db_password` (=`platform` rol password)
- **Faz B** (ileride): `kv/platform/pg-aluser-app-role`
- Service-specific secret'lar (`KEYCLOAK_CLIENT_SECRET`, JWT key, internal API key, peppers, adapter secrets) **mevcut `kv/platform/<svc>` path'lerinde KALIR**.
- ExternalSecret hedef Secret adı **DEĞİŞMEZ** — yalnız `SPRING_DATASOURCE_USERNAME`/`SPRING_DATASOURCE_PASSWORD` entry'lerinin `remoteRef.key`'i canonical path'e taşınır:
  - `SPRING_DATASOURCE_USERNAME` → `kv/platform/pg-platform-role` property `db_username`
  - `SPRING_DATASOURCE_PASSWORD` → `kv/platform/pg-platform-role` property `db_password`

## 5. P0 ön koşul — Vault policy allowlist (Codex Q2 kritik bulgu)

Yeni canonical path yalnız ExternalSecret YAML değişimiyle **ÇALIŞMAZ**. İki Vault policy explicit allowlist kullanır:

- **`bootstrap/vault-policies/common/eso-runtime.hcl`** — ESO read capability. `kv/data/platform/pg-platform-role` allowlist'e eklenmezse ESO **403** alır → Secret sync fail.
- **`bootstrap/vault-policies/common/bootstrap-writer.hcl`** — `platform-bootstrap-writer` AppRole write capability. Mevcut allowlist servis path'leriyle sınırlı; canonical path'i yazamaz.

Her iki policy allowlist update'i planın PARÇASI — herhangi bir repoint'ten ÖNCE uygulanmalı.

## 6. Sequencing (Codex Q3) — operator gate önce

1. **PR-0 (agent)** — bu plan doc + `docs/S2-B1-vault-property-matrix.md` update + policy HCL allowlist diff (`eso-runtime.hcl` + `bootstrap-writer.hcl`) + preflight checklist runbook. **Runtime repoint YOK.**
2. **Operator (test Vault)** — `pg-platform-role` path create+populate (`db_username`/`db_password`); policy apply; ESO read + bootstrap-writer write capability doğrula; hash-only proof (agent'a 16-char prefix sinyali).
3. **PR-1 pilot (agent)** — test-only tek servis repoint; düşük blast radius ilk aday: `endpoint-admin-service` veya `notification-orchestrator` (test).
4. **Pilot verify (agent)** — ESO force-sync + K8s Secret key/hash parity + rollout restart + pod log DB auth + servis smoke.
5. **PR-2 rollout (agent)** — kalan platform-role servisleri testte kademeli (cohort).
6. **Prod** — aynı sıranın AYRI tekrarı. Test kanıtı prod'a otomatik genellenmez (`docs/context-priority-rules.md` test/prod truth ayrımı). Prod credential write açık user approval (ADR-0010).

### Agent / Operator split

- **Agent**: PR, ExternalSecret YAML, policy HCL dosya diff'i, runbook, `kubectl kustomize` build, read-only inventory, ESO force-sync (`kubectl annotate`), Secret hash parity verify, rollout restart, smoke.
- **Operator**: Vault path create/populate (plaintext credential material), policy apply, Vault read/write capability test. Prod credential write → user approval (ADR-0010 §2.5).

## 7. Risk / rollback (Codex Q4)

- **Tek atomik 7-ES live switch ÖNERİLMEZ.** Kademeli: test pilot 1 → test cohort 2-3 → test remaining → prod pilot → prod remaining.
- Base `<svc>/ops/externalsecret.yaml` değişimi test+prod overlay'leri **BİRLİKTE** etkiler → base repoint PR, her iki Vault (test+prod) canonical path + policy hazır olmadan merge **EDİLMEZ**; ya da pilot test-only overlay patch ile yapılır.
- **Rollback** = ExternalSecret `remoteRef`'i eski per-service path'e döndür + ESO force-sync + etkilenen Deployment `rollout restart`.
  - Eski `kv/platform/<svc>` `db_password` değerleri observation penceresi boyunca **SİLİNMEZ**.
  - Target Secret `creationPolicy: Owner` → Secret silerek rollback **YASAK**.
  - `envFrom` pod'lar Secret değişimini process içinde otomatik almaz → rollback sonrası pod restart şart.
  - KV v2 version history yardımcı ama rollback prosedürü "Vault eski version'a dön" değil, öncelikle GitOps `remoteRef` revert + force-sync.

## 8. Sprint parçaları (Codex Q5)

| # | PR | Kapsam |
|---|---|---|
| 1 | `credential-consolidation-plan` | bu doc + S2-B1 matrix update + policy allowlist diff + preflight checklist (runtime repoint yok) |
| 2 | `pg-platform-role pilot` | test-only tek servis repoint + verify |
| 3 | `pg-platform-role rollout` | kalan platform-role servisleri, test sonra prod |
| 4 | `pg-aluser-app-role` | Faz B — report/schema ayrı |
| 5 | `dedicated PG roles` ADR | Faz C — long-term per-service roles |

## 9. Karar (tek cümle)

Near-term canonical Vault path doğru çözüm; ama rollout bir **credential migration** gibi ele alınır (manifest refactor gibi değil) — operator Vault gate + policy allowlist P0 + kademeli 7-servis rollout + test/prod ayrı tekrar; ayrı odaklı sprint olarak yürütülür.

## 10. Referanslar

- D1.1c RCA: `docs/d1.1c-flyway-rca-discovery-2026-05-14.md` §5.Y
- D1.1c credential-convergence runbook: `docs/runbooks/RB-d1.1c-auth-service-credential-convergence.md`
- S2-B1 Vault property matrix: `docs/S2-B1-vault-property-matrix.md`
- Vault policy: `bootstrap/vault-policies/common/eso-runtime.hcl`, `bootstrap/vault-policies/common/bootstrap-writer.hcl`
- ADR-0010 Vault credential lifecycle + DR: `docs/adr/0010-vault-credential-lifecycle-and-dr.md`
- ADR-0011 §2.3 boundary declaration (credential-read/write)
- Codex thread: `019e3386-f41e-7820-861a-0ab90255e09c`
