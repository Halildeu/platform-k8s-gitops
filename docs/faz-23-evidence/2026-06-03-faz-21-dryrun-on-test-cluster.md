# Faz 21.0 dry-run on test cluster — 2026-06-03

> **Generator**: agent-driven dry-run of `audit-and-check.sh` (PR-4 C entry) on k3d-test cluster PG.
> **Scope**: surface design-time assumption drifts BEFORE the natural 30-day stable window (2026-06-22T00:00:00Z + 24h hold) when the operator runs against the prod-shaped snapshot.
> **Authority**: this evidence is NOT an M8 DoD acceptance — it documents test-cluster verdict semantics + flags PR-5 follow-up requirements.
> **Codex consult**: thread `019e8c85-b56a-7260-9026-5a2d7c4240ee` (strategic GO).

---

## 1. Run context

| Field | Value |
|---|---|
| PG host (redacted) | `172.19.0.6` (k3d-test host-bridge) |
| PG cluster | platform-test (k3d-test) |
| PG user | `platform` (test-cluster service user with SELECT grant on application databases) |
| Schema-prefix flag | `notify,endpoint_admin_service,public` |
| Workstation time | 2026-06-03T08:09:31Z (UTC) |
| PG time | 1780474171 / 1780474175 (Unix) |

PG `\l` output (multi-database deployment):

```
auth_db        | platform
core_db        | platform
endpoint_admin | platform
keycloak       | keycloak_user
notify_db      | platform
openfga        | openfga
```

The script (PR-3 A) accepts a **single** `--pg-database` argument. The cluster reality is **multi-database** — Notify in `notify_db`, endpoint-admin in `endpoint_admin`, auth in `auth_db`, core in `core_db`. **This is design assumption drift and the primary follow-up flagged for PR-5.**

---

## 2. notify_db verdict

| Layer | Value |
|---|---|
| `pre-migration-audit.json` verdict | `CLEAN` |
| `r10-invariant-checks.json` verdict | `MANUAL_PENDING` |
| Composite | `MANUAL_PENDING` (exit 2 — Inv-4 not verified) |

### 2.1 Inv-2 per-table

| Schema.Table | Status | Tenant key | NULL count |
|---|---|---|---|
| notify.notification_intent | discovered | `org_id` | 0 |
| notify.notification_dispatch | **missing_table** | — | — |
| notify.notification_delivery | discovered | derived: intent_id → notification_intent.org_id | 0 |
| notify.notification_outbox | **missing_table** | — | — |
| notify.audit_event_v2 | discovered | `org_id` | 0 |
| notify.idempotency_key | discovered | `org_id` | 0 |

Summary: `discovered_count=4 / missing_count=2 / no_tenant_key_count=0 / violation_count=0 / endpoint_discovered_count=0`.

**Findings:**
- `notification_dispatch` + `notification_outbox` missing on test cluster (expected — Faz 23 M6/M7 source-side closure on test cluster differs from prod canonical surface).
- Derived parent-FK join via `intent_id → notification_intent.intent_id` worked end-to-end (Codex iter-3 P0/notifyParentPK absorb verified live).
- Notify schema canonical = `org_id` (charter §1 lock holds for this database).

### 2.2 Inv-3 callback correlation

- Status: `DISCOVERED`
- Tenant path: `derived: delivery.intent_id -> notification_intent.org_id`
- Orphan count: 0
- Provider distinct count: 7

Derived join semantics from Codex iter-3 P0/inv3DerivedJoin absorb executed correctly. Provider distinct count = 7 (multi-provider test cluster — SMTP / SMS / WebPush / etc.).

### 2.3 Inv-1 advisory

- Status: `ADVISORY_ABSENT` (no `request_audit` table on any of the 3 probed schemas).

### 2.4 Verdict route

`r10-invariant-checks.sh` correctly emitted `MANUAL_PENDING` because `--inv4-verified` was NOT passed. This validates Codex iter-1 P0/inv4Gate absorb behavior.

---

## 3. endpoint_admin verdict

| Layer | Value |
|---|---|
| `pre-migration-audit.json` verdict | `CLEAN` |
| `r10-invariant-checks.json` verdict | `OBSERVATION_INSUFFICIENT` |
| Composite | `OBSERVATION_INSUFFICIENT` (exit 2) |

