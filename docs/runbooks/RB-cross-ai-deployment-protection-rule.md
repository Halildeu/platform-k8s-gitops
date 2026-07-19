# RB — Signed Cross-AI Custom Deployment Protection Rule

> **Forward-policy stop (#2638, 2026-07-18):** Bu v1 tasarımındaki üç-sağlayıcı
> ve MiniMax issuer yolu yeni activation veya deployment acceptance için
> kullanılamaz. Mevcut metin, şema ve fixture'lar yalnız arşiv/forensic kayıt
> açıklaması için korunur; cutoff sonrası aktif verifier bunları doğrulamaz.
> Yeni aktif sürüm Claude Opus 4.8 + OpenAI Codex 5.6 SOL ile ayrı versioned
> contract/trust-root kullanmadan Phase 2/3'e ilerlemez. MiniMax içeren bir v1
> trust root cutoff sonrasına taşamaz; pre-cutoff kayıt yeni acceptance üretemez.
> Aktif verifier saati cutoff'a ulaştığında MiniMax taşıyan v1 trust root'u
> payload zamanı backdate edilse bile reddeder. Owner-gated Transit bootstrap
> eski MiniMax issuer policy/AppRole kaydını idempotent olarak siler ve
> yokluğunu doğrular; yeni reconcile yolu grant üretmez. Ayrı v2 activation
> preflight'i credential göstermeden bu absence receipt'ini doğrulamalıdır. Bu
> temizlik tarihsel Transit public-key/evidence kaydını silmez. V1 doğrulama
> yalnız forensic replay içindir; provider issuer ve coordinator yeni v1
> leaf/bundle üretimini kod seviyesinde reddeder.

> **Issue:** #2502 · **ADR:** ADR-0045 · **scope:** reversible test/non-prod only
> **Current state (2026-07-18):** Phase 0 source/schema/tests, the live-found
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
> receive-only observer does not mount or consume it. TEST Vault now has the
> audited `cross-ai/` Transit mount. Its historical six non-exportable
> Ed25519 v1 keys remain as public forensic history; #2638 removes MiniMax
> AppRole/policy signing authority without deleting that public key. The
> owner-local v1 bootstrap receipt digest is
> `sha256:81e629fe61b2cb81578861d7c82b61802a05b4aa2fa4b720706330e6b642c8ac`.
> Provider issuer/coordinator AppRoles and SecretIDs are not live and no bundle
> has been signed. The rule remains disabled until the reviewed five-key v2
> public trust-root release/TLS, exact Claude Opus 4.8 + OpenAI Codex 5.6 SOL
> adapters, dispatcher App,
> signed intent, protected workflows and one real callback are all proven.

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

The two-App split is a GitHub permission boundary, not the provider quorum.
Active v2 provider execution and signing use two separate issuer workloads
(Anthropic and OpenAI); neither issuer inherits either GitHub App identity or
its repository permissions. MiniMax is not an active issuer and its historical
v1 material cannot authorize a new deployment.
The provider routes are not a configurable wrapper allowlist. V2 fixes exactly
`direct-anthropic-cli` + `claude-opus-4-8` and `openai-codex` +
`gpt-5.6-sol`; Anthropic requires provider-reported model identity. Codex is
honestly fixed to
`trusted-launch-attested` because its JSON stream does not report backend model
identity; that weaker class is accepted only while the required reviewer is
retained and is unconditionally rejected by machine-only mode. Both routes
require `directProviderCli=true`. A different channel, model or identity class
needs a reviewed contract migration, not a trust-root edit.

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

- direct Anthropic review issuer (`claude-opus-4-8`);
- direct OpenAI Codex review issuer (`gpt-5.6-sol`);
- evidence coordinator;
- revocation authority;
- runner inventory/admission-lease management.

The historical `minimax` Transit public key may remain for forensic validation,
but no active v2 trust root includes it and no AppRole or ACL policy may grant
signing authority for it.

Each workload may sign only through its own Transit key. Provider keys cannot
sign bundles, the coordinator cannot sign provider leaves, and only the
revocation identity may sign the short-lived revocation set. Pin the Transit
key version in both `keyId` and trust root. Each provider key permits exactly
one direct channel, one exact model ID and one model-identity class; aliases or
fallback models require a new reviewed trust root and invalidate existing
grants. The Transit client sends the pinned `key_version` on every signing
request and rejects a response signed by any other version. Rotate by
overlapping public-key
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
reported model to match. Codex JSONL does not
report backend model identity: its leaf is therefore honestly marked
`trusted-launch-attested`, bound to the live supported-model catalog, exact
executable/version/digest and no-tool read-only launch. It is never upgraded to
`provider-reported`. Cursor is not an authorized provider route.

### 4.1 One-time TEST Transit owner bootstrap

Current live truth is fail-closed: the earlier TEST bootstrap created the
Transit mount and six historical v1 keys, but this does not authorize signing
or the GitHub rule. The reviewed v2 bootstrap retains the historical MiniMax
public key while deleting its AppRole/policy authority and emits only the five
active-key records. The root-free config reconciler still cannot create mounts or issuer
credentials. Do not recover, search for or use the owner root token from
automation. Any owner refresh uses only an explicitly supplied
current-user-owned `0600` token file. The script rejects a symlink, weak mode,
wrong Vault cluster ID, standby/sealed Vault, non-root token, non-Transit path
collision, exportable/backup-enabled key, incomplete public version history or
policy readback drift.

The bootstrap creates or reconciles only:

- the TEST-only `cross-ai/` Transit mount;
- distinct `anthropic`, `openai`, `coordinator`, `revocation` and
  `runner-management` non-derived, non-exportable Ed25519 keys;
- deletion and verified absence of the legacy MiniMax issuer AppRole/policy,
  without deleting its historical Transit public key;
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

The v2 output receipt contains only public key material, immutable safety
settings, complete public version history and digests, but remains host-local
until the owner verifies its cluster ID and printed canonical receipt digest.
The caller, not the script, owns cleanup of the root-token handoff file.

Build the TEST trust root only from that public v2 receipt. Times and UUID are
explicit release inputs; the tool writes canonical public JSON to a new file
and prints its digest. It does not edit policy/workflow pins, Kubernetes state
or evaluator mode:

```bash
python3 scripts/ops/build_cross_ai_test_trust_root.py \
  --receipt /OWNER/LOCAL/cross-ai-transit-bootstrap-receipt-v2.json \
  --trust-root-id RELEASE_UUID \
  --issued-at RELEASE_UTC \
  --expires-at EXPIRY_UTC \
  --out /OWNER/LOCAL/cross-ai-deployment-trust-root.json
```

The output binds a stable `sourcePublicKeysetSha256` projection. Operational
receipt fields such as `verifiedAt` do not move that digest; any key, immutable
setting, reconciler-policy digest or public version-history change does. The
existing v1 owner-local receipt is historical evidence and is deliberately not
accepted as v2 input. Re-run the idempotent bootstrap after this source is
merged/reviewed to obtain v2 public history; never hand-edit or reinterpret v1.

After that one-time owner action, normal TEST policy reconciliation and the
non-issuer AppRole subset are root-free:

```bash
REPO_ROOT="$PWD" scripts/ops/vault-policy-reconcile.sh
```

The routine reconciler cannot create, update or read the named issuer and
coordinator AppRole definitions, role IDs or SecretIDs. It may emit only the
separate runner-management credential. Provider issuer and coordinator roles
must be created by the owner or a dedicated workload-identity controller
outside this reconciler trust domain with `bind_secret_id=true`, one-use
SecretIDs and tokens, a ten-minute explicit maximum token TTL, no default
policy and exactly one `cross-ai/sign/<key>` policy. Revocation SecretID
minting also remains owner-only. Key read/export/backup/restore/datakey/
encrypt/decrypt/rewrap/HMAC are denied. Missing direct provider execution or
exact backend model identity remains an authorization blocker.

Before enabling the custom rule, live Vault capability tests must prove that
the routine reconciler is denied on every issuer/coordinator role definition,
role-id and secret-id path and that a `bind_secret_id=false` downgrade/login is
unavailable. This PR changes the reviewed source policy only; it does not claim
that the owner-gated live policy replacement or role provisioning has occurred.

This source contract does not make two local Transit signatures equivalent to
two provider executions. Each dedicated issuer must execute its provider,
validate its exact allowed identity class and only then consume its one-use
sign token. Until the direct Claude and OpenAI execution adapters and their
redacted, content-addressed receipts are accepted, enforcement remains
`tracked_pending`.

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

### 5.2.2 Source-ready runner bootstrap

Each protected no-input workflow must declare workflow-level
`permissions.id-token: write`. Its governed job may run only one pinned
checkout step before invoking
`scripts/github_apps/run_cross_ai_runner_bootstrap.py`. The bootstrap command
receives the high-entropy Environment credential only through
`CROSS_AI_BOOTSTRAP_TOKEN`; it must never place the credential or GitHub OIDC
token in argv, logs, artifacts or workflow inputs.

The policy's `runnerBootstrapUrl` is the exact full HTTPS endpoint, including
`/v1/runner-bootstrap`, and is covered by the policy digest. The workflow
literal and runtime `CROSS_AI_BOOTSTRAP_URL` must match it byte-for-byte. Do not
substitute another HTTPS host, nonstandard port, redirect or loopback address.

Generate this TEST-only value as at least 64 high-entropy ASCII characters
directly into an owner-only file; do not print it:

```bash
umask 077
openssl rand -base64 48 | tr -d '\n' > /OWNER/LOCAL/cross-ai-bootstrap-token.txt
```

Set the GitHub Environment secret from file/stdin through the attended owner
flow and delete the handoff after redacted presence verification. A human-chosen
password, a reused token or a value shorter than 64 characters is rejected.

The client asks GitHub's runner-local OIDC endpoint for the fixed
`acik-cross-ai-runner-bootstrap` audience. The policy service requires both
`Authorization: Bearer <GitHub OIDC>` and the distinct
`X-Cross-AI-Bootstrap-Credential` header, then re-verifies exact repository,
Environment, intent ref, SHA, workflow, run/attempt, numeric actor and signed
runner lease. One successful response is durably consumed; a retry returns a
conflict and is not a safe automatic retry signal. The verified response is
written as a new `0600` file and must be consumed before any mutation step.
The stage consumer independently recomputes the response and bundle digests and
requires its run ID, run attempt, head SHA, intent ref, workflow path,
repository ID/name and signed subject to match the current GitHub runtime
before the first Kubernetes or endpoint side effect. A stale or locally
substituted bootstrap file therefore fails closed even on a trusted runner.

The browser runner also requires one pre-provisioned, non-secret runtime
archive at the fixed path
`/opt/acik/cross-ai/browser-runtime/playwright-1.60.0-linux-x64.tar`. Build it
in the controlled runner-image pipeline with normalized root ownership and the
exact `browser-runtime/runtime-manifest.json` profile, then record the complete
archive SHA-256 as the browser stage's signed `runtimeBundleSha256`. The stage
does not call npm or a browser CDN: it opens the fixed archive without
following symlinks, rejects unsafe tar members and extracts only after the
signed digest matches. Applying a new runtime archive therefore requires new
provider leaves for the changed exact subject; do not copy a mutable cache into
this path or derive the expected digest from the live file.

The workflow contains exactly one governed job. After bootstrap it may use only
1-8 full-SHA or image-digest pinned execution actions, each with only
`CROSS_AI_BOOTSTRAP_FILE: ${{ runner.temp }}/cross-ai-bootstrap.json`. Free-form
or multiline `run:`, local actions, a second checkout, additional jobs and
unbounded `with:` values are fail-closed. Place required mutation logic in the
reviewed content-addressed execution action; do not fetch live control code.
The remote composite action is pinned to a commit that is an ancestor of the
protected workflow branch and whose action bytes equal the checked-in action.
Its shell commands execute against the single signed-head checkout: the runner
bootstrap binds `GITHUB_SHA`, workflow blob and repository identity before the
action can run, while `scripts/faz22-remote-ops/**` is part of the declared
runtime-authority inventory that retriggers this gate. The browser stage uses
the fixed runner-owned `/home/halil/.ssh/config`; OpenSSH host-key verification,
the signed endpoint-ID digest, live certificate/channel checks and attended
consent remain cumulative gates rather than interchangeable identity claims.
The watchdog NetworkPolicy permits only the Kubernetes service ClusterIP
`10.45.0.1/32:443` and the k3d node CIDR `172.19.0.0/16:6443`. The second rule
is required because the test cluster's policy engine observes the apiserver's
post-DNAT node endpoint; it is not general workload egress. Both CIDRs, ports
and the empty-ingress posture are byte-checked by the protected-workflow
contract, so widening them requires a reviewed authority change.

The protected action pin must remain an ancestor of the landed branch. Merge
this PR with a **merge commit**; squash and rebase merge are prohibited because
they would orphan the reviewed action-source commit. The Cross-AI gate requires
this PR to have merge-commit auto-merge selected and reruns on both
`auto_merge_enabled` and `auto_merge_disabled`; a missing or different merge
method fails closed. Enabling repository-level auto-merge only exposes the
feature: selecting it on this PR remains a deliberate merge authorization and
is not performed by the deployment App. If that topology cannot be guaranteed,
do not merge these protected workflows; first land the source package
separately and open a new exact-main pin/review PR.

Exact provider model IDs are part of the signed contract. On model retirement,
existing grants remain bound to the retired ID and are not rewritten: revoke
unconsumed grants, land and review a contract/trust-root migration, rotate the
affected issuer identity as required, and issue fresh grants. Until that full
migration reaches the exact v2 Claude+Codex consensus, new and existing executions remain
fail-closed as `tracked_pending`.

This path is source-ready only. Do not expose the endpoint or enable the
Environment custom rule until the policy runtime has reviewed HTTPS, the
public trust-root pin exists, the separate dispatcher identity is live, the
protected workflows have landed, and negative/replay/rollback canaries pass.
The three checked-in protected workflows must retain the literal all-zero
trust-root digest while the public policy/trust-root/revocation files are
absent. Only the separate reviewed trust-root release may replace all three
sentinels together with those public artifacts and their independently
computed release digest; an operator must never substitute a live-file-derived
digest or edit one workflow in place.
The static Environment credential does not replace GitHub OIDC, and GitHub
OIDC does not replace the signed Cross-AI bundle or human-only gates.

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
5. **Production:** out of scope for the active v2 TEST contract; required human reviewer stays.

If App availability or decision integrity is uncertain: freeze registrations,
revoke unconsumed grants, cancel waiting runs, disable the App rule, restore
the named required reviewer, and verify Environment secret scope did not
change. Never convert a callback outage into an allow-open decision.
