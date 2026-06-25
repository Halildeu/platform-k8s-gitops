# RB — Faz 24 platform-desktop gateway audience contract

> **Status**: ACTIVE — metadata/runbook + local validator only.
> **Scope**: `platform-test` realm, `platform-desktop` client, recorder
> meeting-admin external path.
> **Boundary**: This runbook does not mutate Keycloak by itself and does not
> prove recorder acceptance. It defines the operator path and the redacted
> token-contract evidence expected before the next recorder external smoke.

## Context

The accepted recorder lifecycle evidence used a cluster-internal
`meeting-service` fixture for meeting creation, then the authoritative external
`https://testai.acik.com/api/v1/audio-gateway` path for consent/session/chunk
and finish.

The remaining external meeting-admin gap is the `platform-desktop` token path:

- `audio-gateway` needs `audio-gateway-service` audience.
- `meeting-service` needs `meeting-service` audience and meeting claims.
- `api-gateway` sits in front of `/api/v1/admin/meetings/**` and currently
  accepts its established gateway-compatible audiences such as `frontend`,
  `account`, or `auth-service`.
- The accepted token preflight carried `aud=[audio-gateway-service,
  meeting-service]`, `tenantId=1`, `companyId=1`, `userId=990001`, and
  `MEETING_ADMIN`; it still did not prove the external meeting-admin path
  because the gateway-compatible audience leg was absent.

## Desired Token Contract

The `platform-desktop` access token used for the external recorder setup path
must carry all of the following:

| Field | Expected |
|---|---|
| `azp` | `platform-desktop` |
| `aud` required service audiences | `audio-gateway-service`, `meeting-service` |
| `aud` gateway-compatible audience | at least one of `frontend`, `account`, `auth-service` |
| identity claims | `tenantId`, `companyId`, `userId` |
| realm role | `MEETING_ADMIN` |
| token handling | token is written only to a local operator-only file; never pasted into issue, PR, shell history, or Mavis content |

The gateway-compatible audience should use the already accepted gateway
contract (`frontend` or `account`) rather than inventing a new `api-gateway`
audience unless the `api-gateway` runtime config is changed and verified in a
separate backend/GitOps change.

## Operator Steps

### 1. Preflight current token

Mint a short-lived `platform-desktop` token through the approved test-only
method and store it in an operator-only file:

```bash
umask 077
TOKEN_FILE=/tmp/faz24-platform-desktop-token.jwt
# Write token value into "$TOKEN_FILE" without echoing it to logs.
```

Run the local validator:

```bash
python3 scripts/keycloak/validate_faz24_platform_desktop_token_contract.py \
  --token-file "$TOKEN_FILE" \
  --expected-issuer "https://testai.acik.com/realms/platform-test"
```

Expected report shape:

```json
{
  "schemaVersion": "faz24.platformDesktopTokenContract.v1",
  "status": "pass",
  "tokenIncluded": false,
  "audience": {
    "gatewayCompatible": true,
    "gatewayMatches": ["frontend"]
  }
}
```

If the validator fails only because `gatewayCompatible=false`, continue with
Step 2. If `tenantId`, `companyId`, `userId`, `MEETING_ADMIN`, or the service
audiences are missing, fix those first; otherwise the token may pass the
gateway and then fail service authorization.

### 2. Converge `platform-desktop` client mappers

Use the approved Keycloak admin path for `platform-test`. Do not use the
operator's personal account as a smoke persona and do not leave direct access
grants enabled after a temporary smoke run.

The required mapper set is:

| Mapper | Type | Access token value |
|---|---|---|
| `audience-audio-gateway-service` | OIDC Audience mapper | `aud` includes `audio-gateway-service` |
| `audience-meeting-service` | OIDC Audience mapper | `aud` includes `meeting-service` |
| `audience-frontend` | OIDC Audience mapper | `aud` includes `frontend` for api-gateway compatibility |
| `tenantId` | User Attribute mapper | `tenantId=1` for the smoke persona |
| `companyId` | User Attribute mapper | `companyId=1` for the smoke persona |
| `userId` | User Attribute mapper | `userId=990001` or the approved smoke user id |
| realm role scope | realm role / client-scope mapping | `realm_access.roles` includes `MEETING_ADMIN` |

