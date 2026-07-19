# Cross-AI deployment policy configuration

`cross-ai-deployment-policy.example.json` is a schema-valid, non-live template.
The repository ID is the live public repository identity read on 2026-07-17.
The three `90000000x` values are deliberate sentinels for, respectively, the
protection-rule App ID, installation ID and dispatcher bot actor ID. They are
not deployed identities and must never be presented as live evidence.

Before use, create an environment-specific copy outside the image, replace the
sentinels from GitHub's live API, validate it with `load_policy`, and bind its
JCS SHA-256 into the signed subject. Changing any field invalidates existing
review leaves and grants.

The trust-root manifest is a separate authority surface. Compute its canonical
JCS digest in the controlled release job and pin that exact `sha256:...` value
in the service deployment as `--expected-trust-root-sha256`. Do not derive the
pin from the mounted trust-root file at service startup; that would make a
tampered file self-authorizing.

Standalone direct-Codex review leaves use the fixed public authority locator
`cross-ai-provider-review-authority.v1.json`. It is intentionally
`tracked_pending` until the TEST Vault Transit public keys, a signed revocation
set and an independently computed trust-root pin are released at the exact
paths declared by the locator. No private Vault key or token belongs in these
public files. The public root may live at most 720 hours; provider-review keys
rotate within 168 hours with at least 24 hours overlap. Signed revocations must
refresh within 60 minutes and individual review leaves remain bounded to 120
minutes. `codexExecutablePolicy` is the independently reviewed, release-managed
official executable allowlist: the runner must resolve the OpenAI npm wrapper,
match the bundled native binary byte digest and CLI version. Darwin launchers
also verify the Apple Developer ID identity, team and full CDHash before launch;
the Kubernetes Linux issuer is admitted only by a pinned npm tarball SHA-512,
registry-signature identity and signature digest, and canonical npm publish plus
SLSA provenance bundle digests bound to the official OpenAI release workflow.
These values
are never accepted from the runner, caller or review response. Updating Codex
therefore requires an explicit authority-manifest policy change, but does not
rotate the provider-review signing root. The signed launch capability snapshot
then binds the matched allowlist entry, private-copy digest, live model catalog
and fixed arguments inside each provider-review leaf. Version discovery, model
catalog and review execution all receive the same complete isolated environment:
no caller variable is inherited, provider endpoint/proxy variables are absent,
and the OS-account Codex home plus private temporary root are fixed. The signed
capability snapshot binds that exact environment policy, so
`OPENAI_BASE_URL`/proxy routing cannot masquerade as direct OpenAI provenance.
The issuer resolves `refs/heads/main` from the fixed GitHub REST ref endpoint
over direct TLS and requires that exact commit object to be present locally;
the caller worktree's mutable `origin/main`, remote URL and ref namespace never
define the signed review base.

The first public root cannot cryptographically authorize its own introduction.
`cross-ai-provider-review-genesis.v1.json` resolves that bootstrap without a
general bypass. It permits exactly two default-branch transitions:

1. `installed -> staged`: a PR may change only the genesis locator plus the
   fixed public trust-root and signed-revocations paths. It carries no provider
   receipt and passes only through the trusted-main
   `cross-ai-provider-review-genesis.yml` workflow after the protected
   `cross-ai-provider-review-genesis` Environment proves a non-self human
   reviewer is configured and approves the run. The workflow independently
   verifies same-repo PR/base/head, exact changed paths, root digest, DSSE and
   revocation freshness; the ordinary audit accepts `none` only with that
   exact successful run.
2. `staged -> retired`: a second PR may change only the authority locator and
   genesis status. The trusted-base verifier uses the already committed staged
   root to validate an exact `gpt-5.6-sol xhigh` signed receipt, requires a
   second protected-Environment run, checks the locator projection byte-for-
   byte and retires the genesis path. A root, revocation, schema or code change
   cannot ride with activation.

