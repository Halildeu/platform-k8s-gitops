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

## Metadata-Only Handoff Package

For an operator-facing command bundle, build the source-side handoff artifact:

```bash
gh workflow run faz24-external-recorder-operator-handoff.yml \
  --repo Halildeu/platform-k8s-gitops \
  --ref main \
  -f operator_batch_id=faz24-external-recorder-20260628 \
  -f gitops_ref=main \
  -f base_url=https://testai.acik.com \
  -f expected_issuer=https://testai.acik.com/realms/platform-test
```

The artifact contains `README.md`,
`faz24-external-recorder-operator-handoff.json`, and `SHA256SUMS`. It is a
coordination artifact only: it does not mint or read tokens, connect to
`testai.acik.com`, mutate Keycloak/Kubernetes/Vault, run the smoke, send audio,
or advance #1615. Use it to hand the exact token-contract -> external-smoke ->
verifier -> G-CAP aggregate command order to the operator without embedding
secrets or raw command transcripts.

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
- The runner output is metadata-only: it does not include the JWT, public
  `baseUrl`, raw audio, transcript text, raw command output, callback,
  destination, internal, webhook, STT, or transcribe URLs. Token-contract
  `issuer` is the only URL-shaped value allowed in the envelope.
- `create_meeting` step returns HTTP `201` from the external `api-gateway`
  path and records the created meeting UUID.
- `record_consent`, `start_session`, `upload_chunk`, `finish_session`, and
  `session_status` all pass against the public `audio-gateway` path using the
  same meeting UUID.
- `ids.sessionId` must be path-safe (`SES-` plus bounded alphanumeric,
  underscore, and dash only); path traversal or URL-shaped session IDs fail.
- Same-session compute-plane audit smoke and direct-STT transcript remain
  separate gates; do not infer them from meeting creation alone.

Manual curl remains acceptable for diagnosis, but the output attached to #1615
should be the redacted runner JSON, not a raw shell transcript.

### 5. Verify the redacted smoke evidence envelope

Before attaching the smoke output to #1615, run the verifier against the
redacted evidence envelope:

```bash
python3 scripts/faz24/verify_external_recorder_smoke_evidence.py \
  --evidence-file /tmp/faz24-external-recorder-smoke.json \
  --output-file /tmp/faz24-external-recorder-smoke.verify.json
```

Expected verifier evidence:

- `/tmp/faz24-external-recorder-smoke.verify.json` has
  `schemaVersion=faz24.externalRecorderSmokeVerifier.v1`, `status=pass`, and
  `tokenIncluded=false`.
- The verifier accepts only the exact token-contract, external meeting create,
  consent, start, chunk, finish and final status sequence.
- The verifier rejects direct-STT, direct client-to-STT, direct-STT transcript,
  compute-plane audit, desktop mic/loopback or production-readiness overclaims
  in the boundary fields.
- The verifier rejects JWT/Bearer/Authorization/private-key shaped values,
  camelCase sensitive-key variants such as `destinationUrl`, URL-like values
  outside the token-contract `issuer`, base64 audio data URIs, raw
  audio/transcript fields, raw request/response payloads, packet captures, and
  unsafe `sessionId` values before evidence is attached.

Attach both redacted JSON files after checking both have `tokenIncluded=false`.
Do not attach raw command transcripts.

### 6. Aggregate G-CAP capture gate

A single recorder smoke only proves one lifecycle attempt. For G-CAP, aggregate
multiple redacted verifier outputs and gate the capture path on attempt count,
distinct meeting/session coverage, success rate, retry rate, and failure rate.
Supported inputs are verifier summaries only:

- `faz24.externalRecorderSmokeVerifier.v1`
- `faz24.desktopCaptureEvidenceVerifier.v1`

External recorder summaries must be produced by the post-hardening verifier:
they must include `boundaries.directClientToStt=false`,
`boundaries.directSttTranscriptProven=false`, and passed
`boundary_directClientToStt` / `boundary_directSttTranscriptProven` checks.
Older external summaries that do not carry these fields are stale and must not
be used for aggregate G-CAP acceptance.

