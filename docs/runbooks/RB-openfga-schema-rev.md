# RB-OpenFGA-schema-rev — OpenFGA Schema Revision Migration Runbook

> Codex 2026-05-04 thread `019df310` Sprint D prep:
> "OpenFGA schema rev migration runbook. Export old model/tuples, write new
> model, dual-read smoke, tuple backfill, OPENFGA_MODEL_ID rotate, rollback,
> fixture update ve D29/D35 evidence adımları. #346 gap'i de bu runbook'un
> ilk concrete case'i olsun."
>
> İlk concrete case: **canonical super-admin inheritance migration** — bootstrap
> fixture model.fga + upstream platform-backend model'i target-state şemaya
> taşımak için çalıştırılacak.

## Runbook scope

OpenFGA model değişiklikleri (relation rename, type addition, inheritance rule
ekleme) için step-by-step migration. Live store'daki tuple'ları kırmadan,
rollback window ile, dual-read smoke ile.

## Triggering scenarios

1. **Canonical super-admin inheritance migration** (concrete case — Codex P1):
   - module/action/report types'a `org: [organization]` relation eklemek
   - `can_view`/`can_manage`/`allowed` relations'ına `or admin from org` rule
   - Live tuple migration: yeni `<obj>#org@organization:default` link'leri

2. **Type addition** (e.g. new `subscription` type for tenant billing):
   - Add new type with relations
   - Backfill tuples for existing tenants
   - Sunset old workaround if any

3. **Relation rename** (e.g. `viewer` → `read_access`):
   - Add alias with both names compatible
   - Backend code update with both names accepted (read-side)
   - Backfill new relation tuples
   - Sunset old name (deletes via tuple write API)

4. **Inheritance rule change** (e.g. add `but not blocked` exception):
   - Same model rev, no tuple change
   - But D35 evidence required to prove no regression on prior allow/deny

## Pre-flight (before any model rev work)

### Snapshot existing state

```bash
# Export current model
curl -s http://10.9.10.53:8081/stores/<store_id>/authorization-models \
  | jq '.authorization_models[0]' > /var/backups/openfga-pre-rev/model.json

# Export ALL tuples
mkdir -p /var/backups/openfga-pre-rev/tuples
# Use cutover-bundle.sh — already does this (Codex P0 #4)
bash scripts/cutover/cutover-bundle.sh
ls /var/backups/cutover/cutover-bundle-*/openfga-export.json
```

### Verify baseline allow/deny

```bash
# D29 smoke baseline: known admin should allow, known regular should deny
OPENFGA_URL=http://10.9.10.53:8081 \
OPENFGA_STORE_ID=<store_id> \
bash scripts/smoke-openfga-fixture.sh

# Or: project-specific super-admin fixture
bash tests/openfga/run_super_admin_fixture.py
```

Save the output as **pre-rev evidence**. Will compare post-rev.

### Operator checklist before proceeding

- [ ] Cutover bundle successfully snapped (sha256 verified in MANIFEST.json)
- [ ] Baseline smoke run captured + saved
- [ ] Codex thread opened with model rev intent + diff
- [ ] Operator on standby for rollback if smoke RED post-rev

## Migration steps

### Step 1: Write new model with backwards compatibility

```fga
# Example: canonical super-admin inheritance migration
type module
  relations
    define org: [organization]
    define can_edit: [user] or admin from org but not blocked
    define can_manage: [user] or can_edit or admin from org but not blocked
    define can_view: [user] or can_manage or admin from org but not blocked
    define blocked: [user]
```

**Backwards compat principles**:
- New relations are additive (existing tuples still resolve)
- Inheritance rules can ADD allow paths, not REMOVE
- Sunset patterns (e.g. removing 39-tuple support) require separate deprecation rev with notice window

### Step 2: Render + write new model

```bash
# Render via existing helper
python3 bootstrap/local-fixtures/openfga/render_model_json.py \
  bootstrap/local-fixtures/openfga/model.fga > /tmp/new-model.json

# Write new auth model (returns new model_id)
NEW_MODEL_ID=$(curl -s -X POST \
  http://10.9.10.53:8081/stores/<store_id>/authorization-models \
  -H "Content-Type: application/json" \
  -d @/tmp/new-model.json | jq -r .authorization_model_id)
echo "new model_id: $NEW_MODEL_ID"
```

