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
- TCP/8200 from staging succeeds.
- TCP/8243 from staging still fails.
- Denetim-local evidence shows `CaddyI7AppMtls` running, `caddy.exe` listening
  on `10.99.0.2:8243`, and `Test-NetConnection 10.99.0.2 -Port 8243`
  succeeding through `wg0`.
- Visible Windows Firewall state includes enabled local allow rules
  `WG-staging-caddy-mtls-8243` and
  `WG-staging-caddy-mtls-8243-program` for remote `10.99.0.1` to local
  TCP/8243, with the program rule bound to `C:\caddy\caddy.exe`.
- Effective Windows Firewall profiles have inbound default block but local
  firewall rule merge enabled. Firewall drop logging is disabled/missing, and
  Security log WFP drop events `5152/5157` did not provide matching drop
  evidence for `8243` / `10.99.0.x`.
- ESET firewall-related services and ERA agent are running.

The current blocker therefore points to endpoint/security policy or another
WFP provider path below/outside the visible local Windows Firewall allow rules,
not GitOps digest rollout, missing Caddy persistence, or an IPv6-only listener.

Do not flip direct-STT based only on a green deploy or plaintext 8200 health.
Do not disable or stop ESET to force this gate open. The safe next action is an
endpoint/security-owner decision: add a TTL-bounded ESET/ERA/central WFP
allow/logging policy for `C:\caddy\caddy.exe`, TCP/8243, remote `10.99.0.1`,
then rerun the `live-stt-preflight` evidence profile.

## 2.1 Host-Policy Owner Action Checklist

Before any #188/#182 smoke preparation, collect or attach evidence for:

- `CaddyI7AppMtls` task state and `caddy.exe` listener on `10.99.0.2:8243`.
- Staging route plus TCP probes showing `8200` succeeds and `8243` is the only
  blocked hop before the policy change.
- Visible Windows Firewall allow rules for `WG-staging-caddy-mtls-8243*`.
- ESET/ERA or central WFP policy change record for the exact tuple:
  `source=10.99.0.1`, `destination=10.99.0.2`, `protocol=TCP`,
  `port=8243`, `program=C:\caddy\caddy.exe`.
- Rollback or expiry for that policy change.
- Fresh `live-stt-preflight` evidence JSON after the policy change.

If the security owner chooses logging before allowlisting, the log must be
bounded to the same tuple and must not include packet payload, raw audio,
private keys, bearer material, JWTs, or raw certificate chains.

## 2.2 Operator Handoff Package

Use the source-side handoff builder when #198 needs a single coordination
artifact for the remaining I7 evidence sequence:

```bash
python3 scripts/faz24/build-i7-app-mtls-operator-handoff.py \
  --output-dir /tmp/faz24-i7-app-mtls-operator-handoff
```

Or build the same package through GitHub Actions:

```bash
gh workflow run faz24-i7-app-mtls-operator-handoff.yml \
  --repo Halildeu/platform-k8s-gitops \
  --ref main
```

The package emits `README.md`, `faz24-i7-app-mtls-operator-handoff.json`, and
`SHA256SUMS`. It is metadata-only: it does not connect to Denetim PC, Vault,
Kubernetes, Caddy, firewall/EDR policy, or production; it does not collect
runtime evidence, enable direct-STT, send audio, or advance #198/#1615.

The package orders the handoff as endpoint/security policy evidence ->
`live-stt-preflight` verifier/ingest -> full `prod-gate` verifier/ingest ->
reviewer acceptance. A `live-stt-preflight` PASS is only the bounded
TCP/8243 profile and does not close full I7.

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
