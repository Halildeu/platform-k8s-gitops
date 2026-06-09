# RB — Faz 22.5 M2 Edge mTLS Activation (#1359)

> **Config prep DONE (agent-doable); activation operator/backend-gated.** This
> runbook + the staged manifests in `kustomize/base/endpoint-agent-mtls/`
> (inert: not referenced by any overlay) + the host-nginx stream snippet are the
> edge config layer for ADR-0029's TLS-passthrough device-API mTLS. The live
> flip needs operator DNS + AD CS CA + the platform-backend mTLS listener + the
> ingress-nginx controller flag. Nothing here mutates a live cluster until the
> operator wires the bundle into the test overlay.

Architecture (ADR-0029 §2.5, owner-approved): dedicated SNI host
`endpoint-agent-mtls.testai.acik.com`, **TLS passthrough** (the backend, not the
edge, terminates mTLS and derives identity from the client cert in the
handshake — never from a request header), standard port 443. Acceptance gate
(plan §0.5.2): DNS resolves + edge client-cert verify (at backend) +
spoof-header strip + no-cert/spoofed negative fail-closed + valid machine-cert
positive tokenless AutoEnroll smoke.

## Prerequisites (NOT agent-doable — operator/backend)

| # | Prerequisite | Owner | Why |
|---|---|---|---|
| P1 | DNS A record `endpoint-agent-mtls.testai.acik.com` → edge public IP | **operator (DNS)** | the dedicated SNI host must resolve; never bind a client-cert prompt onto `testai.acik.com` |
| P2 | AD CS Enterprise Root CA `CN=ACIK Endpoint CA` issuing machine certs (EKU Client Authentication; SAN `URI:adcomputer:{objectGUID}`); CRL/OCSP reachable | **operator (AD CS)** | trust anchor + renewal-safe identity binding (ADR-0029 §1, RB-faz22.3-ad-cs-setup) |
| P3 | platform-backend mTLS listener on container port named `mtls` (8443), `client-auth=need`, trust = AD CS Root CA, serving `POST /api/v1/endpoint-agent/endpoint-enrollments/auto` (canonical route) + heartbeat + command poll/result; identity derived from client cert | **platform-backend PR** | ADR-0029 §2.5; "route parity var, no-cert POST fail-closed" exists but the mTLS-terminating port is the remaining backend slice |
| P4 | ingress-nginx controller running with `--enable-ssl-passthrough` | **operator (cluster)** | required for the passthrough Ingress to SNI-route raw TLS (currently NOT enabled — verified 2026-06-09) |
| P5 | host-nginx built with `--with-stream` + `--with-stream_ssl_preread_module` | **operator (host)** | SNI passthrough at the real internet edge (the wildcard host nginx must not TLS-terminate the mTLS SNI) |
| P6 | port-scope the broad intra-namespace allow (or isolate the mTLS listener on a separately-labeled workload) so 8443 is reachable only from ingress-nginx | **operator (cluster)** | K8s NetworkPolicy is additive — the allow in `netpol.yaml` is necessary but NOT sufficient (Codex F2); see the caveat in that file |
| P7 | fill the PKI egress `ipBlock` CIDRs in `netpol.yaml` (AD CS CRL/OCSP + DC LDAPS) | **operator (AD CS/network)** | default-deny egress otherwise blocks revocation checking → backend fails-closed (Codex F3) |

## Activation steps (after P1–P7 — all are security prerequisites, none optional)

1. **Confirm the backend mTLS Service selector/port** in
   `kustomize/base/endpoint-agent-mtls/service.yaml` against the backend
   mTLS-listener PR (the `mtls`/8443 named port + `app.kubernetes.io/name`
   selector must match).
2. **Host nginx**: place the directives from `host-nginx-stream-snippet.conf`
   INSIDE the host nginx's single `stream { }` block (nginx permits exactly one
   stream context — do NOT add a second `stream {}`; create one in the main
   nginx.conf if none exists). Set the two upstream targets (ingress-nginx
   ssl-passthrough listener + the existing http/TLS edge); `nginx -t` then reload.
3. **Cluster**: reference the bundle from the test overlay
   (`kustomize/overlays/test/kustomization.yaml` → add
   `../../base/endpoint-agent-mtls`); commit a gitops PR; let ArgoCD sync.
4. Verify the Ingress + Service + NetworkPolicy applied and the backend mTLS
   Service has ready endpoints (`kubectl -n platform-test get ep
   endpoint-agent-mtls-backend`).

## Smokes (acceptance — run after activation)

> Canonical AutoEnroll route is **`POST /api/v1/endpoint-agent/endpoint-enrollments/auto`**
> (current-state + gateway route parity — NOT `/endpoint-admin/`).
> Smoke discipline (Codex review F4): "TLS handshake failed" is NOT by itself
> client-cert-enforcement proof, and a no-cert request can't prove the
> spoof-header path. Each smoke needs a SPECIFIC reject reason + a BACKEND
> assertion. Always verify the server cert (`-CAfile`/`--cacert`) so a wrong
> server-cert `verify error` is never mistaken for a client-cert reject.

