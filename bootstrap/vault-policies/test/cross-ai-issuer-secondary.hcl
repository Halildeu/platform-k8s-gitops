# TEST-only signed deployment evidence issuer for the second provider route.
# The eventual trust-root release binds this generic key to one provider family
# and channel. Until that live route exists, no trust root may count this key.
path "cross-ai/sign/provider-secondary" {
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
