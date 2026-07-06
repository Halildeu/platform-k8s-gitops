# Faz 22.5 M2 — Prod `mtls.ai.acik.com` mTLS Activation Evidence

Date: 2026-06-15 / 2026-06-16 local +03
Tracked by: `platform-k8s-gitops#1359`, `platform-k8s-gitops#1376`
GitOps activation PR: `platform-k8s-gitops#1593`
Runtime follow-up: prod ingress-nginx Helm rev4 with `--enable-ssl-passthrough`

## Scope

This evidence closes the prod mTLS host activation slice for the Endpoint Agent
tokenless AutoEnroll path:

- `mtls.ai.acik.com` resolves to the prod edge (`10.9.10.53` internally).
- host nginx SNI maps prod mTLS traffic to k3d-prod ingress-nginx `127.0.0.1:30443`.
- k3d-prod ingress-nginx runs with `--enable-ssl-passthrough`.
- `endpoint-admin-service` terminates mTLS on 8443 and requires a client cert.
- a domain Windows client certificate can AutoEnroll through the prod host.

This is not a 50/800 rollout, 24h soak, OS reboot continuity, revocation matrix,
or destructive rollback drill.

## Desired-State / Runtime Changes

PR `#1593` merged the prod mTLS overlay:

```text
merge commit 5fc00710e92e8a7ada7003ece58913cf5114c546
endpoint-admin-service image digest:
ghcr.io/halildeu/platform-backend-endpoint-admin-service@sha256:0b7e848918481b01d41aab20b49c85e9766d2a62a36855552b486589cc898f97
prod Ingress host: mtls.ai.acik.com
```

During live activation, prod ingress-nginx was found missing
`--enable-ssl-passthrough`. That was the root cause for the initial fake ingress
certificate / 502 response. The Helm release was upgraded with the repo values
file after adding the prod extra arg:

```text
helm upgrade ingress-nginx ingress-nginx/ingress-nginx \
  --version 4.11.3 \
  -n ingress-nginx \
  -f /tmp/ingress-nginx-values-prod-mtls.yaml

Release: ingress-nginx
Revision: 4
Controller arg: --enable-ssl-passthrough
Rollout: daemonset/ingress-nginx-controller successfully rolled out
```

## Kubernetes Read-Back

```text
kubectl --context k3d-prod -n platform-prod get svc endpoint-agent-mtls-backend -o wide
NAME                          TYPE        CLUSTER-IP    PORT(S)    SELECTOR
endpoint-agent-mtls-backend   ClusterIP   10.43.38.53   8443/TCP   app.kubernetes.io/name=endpoint-admin-service

kubectl --context k3d-prod -n platform-prod get ingress endpoint-agent-mtls -o wide
NAME                  CLASS   HOSTS              ADDRESS        PORTS
endpoint-agent-mtls   nginx   mtls.ai.acik.com   10.43.51.142   80

kubectl --context k3d-prod -n platform-prod get endpoints endpoint-agent-mtls-backend -o wide
NAME                          ENDPOINTS
endpoint-agent-mtls-backend   10.42.75.58:8443

endpoint-admin pod:
endpoint-admin-service-65dc8d6d58-cgzjz ready=true restarts=0
imageID=ghcr.io/halildeu/platform-backend-endpoint-admin-service@sha256:0b7e848918481b01d41aab20b49c85e9766d2a62a36855552b486589cc898f97
```

ArgoCD resource rows for the mTLS slice were healthy:

```text
Service     platform-prod endpoint-agent-mtls-backend Synced Healthy
Ingress     platform-prod endpoint-agent-mtls         Synced Healthy
Deployment  platform-prod endpoint-admin-service      Synced Healthy
ConfigMap   platform-prod endpoint-admin-service-config Synced
```

Boundary: the overall `platform-prod` Application still showed
`OutOfSync/Missing` because `ServiceMonitor endpoint-admin-service` is missing.
That drift is not part of the mTLS host activation and did not block the
dedicated mTLS Service/Ingress/Deployment rows above.

## TLS / No-Cert Negative

Forced SNI from staging to the prod edge:

```text
echo | openssl s_client -connect 10.9.10.53:443 -servername mtls.ai.acik.com -showcerts

subject=CN = mtls.testai.acik.com
issuer=DC = local, DC = acik, CN = Acik-Endpoint-CA
X509v3 Subject Alternative Name:
    DNS:mtls.testai.acik.com, DNS:mtls.ai.acik.com
Acceptable client certificate CA names
SSL alert number 116: certificate required
```

No-client-cert HTTP path fails closed:

```text
curl -sk --resolve mtls.ai.acik.com:443:10.9.10.53 \
  https://mtls.ai.acik.com/api/v1/endpoint-agent/endpoint-enrollments/auto

http_code=000
exit=56
err=OpenSSL SSL_read: error:0A00045C:SSL routines::tlsv13 alert certificate required, errno 0
```

This supersedes the earlier fake ingress certificate / 502 snapshot.

## Valid Machine-Cert Positive

Device used through reverse SSH tunnel:

```text
hostname: SRB-AIDENETIMPC
domain: acik.local
service: EndpointAgent Running / Auto / LocalSystem
machine cert subject: CN=SRB-AIDENETIMPC.acik.local
issuer: CN=Acik-Endpoint-CA, DC=acik, DC=local
thumbprint: 1687D3C41443239A12ECA973E6EED87B0876B068
agent version: endpoint-agent v0.2.5
```

Direct contract POST with the machine cert returned HTTP 201. Response body was
not printed because it contains enrollment details:

```text
POST https://mtls.ai.acik.com/api/v1/endpoint-agent/endpoint-enrollments/auto
StatusCode: 201
Content-Type: application/json
BodyLength: 355
```

Then the real agent executable was run with an isolated temporary DPAPI config
path so the existing service config was not altered:

```text
ENDPOINT_AGENT_AUTO_ENROLL_CONFIG_PATH=C:\ProgramData\EndpointAgent\config\prod-smoke-auto-enroll.dpapi
endpoint-agent.exe -auto-enroll -api-url https://mtls.ai.acik.com/api/v1/endpoint-agent -once

auto-enroll cert loaded: subject="SRB-AIDENETIMPC.acik.local"
auto-enroll already-enrolled: device_id=9b4bc321-a59d-4a96-8557-b1e61a597fed thumbprint=da72cae025e650bdd19d59a87ea319ec900533525884e05d9cc10bb33c552ce6 (tokenless mTLS, ADR-0029 M2)
no command available
exit=0
```

Cleanup/read-back:

```text
SmokeConfigExists: False
MainConfigExists: True
EndpointAgent service: Running / Auto / LocalSystem
```

## Acceptance Result

For the prod host activation slice:

| Gate | Result |
|---|---|
| Prod DNS/edge TCP path | PASS |
| Host SNI to prod ingress | PASS |
| ingress-nginx ssl-passthrough | PASS |
| Backend mTLS connector on 8443 | PASS |
| Server cert SAN includes `mtls.ai.acik.com` | PASS |
| No-client-cert negative fail-closed | PASS |
| Valid domain machine cert AutoEnroll | PASS |
| Agent executable tokenless once-run over prod host | PASS |

Remaining work is outside this slice: 50/800 wave rollout, longer stabilization,
revocation/wrong-CA matrix if retained, OS reboot continuity, and destructive
rollback/uninstall drills.
