# Vault Policy — vault-config-reconciler (TEST Vault only)
#
# AI/automation authority to reconcile git-reviewed Vault CONFIG (ACL policies +
# scoped AppRoles) onto the TEST Vault WITHOUT a per-change operator root login.
# Pairs with scripts/ops/vault-policy-reconcile.sh (applies bootstrap/vault-policies/*
# from git) — the PR + cross-AI review of those files is the content gate.
#
# Reviewed: Codex thread (see PR). ADR-0010 credential-lifecycle.
#
# ── Trust model (HONEST — Codex 019f1150 REVISE-absorb) ─────────────────────
# Label this accurately: this AppRole is **TEST-Vault CONFIG-ADMIN over the
# named policy/approle surface**, NOT a "config-only, secret-denied, isolated"
# role. OSS Vault has no policy-CONTENT constraint, so even with the named-path
# scoping below, the holder could rewrite an allowlisted policy (e.g. make
# `audio-gateway-mtls-seeder` grant token-create) and obtain a token without
# this role's DENY set → self-escalation. The Vault ACL is NOT the isolation.
# What actually bounds it:
#   • EXPLICIT named paths (§1/§2) — cannot author new arbitrary policies/roles,
#     cannot self-amend `vault-config-reconciler`.
#   • CONTENT LINTER in scripts/ops/vault-policy-reconcile.sh — fail-closed
#     rejects applying any policy text carrying escalation primitives
#     (auth/token/create, sys/policies, sys/auth, sys/raw, identity, ...).
#   • git PR + cross-AI review = the CHANGE-CONTROL gate (not technical isolation).
#   • TEST Vault only — NEVER applied to prod (prod stays owner-gated; I7-prod gate).
#   • Host-local 0600 secret-id + finite TTL + rotation; short-lived self-revoked tokens.
#   • Hard DENY (§4): unseal/generate-root/seal/rekey/raw/storage/audit/identity/
#     token-create/kv-secret/pki-issue — bounds THIS token's direct reach.
# This is consistent with the SSH+sudo trust the agent already holds on
# staging-sw (where credential-hiding is not an enforceable boundary anyway).
# The root-of-trust (root token / unseal keys) stays OWNER-only, established
# ONCE (README §6.6). For a HARD boundary, the reconciler must run where the
# agent is not root (off-host / narrower sudo) — documented as the ideal.
#
# Separation of duty: this role does NOT touch kv secrets. Secret seeding is done
# by the NARROW seed AppRoles this reconciler creates (e.g. bootstrap-writer,
# audio-gateway-mtls-seeder) — each scoped to its own path. Two credentials.

# ============================================================================
# 1. ALLOW — apply git-reviewed ACL policies (EXPLICIT names, no glob)
# ============================================================================
# Codex 019f1150 REVISE: a `sys/policies/acl/*` glob lets the holder author an
# arbitrary powerful policy → self-escalation. Scope to the EXACT managed names,
# and EXCLUDE `vault-config-reconciler` itself (no self-amendment — its own
# policy/approle stays owner-gated). `delete` NOT granted (owner prunes stale).
path "sys/policies/acl" {
  capabilities = ["list"]
}

path "sys/policies/acl/eso-runtime" {
  capabilities = ["create", "update", "read"]
}

path "sys/policies/acl/eso-runtime-test-extras" {
  capabilities = ["create", "update", "read"]
}

path "sys/policies/acl/platform-bootstrap-writer" {
  capabilities = ["create", "update", "read"]
}

path "sys/policies/acl/audio-gateway-mtls-seeder" {
  capabilities = ["create", "update", "read"]
}

path "sys/policies/acl/cross-ai-issuer-anthropic-test" {
  capabilities = ["create", "update", "read"]
}

path "sys/policies/acl/cross-ai-issuer-secondary-test" {
  capabilities = ["create", "update", "read"]
}

path "sys/policies/acl/cross-ai-coordinator-test" {
  capabilities = ["create", "update", "read"]
}

path "sys/policies/acl/cross-ai-revocation-test" {
  capabilities = ["create", "update", "read"]
}

path "sys/policies/acl/cross-ai-runner-management-test" {
  capabilities = ["create", "update", "read"]
}

# ============================================================================
# 2. ALLOW — manage the scoped seed AppRoles (EXPLICIT names, no glob)
# ============================================================================
# Only the named seed roles — NOT `vault-config-reconciler` (no self-rotate),
# and not arbitrary new roles (can't bind a powerful policy to a fresh role).
path "auth/approle/role/eso-runtime" {
  capabilities = ["create", "update", "read"]
}

path "auth/approle/role/eso-runtime/role-id" {
  capabilities = ["read"]
}

