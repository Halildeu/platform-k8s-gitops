# SMS OTP lane — PROD, wired but dark

**This lane cannot carry a login today, and that is the point.** Owner approval
on 2026-08-02 was explicitly scoped: *wire it, leave it off, nobody's sign-in
changes.* What follows is what that meant in practice, so the next reader does
not mistake "the manifests exist" for "the feature works."

## What is here

Three additive objects. Applying them restarts nothing and mutates no existing
resource:

| object | effect today |
|---|---|
| `auth-service-sms-otp-secret` (ExternalSecret) | materialises a Secret nobody mounts |
| `auth-service-nodeport` / `notification-orchestrator-nodeport` | opens node ports nothing dials |
| two NetworkPolicy allows | admits one source address on one port each; nothing sends |

The Vault side was seeded on 2026-08-02 with `vault kv patch` (not `put` — the
path holds seven other auth-service fields, and the seed verified all seven
byte-identical afterwards). The KC-side half of the same credential is already
on disk at `host-compose/keycloak/prod/secrets/sms_otp_client_secret.txt`,
mode 600, unmounted. Cross-side match `sha256[:12] = 6cd69fac1aaa`.

## What is deliberately absent

Each of these was left out because it would have broken the "nobody's sign-in
changes" guarantee, or because it cannot work yet:

1. **The SPI provider jar and its compose mount.** `platform-kc-prod` has no
   providers mount at all (measured: only the two password secrets). Adding one
   recreates the container, and Keycloak only loads providers at start — so
   this step *is* a login interruption, however brief. It belongs in a
   maintenance window, not in an additive PR.

2. **auth-service environment wiring.** Adding `SERVICE_CLIENT_KEYCLOAK_SMS_OTP_SECRET`
   and `SECURITY_MFA_DELIVERY_GRANT_ALLOWED_CLIENTS` to the Deployment rolls the
   production auth service. It is also pointless right now — see the next item.

3. **The auth-service image.** The running prod digest predates the delivery
   grant entirely. Measured 2026-08-02:
   `POST /oauth2/mfa-delivery-grant` → **404** on prod, where test returns a
   normal auth error. The endpoint does not exist in that build. Promoting the
   image is a production image rotation and a separate decision.

4. **The Keycloak flow.** `scripts/keycloak/setup-privileged-mfa.sh` is NOT run
   against `serban`. Baseline captured before any of this work, unchanged:

   ```
   Cookie                        ALTERNATIVE
   Kerberos                      DISABLED
   Identity Provider Redirector  ALTERNATIVE
   forms                         ALTERNATIVE
     Username Password Form      REQUIRED
     Browser - Conditional OTP   CONDITIONAL
       Condition - user configured  REQUIRED
       OTP Form                     REQUIRED
   ```

   That is stock Keycloak conditional TOTP. Our SMS authenticator appears
   nowhere in it.

## Activation order, when it is approved

The lane is dark on four independent counts, so a single flip cannot switch it
on by accident. In dependency order:

1. Promote the prod auth-service image to a digest that answers
   `/oauth2/mfa-delivery-grant` (verify with the 404→4xx transition, not the tag).
2. Add the auth-service env wiring; confirm the rollout has quota headroom
   before starting it — a 1-replica surge without headroom stalls.
3. Mount providers in the prod KC compose, place the jar, recreate the
   container **in a window** — sign-in is unavailable while Keycloak restarts.
4. Wire the flow, then re-run the D29 three-layer evidence (Up / Functional /
   Zanzibar-ready) against prod before calling it live.

Each step is reversible on its own; step 3 is the only one users can feel.

Refs: gitops#3379, gitops#3212 (the test lane this mirrors).
