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

The example names dedicated `*-protected.yml` workflows. Those workflows are
not in the repository yet: the current human-gated workflows declare dispatch
inputs and therefore correctly fail the v1 machine-gate inspector.

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
