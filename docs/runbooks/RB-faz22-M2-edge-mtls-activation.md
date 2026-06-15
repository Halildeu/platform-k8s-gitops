# RB — Faz 22.5 M2 Edge mTLS Activation (#1359)

> **Test activation is bounded-proven; durable rollout remains gated.** This
> runbook + the manifests in `kustomize/base/endpoint-agent-mtls/` + the
> host-nginx stream snippet are the edge config layer for ADR-0029's
> TLS-passthrough device-API mTLS. As of the 2026-06-14/15 M2 smoke, the test
> path for `mtls.testai.acik.com` serves the AD CS-backed mTLS listener, requests
> client certs, fails closed without a client cert, and accepted one
> `ERP-MOBIL.acik.local` machine-cert AutoEnroll + heartbeat + cert-auth command
> result chain. That is **not** domain rollout acceptance: durable AD DNS,
> service-mode continuity, GPO/MSI pilot, 24h soak/waves and prod
> `mtls.ai.acik.com` remain separate gates.

Architecture (ADR-0029 §2.5, owner-approved; host naming amendment
2026-06-14): dedicated SNI hosts `mtls.testai.acik.com` for test/pilot and
`mtls.ai.acik.com` for prod, **TLS passthrough** (the backend, not the edge,
terminates mTLS and derives identity from the client cert in the handshake —
never from a request header), standard port 443. Acceptance gate (plan §0.5.2):
DNS resolves + edge client-cert verify (at backend) + spoof-header strip +
no-cert/spoofed negative fail-closed + valid machine-cert positive tokenless
AutoEnroll smoke.

## 2026-06-14 DNS naming decision

The retired long-form placeholder host is replaced by:

| Environment | Canonical host | Purpose |
|---|---|---|
| Test / pilot | `mtls.testai.acik.com` | M2 acceptance and 5-PC pilot path |
| Prod | `mtls.ai.acik.com` | Prod mTLS device API after test acceptance |

Public DNS for both names has been operator-created and externally verified to
resolve to `212.115.26.190`. This does **not** close M2: the test host route is
now wired and bounded-smoked, but the smoke used a temporary Windows hosts shim
for the private edge path and only one domain machine. Durable internal AD DNS,
service-mode restart continuity, 5-PC GPO, soak/waves and prod activation still
need their own evidence.

Latest no-client-cert recheck (2026-06-15 ~05:15 +03, Mac -> public edge with
forced SNI) reached `mtls.testai.acik.com:443`, saw the backend/server
certificate `CN=mtls.testai.acik.com` issued by `Acik-Endpoint-CA`, received
TLS `Request CERT`, then failed closed without a client certificate (`curl:
(56)`). That replaces the older 404/default-route snapshot below.

Read-only host/cluster truth, superseding the early 2026-06-14 preflight:

| Check | Observed |
|---|---|
| Host nginx mTLS SNI route | `mtls.testai.acik.com:443` reaches the mTLS path and requests a client cert; `mtls.ai.acik.com` stays prod-gated |
| k3d-test serverlb HTTPS | `127.0.0.1:31443` |
| k3d-prod serverlb HTTPS | `127.0.0.1:30443` |
| endpoint-admin-service mTLS listener | test path has been live-smoked for AutoEnroll/heartbeat and later cert-auth command/result; keep service endpoint/readiness as a per-smoke check |
| ingress-nginx ssl-passthrough | test path has been live-smoked; keep controller arg/read-back verification in every activation run |

## Live prerequisites (not fully agent-doable)

| # | Prerequisite | Owner | Why |
|---|---|---|---|
| P1 | DNS A records `mtls.testai.acik.com` + `mtls.ai.acik.com` → edge public IP | **operator (DNS)** | **DONE 2026-06-14** for public resolvers; still verify from target corp DNS/VPN before pilot |
| P2 | AD CS Enterprise Root CA issuing machine certs (EKU Client Authentication; SAN `URI:adcomputer:{objectGUID}`); CRL/OCSP reachable | **operator (AD CS)** | URI-SAN machine-cert issuance is proven on `ERP-MOBIL` (RequestId 3, thumbprint `F87F0D21F29DCBE77AA861587559BAC974D2FCC0`, URI `adcomputer:2a8a00bf-420f-4741-aad3-c402eed0f74d`); still verify CRL/OCSP reachability from backend namespace before pilot |
| P3 | endpoint-admin mTLS passthrough connector enabled only in test with mounted PKCS12 stores + passwords + fixed tenant UUID; client trust = AD CS Root CA; server cert SAN covers `mtls.testai.acik.com`; connector serves `POST /api/v1/endpoint-agent/endpoint-enrollments/auto` (canonical route) + heartbeat + command poll/result and derives identity from client cert | **operator + GitOps overlay** | **BOUNDED-PROVEN on test 2026-06-14/15** for one machine: AutoEnroll HTTP 201, heartbeat, cert-auth command/result `SUCCEEDED`. Keep as a per-rollout gate for service-mode and multi-device evidence |
| P4 | ingress-nginx controller running with `--enable-ssl-passthrough` | **operator (cluster)** | **BOUNDED-PROVEN on test path** by no-cert fail-closed + valid machine-cert smoke; still read back args/endpoints during every activation |
| P5 | host-nginx built with `--with-stream` + `--with-stream_ssl_preread_module` | **operator (host)** | **BOUNDED-PROVEN on test path** by public SNI no-cert probe reaching backend cert-auth path; prod SNI remains gated |
| P6 | port-scope the broad intra-namespace allow (or isolate the mTLS listener on a separately-labeled workload) so 8443 is reachable only from ingress-nginx | **operator (cluster)** | K8s NetworkPolicy is additive — the allow in `netpol.yaml` is necessary but NOT sufficient (Codex F2); see the caveat in that file |
| P7 | fill the PKI egress `ipBlock` CIDRs in `netpol.yaml` (AD CS CRL/OCSP + DC LDAPS) | **operator (AD CS/network)** | default-deny egress otherwise blocks revocation checking → backend fails-closed (Codex F3) |

