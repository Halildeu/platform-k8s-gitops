# RB - Faz 24 platform-desktop tenant claim reconciliation

## Boundary

This runbook reconciles only the `platform-test` Keycloak realm and the
`platform-desktop` client. It does not mutate production, passwords,
credentials, sessions, roles, or user identifiers. The controlled access-token
claims are:

- `org_id`: the single canonical UUID user attribute;
- `org_id` and `tenant_id`: token claims emitted from that same `org_id`
  attribute, preventing duplicate user-state drift;
- `tenantId` and `companyId`: legacy compatibility attributes;
- `userId`: module-authorization compatibility attribute.

The canonical UUID is derived with the same Java `UUID.nameUUIDFromBytes`
contract used by backend tenant resolvers: `company:<companyId>`. No client
mapper may hardcode a tenant value.

## Preconditions

1. Issue `#2359` is claimed and `In Progress` on Project #2.
2. Execution host is `staging-sw`; container is `platform-kc-test` and realm is
   `platform-test`.
3. `RUN_EXTERNAL_SMOKE=0` is used for the mapper/user reconciliation run. The
   recorder smoke is a separate acceptance step.
4. The output directory is private and has enough space for the mode-`0600`
   rollback snapshot.

## Read-only preflight

Inspect the effective direct claim surface without printing tokens or admin
credentials:

```bash
CID="$(docker exec platform-kc-test /opt/keycloak/bin/kcadm.sh get clients \
  -r platform-test -q clientId=platform-desktop | jq -r '.[0].id')"
docker exec platform-kc-test /opt/keycloak/bin/kcadm.sh get \
  "clients/${CID}/protocol-mappers/models" -r platform-test \
  | jq '[.[] | {name, protocolMapper,
      claim:(.config["claim.name"] // null),
      attribute:(.config["user.attribute"] // null)}]'
```

The evidence chain also checks every assigned default and optional client
scope before and after direct mapper convergence. Any assigned-scope mapper
emitting a controlled claim fails closed; the script never deletes a
shared-scope mapper.

## Apply on test

Pass an explicit, comma-separated user list selected from the read-only realm
inventory. Each user must belong to the configured numeric `COMPANY_ID` or
`TENANT_ID`; out-of-scope aliases fail before update.

```bash
OUT_DIR=/tmp/faz24-tenant-claim-reconcile-$(date -u +%Y%m%dT%H%M%SZ) \
RUN_EXTERNAL_SMOKE=0 \
COMPANY_ID=1 \
TENANT_ID=1 \
RECONCILE_EXISTING_USERNAMES='admin@example.com,zeynep.akkilic@serban.com.tr,faz24-smoke@acik.com,test-recorder-182' \
CONFIRM_EXISTING_USER_RECONCILE=YES \
CONFIRM_CONTROLLED_MAPPER_PRUNE=YES \
bash scripts/faz24/run-platform-desktop-token-evidence-chain.sh
```

Before the first mapper or existing-user update, the script writes a private
snapshot named
`faz24-platform-desktop-tenant-reconcile-backup-<run>-<attempt>.json`. Keep its
path and SHA-256 in the issue evidence; do not upload the raw file because it
contains user representations.

## Verification

The run is accepted only when all of the following hold:

1. Exactly one direct user-attribute mapper emits each controlled claim.
2. No hardcoded or foreign direct mapper emits a controlled claim.
3. No assigned default or optional client scope emits a controlled claim.
4. Existing selected users have `org_id ==` the deterministic company UUID;
   both `org_id` and `tenant_id` token claims are emitted from that single
   attribute, and numeric compatibility attributes remain unchanged.
5. The minted token validator reports all required claims present and
   `tenantAliases.consistent=true` without including claim values.
6. The temporary user is deleted, direct grants are restored, and token files
   are removed.

## Rollback

Rollback uses the private pre-apply snapshot. Do not reconstruct attributes or
mapper values manually.

1. Stop new evidence runs for the client.
2. Remove only the five current controlled direct mappers from
   `platform-desktop`.
3. Recreate only the snapshot mappers whose `config["claim.name"]` is one of
   the five controlled claims.
4. For every snapshot user, stage its saved representation inside the
   Keycloak container with mode `0600` and run `kcadm update users/<id> -f`.
5. Delete staged container files, re-read mapper/user state, and mint a bounded
   test token. Never print the token.

The old mapper/user state is not restored automatically because an automatic
rollback after successful token issuance could reintroduce a conflicting
tenant claim. Rollback is a deliberate operator action bound to the snapshot
SHA and `#2359` evidence.

## Acceptance boundary

Mapper reconciliation proves token identity consistency only. It does not prove
Meeting object ownership, OpenFGA backfill, recorder consent, live STT, or
production readiness. Those remain in `#2360` and the Electron smoke chain.
