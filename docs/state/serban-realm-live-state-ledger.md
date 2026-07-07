# serban Realm — Live-State Ledger (intent-level DR record)

> **Purpose:** The prod `serban` Keycloak realm has **no realm-config-as-code**.
> The DR model is a weekly runtime `kc.sh export --realm serban` JSON
> (`S5-disaster-recovery-runbook.md` §2.2) stored host-local at
> `/srv/backup/prod/keycloak/`. A byte-level export can *reproduce* realm state
> but cannot say which live state is **intentional** vs an **accidental drift**.
> This ledger provides that missing **intent-level** record: an audited
> inventory of hand-applied realm/DB changes, their provenance, and their
> decision status. It is NOT a realm-import file and does not itself mutate
> Keycloak.
>
> **Scope:** realm `serban`, prod cluster (`ai.acik.com`). Snapshot verified
> read-only 2026-07-07. Related: board [#2276], Codex thread `019f3ca0`,
> login-fix gitops PR #2275, backend `docs/runbooks/RB-kc-subject-backfill.md`.

---

## Why serban has no realm IaC (context)

`host-compose/keycloak/prod/docker-compose.yml` runs plain `kc.sh start`
against a persistent data dir (`/srv/platform/stateful/prod/keycloak`) + the
prod PG `keycloak` DB. There is **no** `--import-realm`, **no** committed
realm-import JSON (only `bootstrap/local-fixtures/keycloak/dev-local-realm.json`
exists, and that is dev-local). Establishing full realm-config-as-code for
`serban` is a separate, larger, owner-gated initiative and is **out of scope**
for this ledger. Until then, this ledger is the canonical decision/status
record for hand-applied or observed live realm state — it marks which live
state is intentional, which is pending an owner decision, and which was
reverted.

---

## 1. `frontend` client — protocol mapper inventory

Client `frontend` (KC client id `417b0f73-b78f-4b05-93d2-ba70f197d36e`).
Observed live protocol mappers (2026-07-07, read-only DB query):

| Mapper | Type | Effect | Provenance | Decision status |
|---|---|---|---|---|
| `userId-claim` | `oidc-usermodel-attribute-mapper` | `userId` claim from `user.attribute=userId` (long) | pre-existing (identity claim) | Assumed-intentional (in working realm) |
| `endpoint-admin-prod-tenant-id` | `oidc-hardcoded-claim-mapper` | `tenant_id=00000000-…-000000000001` | pre-existing (endpoint-admin prod tenant) | Assumed-intentional |
| `audience-user-service` | `oidc-audience-mapper` | `aud` includes `user-service` | pre-existing | Assumed-intentional (establishes the "frontend token carries downstream service audiences" pattern) |
| **`auth-service-audience`** | `oidc-audience-mapper` | `aud` includes `auth-service` (access-token only; 3-key shape = testai parity; Admin-API-visible) | **2026-07-07 direct DB INSERT during login-fix diagnosis** | ⚠️ **PENDING OWNER DECISION — see §1.1** |

### 1.1 `auth-service-audience` — pending owner decision (⚠️ NOT canonical yet)

This mapper is **observed live drift**, not blessed canonical state. Facts
(Codex `019f3ca0` REVISE):

- **Not required for the login fix** — the login fix was CORS only
  (`GATEWAY_CORS_ALLOWED_ORIGINS`, PR #2275). This mapper was a red-herring
  diagnostic change left live.
- **Not required for gateway passage** — prod api-gateway
  `SECURITY_JWT_AUDIENCE = endpoint-admin-service,frontend,account,serban-web`;
  `auth-service` is not in that list, so the frontend token does not need it to
  pass the gateway. No known prod consumer reads `aud=auth-service` off the
  frontend token. ("No known consumer" is a *drift* signal, **not** a positive
  security proof.)
- **Adds authorization surface** — widening a token's `aud` is a security-
  relevant change, not cosmetic: any current/future `auth-service` path that
  does audience-based acceptance would now accept the SPA's frontend token.
- **Applied via direct DB INSERT** — bypasses the KC Admin API (not the
  sanctioned provisioning path).

**Verified live state (2026-07-07, read-only):**

- **Admin-API-visible** — the DB-inserted mapper *does* appear in the serban
  realm's Admin-API client model (`kcadm get clients/<id>/protocol-mappers`),
  i.e. the Infinispan cache reflects it, so it is very likely live-effective.
  (Definitive proof is a minted `frontend` token showing `aud=auth-service`;
  that needs a login flow and was not done.) Because it is Admin-API-visible,
  the revert/normalize recipes below can operate through the Admin API.
- **Shape matches testai parity _exactly_** — platform-test's `frontend`
  `auth-service-audience` mapper carries the same three config keys
  (`included.client.audience=auth-service`, `access.token.claim=true`,
  `id.token.claim=false`) and **no** `userinfo`/`introspection` keys. So the
  prod row is *not* "shape-incomplete"; it already equals the testai canonical
  shape. (Do **not** "complete" it with extra keys — that would be new drift.)

**Two candidate resolutions (owner picks — this is a prod-security decision):**

- **Option A — Revert (conservative prod hygiene).** Remove the mapper. Most
  conservative: eliminates an unnecessary, hand-inserted authz-surface drift.
  One `kcadm` delete (mapper is Admin-API-visible). Recipe:
  `docs/runbooks/RB-serban-audience-mapper-decision.md` §Option A.
- **Option B — Accept as canonical.** If the `auth-service` audience is a
  wanted product/parity behaviour (testai/platform-test carry it), accept it:
  the prod row **already matches the testai shape and is Admin-API-managed**,
  so **no prod mutation is required** — just promote this row to
  "Assumed-intentional / canonical" in §1. (Optional provenance hygiene:
  recreate it via the Admin API so it is unambiguously kcadm-managed; recipe
  `RB-serban-audience-mapper-decision.md` §Option B.)

Until the owner decides, this stays **PENDING** and must not be documented
anywhere as "canonical desired state".

---

## 2. `users_db.kc_subject` — 3-admin backfill (intentional, DR-note)

On 2026-07-07 three ADMIN rows in prod `users_db.users` had `kc_subject`
backfilled to their KC `user_entity.id`:

| users_db id | email | kc_subject (KC user_entity.id) |
|---|---|---|
| 1204 | halil.kocoglu@serban.com.tr | `d14c0a96-4e61-4b9a-9a69-43e8424e14fb` |
| 1203 | admin1@example.com | `dfc7d1bf-c138-4f72-9dfb-14e0691b68da` |
| 1201 | admin@example.com | `48102a7f-5144-4e5b-8e01-4b869fd73511` |

**Status: intentional + correct data (KEEP).** Verified 2026-07-07.

- `kc_subject` is consumed **only** by the impersonation-start target-subject
  resolution (auth-service `ImpersonationController` →
  `user-service.findUserById(targetUserId).kcSubject`; **no email fallback**;
  NULL → `422 TARGET_SUBJECT_UNRESOLVABLE`). It does **not** affect login/auth.
  Reverting it would re-break admin impersonation-as-target, so **do not
  revert**.
- The 3-admin `UPDATE` matches the "direct DB INSERT — emergency only" path in
  backend `RB-kc-subject-backfill.md`; the steady-state canonical path is the
  **idempotent email-join backfill**.

### 2.1 The 1201 NULL rows are NOT a gap

`users_db` has 1204 rows; only 3 carry `kc_subject`. This is expected, not a
gap: the serban KC realm has only **25 `user_entity` rows (20 with email)**.
The ~1201 NULLs are almost entirely **legacy Workcube-imported ERP users with
no Keycloak identity at all** — `kc_subject` is inherently N/A for them (they
cannot be impersonation targets because they have no KC subject).

**Precise backfill-able set (verified 2026-07-07 by the reconcile script's
prod dry-run): exactly _one_ row** — `sezerataasik@serban.com.tr`
(`users_db` id 1205 → KC `680bda99-f460-45cc-849a-f353000a52c3`). The other
serban KC personas (canary/smoke: `ag029-*`, `canary-*`, `d29-prod@…`,
`ag042-*`, `notify-canary-*`, plus `yusuf.yildiz@acik.com`, `testuser@acik.com`)
have **no matching `users_db` row**, so a full email-join backfill would not
touch them. So the "optional full backfill" gap is a single real user, not a
large set.

### 2.2 DR durability

- **From-dump restore** (S5-DR §3.1, daily `pg_dumpall`) already reproduces the
  3-admin `kc_subject` — durable.
- **From-scratch / from-migration rebuild** (S5-DR §3.4 nuclear) would start
  from `kc_subject=NULL`. To reproduce the correct mapping, run the idempotent
  reconcile script `scripts/keycloak/reconcile-kc-subject-backfill.sh` as a
  **post-restore reconciliation** step (S5-DR §3.5). Running the full backfill
  on prod today (verified prod dry-run: **exactly 1 row**, `sezerataasik`) is
  **owner-gated** and low marginal value; the future dry-run output is
  authoritative for scope. The reconcile script defaults to a DB-enforced
  read-only dry-run and refuses prod `--apply` without an explicit confirm.

---

## 3. Owner-decision checklist (tracked on [#2276])

- [ ] **Item #1** `frontend` `auth-service-audience` mapper: **Option A revert**
      *or* **Option B accept+normalize** (prod-security decision).
- [ ] **Item #2** (optional) run full email-join `kc_subject` backfill on prod
      — verified to fill **exactly 1 row** (`sezerataasik@serban.com.tr`,
      id 1205). Low-risk, precisely scoped; enables that user as an
      impersonation target. 3-admin state is already sufficient for the admins
      who use impersonation.

---

## References

- Board: [#2276] `Reconcile 2 prod serban-realm live-only drifts`
- Codex adversarial verdict: thread `019f3ca0` (REVISE)
- Login fix: gitops PR #2275 (`GATEWAY_CORS_ALLOWED_ORIGINS`)
- kc_subject backfill procedure: backend `docs/runbooks/RB-kc-subject-backfill.md`
- Reconcile script: `scripts/keycloak/reconcile-kc-subject-backfill.sh`
- Audience-mapper decision recipes: `docs/runbooks/RB-serban-audience-mapper-decision.md`
- DR: `docs/S5-disaster-recovery-runbook.md` §2.2 (export), §3.5 (post-restore reconcile)

[#2276]: https://github.com/Halildeu/platform-k8s-gitops/issues/2276