Note: OpenFGA versions models. Old model still works for existing tuples;
new model only takes effect when explicitly used in /check API call.

### Step 3: Dual-read smoke (old vs new model)

For 5 representative tuples (mix of admin + regular + edge cases):

```bash
for case in tests/openfga/fixtures/super-admin-allow-deny.yaml; do
  for model in $OLD_MODEL_ID $NEW_MODEL_ID; do
    # Run /check with each model_id
    # Compare allow/deny outcome
  done
done
```

**Acceptance criteria**:
- Old model answers unchanged (zero regression)
- New model answers: superset of old (added allow paths only)
- Specifically: previously-denied super-admin checks now ALLOW

If new model produces unexpected DENY where OLD was ALLOW: **STOP**.
This is a regression. Fix model.fga, rewrite, retry.

### Step 4: Backfill tuples

For super-admin inheritance case:

```bash
# For each rendered module/action/report object referenced in production tuples,
# write the org link tuple
PROD_OBJECTS=$(curl -s http://10.9.10.53:8081/stores/<store_id>/list-objects ...)

for obj in $PROD_OBJECTS; do
  case "$obj" in
    module:*|action:*|report:*)
      curl -X POST http://10.9.10.53:8081/stores/<store_id>/write \
        -d "{
          \"writes\": {\"tuple_keys\": [{\"user\": \"organization:default\", \"relation\": \"org\", \"object\": \"$obj\"}]},
          \"authorization_model_id\": \"$NEW_MODEL_ID\"
        }"
      ;;
  esac
done
```

After backfill, every module/action/report has its parent org link.

### Step 5: Update OPENFGA_MODEL_ID env in services

The permission-service backend reads `OPENFGA_MODEL_ID` from ConfigMap.
Switch it to the new model_id.

Selective ConfigMap apply (D17 koruma):

```bash
# Update ConfigMap directly (not via overlay apply)
kubectl --context k3d-prod -n platform-prod set env deployment/permission-service \
  OPENFGA_MODEL_ID=$NEW_MODEL_ID

# Rolling restart to pick up new env
kubectl --context k3d-prod -n platform-prod rollout restart deploy/permission-service
kubectl --context k3d-prod -n platform-prod rollout status deploy/permission-service
```

### Step 6: Post-rev smoke (live verification)

Run D29 4-tier smoke + super-admin fixture against live cluster:

```bash
bash scripts/smoke/d29-smoke-runner.sh prod
# Verify Tier 4 (Zanzibar): allow + deny synthetic OK

bash tests/openfga/run_super_admin_fixture.py
# Verify all super-admin cases now PASS (no DENY where ALLOW expected)
```

**Acceptance**:
- D29 4-tier all GREEN
- Super-admin fixture 100% PASS (no continue-on-error needed)
- No new alarm in alarm_receiver log

### Step 7: D35 evidence (canlı user verification)

Live-user smoke:

```bash
# Halil (existing super-admin) login → /api/v1/users → 200
# Halil → /authz/me → modules: { USER_MANAGEMENT: "MANAGE", ... }
# Regular user (e.g. test-viewer@) → /api/v1/users → 403 (still denied)
```

If live super-admin's existing access changed: **STOP and rollback** (Step 8).

### Step 8: Update gitops repo

After live verification:

1. Update `bootstrap/local-fixtures/openfga/model.fga` to match new model
2. Run `OpenFGA Model Drift Gate (Faz 19.11 Step 4)` — should pass (fixture parity)
3. Update `tests/openfga/run_super_admin_fixture.py` — remove `continue-on-error` from CI workflow
4. Update `docs/authz/openfga-model-contract.md` — replace "target-state" with "current implementation"
5. Open PR for the 3 changes above

## Rollback

If any step fails or post-rev smoke RED:

### Rollback model_id (fast)

```bash
# Switch back to old model_id
kubectl --context k3d-prod -n platform-prod set env deployment/permission-service \
  OPENFGA_MODEL_ID=$OLD_MODEL_ID
kubectl rollout restart deploy/permission-service
```

