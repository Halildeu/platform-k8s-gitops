# RB — Faz 24 OpenFGA Meeting/Transcript Object Model

Purpose: move the Faz 24 recorder path from module-only Zanzibar readiness to
object ReBAC readiness for `meeting:<uuid>` and `transcript:<uuid>` objects.

Tracked by: `platform-k8s-gitops#1660`

Canonical backend source PR: `platform-backend#742`

## Scope

This runbook is for the OpenFGA model extension that adds:

- `type meeting`
- `type transcript`

It does not replace the existing module gates:

- `module:MEETING#can_view|can_manage`
- `module:TRANSCRIPT#can_view|can_manage`

Those remain instances of the existing `module` type.

## Required Model Semantics

`meeting-service` writes the owner tuple during create:

```text
user:<id>#owner@meeting:<uuid>
```

The model must support at least:

```text
type meeting
  relations
    define blocked: [user]
    define owner: [user] but not blocked
    define participant: [user] but not blocked
    define viewer: [user] or participant or owner but not blocked

type transcript
  relations
    define blocked: [user]
    define owner: [user] but not blocked
    define participant: [user] but not blocked
    define viewer: [user] or participant or owner but not blocked
```

## Verified Test Model

- Store: `01KPP0CFP4G82K42Y6NYSPT4JF`
- Previous active model: `01KS8QE8T1EJ2DF5CRS4VV9YX1`
- New verified model: `01KVXG15ETYAHMHANFD0E5CVK8`
- Content digest:
  `sha256:34d59b2230ea944ae1c2a1d9d27dc36baf3ee90f5514600cd007b215b7e642df`
- Ledger:
  `runtime-artifacts/openfga-model/34d59b2230ea944ae1c2a1d9d27dc36baf3ee90f5514600cd007b215b7e642df.json`
- Evidence:
  `docs/faz-24-evidence/2026-06-24-openfga-meeting-transcript-object-model.md`

## Promotion Steps

These steps change the runtime selector. Do not run them until the model write
and explicit-model checks in the evidence file have passed.

1. Patch the shared OpenFGA selector in test Vault:

   ```bash
   vault kv patch kv/platform/openfga model_id="01KVXG15ETYAHMHANFD0E5CVK8"
   ```

2. Force sync every ExternalSecret that consumes `kv/platform/openfga#model_id`
   in platform-test:

   ```bash
   for es in \
     permission-service-secrets \
     core-data-service-secrets \
     variant-service-secrets \
     user-service-secrets \
     report-service-secrets \
     endpoint-admin-service-secrets \
     meeting-service-secrets \
     transcript-service-secrets; do
     kubectl --context k3d-test -n platform-test \
       annotate externalsecret "$es" force-sync="$(date +%s)" --overwrite
   done
   ```

3. Confirm every synced Secret carries the new model ID:

   ```bash
   for secret in \
     permission-service-secrets \
     core-data-service-secrets \
     variant-service-secrets \
     user-service-secrets \
     report-service-secrets \
     endpoint-admin-service-secrets \
     meeting-service-secrets \
     transcript-service-secrets; do
     printf '%s ' "$secret"
     kubectl --context k3d-test -n platform-test get secret "$secret" \
       -o jsonpath='{.data.ERP_OPENFGA_MODEL_ID}' | base64 -d
     printf '\n'
   done
   ```

4. Restart only the deployments that consume `ERP_OPENFGA_MODEL_ID`:

   ```bash
   kubectl --context k3d-test -n platform-test rollout restart \
     deploy/permission-service \
     deploy/core-data-service \
     deploy/variant-service \
     deploy/user-service \
     deploy/report-service \
     deploy/endpoint-admin-service \
     deploy/meeting-service \
     deploy/transcript-service

   for deploy in \
     permission-service core-data-service variant-service user-service \
     report-service endpoint-admin-service meeting-service transcript-service; do
     kubectl --context k3d-test -n platform-test \
       rollout status "deploy/$deploy" --timeout=180s
   done
   ```

5. Confirm the new model ID is live in at least the critical recorder services:

   ```bash
   for deploy in meeting-service transcript-service permission-service; do
     kubectl --context k3d-test -n platform-test exec "deploy/$deploy" -- \
       sh -c 'env | grep ^ERP_OPENFGA_MODEL_ID='
   done
   ```

6. Re-run the module seed smoke:

   ```bash
   ./scripts/faz24/openfga-meeting-transcript-seed.sh
   ```

7. Re-run recorder acceptance in this order:

   - `POST /api/v1/admin/meetings` through `meeting-service`
   - `POST /audio-gateway/sessions` with the created meeting UUID
   - chunk upload
   - finish
   - audit/STT downstream proof

## Rollback

Rollback does not delete the new OpenFGA model. OpenFGA models are append-only;
rollback is selector-based.

1. Patch test Vault back to the previous model:

   ```bash
   vault kv patch kv/platform/openfga model_id="01KS8QE8T1EJ2DF5CRS4VV9YX1"
   ```

2. Repeat the ExternalSecret force-sync and rollout steps above.

3. Confirm `meeting-service` again carries:

   ```text
   ERP_OPENFGA_MODEL_ID=01KS8QE8T1EJ2DF5CRS4VV9YX1
   ```

Rollback impact: the previous model lacks `type meeting` and `type transcript`,
so meeting create will again fail closed on owner tuple write. Use rollback only
if the broader shared-model consumer set regresses.
