# RB — serban `frontend` `auth-service-audience` mapper: owner decision

> **Status:** OWNER DECISION PENDING (prod-security). Board [#2276].
> **Scope:** prod realm `serban`, client `frontend`
> (`417b0f73-b78f-4b05-93d2-ba70f197d36e`), protocol mapper
> `auth-service-audience`.
> **Boundary:** every mutation step below **changes prod Keycloak security
> config** → owner-gated (HARD RULE — credential/security env-scoped: prod =
> owner explicit approval). This runbook does not execute anything by itself.

## Context (why a decision is needed)

During the 2026-07-07 `ai.acik.com` login fix (root cause = CORS, gitops
PR #2275) an `oidc-audience-mapper` named `auth-service-audience`
(`included.client.audience=auth-service`) was added to the serban `frontend`
client via **direct DB INSERT**. It was a red-herring diagnostic change: **not
required** for the login fix and **not required** for gateway passage (prod
api-gateway `SECURITY_JWT_AUDIENCE = endpoint-admin-service,frontend,account,
serban-web` — `auth-service` is not in the list). Full fact set + Codex verdict
`019f3ca0` in
[`docs/state/serban-realm-live-state-ledger.md`](../state/serban-realm-live-state-ledger.md) §1.1.

**Verified live state (2026-07-07, read-only):**

- **Admin-API-visible** — the mapper appears in the serban `frontend` client's
  Admin-API model, so the realm cache reflects it (very likely live-effective)
  and Admin-API delete/get will operate on it.
- **Shape = testai parity, exact** — platform-test's `frontend`
  `auth-service-audience` carries the identical 3 keys
  (`included.client.audience=auth-service`, `access.token.claim=true`,
  `id.token.claim=false`) and no `userinfo`/`introspection` keys. So the prod
  row is **not** shape-incomplete; do **not** add extra keys (that is new
  drift, not "completion").

Pick **Option A (revert)** or **Option B (accept as canonical)**. Both mutation
paths use `kcadm.sh` (Admin API), which invalidates the realm cache correctly —
**no prod KC restart needed** (aligns with `RB-kc-subject-backfill.md`: do not
restart prod KC just to flush cache).

---

## Preflight (both options) — reconcile Admin-API vs DB views

Direct-DB rows are not always Admin-API-visible; verify before acting. (For
this row, 2026-07-07 confirmed it **is** visible — re-confirm at execution.)

```bash
# On staging-sw. Admin password from the docker secret (never echo it).
KC=platform-kc-prod
docker exec -i "$KC" /opt/keycloak/bin/kcadm.sh config credentials \
  --server http://localhost:8080 --realm master \
  --user admin --password "$(docker exec "$KC" cat /run/secrets/kc_admin_password)"

CID=$(docker exec "$KC" /opt/keycloak/bin/kcadm.sh get clients -r serban \
        -q clientId=frontend --fields id --format csv --noquotes | tail -1)

# View A — Admin API:
docker exec "$KC" /opt/keycloak/bin/kcadm.sh get \
  clients/$CID/protocol-mappers/models -r serban --fields name | grep -c auth-service-audience
# View B — DB:
docker exec platform-pg-prod psql -U postgres -d keycloak -tAc "
  SELECT count(*) FROM protocol_mapper pm
  JOIN client c ON c.id=pm.client_id JOIN realm r ON r.id=c.realm_id
  WHERE r.name='serban' AND c.client_id='frontend' AND pm.name='auth-service-audience'"
```

- **Both = 1** → mapper is Admin-API-managed; use the Admin-API paths below.
- **DB = 1, Admin API = 0** → stale/cache-invisible direct-DB row. Do **not**
  use Admin-API delete/create (delete finds nothing; create duplicates). Use
  the §Option A DB-delete fallback + a cache-invalidation plan, then re-verify
  both views = 0 before any re-create.

---

## Option A — Revert (conservative prod hygiene)

Removes the unnecessary, hand-inserted audience-surface drift.

```bash
MID=$(docker exec "$KC" /opt/keycloak/bin/kcadm.sh get \
        clients/$CID/protocol-mappers/models -r serban \
        --format csv --noquotes --fields id,name | awk -F, '$2=="auth-service-audience"{print $1}')
[ -n "$MID" ] || { echo "mapper not Admin-API-visible — use DB fallback"; exit 1; }

docker exec "$KC" /opt/keycloak/bin/kcadm.sh delete \
  clients/$CID/protocol-mappers/models/$MID -r serban

# assert gone (Admin API + DB):
docker exec "$KC" /opt/keycloak/bin/kcadm.sh get \
  clients/$CID/protocol-mappers/models -r serban --fields name | grep -c auth-service-audience  # expect 0
```

**Post-revert:** in the ledger §1 table, set this row's status to
`Reverted YYYY-MM-DD — absent from desired state` (keep the row for audit
history; do **not** delete it). Mark [#2276] Item #1 = reverted.

### Fallback (emergency only — DB delete + cache flush)

Only if the Admin API is unavailable, or preflight shows a DB-only stale row.
Direct DB delete does NOT invalidate the Infinispan cache, so a cache flush
(owner-gated KC restart) is required afterwards.

```bash
docker exec -i platform-pg-prod psql -U postgres -d keycloak -v ON_ERROR_STOP=1 <<'SQL'
BEGIN;
DELETE FROM protocol_mapper_config WHERE protocol_mapper_id IN (
  SELECT pm.id FROM protocol_mapper pm
  JOIN client c ON c.id=pm.client_id JOIN realm r ON r.id=c.realm_id
  WHERE r.name='serban' AND c.client_id='frontend' AND pm.name='auth-service-audience');
DELETE FROM protocol_mapper WHERE id IN (
  SELECT pm.id FROM protocol_mapper pm
  JOIN client c ON c.id=pm.client_id JOIN realm r ON r.id=c.realm_id
  WHERE r.name='serban' AND c.client_id='frontend' AND pm.name='auth-service-audience');
COMMIT;
SQL
# owner-gated cache flush:
# docker compose -f host-compose/keycloak/prod/docker-compose.yml restart keycloak
```

---

## Option B — Accept as canonical

If the owner decides the `auth-service` audience is wanted (testai/platform-test
parity), accept it. Because the prod row **already matches the testai shape and
is Admin-API-managed** (preflight both-views=1), **no prod mutation is
required** — just promote the ledger §1 row from ⚠️ PENDING to
`Assumed-intentional / canonical` and mark [#2276] Item #1 = accepted.

**Optional provenance hygiene** — only if you want it unambiguously
kcadm-managed. Derive the shape from the live testai mapper (never hand-invent
keys); recreate it on prod:

```bash
# 1) export the exact platform-test mapper shape as the canonical source:
KCT=platform-kc-test
docker exec -i "$KCT" /opt/keycloak/bin/kcadm.sh config credentials \
  --server http://localhost:8080 --realm master \
  --user admin --password "$(docker exec "$KCT" cat /run/secrets/kc_admin_password)"
TCID=$(docker exec "$KCT" /opt/keycloak/bin/kcadm.sh get clients -r platform-test \
        -q clientId=frontend --fields id --format csv --noquotes | tail -1)
docker exec "$KCT" /opt/keycloak/bin/kcadm.sh get \
  clients/$TCID/protocol-mappers/models -r platform-test | \
  python3 -c "import sys,json;[print(json.dumps({k:m[k] for k in ('name','protocol','protocolMapper','config')})) for m in json.load(sys.stdin) if m['name']=='auth-service-audience']"
# Expected config (2026-07-07): {"included.client.audience":"auth-service",
#   "access.token.claim":"true","id.token.claim":"false"}  (3 keys, no extras)

# 2) on prod: delete the direct-DB row (Option A delete), then recreate from
#    the exact exported JSON (paste the 3-key config below, do not add keys):
docker exec -i "$KC" /opt/keycloak/bin/kcadm.sh create \
  clients/$CID/protocol-mappers/models -r serban -f - <<'JSON'
{ "name": "auth-service-audience", "protocol": "openid-connect",
  "protocolMapper": "oidc-audience-mapper",
  "config": { "included.client.audience": "auth-service",
              "access.token.claim": "true", "id.token.claim": "false" } }
JSON

# 3) assert exactly one, correct shape (before recreate DB count=0; after =1):
docker exec "$KC" /opt/keycloak/bin/kcadm.sh get \
  clients/$CID/protocol-mappers/models -r serban | \
  python3 -c "import sys,json;m=[x for x in json.load(sys.stdin) if x['name']=='auth-service-audience'];print('count',len(m));print(m[0]['config'] if m else None)"
```

---

## Verification (both options)

Mint a `frontend` token (login flow) and inspect `aud`:
- **Option A (reverted):** `aud` no longer contains `auth-service` (still
  carries `account`, `user-service`, etc.).
- **Option B (accepted):** `aud` contains `auth-service`; DB/Admin-API show the
  single 3-key mapper.

## References

- Ledger: [`docs/state/serban-realm-live-state-ledger.md`](../state/serban-realm-live-state-ledger.md)
- DR: [`docs/S5-disaster-recovery-runbook.md`](../S5-disaster-recovery-runbook.md) §3.5
- Codex verdict: thread `019f3ca0`
- Board: [#2276](https://github.com/Halildeu/platform-k8s-gitops/issues/2276)
