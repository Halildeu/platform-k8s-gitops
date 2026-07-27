# Vault Policy — platform-bootstrap-writer
#
# DR-2 of ADR-0010 (`docs/adr/0010-vault-credential-lifecycle-and-dr.md`).
# Codex consensus thread `019dd2c9`.
#
# Authority: write secrets into kv/data/platform/<service> (KV v2) without
# requiring root token. Used by `platform-ops vault-patch` wrapper (DR-3)
# during bootstrap, dedicated-role onboarding, and credential rotation.
#
# Lifecycle constraints (configured at AppRole creation, see apply runbook):
#   token_ttl=30m, token_max_ttl=60m
#   secret_id_ttl=60m, secret_id_num_uses<=10
#   bind_secret_id=true
#   token_policies="platform-bootstrap-writer"
#
# Test/Prod separation: separate roles per environment, separate secret-ids,
# secret-id NEVER committed to Git.

# ============================================================================
# 1. ALLOW — kv/data/platform/<service> write paths (KV v2)
# ============================================================================
# Write paths cover the platform services + the shared pg-platform-role canonical
# path + openfga + ghcr-token.
# `read` included so the wrapper can fetch existing data + merge before patch.
# `delete` explicitly NOT granted (audit-trail preservation).

path "kv/data/platform/auth-service" {
  capabilities = ["create", "update", "read"]
}

path "kv/data/platform/user-service" {
  capabilities = ["create", "update", "read"]
}

path "kv/data/platform/variant-service" {
  capabilities = ["create", "update", "read"]
}

path "kv/data/platform/core-data-service" {
  capabilities = ["create", "update", "read"]
}

path "kv/data/platform/report-service" {
  capabilities = ["create", "update", "read"]
}

path "kv/data/platform/budget-service" {
  capabilities = ["create", "update", "read"]
}

path "kv/data/platform/schema-service" {
  capabilities = ["create", "update", "read"]
}

path "kv/data/platform/permission-service" {
  capabilities = ["create", "update", "read"]
}

# Signed Cross-AI deployment-protection observer (TEST activation first).
# The App-generated webhook secret is seeded/rotated through the audited
# platform-ops wrapper; ESO remains read-only through the separate eso-runtime
# AppRole. Production activation is outside ADR-0045 v1.
path "kv/data/platform/cross-ai-deployment-protection-test" {
  capabilities = ["create", "update", "read"]
}

# Credential consolidation Faz A — shared `platform` PG role canonical path.
# docs/architecture/runtime/credential-consolidation-plan.md §4-§5 (Codex 019e3386).
# Operator creates + populates kv/platform/pg-platform-role (db_username=platform,
# db_password=platform role password) with this AppRole — no root token; see
# runbook docs/runbooks/RB-credential-consolidation-preflight.md P2 for the
# stdin-piped `vault kv put` command. PR-0 P0 precondition (plan §5): without this
# write allowlist the bootstrap-writer cannot create the canonical path.
# `create` is needed for the first put; `update` for later rotation.
# NOTE: scripts/ops/platform-ops-vault-patch.sh does NOT yet allowlist this path
# (its --service set covers the per-service paths only) — wrapper support for
# pg-platform-role rotation is a follow-up; operators use the Vault CLI directly.
path "kv/data/platform/pg-platform-role" {
  capabilities = ["create", "update", "read"]
}

path "kv/data/platform/openfga" {
  capabilities = ["create", "update", "read"]
}

# GHCR pull token may need rotation via this role too.
path "kv/data/gitops/ghcr-token" {
  capabilities = ["create", "update", "read"]
}

# ============================================================================
# 2. ALLOW — Operational self-inspection
# ============================================================================
# Wrapper performs capabilities-self check before write (fail-fast pattern).
# token/lookup-self enables audit metadata + correlation ID.

path "sys/capabilities-self" {
  capabilities = ["update"]
}

path "auth/token/lookup-self" {
  capabilities = ["read"]
}

# Short-lived writer tokens must be able to revoke only themselves after one
# audited operation. Revoking any other token remains explicitly denied below.
path "auth/token/revoke-self" {
  capabilities = ["update"]
}

# ============================================================================
# 3. DENY — Defense-in-depth explicit denials
# ============================================================================
# Even though absence of grant = no access in Vault, explicit denials are
# safer (immune to wildcard policy expansion).

# No KV metadata mutation (preserve versioned audit trail)
path "kv/metadata/platform/+" {
  capabilities = ["deny"]
}
path "kv/metadata/gitops/+" {
  capabilities = ["deny"]
}

# No KV soft-delete or destroy
path "kv/delete/+/+" {
  capabilities = ["deny"]
}
path "kv/destroy/+/+" {
  capabilities = ["deny"]
}
path "kv/undelete/+/+" {
  capabilities = ["deny"]
}

# No Vault admin (sys/*)
path "sys/auth/*"        { capabilities = ["deny"] }
path "sys/policies/*"    { capabilities = ["deny"] }
path "sys/policy/*"      { capabilities = ["deny"] }
path "sys/audit/*"       { capabilities = ["deny"] }
path "sys/seal/*"        { capabilities = ["deny"] }
path "sys/unseal"        { capabilities = ["deny"] }
path "sys/generate-root/*" { capabilities = ["deny"] }
path "sys/wrapping/*"    { capabilities = ["deny"] }
path "sys/storage/*"     { capabilities = ["deny"] }
path "sys/raw/*"         { capabilities = ["deny"] }
path "sys/rotate/*"      { capabilities = ["deny"] }
path "sys/key-status"    { capabilities = ["deny"] }

# No auth backend admin
path "auth/approle/*"    { capabilities = ["deny"] }
path "auth/token/create*" { capabilities = ["deny"] }
path "auth/token/revoke" { capabilities = ["deny"] }
path "auth/token/revoke-accessor" { capabilities = ["deny"] }
path "auth/token/revoke-orphan" { capabilities = ["deny"] }

# No identity manipulation
path "identity/*"        { capabilities = ["deny"] }