The workflow must be dispatched from exact `refs/heads/main`; its successful
run is valid for 24 hours and must bind the current PR base and head. An
ordinary PR cannot present `Authority genesis run`, and a failed/stale run does
not lower the consultation floor. After retirement, only the active signed
authority path remains; genesis cannot be replayed to recover or replace it.

The public root contains only the OpenAI provider-review role plus one each of
the coordinator, revocation and runner-management roles. A provider rotation
may temporarily expose exactly two consecutive OpenAI key versions; both are
bounded to 168 hours and overlap for at least 24 hours. Anthropic and MiniMax
AppRoles and ACL policies must both be absent in the public bootstrap receipt;
their historical public keys are input provenance only and are never copied
into the active v2 root. The OpenAI role permits only the fixed routine
`gpt-5.3-codex-spark` and high-impact `gpt-5.6-sol` routes; both remain xhigh,
read-only, ephemeral and trusted-launch-attested. The former short-lived
staging root is forensic-only and is not an allowed locator target or fallback.
The routine Spark route is currently `tracked_pending` because the live Codex
catalog does not list its exact slug. It has no model or wrapper fallback;
routine work uses consultation mode `none` until that exact route becomes live.

Provider rotation does not collapse issuer-runtime independence: the OpenAI
provider issuer may use only the provider-review signer, while a separate
workload-identity-bound attestor owns runner-management signing and binds the
pinned issuer image and launcher source to the exact prompt, response, Codex
session, capability snapshot and provider-review envelope. The raw evidence
CLI carries neither credential and cannot issue accepted evidence outside
those fixed services.

Trust-root rotation is an append-only public transition. A replacement root
must start at the exact recorded retirement time of the predecessor and the
same PR must copy the predecessor root plus its final signed revocation
snapshot byte-for-byte into
`cross-ai-provider-review-history/<old-root-digest>/`. The authority manifest
appends one content-addressed entry binding both digests, the executable and
issuer-runtime policies, and the retirement time. Existing history entries and
archived bytes are immutable; deleting, editing, reordering or rotating a root
without the exact archive fails before review evidence is accepted. Product
evidence issued before retirement can therefore be reverified against the
pinned final snapshot after the current root changes, while evidence at or
after retirement cannot use the old root. Retirement cannot be future-dated or
older than the bounded review-leaf window, and the replacement root plus its
signed revocations must still be active and fresh at the trusted verifier's
current observation time; validating only at a backdated retirement timestamp
is forbidden.

The rotation PR's review is signed and transported under the still-active
predecessor authority. The evidence builder and poster derive that predecessor
only from the exact merge-base git objects after validating the complete
append-only rotation and canonical scope binding; they never let the proposed
replacement root authorize its own introduction. The trusted-base PR verifier
repeats the transition validation and verifies the predecessor-signed leaf.
After merge, ordinary reviews use the replacement active authority. This keeps
rotation possible without creating a new-root self-authorization path.

The protected #2373 authorization artifact retains the exact downloaded signed
advisory comment JSON alongside the authorization receipt and covers both with
`SHA256SUMS` plus the immutable artifact digest. The independently produced
operator child then carries both exact byte sequences in its content-addressed
product-evidence payload together with the activation identity and timestamps.
Product replay validates the carried authorization and advisory bytes; it does
not relist or redownload the expiring activation artifact and does not refetch
the live advisory comment. Deletion or unavailability of either GitHub
transport therefore does not erase an already assembled product carrier.