### 3.1 Inv-2 per-table

| Schema.Table | Status | Tenant key | NULL count |
|---|---|---|---|
| endpoint_admin_service.endpoint_device | **missing_table** | — | — |
| endpoint_admin_service.endpoint_devices | discovered | **`tenant_id`** | 0 |
| endpoint_admin_service.endpoint_software_inventory | **missing_table** | — | — |
| endpoint_admin_service.endpoint_software_inventory_state_history | discovered | `tenant_id` | 0 |
| endpoint_admin_service.endpoint_outdated_software | **missing_table** | — | — |
| endpoint_admin_service.endpoint_outdated_software_snapshots | discovered | `tenant_id` | 0 |
| endpoint_admin_service.endpoint_outdated_software_packages | discovered | `tenant_id` | 0 |
| endpoint_admin_service.endpoint_install_audit | discovered | `tenant_id` | 0 |
| endpoint_admin_service.install_audit | **missing_table** | — | — |
| endpoint_admin_service.endpoint_compliance_policy_evaluation | **missing_table** | — | — |
| endpoint_admin_service.endpoint_compliance_evaluations | discovered | `tenant_id` | 0 |
| endpoint_admin_service.endpoint_app_control | **missing_table** | — | — |
| endpoint_admin_service.endpoint_app_control_snapshots | discovered | `tenant_id` | 0 |

Summary: `discovered_count=7 / missing_count=6 / no_tenant_key_count=0 / violation_count=0 / endpoint_discovered_count=7`.

**Findings:**
- **All 7 discovered endpoint tables use `tenant_id`, NOT `org_id`.** The fallback chain (`org_id → tenant_id → derived`) introduced in Codex iter-2 P1/derivedTenantKey absorb caught this drift gracefully — but it means the **charter §1 `tenant == org` lock is not yet realized in code** on the endpoint surface. The endpoint backend currently uses `tenant_id` as its persistence-layer tenant column.
- The plural / `_snapshots` / `_state_history` canonical naming wins; singular fallback candidates (`endpoint_device`, `endpoint_software_inventory`, etc.) are all `missing_table`. Codex iter-4 P1/endpointCoverage absorb verified live.

### 3.2 Inv-3 callback correlation

- Status: `OBSERVATION_INSUFFICIENT`
- Tenant path: empty
- Orphan count: null

Inv-3 probe targets `notify.notification_delivery` which lives in `notify_db`, NOT `endpoint_admin`. The single `--pg-database endpoint_admin` invocation cannot reach Notify schema. This is the visible symptom of the multi-DB design drift.

### 3.3 Verdict route

`OBSERVATION_INSUFFICIENT` correctly emitted because Inv-3 path could not be resolved (cross-DB) and `--inv4-verified` was not passed. Multi-DB cross-schema probes would need a different invocation pattern (PR-5 scope).

---

## 4. Design assumption drifts (PR-5 follow-up scope)

| Drift | Evidence | PR-5 status |
|---|---|---|
| **Multi-DB** — script tek-DB varsayar; prod multi-DB | `\l` shows 6 application DBs | RESOLVED (`--pg-database-list` parametre comma-sep + iter each + merged summary) |
| **tenant_id vs org_id** — endpoint backend `tenant_id` column kullanıyor; charter §1 lock `tenant == org` semantic | endpoint_admin 7/7 `tenant_id`; notify 3/3 `org_id` (+ 1 derived) | DOCUMENTED (charter §1.1 + ADR §3.2 live state); Faz 21.1 sub-faz binding rename + script `tenant_id` fallback chain hazır + Inv-1 test scope `tenant_id` header de kontrol etmeli |
| **Cross-DB Inv-3 callback isolation** — Inv-3 probe Notify schema'da; endpoint_admin DB invocation null path | `tenant_path: ""` ve `status: OBSERVATION_INSUFFICIENT` | **PARTIALLY_RESOLVED** (Codex 019e8c8d Finding 2): wrapper coverage çözüldü — multi-DB iterasyon Notify probe'unu kendi DB'sinde garantiler. **Inv-3 invariant acceptance test'i hâlâ backend integration test gerektirir** (charter §4.3 callback isolation: provider_msg_id reused across tenants → concurrent UPDATE isolated by org_id + external_id pair). Sibling backend repo'da ayrı PR scope'unda kalır. |
| **Singular fallback tables not deployed** — 6 tablo `missing_table` (endpoint_device, install_audit, etc.) | endpoint_admin 6 missing | OBSERVED (audit script `missing_table` status ile graceful; future PR singular fallback alias prune veya `expected_missing` config) |

