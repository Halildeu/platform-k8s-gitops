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

The example names three dedicated no-input `*-protected.yml` workflows. Their
execution actions are pinned to immutable commit
`e1ecc34b63cef3e8be63ae20fc7dbaa7987a62ab`; all three share one literal,
non-cancelling concurrency group and publish the exact canonical stage-outcome
artifact expected by the sweeper. Apply performs immediate in-job compensation
on failure; the separate rollback workflow is only the pre-signed
crash/CallbackUnknown recovery lane and checks the live watchdog bundle marker
before destructive cleanup.

The workflows are intentionally fail-closed until the one-time owner Transit
bootstrap produces the six public keys. Their command currently pins the zero
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
