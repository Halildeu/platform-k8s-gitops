# OpenFGA Notification-Authz Model Extension — Safe-Phase Evidence (2026-05-22)

> **Status**: 🟢 Phase 1 safe-phase DONE (model drafted + written + isolated test PASS)
> **Plan**: `docs/notify/m3-supplement-openfga-model-extension-plan-2026-05-14.md` (Codex `019e2651` AGREE, Yol A)
> **Trigger**: WebPush OP.1 §3.11 — subscriber-recipient push deliveries returned `BLOCKED_BY_AUTHZ` because the live OpenFGA model held only ERP types.
> **Scope of THIS evidence**: additive model-version write + isolated test ONLY. The
> `ERP_OPENFGA_MODEL_ID` cutover (which makes permission-service use the new model)
> is a separate explicit step — see §5.

## 1. Bağlam

The notification-orchestrator `AuthzClient` calls permission-service
`POST /api/v1/internal/authz/check` with `{principal_type:subscriber,
relation:can_receive, object_type:template}`, resolved against OpenFGA. The live
authz model `01KRTJVEMAW80B2D35GN8HJDPG` (store `01KPP0CFP4G82K42Y6NYSPT4JF`
"erp-stage") defined only ERP types — no `template`/`can_receive`/`subscriber` —
so every subscriber-recipient notification delivery was `BLOCKED_BY_AUTHZ` by
construction.

## 2. Yapılan (safe phase — additive, zero live ERP-authz impact)

The extended model DSL (`docs/notify/openfga-notification-model.dsl`) = the 10
ERP types **byte-identical** + 5 new notification types (Codex Yol A design):

| Type | Relations |
|---|---|
| `subscriber` | `member: [user]` |
| `service_account` | — |
| `notification_topic` | `can_receive: [subscriber]`, `can_publish: [service_account, user]` |
| `notification_template` | `topic: [notification_topic]`, `can_receive: can_receive from topic`, `can_publish: can_publish from topic` |
| `template` | (transition-compat alias of `notification_template`) |

Topic-based inheritance: a subscriber is granted `can_receive` on a
`notification_topic`; templates inherit via their `topic` relation. Per-template
direct grant is intentionally NOT modeled (governance: topic-scoped only).

**Written as a NEW immutable model version** via
`POST /stores/01KPP0CFP4G82K42Y6NYSPT4JF/authorization-models`:

```
NEW model_id:  01KS8QE8T1EJ2DF5CRS4VV9YX1
live model_id: 01KRTJVEMAW80B2D35GN8HJDPG  (UNCHANGED — permission-service still uses this)
```

The new version is additive and unused — `ERP_OPENFGA_MODEL_ID` is untouched, so
live ERP authz is unaffected.

## 3. ERP regression guard

Both `model.fga` (current) and the extended DSL were rendered to OpenFGA JSON and
the 10 ERP `type_definitions` compared:

```
ERP types byte-identical in extended model: True
divergent: NONE — ERP authz unaffected
```

## 4. İzole Check test (against new model_id 01KS8QE8T1EJ2DF5CRS4VV9YX1)

Test tuples seeded:
- `notification_topic:test.webpush.delivery#can_receive@subscriber:123be09e-e008-43ca-a7d1-ceba4595f80d`
- `template:t1#topic@notification_topic:test.webpush.delivery`

| Check | Result | Expected |
|---|---|---|
| `subscriber:123be09e-… # can_receive @ template:t1` | **True** | True — topic inheritance resolves |
| `subscriber:nobody-xyz # can_receive @ template:t1` | False | False — no grant |
| `subscriber:123be09e-… # can_receive @ notification_template:t1` | False | False — t1 linked under `template`, type isolation holds |
| `user:nobody-xyz # viewer @ company:nonexist` | False | False — ERP types valid + Check works in new model |

Topic-inheritance ALLOW path verified end-to-end inside OpenFGA.

## 5. Kalan — model_id cutover (separate explicit step, ERP-authz-affecting)

To make the notification authz path live (and unblock `SUCCESS`-status WebPush
delivery, RB-webpush-activation §3.11):

1. `ERP_OPENFGA_MODEL_ID` → `01KS8QE8T1EJ2DF5CRS4VV9YX1` (Vault `kv/platform/openfga/model_id` + ESO sync + permission-service rollout).
2. Backend `AuthzClient` — confirm `object_type=template` keeps resolving (the `template` compat type covers it); long-term migrate to `notification_template`.
3. ERP authz regression smoke (allow + deny) on the cutover model.
4. Seed the production topic→subscriber tuples (here only the `webpush-smoke` test tuple exists).
5. Re-run the WebPush push delivery test → expect intent `DELIVERED` + `notify_dispatch_outcome_total{channel="push",status="SUCCESS"}` > 0.
6. RB-webpush-activation §3.11/§5 metric row 🟡 → ✅.
7. `platform-backend/backend/openfga/model.fga` canonical update + OpenFGA model-drift gate re-baseline.

The cutover changes the platform-wide authz model permission-service resolves
against; per HARD RULE Governance/Sistemic Bug it runs as its own reviewed
change, not bundled into this safe-phase artifact.
