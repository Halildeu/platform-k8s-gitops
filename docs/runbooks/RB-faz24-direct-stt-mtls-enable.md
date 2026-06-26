# RB Faz 24 Direct-STT mTLS Enablement

> Scope: test overlay `audio-gateway` -> Denetim `live-stt.denetim:8243` direct-STT path for `platform-ai#182/#198`.

## Current Safe State

- GitOps `audio-gateway` carries direct-STT configuration with `AUDIO_GATEWAY_DIRECT_STT_ENABLED=false`.
- The pod mounts `/etc/direct-stt-mtls` from `audio-gateway-secrets`, but missing direct-STT files do not change runtime behavior while the flag is false.
- NetworkPolicy `allow-audio-gateway-egress-live-stt-mtls` allows only `audio-gateway` -> `10.99.0.2/32` TCP/8243.
- The pod maps `live-stt.denetim` to `10.99.0.2` with `hostAliases` so HTTPS SNI/Host remains the certificate/Caddy hostname while routing over WireGuard.

## Kubernetes Context Guard

All live Kubernetes reads or mutations in this runbook target the test cluster
only. Do not rely on the shell's default `kubectl` context; on `staging-sw` it
can point at `k3d-prod`.

Use an explicit context wrapper before collecting evidence or applying the
test overlay:

```bash
export KUBECTL_CONTEXT=k3d-test
export KUBECTL_NAMESPACE=platform-test
kubectl --context "${KUBECTL_CONTEXT}" config current-context
kubectl --context "${KUBECTL_CONTEXT}" get ns "${KUBECTL_NAMESPACE}"

k() {
  kubectl --context "${KUBECTL_CONTEXT}" -n "${KUBECTL_NAMESPACE}" "$@"
}
```

The Gate 1 and Gate 2 evidence JSON must include:

```json
{
  "environment": {
    "cluster": "k3d-test",
    "kubectlContext": "k3d-test",
    "namespace": "platform-test"
  }
}
```

Both direct-STT verifiers fail closed when `environment.kubectlContext` is not
`k3d-test`.

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

## Evidence Contract

There are two evidence gates.

### Gate 1 — mTLS enablement preflight, before the flag flip

After Vault seed + ESO mapping, but before `AUDIO_GATEWAY_DIRECT_STT_ENABLED`
is changed, build metadata-only JSON using schema
`faz24.directSttMtlsEnablementPreflight.v1` and run:

```bash
python3 scripts/faz24/verify_direct_stt_mtls_enablement_preflight.py \
  docs/faz-24-evidence/<date>-direct-stt-mtls-preflight.json \
  --summary-json /tmp/faz24-direct-stt-mtls-preflight.verify.json
```

The preflight verifier requires:

- real `audio-gateway` pod evidence from `k3d-test/platform-test`;
- evidence collected with explicit `kubectl --context k3d-test`, recorded as
  `environment.kubectlContext="k3d-test"`;
- `AUDIO_GATEWAY_DIRECT_STT_ENABLED=false` still in desired/runtime state;
- hostAlias `live-stt.denetim -> 10.99.0.2`, narrow NetworkPolicy
  `10.99.0.2/32:8243`, and `/etc/direct-stt-mtls` mount present;
- `ExternalSecret/audio-gateway-secrets` Ready with mappings from
  `direct_stt_ca_crt`, `direct_stt_client_crt`, and `direct_stt_client_key`
  to the file-like Secret keys;
- runtime Secret key names include `direct-stt-ca.crt`,
  `direct-stt-client.crt`, and `direct-stt-client.key`, with no values
  captured;
- `https://live-stt.denetim:8243/health` HTTP 200 from the real pod using the
  mounted client certificate material;
- explicit boundary flags showing no audio was sent, `/transcribe` was not
  called, #182 direct audio e2e is not yet proven, #198 full I7 remains
  separate, desktop mic/loopback is separate, and production readiness is not
  claimed.

The verifier rejects PEM values, token-like material, raw command output,
destination URLs, raw audio, transcript text, and packet captures.

To archive the same preflight evidence through CI:

```bash
DIRECT_STT_MTLS_PREFLIGHT_B64="$(
  base64 < docs/faz-24-evidence/<date>-direct-stt-mtls-preflight.json | tr -d '\n'
)"
gh workflow run faz24-direct-stt-mtls-preflight-ingest.yml \
  -f evidence_json_base64="${DIRECT_STT_MTLS_PREFLIGHT_B64}"
```

