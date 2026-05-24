# OpenFGA Notification-Authz Model Extension — Safe-Phase Evidence (2026-05-22)

> **Status**: 🟢 Phase 1 safe-phase DONE (model drafted + written + isolated test PASS)
> **Plan**: `docs/notify/m3-supplement-openfga-model-extension-plan-2026-05-14.md` (Codex `019e2651` AGREE, Yol A)
> **Trigger (historical, refined 2026-05-23)**: WebPush OP.1 §3.11 — subscriber-recipient push deliveries returned `BLOCKED_BY_AUTHZ`. Pre-cutover diagnosis attributed this to the OpenFGA model gap (ERP-only types). **Post-cutover finding (PR #996 + #997)** the primary trigger was actually a 401 from `InternalApiKeyAuthFilter` (orchestrator vs permission-service `internal_api_key` mismatch); the model gap was a secondary / latent prerequisite that would surface once the 401 was fixed. Both fixes were required — this safe-phase model extension is the prerequisite half; the 401 was the gate that fires first. See RB-webpush-activation §3.11 "TRUTH CORRECTION 2026-05-23" and "POST-CUTOVER LIVE SUCCESS 2026-05-23" blocks for the full chain.
> **Scope of THIS evidence**: additive model-version write + isolated test ONLY. The
> `ERP_OPENFGA_MODEL_ID` cutover (PR #995, applied 2026-05-23) and the 401 alignment
> (PR #996) are separate explicit steps; §3.11 ✅ closure proven 2026-05-23
> (`docs/runbooks/RB-webpush-activation.md` §3.11 POST-CUTOVER LIVE SUCCESS block).

## 1. Bağlam

The notification-orchestrator `AuthzClient` calls permission-service
`POST /api/v1/internal/authz/check` with `{principal_type:subscriber,
relation:can_receive, object_type:template}`, resolved against OpenFGA. The live
authz model `01KRTJVEMAW80B2D35GN8HJDPG` (store `01KPP0CFP4G82K42Y6NYSPT4JF`
"erp-stage") defined only ERP types — no `template`/`can_receive`/`subscriber` —
so every subscriber-recipient notification authz Check would resolve to deny
**if the call reached the OpenFGA Check stage**.

> **Truth correction 2026-05-23 (post PR #996+#997 root-cause finding)**: This
> safe-phase document originally framed the model gap as the root cause of
> `BLOCKED_BY_AUTHZ`. Post-cutover (PR #995 model_id flip) the actual primary
> trigger was uncovered in orchestrator logs: HTTP 401 from
> `InternalApiKeyAuthFilter` (orchestrator's `NOTIFY_AUTHZ_INTERNAL_API_KEY`
> Vault value never aligned with permission-service's
> `PERMISSION_SERVICE_INTERNAL_API_KEY` — different lengths, different sha256
> hashes). Every pre-cutover `BLOCKED_BY_AUTHZ` outcome was a 401 from this
> filter; the OpenFGA Check call never reached the resolution stage where the
> model gap would have mattered. The model extension in this safe-phase is
> therefore the **secondary / prerequisite half** of the fix: it lets the
> Check resolve to allow **once the 401 is cleared** (PR #996 ESO re-align).
> Both fixes were merged 2026-05-23 and §3.11 SUCCESS push delivery is now
> proven end-to-end — see `docs/runbooks/RB-webpush-activation.md` §3.11
> "POST-CUTOVER LIVE SUCCESS 2026-05-23" block for the closure evidence.

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
live model_id: 01KRTJVEMAW80B2D35GN8HJDPG  (safe-phase capture-time 2026-05-22 — permission-service was still on this; superseded 2026-05-23 by PR #995 cutover → permission-service env `ERP_OPENFGA_MODEL_ID=01KS8QE8…`, see §5)
```

At safe-phase capture-time (2026-05-22) the new version was additive and unused
— `ERP_OPENFGA_MODEL_ID` untouched, so live ERP authz unaffected. Superseded
2026-05-23 by PR #995 cutover (env override flips permission-service to the new
model_id; ERP regression smoke verified clean — see §5).

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

## 5. Cutover applied 2026-05-23 — §3.11 ✅ closed (post safe-phase status)

This section originally listed the remaining cutover steps. The full chain has
since been executed and verified live on k3d-test:

1. ✅ `ERP_OPENFGA_MODEL_ID` → `01KS8QE8T1EJ2DF5CRS4VV9YX1` — **PR #995** (test
   overlay permission-service Deployment env override; canonical Vault patch
   pending operator follow-up).
2. ✅ Backend `AuthzClient` — `object_type=template` resolves via the
   `template` compat type's topic-inheritance path; long-term migration to
   `notification_template` deferred (not blocking).
3. ✅ ERP regression smoke clean — permission-service `/actuator/health` UP,
   `/api/v1/authz/me`+`/authz/version` 200 success traffic, no errors.
4. ✅ Test tuple seeded — `template:t1#topic@notification_topic:test.webpush.delivery`
   + `notification_topic:test.webpush.delivery#can_receive@subscriber:123be09e-…`.
   Production topic→subscriber tuples remain operator-driven per topic.
5. ✅ Intent `webpush-authz-push-1779519748` → status **COMPLETED**,
   `notify_dispatch_outcome_total{channel="push",status="DELIVERED"} 1.0`,
   WebPushAdapter `webpush send: status=201 reason=Created` + `webpush
   delivered: endpointId=c8753c6c-… code=201 msg_id=webpush-7c3e91fe-…`,
   `dispatch end: all_delivered=true`.
6. ✅ RB-webpush-activation §3.11 + §5 metric row 🟡 → ✅ — **PR #997** closure.
7. ⏳ Operator follow-up — `platform-backend/backend/openfga/model.fga`
   canonical update + OpenFGA model-drift gate re-baseline (separate
   governance PR). Vault align (PR #995 + #996 overlay overrides revert)
   when operator has `$TEST_ROOT_TOKEN` access.

Plus root-cause finding (PR #996): the **primary** trigger of `BLOCKED_BY_AUTHZ`
was a 401 from `InternalApiKeyAuthFilter` (orchestrator vs permission-service
`internal_api_key` mismatch in Vault). This model extension is the prerequisite
half that lets the Check resolve once the 401 is cleared. See the truth
correction in §1 above and `docs/runbooks/RB-webpush-activation.md` §3.11.

The cutover changes the platform-wide authz model permission-service resolves
against; per HARD RULE Governance/Sistemic Bug it ran as its own reviewed
chain (#990 → #995 → #996 → #997), not bundled into this safe-phase artifact.
