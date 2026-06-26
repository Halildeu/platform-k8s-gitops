# RB — Faz 24 audio-gateway JWT audience/capability enforcement

> **Status**: ACTIVE — test desired-state enforce flip is GitOps-authoritative;
> live acceptance still requires rollout evidence and verifier PASS.
>
> **Scope**: `platform-backend#716`, `audio-gateway-service`,
> `platform-test` realm, testai `k3d-test`.
>
> **Boundary**: This runbook does not mint or expose tokens, does not mutate
> Keycloak by itself, does not enable direct-STT, does not send raw audio, and
> does not make production ready. It describes the only accepted path for
> turning the already-merged backend validator from default-off to fail-closed
> runtime enforcement.

## 1. Context

`audio-gateway-service` runs in a shared Keycloak realm. Before
`platform-backend#719/#720`, any valid realm token could pass issuer/signature
validation unless meeting/session business policy rejected later. That is not
enough for real meeting audio.

The durable contract is two-layer:

1. JWT `aud` must include `audio-gateway-service`.
2. JWT `resource_access.audio-gateway-service.roles` must include
   `audio_record`.

Meeting/session/consent authorization remains separate and does not replace the
audience/capability gate.

## 2. Desired-State Contract

The pre-flip baseline carried backend validator flags explicitly as
default-off:

```yaml
AUDIO_GATEWAY_SECURITY_RESOURCE_CLIENT_ID: "audio-gateway-service"
AUDIO_GATEWAY_SECURITY_ENFORCE_AUDIENCE: "false"
AUDIO_GATEWAY_SECURITY_REQUIRE_AUDIO_RECORD_ROLE: "false"
```

The test desired-state enforce flip changes both booleans to `"true"` through
the `kustomize/overlays/test/kustomization.yaml` patch. The base ConfigMap
remains default-off so a later prod overlay inclusion requires its own D30
review and prod-specific preconditions.

Live acceptance is not automatic at merge time. It still requires rollout
evidence plus the fail-closed matrix in this runbook. Because these properties
are consumed through `envFrom`, ConfigMap truth is not enough: the running pod
process environment must also show the new values after a pod-template rollout.

## 3. Preconditions

Do not flip enforcement until all are true:

- `platform-backend#719` validator code is in the live `audio-gateway` image.
- `platform-backend#720` fail-closed source tests are in the live image lineage.
- Keycloak `platform-test` has resource client `audio-gateway-service` and role
  `audio_record`.
- Legit recorder clients carry both audience and role in new-login and
  refresh-grant tokens. For current Faz 24 scope this is `platform-desktop`;
  do not add the mapper to generic browser SSO clients.
- Existing access-token max lifespan has drained, or a bounded maintenance
  window accepts that older in-flight tokens may receive `401/403`.
- `AUDIO_GATEWAY_JWT_JWKS_URI` points to the internal Keycloak service
  (`http://keycloak:8080/.../certs`), while issuer remains the public edge
  issuer (`https://testai.acik.com/...`).

## 4. Enforce Flip

Change the GitOps desired-state booleans:

```yaml
AUDIO_GATEWAY_SECURITY_ENFORCE_AUDIENCE: "true"
AUDIO_GATEWAY_SECURITY_REQUIRE_AUDIO_RECORD_ROLE: "true"
```

For test, the accepted location is the `kustomize/overlays/test` patch, not the
base ConfigMap. Deploy through the normal `platform-k8s-gitops` PR + testai
deploy path. Do not apply an out-of-band `kubectl patch` to the shared
`k3d-test` workload; ADR-0023 keeps test overlay authoritative.

The test overlay must also bump the `audio-gateway` Deployment pod-template
annotation `audio-gateway.acik.com/authz-enforce-rev` whenever this env flip
changes. A ConfigMap-only patch can sync successfully while the old pod keeps
stale environment values. After merge, confirm the live ConfigMap and the
running pod environment both render both booleans as `"true"` before collecting
the matrix below.

```bash
kubectl --context k3d-test -n platform-test get cm audio-gateway-config -o json \
  | jq -r '.data | {enforce:.AUDIO_GATEWAY_SECURITY_ENFORCE_AUDIENCE,role:.AUDIO_GATEWAY_SECURITY_REQUIRE_AUDIO_RECORD_ROLE}'

POD="$(kubectl --context k3d-test -n platform-test get pod \
  -l app.kubernetes.io/name=audio-gateway \
  -o jsonpath='{.items[0].metadata.name}')"
kubectl --context k3d-test -n platform-test exec "$POD" -- sh -c \
  'printf "ENFORCE=%s\nROLE=%s\n" "$AUDIO_GATEWAY_SECURITY_ENFORCE_AUDIENCE" "$AUDIO_GATEWAY_SECURITY_REQUIRE_AUDIO_RECORD_ROLE"'
```

