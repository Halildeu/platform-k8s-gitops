# RB Faz 24 Direct-STT mTLS Enablement

> Scope: test overlay `audio-gateway` -> Denetim `live-stt.denetim:8243` direct-STT path for `platform-ai#182/#198`.

## Current Safe State

- GitOps `audio-gateway` carries direct-STT configuration with `AUDIO_GATEWAY_DIRECT_STT_ENABLED=false`.
- The pod mounts `/etc/direct-stt-mtls` from `audio-gateway-secrets`, but missing direct-STT files do not change runtime behavior while the flag is false.
- NetworkPolicy `allow-audio-gateway-egress-live-stt-mtls` allows only `audio-gateway` -> `10.99.0.2/32` TCP/8243.
- The pod maps `live-stt.denetim` to `10.99.0.2` with `hostAliases` so HTTPS SNI/Host remains the certificate/Caddy hostname while routing over WireGuard.

## Secret Contract

Vault path: `kv/platform/audio-gateway-service`

Required properties before flipping direct-STT on:

| Vault property | K8s Secret key | Mounted file |
|---|---|---|
| `direct_stt_ca_crt` | `direct-stt-ca.crt` | `/etc/direct-stt-mtls/direct-stt-ca.crt` |
| `direct_stt_client_crt` | `direct-stt-client.crt` | `/etc/direct-stt-mtls/direct-stt-client.crt` |
| `direct_stt_client_key` | `direct-stt-client.key` | `/etc/direct-stt-mtls/direct-stt-client.key` |

Use file-like Secret keys intentionally. The deployment also uses `envFrom` for
`audio-gateway-secrets`; file-like keys are not valid environment variable
names, so Kubernetes skips exporting PEM material as env vars while the Secret
volume still exposes them as files.

## Enablement Order

1. Seed the three Vault properties with stdin-pipe or an approved equivalent. Do not print PEM values.
2. Update `kustomize/overlays/test/eso/audio-gateway/externalsecret.yaml` to map the three properties above into `audio-gateway-secrets`.
3. Verify `ExternalSecret/audio-gateway-secrets` is `Ready=True` and the target Secret exposes the three file-like keys by key name only.
4. Flip `AUDIO_GATEWAY_DIRECT_STT_ENABLED` to `"true"` in `kustomize/base/apps/audio-gateway/configmap.yaml`.
5. Deploy/sync the test overlay and verify the `audio-gateway` pod image digest is unchanged unless a newer backend artifact is intentionally pinned.
6. From the real `audio-gateway` pod, verify `live-stt.denetim` resolves to `10.99.0.2` and `https://live-stt.denetim:8243/health` reaches Caddy/live-stt with the mounted client certificate.
7. Run the #182 smoke: start meeting/capture/session, upload a privacy-safe WAV chunk, finish session, then prove:
   - HTTP lifecycle returns expected `201/200` statuses.
   - `CHUNK_FORWARDED_TO_COMPUTE_PLANE` exists in `audit:events` for the same session/chunk/correlation.
   - `transcript:direct-stt-results` contains the same session/chunk/correlation.
   - Redis `audio:chunks:pNN` carries metadata only, not raw audio.

## Rollback

- First rollback: set `AUDIO_GATEWAY_DIRECT_STT_ENABLED=false` and redeploy.
- If Secret material is suspected compromised, remove or rotate only the three direct-STT Vault properties; keep `redis_password` intact.
- Keep #182/#198 open unless `/transcribe` result-stream evidence is present and reviewed.