---

## 5. Anti-pattern guards (verified live)

- [x] READ-ONLY ran on test cluster (no UPDATE/INSERT/DELETE issued)
- [x] No raw tenant/PII data in this evidence document (counts only)
- [x] Workstation `date -u` + PG `time()` both recorded
- [x] `--inv4-verified` flag NOT passed → MANUAL_PENDING + exit 2 (correct gate behavior)
- [x] No backdated evidence — timestamps live from PG `now()` + workstation `date -u`
- [x] Operator manual cross-check checklist still required for any future M8 closure attempt

---

## 6. M8 DoD position

This evidence:
- **DOES** validate PR-3 A audit harness end-to-end against a real PG cluster
- **DOES** surface 4 design drifts requiring PR-5 follow-up
- **DOES NOT** count as Faz 21.0 sub-faz DoD closure (test cluster ≠ prod snapshot; Inv-4 not verified)
- **DOES NOT** advance the M8 DoD blocker chain

The M8 DoD blocker chain remains:
- [ ] M7 v1 30-day stable observation (`MOSTLY_CLEAN_INV4_VERIFIED` from observation harness PR #1234) — natural mark 2026-06-22T00:00:00Z + 24h hold
- [ ] R10 mitigation execution against **prod-shaped snapshot** (after PR-5 multi-DB support lands)
- [ ] Inv-4 manual cross-check against `platform-ai` repo
- [ ] Faz 21 charter draft (MERGED #1235)
- [ ] PR-5 multi-DB / tenant_id discovery enhancements (this evidence's downstream)

---

## 7. Operator next steps (post-PR-5)

1. PR-5 lands multi-DB support
2. Operator obtains prod-shaped snapshot restored to isolated read-only PG
3. `chmod 0400 ~/.faz21-audit.pw` + `audit-and-check.sh --pg-database-list notify_db,endpoint_admin,auth_db,core_db --out-dir /tmp/faz-21-prod-audit`
4. Inv-4 manual cross-check against `platform-ai` (vector partition + prompt filter + embedding cache + audit label)
5. Re-run with `--inv4-verified --inv4-evidence <path>`
6. Composite verdict `MOSTLY_CLEAN_INV4_VERIFIED` → commit `docs/faz-23-evidence/<date>-r10-invariant-evidence-prod.md`
7. M8 closure board comment + advance Faz 21.1 (tenant model code lock-in)

---

## 8. References

- [PR #1234 — PR-1 D M7 observation harness](https://github.com/Halildeu/platform-k8s-gitops/pull/1234)
- [PR #1235 — PR-2 B Faz 21 charter + ADR-0032](https://github.com/Halildeu/platform-k8s-gitops/pull/1235)
- [PR #1236 — PR-3 A R10 mitigation harness](https://github.com/Halildeu/platform-k8s-gitops/pull/1236)
- [PR #1237 — PR-4 C audit-and-check.sh wrapper](https://github.com/Halildeu/platform-k8s-gitops/pull/1237)
- [docs/faz-21/charter.md](../faz-21/charter.md) (§1 `tenant == org` lock; needs §1.2 / §5.3 endpoint `tenant_id` follow-up notation)
- [docs/adr/0032-faz-21-tenant-model.md](../adr/0032-faz-21-tenant-model.md) (§3.2 persistence)
- [docs/operations/RUNBOOKS/RB-faz-21-pre-migration-audit.md](../operations/RUNBOOKS/RB-faz-21-pre-migration-audit.md) (§3.1 wrapper invocation)
- Codex thread audit: `019e8c24` (sprint plan) + `019e8c3e` (charter strategic) + `019e8c85` (next-step consult)
- Board: #760 [Faz 23][M8] Multi-tenant Trigger Gate