`build_cross_ai_provider_review_revocations.py` is the only repository release
entrypoint for the public revocation file. It signs only
`acik.cross-ai-deployment-revocations.v1` with the fixed
`cross-ai/revocation` Transit route, requires the independently supplied root
pin, enforces a maximum 60-minute `nextUpdate`, verifies the emitted DSSE and
writes create-once bytes. Missing or stale revocations never mean an empty set.
If the 60-minute window is missed after genesis retirement, recovery is not a
genesis replay and does not lower the high-impact review floor. The trusted-base
verifier accepts only an exact revocations-file-only PR whose replacement is a
fresh DSSE from the already pinned revocation key, has a new set identity/time,
and contains every predecessor revocation byte-for-byte. Any other changed path,
forged release or attempted unrevocation fails closed. The same validation is
mandatory for a proactive refresh while the predecessor is still fresh; the
active file can never bypass validation merely because its `nextUpdate` has not
yet elapsed.

The example names three dedicated no-input `*-protected.yml` workflows. Their
execution actions are pinned to immutable commit
`ead8b151457929c7a7525ebdab2fd2b374b4f976`; all three share one literal,
non-cancelling concurrency group and publish the exact canonical stage-outcome
artifact expected by the sweeper. Apply performs immediate in-job compensation
on failure; the separate rollback workflow is only the pre-signed
crash/CallbackUnknown recovery lane and checks the live watchdog bundle marker
before destructive cleanup.

The workflows are intentionally fail-closed until the one-time owner Transit
bootstrap produces the five-key public v2 receipt and the four-role active
root. Their command currently pins the zero
digest sentinel and references environment-specific policy, trust-root and
revocation files that are deliberately absent. A separate reviewed release
change must add those public artifacts and replace the sentinel with the
independently computed trust-root digest. Do not substitute the mounted file's
digest at runtime or weaken the command to accept mutable workflow inputs.

`cross-ai-protection-evaluator-app.example.json` and
`cross-ai-intent-dispatcher-app.example.json` are reviewable registration
projections, not credentials and not proof that either App exists. The first
App has only Actions read, Contents read and Deployments write plus the
`deployment_protection_rule` event. The second has Actions/Contents write but
no webhook events; repository rules and egress containment must still prove it
cannot write branches, non-intent tags or move an existing intent tag.

The public evaluator webhook URL in the template maps to the receive-only test
overlay. The raw webhook secret must be generated during the owner-controlled
App registration and written directly to
`kv/platform/cross-ai-deployment-protection-test` property
`github_webhook_secret_current`; never paste it into the repository, an issue,
chat, shell argument or workflow log.

Phase 2 also stores the evaluator App private key at the same test-only Vault
path under the distinct property `github_app_private_key_pem`. Keep the
download in a current-user-owned `0600` regular file and use only the audited
file-input operation:

```bash
VAULT_BOOTSTRAP_ROLE_ID="$(cat /tmp/platform-bootstrap-writer-test-role-id.txt)" \
VAULT_BOOTSTRAP_SECRET_ID_FILE=/tmp/platform-bootstrap-writer-test-secret-id.txt \
bash scripts/ops/platform-ops-vault-patch.sh \
  --vault-addr http://127.0.0.1:8201 \
  --service cross-ai-deployment-protection-test \
  --field-from-file "github_app_private_key_pem=$HANDOFF" \
  --cleanup-field-files \
  --cleanup-secret-id-file
```

The wrapper accepts exactly one operation per invocation on this dedicated
path: the webhook secret from one-line stdin, or the App PEM from an
owner-only file. It rejects arbitrary property names, merges with KV v2 CAS,
self-revokes the short-lived token and removes both handoff files when the
cleanup flags are used. Never pass the PEM value as `--field`, environment
text, chat, an issue comment or a log. Seeding the property does not authorize
mounting it into the Phase 1 receive-only observer; only the future reviewed
enforcement overlay may consume it.

Before the ExternalSecret is activated, an owner applies the reviewed
`bootstrap/vault-policies/common/eso-runtime.hcl` to the test Vault.  Its
dedicated rule grants ESO only `read` on
`kv/data/platform/cross-ai-deployment-protection-test`; it does not grant
secret creation, update or broad wildcard access.  Verify the live AppRole
capability after the owner-gated policy apply rather than assuming the source
file is already active.
