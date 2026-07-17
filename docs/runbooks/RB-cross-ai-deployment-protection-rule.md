# RB — Signed Cross-AI Custom Deployment Protection Rule

> **Issue:** #2502 · **ADR:** ADR-0045 · **scope:** reversible test/non-prod only
> **Current state (2026-07-17):** Phase 0 source/schema/tests, the live-found
> webhook header normalization fix and the Phase 1 receive-only observer are
> merged to `main`; the current truth-sync commit is
> `d092db7e5a7fa9558369afca4762454c6b1f0639`. Main workflow
> [29581180381](https://github.com/Halildeu/platform-k8s-gitops/actions/runs/29581180381)
> published and attested
> `ghcr.io/halildeu/platform-k8s-gitops-cross-ai-deployment-protection@sha256:0a79f6facfadb29daaeb096f5491e07fd8b01eabfbbb4db7d896f5663f9e9285`;
> registry manifest and GitHub attestation verification both pass. The
> protection evaluator App is registered as `Acik Cross-AI Deploy Protection`
> (App ID `4322193`) and installed only on
> `Halildeu/platform-k8s-gitops` (installation ID `147158710`). Its webhook is
> active with SSL verification and the reviewed URL/event/permissions. The
> test Vault policy was reconciled from merged commit `bb0a1d658f7c38178f19847d99a91d277bde2f86`
> without root-token recovery. The webhook secret was seeded through the
> short-lived `platform-bootstrap-writer-test` flow at KV version 1; handoff and
> emitted credential files were cleaned, and ESO read capability/property/hash
> alignment passed without exposing the value. The Phase 1 activation pins the
> attested digest above and connects the receive-only overlay to the canonical
> test root. Dedicated self-hosted verification
> [29585694840 attempt 2](https://github.com/Halildeu/platform-k8s-gitops/actions/runs/29585694840/attempts/2)
> passed against that exact digest and Argo revision: the observer stayed
> Ready with zero restarts, ESO was `Ready=True`, Argo was `Synced/Healthy`, one
> signed synthetic delivery was durably admitted and its replay was reported as
> a duplicate. No protected workflow lane or Environment custom rule is enabled.
> This is not GitHub-origin delivery, evaluator, callback, deployment or
> production evidence. A 2026-07-17 GitHub UI redelivery of the App `ping`
> still returned `failed to connect to host`; hosted-runner probe
> [29600152003](https://github.com/Halildeu/platform-k8s-gitops/actions/runs/29600152003)
> independently timed out on `testai.acik.com:443`. The outbound failed-delivery
> reconciler and file-only Vault seed wrapper are merged. The evaluator App PEM
> is present at the dedicated TEST KV path with redacted hash-match proof; the
> receive-only observer does not mount or consume it. The TEST Vault still has
> no Transit mount. The rule must remain disabled until owner-gated Transit/TLS,
> a real second provider, dispatcher App, signed intent, protected workflows and
> one real callback are all proven.

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

### 4.1 One-time TEST Transit owner bootstrap

Current live truth is fail-closed: TEST Vault has no Transit mount and the
root-free config reconciler can read but cannot create mounts. Do not recover,
search for or use the owner root token from automation. The owner performs this
step once with an explicitly supplied current-user-owned `0600` token file. The
script rejects a symlink, weak mode, wrong Vault cluster ID, standby/sealed
Vault, non-root token, non-Transit path collision, exportable/backup-enabled
key or policy readback drift.

The bootstrap creates only:

- the TEST-only `cross-ai/` Transit mount;
- distinct `anthropic`, `provider-secondary`, `coordinator` and `revocation`
  non-derived, non-exportable Ed25519 keys;
- the git-reviewed update of the already owner-gated
  `vault-config-reconciler` policy.

It does not enable the GitHub rule, create an Environment, mint issuer
credentials, write Kubernetes state or touch production. Run only from the
reviewed commit on `staging-sw`, substituting the live public cluster ID and
owner-local file paths. Never paste the token value into the command:

```bash
chmod 600 /OWNER/LOCAL/ROOT_TOKEN_FILE
python3 scripts/ops/bootstrap_cross_ai_transit.py \
  --vault-addr http://127.0.0.1:8201 \
  --root-token-file /OWNER/LOCAL/ROOT_TOKEN_FILE \
  --expected-cluster-id LIVE_TEST_VAULT_CLUSTER_ID \
  --reconciler-policy bootstrap/vault-policies/test/vault-config-reconciler.hcl \
  --receipt-out /OWNER/LOCAL/cross-ai-transit-bootstrap-receipt.json
```

The output receipt contains only public key material and digests, but remains
host-local until the owner verifies its cluster ID and printed canonical
receipt digest. The caller, not the script, owns cleanup of the root-token
handoff file.

After that one-time owner action, normal TEST policy/AppRole reconciliation is
root-free:

```bash
REPO_ROOT="$PWD" scripts/ops/vault-policy-reconcile.sh
```

The reconciler may mint one-use credentials only for the Anthropic issuer,
secondary issuer and coordinator roles. It cannot mint a revocation
secret-id. Every role can call only its exact `cross-ai/sign/<key>` endpoint;
key read/export/backup/restore/datakey/encrypt/decrypt/rewrap/HMAC are denied. A missing
second provider remains an authorization blocker; do not create a trust root
that claims a provider route which has not been live-verified.

The evaluator's Transit client requires a canonical HTTPS Vault origin. The
loopback HTTP address above is accepted only by the attended owner bootstrap.
If TEST Vault still lacks a reviewed HTTPS service identity, signed evidence
issuance and enforcement remain disabled.

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
bash scripts/ops/platform-ops-vault-patch.sh \
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

After the receive-only overlay is synced, run the dedicated self-hosted live
verification from `main`:

```bash
gh workflow run verify-cross-ai-observer.yml \
  --repo Halildeu/platform-k8s-gitops \
  --ref main
```

The workflow sandwiches one signed synthetic delivery and its replay between
two identical runtime attestations. The Deployment generation, Pod UID, named
`observer` imageID, Argo revision, ESO readiness and receive-only readiness
tuple must remain stable. The ESO-delivered webhook value travels through an
owner-only FIFO and is never written as a regular file, argument, log or
artifact. A pass proves the pinned test observer accepted one valid HMAC
delivery, deduplicated its replay and durably recorded the event. The delivery
is synthetic, not GitHub-origin evidence; it does not enable or prove an
Environment custom rule, approval callback, deployment or production gate.

The canonical 2026-07-17 pass is
[run 29585694840 attempt 2](https://github.com/Halildeu/platform-k8s-gitops/actions/runs/29585694840/attempts/2)
at source/Argo revision `ea9e6b587fd4e5c7381330762ace014508d046d3`:

- desired image and live `imageID` both resolved to
  `ghcr.io/halildeu/platform-k8s-gitops-cross-ai-deployment-protection@sha256:0a79f6facfadb29daaeb096f5491e07fd8b01eabfbbb4db7d896f5663f9e9285`;
- the probe-window identity remained Pod UID
  `5403c369-bd4b-4c1c-b333-3e963c4d759b`, Deployment generation `2`;
- Argo remained `Synced/Healthy`, ESO remained `Ready=True`, and the delivered
  secret property length was `64` bytes without disclosing the value;
- synthetic delivery `d22e5c5d-4406-442e-a92c-a32245546926` returned
  `202 duplicate=false`, then its replay returned `202 duplicate=true`;
- durable delivery and event counters both moved exactly `0 -> 1`;
- readiness reported `mode=observe`, `evaluationEnabled=false` and
  `reconciliationReady=true`; the probe attempted no callback and emitted no
  raw webhook secret, signature or payload.

Treat this as Phase 1 receive-only evidence only. A real GitHub-origin
`deployment_protection_rule` delivery, evaluator dependencies, App callback,
protected Environment custom-rule activation and deployment outcome remain
separate Phase 2/3 gates.

### 5.2 GitHub-origin reachability and failed-delivery recovery

The 2026-07-17 App delivery log is authoritative for the current ingress path:

- original `ping` and `installation.created` deliveries reported
  `failed to connect to host`;
- an owner-authorized UI redelivery of `ping` at 20:23:45 reported the same
  failure;
- hosted-runner run
  [29600152003](https://github.com/Halildeu/platform-k8s-gitops/actions/runs/29600152003)
  timed out connecting to `testai.acik.com:443`;
- from the test-side network, DNS resolves to `212.115.26.190`, TLS verification
  succeeds, the root returns HTTP 200 and an unsigned POST to the exact webhook
  route reaches the service and fails as expected with
  `WEBHOOK_EVENT_INVALID`/HTTP 400.

This separates a GitHub-origin network reachability failure from service/TLS
failure. Do not enable the Environment rule while only the inbound route
exists: GitHub would wait on a callback the evaluator never received.

The bounded recovery path reads the App's own webhook deliveries through:

```text
GET https://api.github.com/app/hook/deliveries
GET https://api.github.com/app/hook/deliveries/{delivery_id}
```

These calls use one freshly minted App JWT per poll cycle. The JWT lifetime is
at most five minutes from `iat`; it is never the credential used for the
decision callback. The poller follows no redirects, walks at most five
100-item pages, validates newest-first order and exact list/detail equality,
requires the configured target URL and expected installation/repository, and
processes only fresh failed `deployment_protection_rule/requested` records.

The detail `request.payload` is parsed GitHub REST JSON, not the original raw
webhook body. Its ledger provenance is therefore
`github_app_delivery_api_v1`, never `github_webhook_hmac_sha256_v1`. The normal
evaluator still re-fetches the exact run, workflow, Environment and signed
evidence before any decision. The callback is reconstructed under the exact
GitHub API origin, uses a repository installation access token and must return
empty HTTP 204. The high-water advances only after that callback is durably
`Succeeded`; overlap replay and decision idempotency repair a crash between
callback and cursor update.

Enforcement with recovery is explicit:

```bash
python3 scripts/github_apps/run_cross_ai_deployment_policy.py \
  --mode enforce \
  --delivery-poll \
  --delivery-poll-interval 30 \
  --expected-webhook-url \
    https://testai.acik.com/github-apps/cross-ai-deployment-protection \
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

This command is a reviewed shape, not permission to place the PEM or any token
in arguments, Git or chat. For Phase 2, the owner generates one App private key
into a current-user-owned local `0600` handoff. Transfer only that file to an
owner-only `0600` handoff on `staging-sw`; do not print or copy its contents.
Reconcile a fresh short-lived test writer credential, then seed the distinct
Vault property with the audited file-input operation:

```bash
set -euo pipefail
HANDOFF=/tmp/.cross-ai-github-app-key-codex-2502.pem
SID=/tmp/platform-bootstrap-writer-test-secret-id.txt
chmod 600 "$HANDOFF"

REPO_ROOT="$PWD" scripts/ops/vault-policy-reconcile.sh \
  --emit-seed-secret-id platform-bootstrap-writer-test

VAULT_BOOTSTRAP_ROLE_ID="$(cat /tmp/platform-bootstrap-writer-test-role-id.txt)" \
VAULT_BOOTSTRAP_SECRET_ID_FILE="$SID" \
bash scripts/ops/platform-ops-vault-patch.sh \
  --vault-addr http://127.0.0.1:8201 \
  --service cross-ai-deployment-protection-test \
  --field-from-file "github_app_private_key_pem=$HANDOFF" \
  --cleanup-field-files \
  --cleanup-secret-id-file
```

The wrapper validates a bounded PEM shape and owner-only file mode, transports
the multiline value internally without exposing it in argv, merges with KV v2
CAS and self-revokes. Verify only the `github_app_private_key_pem` property
presence and Vault metadata; do not read the value back. At this preparation
stage the receive-only observer ExternalSecret and Deployment remain unchanged
and cannot consume the key. A later reviewed enforcement overlay must select
the property explicitly and prove ESO readiness plus redacted hash alignment.
Production Vault, root-token recovery and raw PEM output remain forbidden.

### 5.2.1 Source-ready intent dispatcher

The dispatcher CLI is source-ready but must not be invoked against the live
repository until the separate dispatcher App, tag ruleset/egress deny rules,
real provider-distinct signed bundle, protected no-input workflows and TEST
Vault HTTPS are proven. It re-verifies trust, revocations, policy, repository,
Environment, dispatcher actor and workflow paths on every stage operation.

```bash
python3 scripts/github_apps/run_cross_ai_intent_dispatcher.py \
  --db /var/lib/cross-ai/registry.sqlite3 \
  --cas-dir /var/lib/cross-ai/cas \
  --policy-file /run/config/cross-ai-policy.json \
  --trust-root-file /run/config/cross-ai-trust-root.json \
  --expected-trust-root-sha256 'sha256:RELEASE_PIN_FROM_DUAL_CONTROL' \
  --revocations-file /run/config/cross-ai-revocations.dsse.json \
  --github-app-id "$DISPATCHER_GITHUB_APP_ID" \
  --github-app-key-file /run/secrets/dispatcher-github-app.pem \
  --installation-id "$DISPATCHER_INSTALLATION_ID" \
  register-and-dispatch-apply \
  --bundle-file /run/evidence/cross-ai-deployment-bundle.dsse.json
```

The key and bundle are file mounts; never place their contents in arguments,
logs, Git or chat. Exit `0` means GitHub accepted the dispatch with empty 204.
Exit `3` means a durable non-accepted state such as `Uncertain`; it is not a
retry signal. `Sending`, `Uncertain` and `Rejected` are never automatically
posted again. Use `reconcile-dispatch` only to read live GitHub truth; it can
accept an ambiguous job only when exactly one signed-intent-bound run exists.
Issue a new signed request ID when liveness must be recovered after a
fail-closed no-run result.

Poll interval is never below 30 seconds, success and failure paths have bounded
jitter, exponential backoff caps at five minutes, and `/readyz` fails after a
poll/API/callback error or stale success. An empty successful poll may make the
poller ready; it does not prove a deployment callback. Phase 2 still requires
one real failed delivery, evaluator result, HTTP 204 callback and retained
human reviewer before the custom rule is considered live.

### 5.3 Local process and enforcement

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
