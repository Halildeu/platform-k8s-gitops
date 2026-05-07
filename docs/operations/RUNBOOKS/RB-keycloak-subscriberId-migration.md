# RB-keycloak-subscriberId-migration

> Faz 23.6 PR-2 — canonical `subscriberId` JWT claim rollout (Codex thread `019e03de` AGREE iter-1, model C: built-in `oidc-usermodel-attribute-mapper` + Keycloak user attribute backfill from canonical user-service).

## Tetik

`SubscriberIdentityGuard` already accepts `subscriberId | userId | sub` from incoming JWTs (env: `NOTIFY_SECURITY_SUBSCRIBER_IDENTITY_CLAIMS`, default the legacy-compatible list). Strict cutover (Faz 24 / PR-4) flips that env to `subscriberId` only — but only after every JWT in flight already carries the canonical claim. This runbook walks the 5-step path that gets us there.

## Karar matrisi (model C özet)

| Soru | Cevap |
|---|---|
| Claim kaynağı | Keycloak user attribute `subscriberId` |
| Mapper tipi | Built-in `oidc-usermodel-attribute-mapper` (no custom SPI) |
| Attribute kaynağı | Canonical `user-service.users.id` (numeric) |
| Sync yönü | user-service → Keycloak (one-shot backfill + on-create webhook future PR) |
| Token surface | access token + userinfo + introspection (NOT id token) |

## Adımlar

Her adım için süre, komut, beklenen çıktı, fail sinyali ve devam eşiği yazılı.

### F1 — Realm mapper apply (5 dk)

| | |
|---|---|
| **Komut** | Apply the realm JSON via Keycloak admin REST partial-import OR re-import the full realm fixture. For the dev cluster the seed is `bootstrap/local-fixtures/keycloak/dev-local-realm.json`. |
| **Beklenen** | `GET /admin/realms/<realm>/clients?clientId=platform-gateway` returns the new mapper inline (or as a default client scope on prod-shaped realms). |
| **Fail sinyali** | Mapper missing → `validate-subscriber-id-claim.sh` exits non-zero with `mapperPresent: false` evidence. |
| **Devam eşiği** | Validator green for `platform-gateway` AND `platform-frontend` clients. |
| **Rollback** | Remove the `protocolMappers` block from the client (or delete the client scope) and re-import. Token issuance falls back to `userId / sub` claims; backend guard already accepts both. |

### F2 — Dry-run validator (2 dk)

| | |
|---|---|
| **Komut** | `KEYCLOAK_BASE_URL=... KEYCLOAK_REALM=... EXPECTED_SUBSCRIBER_ID=1204 scripts/keycloak/validate-subscriber-id-claim.sh` |
| **Beklenen** | JSON evidence: `subscriberIdPresent: true`, `subscriberIdMatchesExpected: true`, `claimType: "string"`. Exit 0. |
| **Fail sinyali** | `subscriberIdPresent: false` → mapper not active OR persona missing the attribute. `subscriberIdMatchesExpected: false` → attribute drift (persona has stale value). |
| **Devam eşiği** | Validator green on the dedicated test persona (`subscriber-claim-test@localtest.me` for dev; pick a non-operator persona on staging/prod). |
| **Rollback** | None — validator is read-only. Set `ENSURE_TEST_PERSONA=1` to auto-fix the persona attribute if the realm allows it, but never run `ENSURE_TEST_PERSONA=1` against a realm that hosts the operator's login user without explicit confirmation. |

### F3 — Backfill dry-run (5 dk per realm)

| | |
|---|---|
| **Komut** | `APPLY=0 OPERATOR_LOGIN_USERNAME=<your-login-username> KEYCLOAK_REALM=<realm> USER_SERVICE_URL=<svc-url> USER_SERVICE_TOKEN=<svc-jwt> scripts/keycloak/backfill-subscriber-id-attributes.sh \| tee evidence/pr2-backfill-dryrun-<realm>.json` |
| **Beklenen** | `wouldUpdate >= 0`, `conflicts: []`, `skippedNoEmail` accounted for, `skippedOperator >= 1` if your login user lives in the realm. |
| **Fail sinyali** | `conflicts: [...]` non-empty → resolve manually before the apply. Two conflict types: `multiple-canonical-matches` (user-service has duplicate rows for the email — pick the canonical one) and `attribute-drift` (Keycloak attribute disagrees with user-service id — confirm which side is correct). |
| **Devam eşiği** | Conflicts list empty AND `wouldUpdate` matches the operator's expectation (rough sanity check: it should be roughly equal to "real users without the attribute yet"). |
| **Rollback** | None — dry-run is non-mutating. |

