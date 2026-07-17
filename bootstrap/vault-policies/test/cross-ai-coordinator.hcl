# TEST-only coordinator signer. It can sign bundles but cannot sign provider
# leaves because every DSSE role is bound to a distinct Transit key ID.
path "cross-ai/sign/coordinator" {
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
