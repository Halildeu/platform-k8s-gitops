# Cross-AI deployment policy configuration

`cross-ai-deployment-policy.example.json` is the historical v2 three-stage
template. It remains for immutable audit/rollback compatibility but cannot
authorize a new VIEW_ONLY transaction.

`cross-ai-deployment-policy-v2.example.json` is the forward, schema-valid,
non-live policy for bundle contract v3. The repository and evaluator App IDs
reflect the reviewed TEST identity; each `90000000x` value is still a deliberate
dispatcher sentinel, not a deployed identity and never live evidence.

Before use, create an environment-specific copy outside the image, replace the
sentinels from GitHub's live API, validate it with `load_policy`, and bind its
JCS SHA-256 into the signed subject. Changing any field invalidates existing
review leaves and grants.

The trust-root manifest is a separate authority surface. Compute its canonical
JCS digest in the controlled release job and pin that exact `sha256:...` value
in the service deployment as `--expected-trust-root-sha256`. Do not derive the
pin from the mounted trust-root file at service startup; that would make a
tampered file self-authorizing.

The historical example names three dedicated no-input `*-protected.yml`
workflows. Their
execution actions are pinned to immutable commit
`ead8b151457929c7a7525ebdab2fd2b374b4f976`; all three share one literal,
non-cancelling concurrency group and publish the exact canonical stage-outcome
artifact expected by the sweeper. Apply performs immediate in-job compensation
on failure; the separate rollback workflow is only the pre-signed
crash/CallbackUnknown recovery lane and checks the live watchdog bundle marker
before destructive cleanup.

The forward example instead authorizes exactly one stage, `transaction`, at
`.github/workflows/faz22-6-view-only-viewer-transaction.yml`. Its signed bundle
must bind the exact workflow blob, dependency/concurrency digests, complete
authority-file inventory, same-run preflight and one protected Environment
gate. A v2 dispatcher or any of the separate protected workflows is not a v3
fallback.

The historical workflows are intentionally fail-closed until their retired
release material is present. Their command currently pins the zero
digest sentinel and references environment-specific policy, trust-root and
revocation files that are deliberately absent. A separate reviewed release
change must add those public artifacts and replace the sentinel with the
independently computed trust-root digest. Do not substitute the mounted file's
digest at runtime or weaken the command to accept mutable workflow inputs.

Forward v3 uses the five-key public v2 trust plane: Anthropic, OpenAI,
coordinator, revocation and runner-management. The retained MiniMax public key
is forensic-only and has no AppRole/policy authority. The final v3 policy bytes
and authority hashes must not be released until the exact stabilized #2644
head is bound and the merge-time Cross-AI gate required by canonical `main`
passes. After #2688 lands, that gate is the isolated exact-scope Codex
high-impact profile; Claude, MiniMax, Cursor, wrappers and UI review paths are
forbidden.

`run_cross_ai_review_issuer.py` and
`run_cross_ai_evidence_coordinator.py` are the only forward operational signing
entry points. They require owner-only file inputs, independently pinned
trust-root bytes and separate one-use Vault tokens; neither accepts a model
override or MiniMax route. A schema-valid local example is not an issuance
request and must never be signed as live authority.

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