### F4 — Backfill apply + post-validation (10 dk per realm)

| | |
|---|---|
| **Komut** | Re-run F3 with `APPLY=1` and the same env. Then re-run F2 against several representative personas (dev login + at least one fresh user) to confirm the claim is now in their tokens. |
| **Beklenen** | Apply report: `updated == previous wouldUpdate`. Validator green on each spot-checked persona. |
| **Fail sinyali** | `updated < previous wouldUpdate` → some PUTs failed (network, RBAC). `subscriberIdPresent: false` post-apply on a fresh persona → mapper or attribute did not propagate; check the user representation `attributes.subscriberId` directly. |
| **Devam eşiği** | All representative personas pass validator AND backend metric `notify_subscriber_identity_match_total{claim="userId"}` and `{claim="sub"}` start trending toward zero. |
| **Rollback** | The backfill writes additive attributes — to revert, run a similar admin-REST sweep that removes the `subscriberId` key from `attributes`. The mapper continues to function without the attribute (the claim simply becomes absent), so backend's legacy `userId / sub` claims keep working. |

### F5 — Strict-cutover gate (Faz 24 / PR-4) — separate ops handoff

This runbook stops here. The strict cutover (env flip to `NOTIFY_SECURITY_SUBSCRIBER_IDENTITY_CLAIMS=subscriberId`) is a separate ops decision because:

* The backend metric must show `legacy_claim_count == 0` for at least N hours before the flip is safe (suggested N: 24h on prod, 1-2h on pre-prod).
* The metric query is:

  ```promql
  sum(rate(notify_subscriber_identity_match_total{claim=~"userId|sub|none"}[5m]))
  ```

* `claim="none"` MUST also be zero — any non-zero `none` rate means a JWT in flight has neither `subscriberId` nor a legacy fallback, which is a real authn failure that strict mode would surface as 403.
* Frontend (mfe-shell + mfe-audit) PR-3 ships the FE-side canonical selector so browser tokens carry the new claim consistently. Until PR-3 ships, browser tokens still rely on the mapper firing on the `platform-frontend` client; the gate above catches that.

When all three conditions hold, the cutover is the env flip + a rolling restart on `notification-orchestrator` (and any other service that adopts the same guard). Rollback: flip the env back to the legacy list and roll again — token issuance continues to carry both the canonical and legacy claims, so the rollback path is reversible without any user-facing impact.

## HARD RULE notes

* **Operator login protection**: F4 backfill MUST always pass `OPERATOR_LOGIN_USERNAME=<your-username>` so the script skips the operator's own user. The script's default skips no one — you'll see `skippedOperator: 0` in the report — so this is a per-run decision the runbook surfaces.
* **No password mutation**: neither script touches passwords. The dev-local fixture seeds the test persona's password as `subscriber-test-NOT_FOR_PROD`, but staging/prod realms must never have personas seeded with a password the operator did not author.
* **Pre-prod authority**: per "Pre-Production Full Authority", the agent can run F2-F4 end-to-end against the pre-prod cluster with admin credentials, write the dry-run evidence to `docs/evidence/pr2-...`, and report. Live (prod) realm runs are still operator decisions because the cutover gate (F5) is irreversible at the metric level (a botched flip will 403 every browser session for as long as it takes to re-roll).

## Referans

* Codex thread: `019e03de` AGREE iter-1 (model C lock-in + script shape + cutover sequence)
* PR-1 backend implementation: notification-orchestrator commit `0afa3aa` (config-driven `subscriber-identity-claims` + `notify.subscriber.identity.match` metric)
* PR-3 frontend canonical selector: tracked separately (mfe-shell + mfe-audit)
* PR-4 strict cutover: tracked separately (env flip + rolling restart + post-flip smoke)
