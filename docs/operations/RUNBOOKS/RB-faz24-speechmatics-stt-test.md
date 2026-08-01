# Faz 24 Speechmatics STT TEST activation

Issue: [platform-k8s-gitops#3240](https://github.com/Halildeu/platform-k8s-gitops/issues/3240)

## Boundary

This runbook activates Speechmatics only for synthetic Turkish audio in
`k3d-test/platform-test`. The existing `internal` provider remains the default
and rollback target. It does not authorize real meeting audio, production use,
PII transfer, DPA/subprocessor acceptance or cross-border transfer.

Never paste the API key into chat, GitHub, a file, a command argument, logs or
evidence. Evidence is limited to key presence, ESO condition, provider id,
immutable image digest and transcript metadata/content from the synthetic
fixture.

## 1. Seed the isolated Vault path

Run from this repository. The key is entered on the remote Vault host without
echo and is piped to Vault on stdin:

```bash
scripts/faz24/seed-speechmatics-test-secret.sh
```

This writes only `kv/platform/audio-gateway-speechmatics:api_key`. It must not
be added to `kv/platform/audio-gateway-service`, because a missing provider key
must not disturb Redis or the internal direct-STT mTLS secret.

## 2. Verify ESO without reading the value

After the ESO desired-state PR is merged and synced:

```bash
kubectl --context k3d-test -n platform-test get externalsecret audio-gateway-speechmatics \
  -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}{"\n"}'
kubectl --context k3d-test -n platform-test get secret audio-gateway-speechmatics \
  -o jsonpath='{.metadata.name}{" keys="}{range $k,$v := .data}{$k}{" "}{end}{"\n"}'
```

Required result: `Ready=True` and exactly the `api-key` key name. Do not decode
or print `.data.api-key`.

## 3. Activation commit

Activation is a separate GitOps commit after the backend image containing
`platform-backend#1046` is built and pinned by immutable digest. In that same
commit:

1. Add `netpol-audio-gateway-speechmatics.yaml` to the TEST overlay resources.
2. Patch `audio-gateway-config` with
   `AUDIO_GATEWAY_DIRECT_STT_SELECTABLE_PROVIDERS=internal,speechmatics`.
   Keep `AUDIO_GATEWAY_DIRECT_STT_PROVIDER=internal` and do not change the
   internal TLS or streaming settings. Speechmatics sessions use the bounded
   REST chunk path; the server rejects their internal WebSocket attempt.
3. Keep `AUDIO_GATEWAY_DIRECT_STT_SPEECHMATICS_ALLOW_INSECURE=false` and the endpoint
   `wss://eu2.rt.speechmatics.com/v2`.
4. Bump `audio-gateway.acik.com/direct-stt-enable-rev` so the pod re-reads both
   ConfigMap and Secret.

Widening the selectable set before key presence or image support is
deliberately invalid. The application must fail startup; it must never fall
back silently.

## 4. Synthetic acceptance

Use a generated or otherwise non-PII 16 kHz mono PCM16 Turkish fixture. Verify
all of the following on the exact rolled pod:

- desired and live image digest match;
- pod readiness is `True` and `audio_gateway_direct_stt_provider_active` has
  `provider="speechmatics"`;
- one canonical transcript result is written for the test session;
- the owner-scoped transcript events endpoint returns the expected synthetic
  sentence;
- no API key, Authorization header or raw audio appears in pod logs;
- decision/action consumers can read the same canonical transcript event.

This is not satisfied by DNS/TCP reachability, ESO `Ready`, a WebSocket 101,
CI, image build or deployment alone.

## 5. Rollback

In GitOps, restore
`AUDIO_GATEWAY_DIRECT_STT_SELECTABLE_PROVIDERS=internal`, remove the
Speechmatics egress policy from the TEST resources and bump the rollout
annotation. The internal default, TLS and streaming settings do not change in
this rollback. Re-read the live pod env with secret values excluded, verify the
internal mTLS target, and run the internal synthetic transcript smoke. Do not
delete or rotate the provider key as part of application rollback; key
lifecycle is a separate owner operation.
