# Admin Onboarding Saga Contract — Sprint D Prep

> Codex 2026-05-04 thread `019df310` Sprint D prep:
> "Admin onboarding saga contract doc. POST /api/v1/admin/users/onboard
> için request/response, idempotency key, KC user + users_db + OpenFGA tuple
> + audit event + rollback semantics yazılsın. Manual SQL onboarding
> break-glass olarak işaretlensin."
>
> Bu doc backend implementation'dan ÖNCE yazılan kontrat. Backend repo'sunda
> POST /api/v1/admin/users/onboard endpoint'i bu contract'a uyacak.
> Halil/Sezer Session 37 manual onboarding'inin (5 adım) atomic API'ye
> indirgenmesi.

## Why an endpoint, not 5 manual steps?

Session 37 (2026-05-04) halil + sezer manuel onboarding deneyiminde:

1. **5 manuel adım** required:
   - users_db.users INSERT
   - KC user create
   - KC realm role mapping (3 role)
   - KC client role mapping (12 client roles)
   - OpenFGA tuple write (post-canonical-tuple migration: 1 tuple; pre: 39 tuples)

2. **Each step has independent failure modes**:
   - users_db down → user record never created → backend 401 silently
   - KC unavailable → user can't log in but tuple may exist → orphan
   - OpenFGA store unhealthy → user authenticates but all checks deny → frustrating UX
   - Partial commits → drift between systems → audit nightmare

3. **No rollback path**: each step is independently committed; failure midway leaves user in inconsistent state

4. **Operator-only**: only halil can do this; can't delegate

The saga endpoint provides:

- **Atomic transaction** semantics (compensating actions on failure)
- **Idempotency** via Idempotency-Key header (retry safe)
- **Audit trail** (single event per onboarding)
- **Self-service** (any operator with admin role can call)
- **Rollback** (delete-onboarding endpoint reverses all steps)

## Endpoint contract

### POST /api/v1/admin/users/onboard

**Auth**: Bearer token of an existing admin (super-admin per OpenFGA contract).

**Headers**:
- `Authorization: Bearer <jwt>` (required)
- `Idempotency-Key: <uuid>` (required; replay-safe)
- `Content-Type: application/json`

**Request body**:
```json
{
  "email": "newuser@serban.com.tr",
  "name": "New User",
  "role": "ADMIN",
  "kc_realm_roles": ["ADMIN", "admin", "viewer"],
  "kc_client_roles": {
    "frontend": ["admin", "viewer", ...]
  },
  "make_super_admin": true,
  "initial_password": "<optional; if omitted, KC sends activation email>"
}
```

**Field semantics**:
- `email` — primary identifier; unique constraint in users_db.users.email + KC users.email
- `name` — display name
- `role` — users_db.users.role enum (ADMIN, USER)
- `kc_realm_roles` — Keycloak realm-level role names (must exist in realm)
- `kc_client_roles` — Keycloak per-client role mappings
- `make_super_admin` — if true, write canonical OpenFGA tuple `organization:default#admin@user:<users_db_id>` (per contract; works after model migration)
- `initial_password` — optional; if omitted, KC sends activation email per realm config

**Response 201 Created**:
```json
{
  "user_id": 1207,
  "kc_user_id": "048bff34-...",
  "openfga_tuples_written": 1,
  "audit_event_id": "evt_2026-05-04T16:00:00Z_1207",
  "saga_correlation_id": "saga_2026-05-04_1207",
  "next_steps": [
    "User receives activation email at newuser@serban.com.tr",
    "After login, /authz/me reflects super-admin module access"
  ]
}
```

**Response 409 Conflict** (idempotent retry):
```json
{
  "user_id": 1207,
  "saga_correlation_id": "saga_2026-05-04_1207",
  "message": "User already onboarded; idempotency key matched existing saga",
  "previous_response": { ... }
}
```

**Response 400 Bad Request** (validation):
```json
{
  "errors": [
    {"field": "email", "message": "must be a valid email"},
    {"field": "kc_realm_roles", "message": "role 'BADROLE' does not exist"}
  ]
}
```

**Response 503 Service Unavailable** (downstream failure):
```json
{
  "saga_correlation_id": "saga_2026-05-04_1207",
  "stage": "openfga_write",
  "compensated": ["kc_user_create", "kc_realm_roles", "users_db_insert"],
  "message": "OpenFGA write failed; saga compensated steps 1-3, no user created",
  "retry_after": 30
}
```

## Saga steps

The endpoint orchestrates 5 steps with compensating actions:

```
Step 1: users_db.users INSERT
  Compensate: DELETE FROM users WHERE id = ?
Step 2: KC create user (POST /admin/realms/{realm}/users)
  Compensate: DELETE /admin/realms/{realm}/users/{kc_id}
Step 3: KC realm role mapping (POST /admin/realms/{realm}/users/{kc_id}/role-mappings/realm)
  Compensate: DELETE /admin/realms/{realm}/users/{kc_id}/role-mappings/realm
Step 4: KC client role mapping (POST /admin/realms/{realm}/users/{kc_id}/role-mappings/clients/{cid})
  Compensate: DELETE /admin/realms/{realm}/users/{kc_id}/role-mappings/clients/{cid}
Step 5: OpenFGA write (POST /stores/{store}/write)
  Compensate: POST /stores/{store}/write { deletes: [...] }
```

Each step:
- Logs to audit table BEFORE execution (intent)
- Logs to audit table AFTER execution (outcome)
- On failure, runs compensating actions in reverse order
- Final audit event includes saga_correlation_id + per-step status

## Idempotency

`Idempotency-Key` header is REQUIRED. Same key = same response (within 24h window).

Implementation:
- `idempotency_keys` table in users_db (or separate cache)
- key column UNIQUE NOT NULL
- response_body JSON column
- expires_at timestamp (24h after first use)

First call with key → execute saga, store response with key.
Subsequent calls with same key → return stored response (200, not re-execute).

## Audit trail

`audit_events` table (users_db or shared audit_db):

```sql
CREATE TABLE audit_events (
  id TEXT PRIMARY KEY,           -- evt_<timestamp>_<user_id>
  ts TIMESTAMPTZ NOT NULL,
  actor_user_id INTEGER,         -- who called the endpoint
  actor_email TEXT,
  saga_correlation_id TEXT,      -- groups all events from one saga
  step TEXT,                     -- 'users_db.insert', 'kc.user.create', ...
  status TEXT,                   -- 'INTENT', 'SUCCESS', 'FAILURE', 'COMPENSATED'
  details JSONB                  -- step-specific payload (e.g. user_id, kc_id)
);
```

For each onboarding: 11+ rows (5 INTENT + 5 SUCCESS + 1 saga-complete) on success path.
On failure: variable count, all linked by saga_correlation_id.

## Rollback (delete-onboarding)

### DELETE /api/v1/admin/users/{user_id}/onboard

Reverses all saga steps. Used when:
- User was onboarded by mistake
- User leaves company / access revoked
- Test/staging onboarding cleanup

**Effect**:
1. Delete OpenFGA tuples for user
2. Delete KC client role mappings
3. Delete KC realm role mappings
4. Delete KC user
5. Delete users_db.users row (or set status='DELETED' for soft-delete)

**Audit**: separate saga_correlation_id, each step audited.

**Idempotency**: yes, via Idempotency-Key header. Repeated calls return same response.

## Break-glass — manual SQL onboarding

When the saga endpoint is unavailable (e.g. permission-service crash during prod incident), operators MUST use the manual 5-step SQL+REST process documented in:

- `docs/runbooks/RB-admin-onboarding-manual.md` (TODO — separate PR after this contract is implemented)

Manual onboarding is **break-glass only**:
- Should leave a recovery audit log entry (manual SQL INSERT into audit_events with status='BREAK_GLASS')
- Reconciliation PR should follow within 24h to record the break-glass event in source-of-truth governance

## Implementation tracking

- This doc: contract definition (gitops repo, this PR)
- Backend impl: platform-backend repo (separate session/PR)
  - Spring Boot @RestController in admin-service or user-service
  - Saga orchestration via Spring Cloud Stream OR custom Java orchestrator
  - Idempotency cache via Redis (or PG table for simplicity)
- Frontend: admin user-management page already has "+ Yeni Admin" button; wire to call new endpoint instead of open-form
- E2E test: tests/e2e/admin-onboarding-saga.spec.ts (frontend repo)

## Cutover prerequisite

D30 atomic cutover does NOT block on this endpoint. Manual SQL onboarding remains the break-glass path during cutover. Saga endpoint is post-cutover Sprint D work.

## Related artifacts

- `docs/authz/openfga-model-contract.md` — OpenFGA tuple semantics (canonical super-admin)
- `docs/runbooks/RB-admin-onboarding-manual.md` (TODO) — break-glass manual procedure
- platform-backend `OpenFgaCheckService.java`, `DefaultAdminRoleAssignmentInitializer.java` — current admin handling
