# TEST-only short-lived mTLS client certificate issuer for meeting-ai.
#
# The operator token must be minted without the default policy, with a short
# non-renewable TTL and bounded uses. It can issue only the dedicated
# meeting-ai client role, read the server CA, inspect itself, and revoke itself.

path "pki_meeting_ai_client/issue/meeting-ai" {
  capabilities = ["update"]
}

path "pki_meeting_ai_server/cert/ca" {
  capabilities = ["read"]
}

path "auth/token/lookup-self" {
  capabilities = ["read"]
}

path "auth/token/revoke-self" {
  capabilities = ["update"]
}