### Negative (MUST fail-closed)
```bash
# N1 — no client cert → server demands one. Assert server trust AND the specific
# reject class separately, so a wrong-server-cert error can never read as PASS.
set -o pipefail
out=$(openssl s_client -connect endpoint-agent-mtls.testai.acik.com:443 \
  -servername endpoint-agent-mtls.testai.acik.com \
  -CAfile acik-endpoint-ca-chain.pem -verify_return_error </dev/null 2>&1)
echo "$out" | grep -q "Verify return code: 0 (ok)" \
  || { echo "FAIL: server cert not trusted — fix trust before judging client-auth"; exit 1; }
echo "$out" | grep -Eiq "certificate required|peer did not return a certificate" \
  && echo "N1 client-auth-required OK" \
  || { echo "INCONCLUSIVE: only a generic handshake failure — correlate with the ingress/backend log line \"client certificate required / no certificate\" before counting PASS"; }
#   PASS = server-cert trusted (Verify return code 0) AND a no-client-cert reject
#   class AND a backend audit assertion that NO enrollment row was created.

# N2 — VALID client cert + FORGED identity headers → backend must use the CERT, ignore headers
curl -sS --cert pilot-machine.crt --key pilot-machine.key --cacert acik-endpoint-ca-chain.pem \
  https://endpoint-agent-mtls.testai.acik.com/api/v1/endpoint-agent/endpoint-enrollments/auto -X POST \
  -H "X-Client-Cert: FORGED" -H "X-Tenant-Id: 00000000-0000-0000-0000-000000000001" \
  -H "X-Company-Id: 00000000-0000-0000-0000-000000000001" -H "ssl-client-verify: SUCCESS"
#   PASS only if the backend audit shows identity_source = tls_client_cert AND the
#   enrolled tenant/identity matches the CERT's bound tenant — NEVER the forged header value
#   (enroll under cert identity, or reject; the header must have zero effect).
```
Raw cert/key/JWT/token MUST NOT appear in any log or doc.

### Positive (valid pilot machine cert — full chain, not just handshake)
```bash
# P — tokenless AutoEnroll end-to-end (no one-time token)
curl -sS --cert pilot-machine.crt --key pilot-machine.key --cacert acik-endpoint-ca-chain.pem \
  https://endpoint-agent-mtls.testai.acik.com/api/v1/endpoint-agent/endpoint-enrollments/auto -X POST
#   PASS requires ALL: HTTP 200/201 + a credential issued (cert-bound, no one-time token used)
#   + a first heartbeat accepted over mTLS-continuous + a backend audit row with
#   identity_source = tls_client_cert and SAN URI:adcomputer:{guid} ↔ LDAP objectGUID match.
#   A bare `openssl s_client` "handshake OK" is NOT a positive PASS.
```

### Header-strip verification
**With ssl-passthrough the Ingress is L4** (raw TLS stream) and does NOT process
HTTP headers — so the strip is **enforced at the backend**, not via an ingress
`configuration-snippet` (that would be a no-op in passthrough mode; §0.5.2's
"edge strips" wording assumed edge-termination). The backend derives identity
ONLY from the client cert in the handshake (ADR-0029 §2.5) and MUST ignore any
caller-supplied `X-Client-Cert / X-Client-Verify / X-Client-DN / X-Tenant-Id /
X-Company-Id / ssl-client-*`. Verify with a backend audit/log assertion: a POST
carrying a spoofed `X-Tenant-Id` (different from the cert's bound tenant) is
enrolled under the CERT's identity (or rejected), never under the header value.
If a future design switches to edge-TERMINATION instead of passthrough, move the
strip to the terminating layer (ingress `auth-tls-*` + header clear, or the host
nginx) — but that is an ADR-0029 change, not this prep.

## Rotation drill (before the 50-PC wave — plan §0.5.2)
Prove client-CA / edge-cert rotation in test: issue a new AD CS intermediate or
roll the edge listener cert; confirm in-flight agents reconnect (mTLS-continuous,
cert-bound bearer re-issued) with zero or planned downtime; write the
downtime decision before scaling.

## Status
- **Edge config layer: PREPARED** (this runbook + staged manifests + host-nginx
  snippet), 2026-06-09. M2 stays **BLOCKED** on P1–P7 (operator DNS + AD CS CA +
  backend mTLS listener PR + controller/host-nginx flags + 8443 isolation +
  PKI-egress /32s) — board `#1359`.
- Cross-references: ADR-0029, RB-faz22.3-ad-cs-setup.md, plan §0.5.2,
  `kustomize/base/endpoint-agent-mtls/`.
