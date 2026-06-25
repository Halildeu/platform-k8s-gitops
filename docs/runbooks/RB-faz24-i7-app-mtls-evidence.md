# RB-faz24-i7-app-mtls-evidence

> Scope: `platform-ai#198` / Faz 24 WG-B+ I7 data-plane app-mTLS. This
> runbook defines the metadata-only evidence contract for Denetim `8243` /
> `8343` app-layer mTLS. It does not enable direct-STT and does not prove
> `platform-ai#188` or `platform-ai#182` by itself.

## 1. Acceptance Boundary

I7 exists because WireGuard L3 encryption is not enough for real KVKK m.6
meeting audio. The data plane needs service identity, client authentication,
request audit, log minimization, rotation, and fail-fast failure behavior.

This runbook has two evidence profiles:

| Profile | Meaning | Allowed use |
|---|---|---|
| `live-stt-preflight` | Proves the immediate `audio-gateway` to Denetim `live-stt` mTLS path on TCP/8243: route, TCP, server identity, valid-client success, no-client rejection, wrong-client rejection, redaction. | Can unblock the next bounded #188/#182 smoke preparation, but does not close I7 prod gate. |
| `prod-gate` | Proves live-stt and meeting-ai app-mTLS plus request audit, plaintext bypass closure, rotation drill, failure drill, and redaction. | Required before treating I7 as accepted for real KVKK meeting audio / pilot / production. |

Neither profile proves:

- `audio.gateway.direct-stt.enabled=true`,
- `CHUNK_FORWARDED_TO_COMPUTE_PLANE` audit smoke (`platform-ai#188`),
- direct audio `/transcribe` e2e (`platform-ai#182`),
- desktop mic/loopback capture,
- broad production readiness or D30 cutover.

## 2. Current Blocker Shape

Current known live shape from `staging-sw`:

- Route to Denetim is present: `10.99.0.2 dev wg0 src 10.99.0.1`.
- TCP/8243 from staging still fails.
- Earlier Denetim-local evidence showed Caddy listening on `:8243`; staging
  timeout points to Denetim host policy / WFP / ESET / central allowlist or
  equivalent TCP processing, not GitOps digest rollout.

Do not flip direct-STT based only on a green deploy or plaintext 8200 health.

## 3. Metadata Contract

Write a JSON file using schema `faz24.i7.app-mtls.evidence.v1`.

Minimal `live-stt-preflight` example:

```json
{
  "schemaVersion": "faz24.i7.app-mtls.evidence.v1",
  "evidenceProfile": "live-stt-preflight",
  "collectedAt": "2026-06-25T11:00:00Z",
  "status": "pass",
  "tokenIncluded": false,
  "protectedEvidencePath": "github-actions://Halildeu/platform-k8s-gitops/actions/runs/0",
  "redaction": {
    "secretMaterialIncluded": false,
    "privateKeyIncluded": false,
    "rawCommandOutputIncluded": false,
    "rawPacketCaptureIncluded": false,
    "rawAudioIncluded": false,
    "rawTranscriptIncluded": false
  },
  "topology": {
    "source": "staging-sw/audio-gateway",
    "wgInterface": "wg0",
    "sourceWgIp": "10.99.0.1",
    "denetimWgIp": "10.99.0.2",
    "dnsName": "live-stt.denetim"
  },
  "pki": {
    "authority": "vault-pki-denetim-ai",
    "caBundleSha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "serverCertFingerprintSha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "clientCertFingerprintSha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
    "serverCertSanDns": ["live-stt.denetim"],
    "serverCertSanIps": ["10.99.0.2"]
  },
  "services": [
    {
      "name": "live-stt",
      "endpoint": {
        "host": "live-stt.denetim",
        "wgIp": "10.99.0.2",
        "port": 8243,
        "path": "/health"
      },
      "validClientProbe": {
        "status": "pass",
        "observedAt": "2026-06-25T11:00:00Z",
        "tlsVerified": true,
        "clientCertificatePresented": true,
        "accepted": true,
        "httpStatus": 200,
        "evidenceRef": "services/live-stt/valid-client.json"
      },
      "noClientCertProbe": {
        "status": "pass",
        "observedAt": "2026-06-25T11:00:00Z",
        "rejected": true,
        "failureClass": "tls_client_certificate_required",
        "evidenceRef": "services/live-stt/no-client-cert.json"
      },
      "wrongClientCertProbe": {
        "status": "pass",
        "observedAt": "2026-06-25T11:00:00Z",
        "rejected": true,
        "failureClass": "tls_unknown_ca",
        "evidenceRef": "services/live-stt/wrong-client-cert.json"
      }
    }
  ],
  "checks": [
    {
      "id": "wg-route-to-denetim",
      "status": "pass",
      "observedAt": "2026-06-25T11:00:00Z",
      "summary": "staging route to Denetim WG IP is present",
      "evidenceRef": "checks/wg-route-to-denetim.json",
      "evidenceHash": "0123456789abcdef"
    },
    {
      "id": "tcp-8243-reachable",
      "status": "pass",
      "observedAt": "2026-06-25T11:00:00Z",
      "summary": "TCP 8243 returns SYN-ACK from Denetim WG IP",
      "evidenceRef": "checks/tcp-8243-reachable.json",
      "evidenceHash": "0123456789abcdef"
    },
    {
      "id": "tls-server-identity-verified",
      "status": "pass",
      "observedAt": "2026-06-25T11:00:00Z",
      "summary": "server cert SAN and CA hash match expected metadata",
      "evidenceRef": "checks/tls-server-identity-verified.json",
      "evidenceHash": "0123456789abcdef"
    },
    {
      "id": "mtls-valid-client-accepted",
      "status": "pass",
      "observedAt": "2026-06-25T11:00:00Z",
      "summary": "authorized audio-gateway client cert is accepted",
      "evidenceRef": "checks/mtls-valid-client-accepted.json",
      "evidenceHash": "0123456789abcdef"
    },
    {
      "id": "mtls-no-client-rejected",
      "status": "pass",
      "observedAt": "2026-06-25T11:00:00Z",
      "summary": "request without client certificate is rejected",
      "evidenceRef": "checks/mtls-no-client-rejected.json",
      "evidenceHash": "0123456789abcdef"
    },
    {
      "id": "mtls-wrong-client-rejected",
      "status": "pass",
      "observedAt": "2026-06-25T11:00:00Z",
      "summary": "request with wrong client CA is rejected",
      "evidenceRef": "checks/mtls-wrong-client-rejected.json",
      "evidenceHash": "0123456789abcdef"
    },
    {
      "id": "redaction-no-audio-transcript",
      "status": "pass",
      "observedAt": "2026-06-25T11:00:00Z",
      "summary": "evidence and logs contain no raw audio or transcript",
      "evidenceRef": "checks/redaction-no-audio-transcript.json",
      "evidenceHash": "0123456789abcdef"
    }
  ],
  "boundaries": {
    "liveSttAppMtlsPreflightProven": true,
    "meetingAiAppMtlsProven": false,
    "i7ProdGateProven": false,
    "directSttEnabled": false,
    "computePlaneAuditProven": false,
    "directAudioE2eProven": false,
    "desktopMicLoopbackProven": false,
    "productionReady": false
  }
}
```

