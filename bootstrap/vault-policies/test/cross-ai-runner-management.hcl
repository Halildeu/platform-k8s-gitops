# TEST-only runner inventory/admission lease signer. This identity cannot sign
# provider leaves, coordinator bundles or revocation sets.
path "cross-ai/sign/runner-management" {
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