## Activation steps (after P1–P7 — all are security prerequisites, none optional)

1. **Seed the mTLS runtime material** without committing secrets:
   - Secret `endpoint-admin-service-mtls-stores` with
     `server-keystore.p12` and `truststore.p12`.
   - Secret `endpoint-admin-service-mtls-secrets` with
     `ENDPOINT_ADMIN_MTLS_PASSTHROUGH_KEY_STORE_PASSWORD` and
     `ENDPOINT_ADMIN_MTLS_PASSTHROUGH_TRUST_STORE_PASSWORD`.
   - Server certificate SAN must cover `mtls.testai.acik.com`; truststore must
     contain the dedicated Endpoint CA chain used to issue machine certs.
2. **Enable the endpoint-admin passthrough connector in the test overlay only**:
   set `ENDPOINT_ADMIN_MTLS_FORWARD_HEADER_ENABLED=false`,
   `ENDPOINT_ADMIN_MTLS_PASSTHROUGH_ENABLED=true`, and a non-empty
   `ENDPOINT_ADMIN_MTLS_PASSTHROUGH_FIXED_TENANT_ID` matching the pilot tenant.
   Do not enable prod until test negative/positive smokes pass.
3. **Host nginx**: place the directives from `host-nginx-stream-snippet.conf`
   INSIDE the host nginx's single `stream { }` block (nginx permits exactly one
   stream context — do NOT add a second `stream {}`; create one in the main
   nginx.conf if none exists). The staged snippet defaults the test/prod
   passthrough upstreams to the currently observed serverlb HTTPS ports
   (`127.0.0.1:31443` test, `127.0.0.1:30443` prod). Set the existing http/TLS
   edge fallback upstream (`127.0.0.1:8444` placeholder) only after deliberately
   reshaping the current terminating nginx so the stream listener can own
   `:443`; `nginx -t` then reload. If prod is not being activated yet, keep
   `mtls.ai.acik.com` mapped to a fail-closed upstream rather than test.
4. **Cluster**: apply the ingress-nginx values with ssl-passthrough enabled,
   then sync the GitOps PR that renders `../../base/endpoint-agent-mtls` in the
   test overlay.
5. Verify the Ingress + Service + NetworkPolicy applied and the backend mTLS
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
out=$(openssl s_client -connect mtls.testai.acik.com:443 \
  -servername mtls.testai.acik.com \
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
  https://mtls.testai.acik.com/api/v1/endpoint-agent/endpoint-enrollments/auto -X POST \
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
  https://mtls.testai.acik.com/api/v1/endpoint-agent/endpoint-enrollments/auto -X POST
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
- **Test edge mTLS path: BOUNDED-PROVEN / durable rollout gated**
  (2026-06-14/15). The test SNI host reaches the mTLS listener, serves a
  `mtls.testai.acik.com` server cert from `Acik-Endpoint-CA`, requests a client
  cert and fail-closes no-cert traffic. A valid `ERP-MOBIL.acik.local` machine
  cert produced AutoEnroll HTTP 201, backend DB/audit cert identity, tokenless
  heartbeat and later cert-auth command/result `SUCCEEDED` evidence.
- M2 remains **not domain-rollout accepted**: durable no-hosts AD DNS,
  service-mode continuity/restart behavior, admin-dispatch API, 5-PC GPO, 24h
  soak, 50/800 waves and prod `mtls.ai.acik.com` stay open under `#1359/#1376`.
- Cross-references: ADR-0029, RB-faz22.3-ad-cs-setup.md, plan §0.5.2,
  `kustomize/base/endpoint-agent-mtls/`.