### Gate 2 — direct-STT e2e, after the flag flip

After the flag flip, #182 evidence is accepted only as metadata-only JSON using
schema `faz24.directSttE2eEvidence.v1` and passing:

```bash
python3 scripts/faz24/verify_direct_stt_e2e_evidence.py \
  docs/faz-24-evidence/<date>-direct-stt-e2e.json \
  --summary-json /tmp/faz24-direct-stt-e2e.verify.json
```

The verifier requires:

- real `audio-gateway` pod evidence from `k3d-test/platform-test`;
- evidence collected with explicit `kubectl --context k3d-test`, recorded as
  `environment.kubectlContext="k3d-test"`;
- `AUDIO_GATEWAY_DIRECT_STT_ENABLED=true`;
- `live-stt.denetim:8243` mTLS health HTTP 200 from the real pod with mounted
  client certificate material;
- same session/chunk/correlation for lifecycle HTTP statuses,
  `/transcribe` HTTP 200, `transcript:direct-stt-results`, and
  `CHUNK_FORWARDED_TO_COMPUTE_PLANE`;
- Redis/audio persistence boundary flags proving metadata-only chunk state and
  no raw audio/transcript in Redis, result stream, logs, or the evidence file;
- explicit boundary flags showing #198 full I7, desktop mic/loopback, and
  production readiness are still separate gates.

The verifier rejects PEM values, tokens, raw command output, destination URLs,
raw audio, raw transcript text, transcript segments, and raw packet captures.
Only key names, hashes, IDs, HTTP statuses, and bounded timing metadata belong
in the JSON. The verifier intentionally rejects evidence unless it still shows
`live-stt.denetim -> 10.99.0.2`; if the Denetim WireGuard address changes,
update the hostAlias, NetworkPolicy destination, and verifier expected IP in
the same PR. To archive the same evidence through CI:

```bash
DIRECT_STT_EVIDENCE_B64="$(
  base64 < docs/faz-24-evidence/<date>-direct-stt-e2e.json | tr -d '\n'
)"
gh workflow run faz24-direct-stt-e2e-evidence-ingest.yml \
  -f evidence_json_base64="${DIRECT_STT_EVIDENCE_B64}"
```

## Enablement Order

1. Seed the three Vault properties with stdin-pipe or an approved equivalent. Do not print PEM values.
2. Update `kustomize/overlays/test/eso/audio-gateway/externalsecret.yaml` to map the three properties above into `audio-gateway-secrets`.
3. Verify `ExternalSecret/audio-gateway-secrets` is `Ready=True` and the
   target Secret exposes the three file-like keys by key name only, using
   `kubectl --context k3d-test -n platform-test`.
4. Write the metadata-only mTLS enablement preflight JSON and run
   `verify_direct_stt_mtls_enablement_preflight.py`. Do not continue to the
   flag flip unless it reports PASS.
5. Flip `AUDIO_GATEWAY_DIRECT_STT_ENABLED` to `"true"` in `kustomize/base/apps/audio-gateway/configmap.yaml`.
6. Deploy/sync the test overlay and verify the `audio-gateway` pod image digest is unchanged unless a newer backend artifact is intentionally pinned.
7. From the real `audio-gateway` pod, verify `live-stt.denetim` resolves to `10.99.0.2` and `https://live-stt.denetim:8243/health` reaches Caddy/live-stt with the mounted client certificate.
8. Run the #182 smoke: start meeting/capture/session, upload a privacy-safe WAV chunk, finish session, then prove:
   - HTTP lifecycle returns expected `201/200` statuses.
   - `CHUNK_FORWARDED_TO_COMPUTE_PLANE` exists in `audit:events` for the same session/chunk/correlation.
   - `transcript:direct-stt-results` contains the same session/chunk/correlation.
   - Redis `audio:chunks:pNN` carries metadata only, not raw audio.
9. Write the metadata-only JSON evidence and run the e2e verifier above locally and,
   when reviewer handoff is needed, through the GitHub workflow ingest.

## Rollback

- First rollback: set `AUDIO_GATEWAY_DIRECT_STT_ENABLED=false` and redeploy.
- If Secret material is suspected compromised, remove or rotate only the three direct-STT Vault properties; keep `redis_password` intact.
- Keep #182/#198 open unless `/transcribe` result-stream evidence is present and reviewed.
