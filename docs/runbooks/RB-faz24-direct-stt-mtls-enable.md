# RB Faz 24 Direct-STT mTLS Enablement

> Scope: test overlay `audio-gateway` -> Denetim `live-stt.denetim:8243` direct-STT path for `platform-ai#182/#198`.

## Current Test State

- GitOps `audio-gateway` now carries
  `AUDIO_GATEWAY_DIRECT_STT_ENABLED=true` for the test path after
  platform-k8s-gitops #2170 (`5fb581052354c8874c575573d755a0bf47ba923f`).
  Production still excludes `audio-gateway` until its own D30 cutover decision.
- The pod mounts `/etc/direct-stt-mtls` from dedicated
  `audio-gateway-direct-stt-mtls`; the latest post-#2170 metadata refresh saw
  `ExternalSecret` Ready, runtime Secret keys present, and pod-local mTLS
  `/health` returning HTTP 200 with the mounted client certificate.
- NetworkPolicy `allow-audio-gateway-egress-live-stt-mtls` allows only `audio-gateway` -> `10.99.0.2/32` TCP/8243.
- The pod maps `live-stt.denetim` to `10.99.0.2` with `hostAliases` so HTTPS SNI/Host remains the certificate/Caddy hostname while routing over WireGuard.
- Gate 1 preflight is a pre-flag verifier and expects
  `AUDIO_GATEWAY_DIRECT_STT_ENABLED=false`. After #2170 it must not be used as
  the active acceptance gate. Current #182 acceptance is Gate 2: real recorder
  lifecycle -> direct-STT `/transcribe` -> `transcript:direct-stt-results` ->
  same-session compute-plane audit -> no raw audio/transcript in evidence/logs.

## Kubernetes Context Guard

All live Kubernetes reads or mutations in this runbook target the test cluster
only. Do not rely on the shell's default `kubectl` context; on `staging-sw` it
can point at `k3d-prod`.

Use an explicit context wrapper before collecting evidence or applying the
test overlay:

```bash
export KUBECTL_CONTEXT=k3d-test
export KUBECTL_NAMESPACE=platform-test
kubectl config get-contexts "${KUBECTL_CONTEXT}" -o name
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
    "namespace": "platform-test",
    "contextAvailable": true,
    "namespaceReachable": true,
    "contextFailure": ""
  }
}
```

Both direct-STT verifiers fail closed when `environment.kubectlContext` is not
`k3d-test`. The preflight collector also fails before runtime object reads when
the local executor lacks the `k3d-test` context or cannot reach
`platform-test`; that failure is execution-environment evidence only and must
not be used as runtime object drift proof.

## Secret Contract

Vault path: `kv/platform/audio-gateway-service`

Runtime Secret split:

- `audio-gateway-secrets` remains the aggregate envFrom Secret for
  `SPRING_DATA_REDIS_PASSWORD` only.
- `audio-gateway-direct-stt-mtls` carries only direct-STT certificate/key
  files. Do not add these properties to `audio-gateway-secrets`; one missing
  ESO property in an aggregate ExternalSecret would risk `SecretSyncedError`
  for the Redis password path.
- Before the three Vault properties are seeded, the dedicated
  `ExternalSecret/audio-gateway-direct-stt-mtls` may report `SecretSyncedError`
  / `Ready=False`. Treat that as expected fail-closed noise: it is not preflight
  PASS evidence, but it must not disturb the Redis aggregate.

Required properties before flipping direct-STT on:

| Vault property | K8s Secret key | Mounted file |
|---|---|---|
| `direct_stt_ca_crt` | `direct-stt-ca.crt` | `/etc/direct-stt-mtls/direct-stt-ca.crt` |
| `direct_stt_client_crt` | `direct-stt-client.crt` | `/etc/direct-stt-mtls/direct-stt-client.crt` |
| `direct_stt_client_key` | `direct-stt-client.key` | `/etc/direct-stt-mtls/direct-stt-client.key` |

Use file-like Secret keys intentionally. The deployment does not reference the
dedicated mTLS Secret via `envFrom`; it is mounted read-only as files only.