```bash
python3 scripts/faz24/verify_gcap_capture_gate_evidence.py \
  --evidence-file /tmp/faz24-external-recorder-smoke-01.verify.json \
  --evidence-file /tmp/faz24-external-recorder-smoke-02.verify.json \
  --evidence-file /tmp/faz24-external-recorder-smoke-03.verify.json \
  --evidence-file /tmp/faz24-desktop-capture-evidence-04.verify.json \
  --evidence-file /tmp/faz24-desktop-capture-evidence-05.verify.json \
  --min-attempts 5 \
  --min-distinct-meetings 5 \
  --min-distinct-sessions 5 \
  --min-success-rate 0.95 \
  --max-retry-rate 0.10 \
  --max-failure-rate 0.05 \
  --output-file /tmp/faz24-gcap-capture-gate.verify.json
```

Expected aggregate evidence:

- `/tmp/faz24-gcap-capture-gate.verify.json` has
  `schemaVersion=faz24.gcapCaptureGateVerifier.v1`, `tokenIncluded=false`,
  and `status=pass` only when all threshold checks pass.
- `status=blocked` means the evidence set is too small or coverage is
  insufficient for the configured G-CAP threshold.
- `status=fail` means the submitted verifier set has a privacy/schema/overclaim
  problem or enough evidence exists but success/retry/failure rates miss the
  configured threshold.
- `status=error` means the evidence files could not be loaded because of
  invalid JSON, wrong top-level shape/schema, or I/O failure.
- The aggregate verifier consumes only verifier summaries. It rejects raw
  recorder smoke envelopes, raw desktop capture envelopes, raw audio, transcript
  text, JWT/Bearer/Authorization-shaped values, stale external summaries
  without direct client-to-STT / direct-STT transcript boundary checks, and
  direct-STT/compute-plane/production overclaims.

Attach the aggregate JSON only after checking `tokenIncluded=false`. This G-CAP
aggregate does not prove direct-STT, same-session compute-plane audit, or
product-wide readiness. If desktop verifier summaries are included,
`desktopMicLoopbackProven=true` in the G-CAP output means only that submitted
desktop verifier summaries proved mic+loopback for their attempts.

### 7. Desktop mic + loopback evidence

The external recorder smoke proves the public gateway lifecycle from a
redacted client-token path. It still does not prove that the `platform-desktop`
app captured real microphone and system-loopback audio sources. For that gate,
collect a separate metadata-only desktop evidence envelope and run:

```bash
python3 scripts/faz24/verify_desktop_capture_evidence.py \
  /tmp/faz24-desktop-capture-evidence.json \
  --summary-json /tmp/faz24-desktop-capture-evidence.verify.json
```

The desktop verifier requires real-device `microphone` and `loopback` sources,
visible active indicator, consent capture, exact public `audio-gateway`
lifecycle ordering, and matching upload digests. It rejects raw audio, transcript
text, token material, destination URLs, direct client-to-STT, compute-plane,
direct-STT transcript, and production-readiness overclaims. See
`docs/runbooks/RB-faz24-desktop-capture-evidence.md`.

Use `/tmp/faz24-desktop-capture-evidence.verify.json` as a G-CAP aggregate input
only after confirming that verifier summary has `schemaVersion=
faz24.desktopCaptureEvidenceVerifier.v1`, `status=pass`, and
`tokenIncluded=false`.

## Cleanup

```bash
AUTH_HEADER_FILE=${AUTH_HEADER_FILE:-/tmp/faz24-platform-desktop-auth-header.txt}
shred -u "$TOKEN_FILE" 2>/dev/null || rm -f "$TOKEN_FILE"
shred -u "$AUTH_HEADER_FILE" 2>/dev/null || rm -f "$AUTH_HEADER_FILE"
rm -f /tmp/faz24-platform-desktop-token-contract.json
rm -f /tmp/faz24-external-recorder-smoke.json
rm -f /tmp/faz24-external-recorder-smoke.verify.json
rm -f /tmp/faz24-gcap-capture-gate.verify.json
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
- External recorder smoke verifier:
  `scripts/faz24/verify_external_recorder_smoke_evidence.py`
- G-CAP aggregate capture gate verifier:
  `scripts/faz24/verify_gcap_capture_gate_evidence.py`