## 5. Required Fail-Closed Live Smoke

Use a non-sensitive endpoint under `/api/v1/audio-gateway/**`; a synthetic
nonexistent session status path is acceptable because a valid recorder token
should pass security and then return business `404`.

Required matrix:

| Check | Token class | Expected |
|---|---|---|
| `no_token` | no Authorization header | `401` |
| `wrong_audience` | valid realm token without `aud=audio-gateway-service` | `401` |
| `missing_audio_record_role` | correct audience, missing `audio_record` | `403` |
| `valid_recorder` | correct audience + `audio_record` | `2xx`, `204`, or `404 session-not-found` |

Do not paste JWTs, raw Keycloak responses, cookies, bearer headers, or shell
transcripts into GitHub. The only attachable artifact is the redacted evidence
JSON plus verifier JSON.

## 6. Evidence Envelope

Create `/tmp/faz24-audio-gateway-authz-enforce.json` with this shape. Values
shown are examples; never include raw token material.

```json
{
  "schemaVersion": "faz24.audioGatewayAuthzEnforceEvidence.v1",
  "status": "pass",
  "tokenIncluded": false,
  "environment": {
    "baseUrl": "https://testai.acik.com",
    "namespace": "platform-test",
    "resourceClientId": "audio-gateway-service",
    "enforceAudience": true,
    "requireAudioRecordRole": true,
    "jwksInternal": true
  },
  "recorderToken": {
    "tokenIncluded": false,
    "audiencePresent": true,
    "audioRecordRolePresent": true,
    "newLoginVerified": true,
    "refreshGrantVerified": true
  },
  "boundaries": {
    "testClusterOnly": true,
    "directSttProven": false,
    "rawAudioSent": false,
    "computePlaneAuditProven": false,
    "desktopMicLoopbackProven": false,
    "productionReady": false
  },
  "failures": [],
  "checks": [
    {
      "name": "no_token",
      "method": "GET",
      "path": "/api/v1/audio-gateway/sessions/SES-negative/status",
      "statusCode": 401,
      "ok": true,
      "tokenIncluded": false
    },
    {
      "name": "wrong_audience",
      "method": "GET",
      "path": "/api/v1/audio-gateway/sessions/SES-negative/status",
      "statusCode": 401,
      "ok": true,
      "tokenIncluded": false
    },
    {
      "name": "missing_audio_record_role",
      "method": "GET",
      "path": "/api/v1/audio-gateway/sessions/SES-negative/status",
      "statusCode": 403,
      "ok": true,
      "tokenIncluded": false
    },
    {
      "name": "valid_recorder",
      "method": "GET",
      "path": "/api/v1/audio-gateway/sessions/SES-nonexistent/status",
      "statusCode": 404,
      "ok": true,
      "tokenIncluded": false,
      "securityPassed": true,
      "businessStatus": "session-not-found"
    }
  ]
}
```

Run the verifier before attachment:

```bash
python3 scripts/faz24/verify_audio_gateway_authz_enforce_evidence.py \
  --evidence-file /tmp/faz24-audio-gateway-authz-enforce.json \
  --output-file /tmp/faz24-audio-gateway-authz-enforce.verify.json
```

Acceptance evidence requires:

- verifier `schemaVersion=faz24.audioGatewayAuthzEnforceVerifier.v1`;
- verifier `status=pass`;
- `tokenIncluded=false`;
- no raw token/audio/transcript/private-material findings.

Attach only the redacted evidence JSON and verifier JSON.

## 7. Rollback

Rollback is GitOps-authoritative:

```yaml
AUDIO_GATEWAY_SECURITY_ENFORCE_AUDIENCE: "false"
AUDIO_GATEWAY_SECURITY_REQUIRE_AUDIO_RECORD_ROLE: "false"
```

After rollback deploy, `audio-gateway` returns to authenticated-only behavior
for non-public endpoints. Keep the token mapper and resource client in Keycloak;
they are harmless and required for the next enforce attempt.

## 8. What This Does Not Prove

A passing #716 verifier proves only audio-gateway JWT audience/capability
fail-closed behavior on testai. It does not prove:

- object-level `meeting#can_record` authorization matrix;
- direct-STT `/transcribe` e2e;
- `CHUNK_FORWARDED_TO_COMPUTE_PLANE` same-session audit;
- desktop mic/loopback capture;
- G-CAP/G-OPS/G-COMP product gates;
- production readiness.