### Operator-safe Vault seed helper

When the approved mTLS files are available on the operator machine, prefer the
repo helper below instead of ad hoc `vault kv patch key="$(cat file)"` commands.
The helper keeps raw PEM values and the Vault token out of shell arguments,
stdout, issue comments, artifacts, and evidence files. It emits only redacted
presence/status evidence.

Prerequisites:

- the Vault token is stored in an operator-only file, for example
  `/secure/operator-vault.token`;
- the three approved PEM files are stored in operator-only files;
- all four files are `chmod 600`;
- the operator substitutes the `/secure/...` placeholders locally and does not
  paste PEM/token values into the terminal transcript or GitHub.

Validate file formats and produce dry-run redacted evidence first:

```bash
python3 scripts/faz24/direct_stt_mtls_seed_operator.py \
  --vault-addr https://vault.testai.acik.com \
  --vault-path kv/platform/audio-gateway-service \
  --vault-token-file /secure/operator-vault.token \
  --ca-crt-file /secure/direct-stt-ca.crt \
  --client-crt-file /secure/direct-stt-client.crt \
  --client-key-file /secure/direct-stt-client.key \
  --evidence-out docs/faz-24-evidence/direct-stt-mtls-seed-evidence.json
```

Apply the Vault KV v2 merge patch only after the dry-run evidence is redacted:

```bash
python3 scripts/faz24/direct_stt_mtls_seed_operator.py \
  --vault-addr https://vault.testai.acik.com \
  --vault-path kv/platform/audio-gateway-service \
  --vault-token-file /secure/operator-vault.token \
  --ca-crt-file /secure/direct-stt-ca.crt \
  --client-crt-file /secure/direct-stt-client.crt \
  --client-key-file /secure/direct-stt-client.key \
  --evidence-out docs/faz-24-evidence/direct-stt-mtls-seed-evidence.json \
  --apply
```

Verify the applied seed evidence locally:

```bash
python3 scripts/faz24/verify_direct_stt_mtls_seed_operator_evidence.py \
  docs/faz-24-evidence/direct-stt-mtls-seed-evidence.json \
  --summary-json /tmp/faz24-direct-stt-mtls-seed.verify.json
```

Archive the redacted seed evidence through CI:

```bash
DIRECT_STT_MTLS_SEED_B64="$(
  base64 < docs/faz-24-evidence/direct-stt-mtls-seed-evidence.json | tr -d '\n'
)"
gh workflow run faz24-direct-stt-mtls-seed-evidence-ingest.yml \
  --repo Halildeu/platform-k8s-gitops \
  --ref main \
  -f evidence_json_base64="${DIRECT_STT_MTLS_SEED_B64}"
```

Accepted seed evidence is still not Direct-STT acceptance. It proves only that
the seed helper applied the bounded Vault merge patch and wrote safe redacted
evidence. After the apply, force or wait for ESO reconciliation and run Gate 1
preflight. Gate 1 is the first accepted proof that
`ExternalSecret/audio-gateway-direct-stt-mtls` is Ready, the runtime Secret
exposes the three expected key names, and the real `audio-gateway` pod can use
the mounted client certificate.

## Evidence Contract

There are three evidence gates: Gate 0 seed-helper evidence, Gate 1 preflight
evidence, and Gate 2 e2e evidence.

### Operator handoff package

When the runtime executor and credential seed authority are ready, generate a
metadata-only handoff package before any live mutation:

```bash
gh workflow run faz24-direct-stt-operator-handoff.yml \
  --repo Halildeu/platform-k8s-gitops \
  --ref main \
  -f operator_batch_id=faz24-direct-stt-20260628 \
  -f gitops_ref=main \
  -f kube_context=k3d-test \
  -f namespace=platform-test \
  -f preflight_evidence_path=docs/faz-24-evidence/direct-stt-mtls-preflight.json \
  -f e2e_evidence_path=docs/faz-24-evidence/direct-stt-e2e.json
```

Download the artifact `faz24-direct-stt-operator-handoff-<run_id>` and verify:

```bash
sha256sum --check SHA256SUMS
```

The package contains only `README.md`,
`faz24-direct-stt-operator-handoff.json`, and `SHA256SUMS`. It is coordination
material for Gate 0 -> Gate 1 -> flag flip -> Gate 2; it is not evidence by
itself. It must not contain Vault values, PEM data, bearer/JWT material, raw
command output, raw audio, transcript text, packet captures, or destination URL
payloads.

### Gate 1 — mTLS enablement preflight, before the flag flip

After Vault seed + ESO mapping, but before `AUDIO_GATEWAY_DIRECT_STT_ENABLED`
is changed, build metadata-only JSON using schema
`faz24.directSttMtlsEnablementPreflight.v1` and run:

```bash
python3 scripts/faz24/collect_direct_stt_mtls_enablement_preflight.py \
  --context k3d-test \
  --namespace platform-test \
  --output docs/faz-24-evidence/<date>-direct-stt-mtls-preflight.json

python3 scripts/faz24/verify_direct_stt_mtls_enablement_preflight.py \
  docs/faz-24-evidence/<date>-direct-stt-mtls-preflight.json \
  --summary-json /tmp/faz24-direct-stt-mtls-preflight.verify.json
```

If the evidence should be collected by the canonical self-hosted test runner
instead of an interactive shell on `staging-sw`, dispatch the collector
workflow. It runs the same collector/verifier on the `staging-sw` runner,
uploads the metadata-only JSON + verifier summary, and stays red when the
preflight is not accepted:

```bash
gh workflow run faz24-direct-stt-mtls-preflight-collect.yml \
  --repo Halildeu/platform-k8s-gitops \
  --ref main \
  -f kube_context=k3d-test \
  -f namespace=platform-test \
  -f deployment=audio-gateway \
  -f probe_timeout=40
```

The artifact name is
`faz24-direct-stt-mtls-preflight-collect-<run_id>`. A red workflow can still be
useful fail-closed blocker evidence, but it is not acceptance. Gate 1 is
accepted only when the verifier exit code is `0` and the artifact leak guard
passes.

The collector fails closed if the Secret key names are absent, the real pod
cannot use the mounted cert material, or any expected GitOps/runtime shape is
missing. It writes only key names, bounded HTTP status/timing metadata, and
boolean boundary flags; it does not write PEM values, token material, raw
command output, raw audio, transcript text, or destination URLs.

The preflight verifier requires:

- real `audio-gateway` pod evidence from `k3d-test/platform-test`;
- evidence collected with explicit `kubectl --context k3d-test`, recorded as
  `environment.kubectlContext="k3d-test"`;
- `environment.contextAvailable=true`, `environment.namespaceReachable=true`,
  and `environment.contextFailure=""`;
- `AUDIO_GATEWAY_DIRECT_STT_ENABLED=false` still in desired/runtime state;
- hostAlias `live-stt.denetim -> 10.99.0.2`, narrow NetworkPolicy
  `10.99.0.2/32:8243`, and `/etc/direct-stt-mtls` mount present;
- `ExternalSecret/audio-gateway-direct-stt-mtls` Ready with mappings from
  `direct_stt_ca_crt`, `direct_stt_client_crt`, and `direct_stt_client_key`
  to the file-like Secret keys;
- redacted `ExternalSecret` condition diagnostics for the dedicated mTLS
  object. The collector records only bounded condition metadata such as
  `type`, `status`, `reason`, `lastTransitionTime`, and whether a message was
  present. Raw condition messages are not written to evidence; use the reason
  and failure codes to route follow-up without leaking Vault/ESO provider
  detail or secret-shaped text;
- runtime `Secret/audio-gateway-direct-stt-mtls` key names include `direct-stt-ca.crt`,
  `direct-stt-client.crt`, and `direct-stt-client.key`, with no values
  captured;
- `audio-gateway-direct-stt-mtls` is not referenced by `envFrom`;
- `https://live-stt.denetim:8243/health` HTTP 200 from the real pod using the
  mounted client certificate material;