`prod-gate` additionally requires:

- service `meeting-ai` on port `8343`,
- checks `tcp-8343-reachable`, `meeting-ai-mtls-valid-client-accepted`,
  `request-audit-emitted`, `plaintext-bypass-closed`, `cert-rotation-drill`,
  and `failure-drill-fail-fast`,
- `requestAudit`, `rotation`, `failureDrill`, and `plaintextBypass` sections,
- boundaries `meetingAiAppMtlsProven=true` and `i7ProdGateProven=true`.

## 4. Redaction Rules

Allowed:

- hostnames, WG IPs, interface names, ports, timestamps,
- SHA-256 hashes or 16-char hash prefixes,
- bounded HTTP status metadata,
- failure classes such as `tls_client_certificate_required` or
  `tls_unknown_ca`,
- relative evidence references under the protected path.

Not allowed:

- passwords, tokens, JWTs, cookies, Vault material, private keys,
- raw PEM certificates or raw certificate chains,
- raw command output, packet captures, Caddy logs, or firewall dumps,
- raw audio, transcript text, segment JSON, destination URLs.

Keep raw host material, if needed for audit, inside the protected operator
path. The JSON contract carries hashes and bounded summaries only.

## 5. Validate and Ingest

Validate locally:

```bash
python3 scripts/faz24/verify-i7-app-mtls-evidence.py \
  docs/faz-24-evidence/<date>-i7-app-mtls.json \
  --summary-json /tmp/faz24-i7-app-mtls.verify.json
```

Expected output for a passing `live-stt-preflight`:

```text
Faz24 I7 app-mTLS evidence: PASS
- evidenceProfile=live-stt-preflight
- services=live-stt
- denetimWgIp=10.99.0.2
- tokenIncluded=false
```

Ingest through GitHub Actions:

```bash
I7_EVIDENCE_B64="$(base64 < docs/faz-24-evidence/<date>-i7-app-mtls.json | tr -d '\n')"

gh workflow run faz24-i7-app-mtls-evidence-ingest.yml \
  --repo Halildeu/platform-k8s-gitops \
  --ref main \
  -f evidence_json_base64="$I7_EVIDENCE_B64"
```

The uploaded artifact is `faz24-i7-app-mtls-evidence-<run_id>`.

Boundary: a passing ingest validates the metadata contract only. For
`live-stt-preflight`, update `platform-ai#198` as preflight evidence, then run
the separate `platform-ai#188` compute-plane audit smoke. For `prod-gate`, keep
#198 open until reviewer acceptance records that the full I7 gate is accepted.
