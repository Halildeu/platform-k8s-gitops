# RB — Signed Cross-AI Custom Deployment Protection Rule

> **Issue:** #2502 · **ADR:** ADR-0045 · **scope:** reversible test/non-prod only
> **Current state (2026-07-17):** Phase 0 source/schema/tests merged to `main`
> as `d31bae376c9520d30ea655d80326536c59cf81f3`. Main workflow
> [29577665709](https://github.com/Halildeu/platform-k8s-gitops/actions/runs/29577665709)
> published and attested
> `ghcr.io/halildeu/platform-k8s-gitops-cross-ai-deployment-protection@sha256:5b3532cdacc7d6f60bcf317982ab9bf7e1fcfe51f4c94de2a11aa3226c19af59`;
> registry manifest and GitHub attestation verification both pass. The
> protection evaluator App is registered as `Acik Cross-AI Deploy Protection`
> (App ID `4322193`) and installed only on
> `Halildeu/platform-k8s-gitops` (installation ID `147158710`). Its webhook is
> active with SSL verification and the reviewed URL/event/permissions. The
> test Vault policy was reconciled from merged commit `bb0a1d658f7c38178f19847d99a91d277bde2f86`
> without root-token recovery. The webhook secret was seeded through the
> short-lived `platform-bootstrap-writer-test` flow at KV version 1; handoff and
> emitted credential files were cleaned, and ESO read capability/property/hash
> alignment passed without exposing the value. The Phase 1 activation change
> pins the attested digest above and connects the receive-only overlay to the
> canonical test root. This source change does not itself claim a live endpoint,
> protected workflow lane or enabled Environment custom rule.

## 1. What this removes — and what it does not

After Phase 3, the App may replace the repeated GitHub required-reviewer click
only for an allowlisted reversible test/non-prod Environment. It verifies
signed provider-distinct review leaves and live GitHub truth, atomically binds
one grant to one run/attempt, and posts its own App decision.

It never claims a human identity and never approves production, break-glass,
irreversible mutation, production secret-owner, named Legal/DPO/authority or
attended endpoint consent. Those remain separate gates. App authorization is
also not #2373 customer acceptance: runtime D29 and browser evidence remain
mandatory.

## 2. Two-App least-privilege split

Create two repository-scoped GitHub Apps. This is a one-time account-owner
bootstrap, not a recurring deployment approval.

| App | Repository permissions | Events | Implemented operations |
|---|---|---|---|
| Protection evaluator | Actions read; Contents read; Deployments write; Metadata read | `deployment_protection_rule`, later `workflow_run` | exact read routes plus one reconstructed protection-decision POST |
| Intent dispatcher | Actions write; Contents write; Metadata read | none required | create/get `refs/tags/cross-ai-intent/**`; no-input workflow dispatch |

Repository rulesets must deny the dispatcher every branch write, every
non-intent tag write and every update/force-move. Egress policy must repeat the
method/path restriction; GitHub's coarse `contents:write` permission alone is
not sufficient containment.

Never paste App PEM, installation tokens, Vault tokens or webhook secrets into
chat, issue comments, shell arguments or repository files. Mount key/token and
webhook secret files with owner-only permissions. The service reads files and
logs only IDs/digests/reason codes.

## 3. Live preflight

Read current identities before generating the phase policy:

```bash
gh api repos/Halildeu/platform-k8s-gitops \
  --jq '{id,full_name,visibility,default_branch}'
gh api repos/Halildeu/platform-k8s-gitops/environments/faz22-view-only-pilot \
  --jq '{id,name,protection_rules,deployment_branch_policy}'
```

The 2026-07-17 snapshot was repository ID `1211415632`, public visibility,
one required-reviewer rule, no custom rule, and no deployment branch policy.
That snapshot is informational and must be refreshed before rollout.

Copy `config/github-apps/cross-ai-deployment-policy.example.json` to the
mounted configuration location and replace all `90000000x` sentinels with live
numeric IDs. Phase transitions are explicit policy changes; do not modify the
same policy bytes in place while unexpired grants exist.

## 4. Vault Transit issuer boundary

Use distinct Ed25519 Transit keys and policies for:

- direct Anthropic review issuer;
- second provider review issuer;
- evidence coordinator;
- revocation authority.

Each workload may sign only through its own Transit key. Provider keys cannot
sign bundles, the coordinator cannot sign provider leaves, and only the
revocation identity may sign the short-lived revocation set. Pin the Transit
key version in both `keyId` and trust root. Rotate by overlapping public-key
validity, issuing a fresh trust root, then revoking the old version after all
grants expire.

Trust-root issuance must compare every candidate public key with the retained
history of prior trust-root manifests. Reusing the same public key under a new
`keyId`, provider family or role is a release rejection even when the current
manifest has no duplicate. This cross-generation check belongs to the
dual-control release ledger because one running verifier cannot infer deleted
trust-root generations.

The service reloads the mounted revocation envelope for every evaluation and
verifies its signature and `nextUpdate` then. Replace the file atomically. A
missing, partially written, stale or invalid envelope rejects the decision;
revocation activation does not depend on a process restart.

V1 evaluates only current, unconsumed authorizations. A matching revocation
entry therefore takes effect immediately, even if its `effectiveAt` is in the
future or the signed leaf predates it. `effectiveAt` remains historical audit
metadata; it is not a grace-period switch. Issuers must not publish a
future-dated entry unless this immediate preemption is intended.

Direct Claude JSON reports `modelUsage`; the issuer requires the requested and
reported model to match. Cursor JSON currently does not report backend model
identity. Its leaf is therefore honestly marked `trusted-launch-attested`,
bound to the live model list and launched route, never `provider-reported` or
`direct-provider-CLI=true`.

## 5. Service start and phase safety

### 5.1 Receive-only observe activation

The first deployable slice is
`kustomize/overlays/test/activation/cross-ai-deployment-protection-observe`.
Its image is pinned to the exact main-workflow subject digest recorded above,
and the activation directory is present in
`kustomize/overlays/test/kustomization.yaml`. Runtime readiness, HMAC delivery
and durable ledger evidence remain separate post-sync gates.

Receive-only mode mounts only the current GitHub webhook secret and the SQLite
PVC. It has no evaluator App private key, no Kubernetes service-account token,
no GitHub/Vault/runtime egress and no decision callback client. The only public
route is the exact HMAC-protected POST surface:

```text
https://testai.acik.com/github-apps/cross-ai-deployment-protection
```

The ingress rewrites that exact path to `/webhooks/github`; health/readiness
paths remain cluster-internal. An HTTP 202 proves only that the raw GitHub
delivery passed HMAC/schema admission and entered the durable observe queue. It
does not prove evaluation, approval, deployment or product acceptance.

Before activation, the owner creates the evaluator App with the reviewed
projection in `config/github-apps/cross-ai-protection-evaluator-app.example.json`
and installs it only on `Halildeu/platform-k8s-gitops`. The generated webhook
secret stays in an owner-only `0600` handoff file; it is never copied into Git,
chat, shell arguments or evidence.

Test Vault policy and secret delivery use the established root-free flow:

1. `scripts/ops/vault-policy-reconcile.sh` applies the git-reviewed
   `eso-runtime` and `platform-bootstrap-writer` policies to the test Vault.
2. The reconciler emits a short-lived `platform-bootstrap-writer-test` AppRole
   secret-id into a host-local `0600` file.
3. `scripts/ops/platform-ops-vault-patch.sh` reads the webhook value from stdin,
   writes only `github_webhook_secret_current` at
   `kv/data/platform/cross-ai-deployment-protection-test`, and self-revokes its
   token. Use `--cleanup-secret-id-file`; the caller's exit trap shreds the
   owner handoff even when login or write fails.
4. The agent verifies ESO AppRole capability, property presence, ExternalSecret
   `Ready=True` and value-hash alignment without printing the value.

Run from the git-reviewed detached worktree on `staging-sw`; the handoff path is
the owner-provided file path, not the value:

```bash
set -euo pipefail
HANDOFF=/tmp/.cross-ai-webhook-secret-codex-2502
SID=/tmp/platform-bootstrap-writer-test-secret-id.txt
cleanup() {
  shred -u "$HANDOFF" "$SID" 2>/dev/null || true
}
trap cleanup EXIT

REPO_ROOT="$PWD" scripts/ops/vault-policy-reconcile.sh \
  --emit-seed-secret-id platform-bootstrap-writer-test

VAULT_BOOTSTRAP_ROLE_ID="$(cat /tmp/platform-bootstrap-writer-test-role-id.txt)" \
VAULT_BOOTSTRAP_SECRET_ID_FILE="$SID" \
scripts/ops/platform-ops-vault-patch.sh \
  --vault-addr http://127.0.0.1:8201 \
  --service cross-ai-deployment-protection-test \
  --field-from-stdin github_webhook_secret_current \
  --cleanup-secret-id-file < "$HANDOFF"
```

The wrapper uses KV v2 check-and-set: first creation requires `cas=0`; rotations
require the version read immediately before the write. A concurrent mutation
therefore fails closed instead of overwriting an unseen update. If the first
seed is wrong, generate/rotate the GitHub App webhook secret and repeat this
flow; do not soft-delete or destroy the Vault version. Before any observer pod
exists, rollback is simply to leave the activation overlay disconnected. After
activation, rotate the GitHub App secret, re-seed, force-sync ESO and restart the
single observer pod as one coordinated operation.

The reconciler is test-only and cannot read KV secret data. Test Vault root-token
recovery, Vault root-of-trust, production Vault and Environment custom-rule
activation remain outside this delegated flow. After the gates above pass, the
agent may replace the image sentinel, render/server-dry-run the isolated
activation overlay and add it to the test root through the normal GitOps PR.

### 5.2 Local process and enforcement

Observe with evaluation but no callback:

```bash
python3 scripts/github_apps/run_cross_ai_deployment_policy.py \
  --mode observe \
  --listen 127.0.0.1 --port 8080 \
  --db /var/lib/cross-ai/observe.sqlite3 \
  --registry-db /var/lib/cross-ai/registry.sqlite3 \
  --cas-dir /var/lib/cross-ai/cas \
  --webhook-secret-file /run/secrets/github-webhook-current \
  --policy-file /run/config/cross-ai-policy.json \
  --trust-root-file /run/config/cross-ai-trust-root.json \
  --expected-trust-root-sha256 'sha256:RELEASE_PIN_FROM_DUAL_CONTROL' \
  --revocations-file /run/config/cross-ai-revocations.dsse.json \
  --github-app-id "$GITHUB_APP_ID" \
  --github-app-key-file /run/secrets/github-app.pem
```

Do not put `$GITHUB_APP_ID` or any secret value directly in the process
argument in production service definitions; use an environment file for the
non-secret numeric ID and trust-root digest, and file mounts for secret
material. The digest is an explicit release-time pin produced independently
of the mounted trust-root file. The example above shows argument names, not a
live invocation.

`--mode enforce` is accepted only when policy, trust, revocation, registry,
CAS and GitHub App dependencies are all present. Enforcement reserves the
grant, performs a second full GitHub truth read, and moves to
`ApprovedPendingOutcome` only after HTTP 204. Timeout, 5xx, 409 or 422 becomes
`OutcomeOverdue`; the grant is not freed for another run and rollback remains
blocked while the exact run attempt is non-terminal.

`GET /readyz` returns HTTP 503 in enforce mode unless the outcome sweeper
thread is alive with a recent heartbeat. The sweeper re-reads revocations,
uses attempt-specific run and jobs endpoints, downloads exactly one bounded
Actions artifact named
`cross-ai-stage-outcome-<requestId>-<stage>-<run_id>-<run_attempt>`, hashes the
archive and stores the verified canonical outcome atomically. Missed webhooks
are therefore repaired by polling. On callback ambiguity or deadline expiry,
the state remains `OutcomeOverdue` until GitHub proves that exact attempt
terminal; only then does `CallbackUnknown` unlock the pre-signed rollback
stage. Never dispatch rollback merely because a timer elapsed.

An `observe` phase policy can never be used with `--mode enforce`. Every live
enforcement read also requires `can_admins_bypass: false`; an absent field is
not interpreted as disabled. The dual-gate phase additionally requires the
human reviewer rule, while the machine-only nonprod phase requires that the
reviewer has been deliberately removed.

## 6. Rollout gates

1. **Phase 0:** merge schemas and negative tests. Legacy unsigned receipts
   must reject.
2. **Phase 1:** run observe/evaluate without enabling an Environment custom
   rule. Replay at least ten redacted cases; zero false approvals.
3. **Phase 2:** enable the App rule while retaining the current required
   reviewer. Land dedicated no-input protected workflows, runner admission
   lease verification and a dedicated rollback path first. Complete the
   negative matrix and rollback drill.
4. **Phase 3:** only after recorded acceptance, remove the repeated reviewer
   from this one reversible test Environment. Retain the App rule, admin-bypass
   prohibition, secret scope, watchdog and compensating rollback.
5. **Production:** out of scope for ADR-0045 v1; required human reviewer stays.

If App availability or decision integrity is uncertain: freeze registrations,
revoke unconsumed grants, cancel waiting runs, disable the App rule, restore
the named required reviewer, and verify Environment secret scope did not
change. Never convert a callback outage into an allow-open decision.
