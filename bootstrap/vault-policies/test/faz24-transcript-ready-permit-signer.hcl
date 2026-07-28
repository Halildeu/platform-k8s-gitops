# TEST-only Faz 24 transcript-ready pre-enable permit signer.
#
# This token can sign with one dedicated non-exportable Ed25519 Transit key. It
# cannot read/export/delete/rotate keys, mint tokens, access KV, or use the
# cross-ai signing domain.

path "meeting-ai/sign/transcript-ready-permit" {
  capabilities = ["update"]
}

path "auth/token/lookup-self" {
  capabilities = ["read"]
}

path "auth/token/revoke-self" {
  capabilities = ["update"]
}