path "auth/approle/role/eso-runtime/secret-id" {
  capabilities = ["create", "update"]
}

path "auth/approle/role/platform-bootstrap-writer-test" {
  capabilities = ["create", "update", "read"]
}

path "auth/approle/role/platform-bootstrap-writer-test/role-id" {
  capabilities = ["read"]
}

path "auth/approle/role/platform-bootstrap-writer-test/secret-id" {
  capabilities = ["create", "update"]
}

path "auth/approle/role/audio-gateway-mtls-seeder-test" {
  capabilities = ["create", "update", "read"]
}

path "auth/approle/role/audio-gateway-mtls-seeder-test/role-id" {
  capabilities = ["read"]
}

path "auth/approle/role/audio-gateway-mtls-seeder-test/secret-id" {
  capabilities = ["create", "update"]
}

path "auth/approle/role/cross-ai-issuer-anthropic-test" {
  capabilities = ["create", "update", "read"]
}

path "auth/approle/role/cross-ai-issuer-anthropic-test/role-id" {
  capabilities = ["read"]
}

path "auth/approle/role/cross-ai-issuer-anthropic-test/secret-id" {
  capabilities = ["create", "update"]
}

path "auth/approle/role/cross-ai-issuer-secondary-test" {
  capabilities = ["create", "update", "read"]
}

path "auth/approle/role/cross-ai-issuer-secondary-test/role-id" {
  capabilities = ["read"]
}

path "auth/approle/role/cross-ai-issuer-secondary-test/secret-id" {
  capabilities = ["create", "update"]
}

path "auth/approle/role/cross-ai-coordinator-test" {
  capabilities = ["create", "update", "read"]
}

path "auth/approle/role/cross-ai-coordinator-test/role-id" {
  capabilities = ["read"]
}

path "auth/approle/role/cross-ai-coordinator-test/secret-id" {
  capabilities = ["create", "update"]
}

path "auth/approle/role/cross-ai-revocation-test" {
  capabilities = ["create", "update", "read"]
}

path "auth/approle/role/cross-ai-revocation-test/role-id" {
  capabilities = ["read"]
}

path "auth/approle/role/cross-ai-runner-management-test" {
  capabilities = ["create", "update", "read"]
}

path "auth/approle/role/cross-ai-runner-management-test/role-id" {
  capabilities = ["read"]
}

path "auth/approle/role/cross-ai-runner-management-test/secret-id" {
  capabilities = ["create", "update"]
}

# Deliberately no cross-ai-revocation-test/secret-id capability. Revocation is
# an exceptional owner-authorized operation, not a routine automation token.

# ============================================================================
# 3. ALLOW — read-only introspection (idempotency + audit correlation)
# ============================================================================
path "sys/mounts" {
  capabilities = ["read"]
}

path "sys/capabilities-self" {
  capabilities = ["update"]
}

path "auth/token/lookup-self" {
  capabilities = ["read"]
}

# ============================================================================
# 4. DENY — defense-in-depth (the irreducible owner-only surface)
# ============================================================================
# No Vault disaster-recovery / sealing — root-of-trust stays owner-only.
path "sys/seal" {
  capabilities = ["deny"]
}

path "sys/unseal" {
  capabilities = ["deny"]
}

path "sys/step-down" {
  capabilities = ["deny"]
}

path "sys/generate-root/*" {
  capabilities = ["deny"]
}

path "sys/rotate/*" {
  capabilities = ["deny"]
}

path "sys/rekey/*" {
  capabilities = ["deny"]
}

path "sys/raw/*" {
  capabilities = ["deny"]
}

path "sys/storage/*" {
  capabilities = ["deny"]
}

path "sys/audit/*" {
  capabilities = ["deny"]
} # cannot disable audit

path "identity/*" {
  capabilities = ["deny"]
}

# No direct token minting — auth flows only through the scoped AppRoles.
path "auth/token/create*" {
  capabilities = ["deny"]
}

path "auth/token/root" {
  capabilities = ["deny"]
}

# No secret read/write — separation of duty (seed AppRoles own kv, not this one).
path "kv/data/*" {
  capabilities = ["deny"]
}

path "kv/metadata/*" {
  capabilities = ["deny"]
}

path "kv/delete/*" {
  capabilities = ["deny"]
}

path "kv/destroy/*" {
  capabilities = ["deny"]
}

# No PKI issuance/signing/admin — seed AppRoles own pki issue, not this one.
path "pki-denetim-ai/issue/*" {
  capabilities = ["deny"]
}

path "pki-denetim-ai/sign/*" {
  capabilities = ["deny"]
}

path "pki-denetim-ai/root/*" {
  capabilities = ["deny"]
}