Old model is still in store (OpenFGA versions models, doesn't delete).

### Rollback tuples (if backfilled new tuples need removal)

```bash
# Reverse the org-link backfill
for obj in $BACKFILLED_OBJECTS; do
  curl -X POST http://10.9.10.53:8081/stores/<store_id>/write \
    -d "{\"deletes\": {\"tuple_keys\": [{\"user\": \"organization:default\", \"relation\": \"org\", \"object\": \"$obj\"}]}}"
done
```

### Full rollback (worst case — restore from cutover-bundle)

```bash
# Use cutover-restore.sh with OpenFGA component
bash scripts/cutover/cutover-restore.sh /var/backups/cutover/cutover-bundle-<pre-rev-ts> \
  --components openfga
# Manual: re-import store + tuples per cutover-bundle-design.md
```

### Audit trail

Every step (model write, tuple backfill, env rotate) logs to:
- alarm_receiver if drift detected
- audit_events table (if DB-backed audit added)
- Operator's session log (manual, Codex thread reference)

Rollback also logs as a separate sequence.

## Concrete case: canonical super-admin inheritance

This is the runbook's first scheduled application. Cross-repo work:

| Step | Repo | Owner |
|---|---|---|
| 1. Update model.fga in upstream | `platform-backend/backend/openfga/` | Backend dev (Sprint D) |
| 2. PR + drift gate validation in upstream | platform-backend | Backend reviewer |
| 3. After upstream merged: drift sync PR in gitops | platform-k8s-gitops | Gitops auto-bot OR operator |
| 4. Tuple backfill (org links) — production | OpenFGA store | Operator (using this runbook) |
| 5. OPENFGA_MODEL_ID env rotate (ConfigMap update) | gitops + cluster | Operator |
| 6. Verification (D29 smoke + super-admin fixture) | CI + gitops | Auto via systemd timer |
| 7. Sunset 39-tuple legacy pattern (separate sprint) | platform-backend + OpenFGA store | Backend dev + Operator |

This runbook handles steps 4-6. Steps 1-3 require the model.fga upstream PR
(Sprint D backend work). Step 7 is a separate deprecation sprint.

## Time budget

| Phase | Duration | Operator activity |
|---|---|---|
| Pre-flight + bundle | 10min | Run cutover-bundle.sh, capture baseline smoke |
| Step 1-2 (write new model) | 5min | Render + POST authorization-models |
| Step 3 (dual-read smoke) | 10min | 5 representative cases × 2 models |
| Step 4 (tuple backfill) | 15min | For ~50 module/action/report objects |
| Step 5 (env rotate) | 5min | kubectl set env + rollout restart |
| Step 6-7 (verification) | 10min | D29 smoke + live user smoke |
| Step 8 (gitops PR) | 15min | model.fga update + workflow toggles |
| **Total happy path** | **70min** | — |

If rollback needed: +30min for env rotate + tuple delete + verification.

## Checklist (operator copy)

```
PRE-FLIGHT
[ ] cutover-bundle.sh succeeded; sha256 manifest verified
[ ] baseline smoke captured: /tmp/smoke-pre-rev-<ts>.json
[ ] Codex thread opened: model rev intent + diff posted
[ ] Operator confirmed standby for rollback

MIGRATION
[ ] Step 1: model.fga drafted with backward-compat
[ ] Step 2: new model_id written: ____________________
[ ] Step 3: dual-read smoke 100% match (no regression on old paths)
[ ] Step 4: tuple backfill complete (org links written for all module/action/report)
[ ] Step 5: OPENFGA_MODEL_ID env rotated; permission-service rolled
[ ] Step 6: D29 smoke GREEN; super-admin fixture 100% PASS

EVIDENCE + GITOPS
[ ] Step 7: live-user smoke OK (halil + sezer login + module access)
[ ] Step 8: gitops PR opened with model.fga + workflow + contract doc updates
[ ] D35 evidence committed under docs/faz-XX-evidence/<date>-openfga-rev/

CLEANUP
[ ] alarm_receiver log clean (no new P1/P2 from model rev)
[ ] Codex thread closed: AGREE on rev complete
[ ] Old model_id retained for 30 days (rollback safety)
```

## Related artifacts

- `scripts/cutover/cutover-bundle.sh` — pre-flight snapshot
- `scripts/cutover/cutover-restore.sh` — emergency rollback
- `scripts/smoke/d29-smoke-runner.sh` — post-rev verification
- `tests/openfga/run_super_admin_fixture.py` — fixture-level regression
- `docs/authz/openfga-model-contract.md` — target-state contract
- `bootstrap/local-fixtures/openfga/model.fga` — fixture mirror of upstream
- `.github/workflows/openfga-model-drift.yml` — fixture vs upstream parity gate
