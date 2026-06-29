# Vault Policy — audio-gateway-mtls-seeder (TEST Vault only)
#
# Faz 24 direct-STT app-mTLS (I7, docs/runbooks/RB-bplus-i7-app-mtls.md).
# Codex design `019ef0a2`; this policy reviewed in thread `019f1124` (REVISE-absorb).
#
# Single-purpose, blast-radius-isolated authority for ONE operation: mint the
# audio-gateway CLIENT mTLS cert from the pre-existing `pki-denetim-ai` engine
# (I7a foundation, EC P-256 root `denetim-ai-ca-test`) and seed it ADDITIVELY
# into kv/data/platform/audio-gateway-service so ESO `audio-gateway-direct-stt-mtls`
# goes Ready. NO root token; NOT the broad `platform-bootstrap-writer` AppRole
# (Codex 019f1124: a leaked bootstrap-writer secret-id must NOT also mint certs).
#
# Bind to a DEDICATED test AppRole `audio-gateway-mtls-seeder-test`:
#   secret_id_num_uses=1, token_ttl<=15m, bind_secret_id=true, secret-id NEVER in
#   Git, role-id/secret-id files mode 0600. token_num_uses=0 (unbounded WITHIN the
#   15m TTL) — the one-shot secret_id + short TTL are the real bounds; a fixed
#   num_uses is intentionally NOT set so the boundary verifier can run its full
#   negative suite on a single token (Codex 019f1124 caveat-1). See README §6.5.
#
# CRITICAL non-policy precondition (Codex 019f1124): the `audio-gateway-client`
# PKI role itself must be locked down BEFORE this is used — the policy only gates
# access to the role endpoint; a permissive role mints permissive certs. Verify
# live: client_flag=true, server_flag=false, max_ttl<=24h, allow_any_name=false,
# exact allowed CN/URI-SAN, key constraints. README §6.5 records the proof.
#
# TEST ONLY — prod direct-STT is the I7-prod GATE (KVKK m.6 + legal/consent,
# operator+hukuk). This policy is NEVER written to the prod Vault.

# ============================================================================
# 1. ALLOW — additive KV seed (server-side PATCH = non-destructive merge)
# ============================================================================
# `patch` = KV v2 server-side merge: only the supplied keys (direct_stt_*) are
# set/updated; pre-existing keys at this path (e.g. the Redis password) are
# preserved. `create`/`update` are intentionally NOT granted — they allow a full
# current-version overwrite, which is destructive. `read` for post-seed verify.
path "kv/data/platform/audio-gateway-service" {
  capabilities = ["patch", "read"]
}

# ============================================================================
# 2. ALLOW — issue the single audio-gateway client cert
# ============================================================================
# Vault PKI `issue/<role>` is exercised with the `update` capability.
path "pki-denetim-ai/issue/audio-gateway-client" {
  capabilities = ["update"]
}

# Inspect the role (TTL/EKU/SAN limits) before issuing — fail-fast. Role config
# is not a secret. NB: no blanket `roles/*` allow — only this one role.
path "pki-denetim-ai/roles/audio-gateway-client" {
  capabilities = ["read"]
}

# Read the CA chain to seed direct_stt_ca_crt (CA is public trust material).
path "pki-denetim-ai/cert/ca" {
  capabilities = ["read"]
}

# ============================================================================
# 3. ALLOW — operational self-inspection (fail-fast + audit correlation)
# ============================================================================
path "sys/capabilities-self" {
  capabilities = ["update"]
}

path "auth/token/lookup-self" {
  capabilities = ["read"]
}

# ============================================================================
# 4. DENY — defense-in-depth (immune to wildcard expansion)
# ============================================================================
# No full overwrite / soft-delete / destroy / metadata mutation on the KV path.
path "kv/metadata/platform/audio-gateway-service" {
  capabilities = ["deny"]
}

path "kv/delete/platform/audio-gateway-service" {
  capabilities = ["deny"]
}

path "kv/destroy/platform/audio-gateway-service" {
  capabilities = ["deny"]
}

path "kv/undelete/platform/audio-gateway-service" {
  capabilities = ["deny"]
}

# No PKI admin / server cert / arbitrary signing / revoke / tidy.
# (No blanket `pki-denetim-ai/roles/*` deny — it would shadow the single-role
# read allow above; absence-of-grant already denies every other role.)
path "pki-denetim-ai/issue/denetim-ai-server" {
  capabilities = ["deny"]
}

path "pki-denetim-ai/sign/*" {
  capabilities = ["deny"]
}

path "pki-denetim-ai/sign-verbatim/*" {
  capabilities = ["deny"]
}

path "pki-denetim-ai/root/*" {
  capabilities = ["deny"]
}

path "pki-denetim-ai/config/*" {
  capabilities = ["deny"]
}

path "pki-denetim-ai/revoke" {
  capabilities = ["deny"]
}

path "pki-denetim-ai/tidy*" {
  capabilities = ["deny"]
}

# No Vault admin / auth / identity manipulation.
path "sys/policies/*" {
  capabilities = ["deny"]
}

path "sys/policy/*" {
  capabilities = ["deny"]
}

path "sys/auth/*" {
  capabilities = ["deny"]
}

path "sys/audit/*" {
  capabilities = ["deny"]
}

path "sys/generate-root/*" {
  capabilities = ["deny"]
}

path "auth/approle/*" {
  capabilities = ["deny"]
}

path "auth/token/create*" {
  capabilities = ["deny"]
}

path "identity/*" {
  capabilities = ["deny"]
}