- explicit boundary flags showing no audio was sent, `/transcribe` was not
  called, #182 direct audio e2e is not yet proven, #198 full I7 remains
  separate, desktop mic/loopback is separate, and production readiness is not
  claimed.

The verifier rejects PEM values, token-like material, raw command output,
destination URLs, URL-like values, camelCase sensitive-key variants such as
`destinationUrl`, raw audio, base64 audio data URIs, transcript text, and
packet captures.

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
gh workflow run faz24-direct-stt-e2e-collect.yml \
  --repo Halildeu/platform-k8s-gitops \
  --ref main \
  -f base_url=https://testai.acik.com \
  -f expected_issuer=https://testai.acik.com/realms/platform-test \
  -f keycloak_base_url=http://127.0.0.1:8082 \
  -f kube_context=k3d-test \
  -f namespace=platform-test \
  -f deployment=audio-gateway \
  -f redis_container=platform-redis-streams-test \
  -f chunk_file=/tmp/sample-tr-cv17-001.wav \
  -f audio_format=WAV \
  -f sample_rate_hz=48000 \
  -f channels=1 \
  -f probe_timeout=40
```

The collector workflow mints a short-lived `platform-desktop` test token,
uses a runner-local privacy-safe WAV fixture for the recorder lifecycle, then
collects only metadata from Kubernetes, Redis Streams, and bounded pod logs.
The uploaded artifact must not contain bearer/JWT material, PEM/certificate
values, raw audio, raw transcript text, destination URLs, or raw command
output. A red workflow is blocker evidence; accepted Gate 2 requires the
collector and verifier exit codes to be `0`.

For manual/local verification of an already produced JSON:

```bash
python3 scripts/faz24/verify_direct_stt_e2e_evidence.py \
  docs/faz-24-evidence/<date>-direct-stt-e2e.json \
  --summary-json /tmp/faz24-direct-stt-e2e.verify.json
```

The verifier requires:

- real Ready `audio-gateway` pod evidence from `k3d-test/platform-test`;
- evidence collected with explicit `kubectl --context k3d-test`, recorded as
  `environment.kubectlContext="k3d-test"`;
- top-level `tokenIncluded=false`; do not attach access tokens or token-shaped
  data to the evidence;
- `AUDIO_GATEWAY_DIRECT_STT_ENABLED=true`;
- `live-stt.denetim:8243` mTLS health HTTP 200 from the real pod with explicit
  `mtlsProbe.host="live-stt.denetim"` and `mtlsProbe.port=8243`, using the
  mounted client certificate material;
- same session/chunk/correlation for lifecycle HTTP statuses,
  `/transcribe` HTTP 200, `transcript:direct-stt-results`, and
  `CHUNK_FORWARDED_TO_COMPUTE_PLANE`;
- Redis/audio persistence boundary flags proving metadata-only chunk state and
  no raw audio/transcript in Redis, result stream, logs, or the evidence file;
- explicit boundary flags showing direct client-to-STT is false, and #198 full
  I7, desktop mic/loopback, and production readiness are still separate gates.

The verifier rejects PEM values, tokens, raw command output, destination URLs,
URL-like values, camelCase sensitive-key variants such as `transcriptText` or
`destinationUrl`, raw audio, base64 audio data URIs, raw transcript text,
transcript segments, and raw packet captures.
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

1. Seed the three Vault properties with
   `scripts/faz24/direct_stt_mtls_seed_operator.py` or an approved equivalent.
   Do not print PEM values.
2. Ensure `kustomize/overlays/test/eso/audio-gateway/externalsecret.yaml`
   maps the three properties above into `audio-gateway-direct-stt-mtls`.
   The Redis aggregate `audio-gateway-secrets` must stay Redis-only.
   A pre-seed `SecretSyncedError` on the dedicated mTLS ExternalSecret is
   expected until the properties exist; do not flip direct-STT on from that
   state.
3. Sync/apply the ESO overlay, then verify
   `ExternalSecret/audio-gateway-direct-stt-mtls` is `Ready=True` and the
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
