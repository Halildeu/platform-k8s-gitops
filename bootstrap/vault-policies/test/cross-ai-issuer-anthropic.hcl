# TEST-only signed deployment evidence issuer for the direct Anthropic route.
# Private key material never leaves Vault Transit. The runtime may sign with
# this one key and has no read/export/rotate/decrypt/datakey authority.
path "cross-ai/sign/anthropic" {
  capabilities = ["update"]
}

path "cross-ai/keys/*" {
  capabilities = ["deny"]
}

path "cross-ai/export/*" {
  capabilities = ["deny"]
}

path "cross-ai/backup/*" {
  capabilities = ["deny"]
}

path "cross-ai/restore/*" {
  capabilities = ["deny"]
}

path "cross-ai/datakey/*" {
  capabilities = ["deny"]
}

path "cross-ai/encrypt/*" {
  capabilities = ["deny"]
}

path "cross-ai/decrypt/*" {
  capabilities = ["deny"]
}

path "cross-ai/rewrap/*" {
  capabilities = ["deny"]
}

path "cross-ai/hmac/*" {
  capabilities = ["deny"]
}
