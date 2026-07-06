# Release Candidates Ledger

> Codex P0 #2 — promotion ledger directory. Per-(repo,sha) JSON entries
> tracking image build → test promotion → D29 smoke evidence → prod
> candidate PR → prod deploy.

## Layout

```
release-candidates/
├── platform-backend/
│   ├── <git-sha-1>.json
│   ├── <git-sha-2>.json
│   └── ...
├── platform-web/
│   ├── <git-sha-1>.json
│   └── ...
└── platform-agent/
    ├── <git-sha-1>.json   # artifact-host (Faz 22.5 M1 endpoint-agent install host)
    └── ...
```

Each `.json` validated against `schema/promotion-ledger-v1.schema.json`
on every PR via `.github/workflows/promotion-ledger-validate.yml`.

## Lifecycle

1. **Created** by upstream CI (`platform-backend` or `platform-web`)
   on every successful image build + GHCR push.
2. **Updated to test-promoted** when bot opens gitops PR with test
   overlay digest update; merged → ArgoCD test sync.
3. **Updated to test-verified** by smoke gate workflow after D29
   Up + Functional + Zanzibar pass on test cluster.
4. **Prod candidate** — bot opens DRAFT prod PR referencing the
   test-verified ledger entry; operator reviews + merges.
5. **Prod deployed** — bot updates ledger after ArgoCD prod sync.

## File naming

`<repo>/<git_sha>.json` where `git_sha` is the FULL 40-char git commit
SHA from the upstream repo (NOT the OCI image digest, which is in the
`image.digest` field). This avoids collision when multiple repos build
the same code-content.

## Why JSON not YAML

- Easier programmatic consumption from Bash/jq
- Strict schema validation via JSON Schema (yaml needs translation)
- ArgoCD revision tracking is naturally hex strings (no YAML quoting weirdness)

## Read-only governance

This directory is **append-mostly**. Entries can be updated through
their lifecycle (test promoted → verified → prod promoted), but the
core fields (`repo`, `service`, `git_sha`, `image.digest`) MUST NOT
change once written. Schema enforces this via `additionalProperties: false`.

## Garbage collection

After 30 days post-prod-deploy, entries can be archived to
`release-candidates/.archive/<year>/<month>/` (manual or scheduled).
Initial cutover phase: NO archival (full audit trail).

## See also

- `docs/operations/promotion-ledger-design.md` — full architecture spec
- `schema/promotion-ledger-v1.schema.json` — JSON schema
- `scripts/promotion/` — generator + verifier scripts