Example mapper payload for the `frontend` audience leg:

```json
{
  "name": "audience-frontend",
  "protocol": "openid-connect",
  "protocolMapper": "oidc-audience-mapper",
  "config": {
    "included.custom.audience": "frontend",
    "access.token.claim": "true",
    "id.token.claim": "false"
  }
}
```

Example mapper payload for a user-attribute claim:

```json
{
  "name": "companyId",
  "protocol": "openid-connect",
  "protocolMapper": "oidc-usermodel-attribute-mapper",
  "config": {
    "user.attribute": "companyId",
    "claim.name": "companyId",
    "jsonType.label": "String",
    "access.token.claim": "true",
    "id.token.claim": "false",
    "userinfo.token.claim": "true",
    "multivalued": "false",
    "aggregate.attrs": "false"
  }
}
```

### 3. Re-run token contract validation

Re-mint the token and re-run:

```bash
python3 scripts/keycloak/validate_faz24_platform_desktop_token_contract.py \
  --token-file "$TOKEN_FILE" \
  --expected-issuer "https://testai.acik.com/realms/platform-test" \
  > /tmp/faz24-platform-desktop-token-contract.json
```

Evidence attachment rule:

- Attach only `/tmp/faz24-platform-desktop-token-contract.json` after reviewing
  that `tokenIncluded=false`.
- Do not attach the JWT, raw Keycloak admin response, admin token, password,
  bearer token, cookie, or raw command transcript.

### 4. External meeting-admin + recorder lifecycle smoke

After the validator reports `status=pass`, prefer the bundled smoke runner so
the external meeting-admin path and the recorder lifecycle are captured in one
redacted evidence envelope:

```bash
python3 scripts/faz24/run_external_recorder_smoke.py \
  --token-file "$TOKEN_FILE" \
  --base-url "https://testai.acik.com" \
  --expected-issuer "https://testai.acik.com/realms/platform-test" \
  --output-file /tmp/faz24-external-recorder-smoke.json
```

Expected next evidence:

- `/tmp/faz24-external-recorder-smoke.json` has
  `schemaVersion=faz24.externalRecorderSmoke.v1`, `status=pass`, and
  `tokenIncluded=false`.
- `create_meeting` step returns HTTP `201` from the external `api-gateway`
  path and records the created meeting UUID.
- `record_consent`, `start_session`, `upload_chunk`, `finish_session`, and
  `session_status` all pass against the public `audio-gateway` path using the
  same meeting UUID.
- Same-session compute-plane audit smoke and direct-STT transcript remain
  separate gates; do not infer them from meeting creation alone.

Manual curl remains acceptable for diagnosis, but the output attached to #1615
should be the redacted runner JSON, not a raw shell transcript.

## Cleanup

```bash
AUTH_HEADER_FILE=${AUTH_HEADER_FILE:-/tmp/faz24-platform-desktop-auth-header.txt}
shred -u "$TOKEN_FILE" 2>/dev/null || rm -f "$TOKEN_FILE"
shred -u "$AUTH_HEADER_FILE" 2>/dev/null || rm -f "$AUTH_HEADER_FILE"
rm -f /tmp/faz24-platform-desktop-token-contract.json
rm -f /tmp/faz24-external-recorder-smoke.json
```

If direct access grants were temporarily enabled for smoke token minting,
restore `platform-desktop.directAccessGrantsEnabled=false` and verify it in
Keycloak before ending the operator window.

## References

- Issue: #1615
- OpenFGA selector acceptance: #1660
- Plan/current-state refresh: #1993
- Validator: `scripts/keycloak/validate_faz24_platform_desktop_token_contract.py`
- External recorder smoke runner:
  `scripts/faz24/run_external_recorder_smoke.py`
