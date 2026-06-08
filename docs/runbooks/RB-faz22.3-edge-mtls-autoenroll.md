# RB-Faz22.3 — Endpoint Agent Edge mTLS AutoEnroll Host Activation

> Scope: activate the tokenless standard-PC AutoEnroll path for Endpoint
> Agent. This runbook covers DNS + host-edge mTLS + spoof-safe forwarding to
> `endpoint-admin-service`. It does not replace the HMAC enrollment-token
> fallback used for immediate two-device pilot installs.

## 1. Boundary

Tokenless AutoEnroll is accepted only when all of these are true:

- `endpoint-agent-mtls.testai.acik.com` resolves to the test edge.
- The edge TLS listener requests and verifies a client machine certificate
  against an approved client CA bundle.
- The edge strips any client-supplied identity headers before injecting trusted
  values.
- The backend receives:
  - `X-Client-Cert`: URL-escaped PEM from NGINX `$ssl_client_escaped_cert`
  - `X-Tenant-Id`: validated tenant UUID injected by trusted edge config
- No-cert requests fail closed.
- A valid test machine certificate enrolls without a one-time enrollment token.

Do not overload the general browser host `testai.acik.com` with optional client
certificate prompts unless explicitly approved. Use the dedicated mTLS host so
normal browser/MFE traffic remains unaffected.

## 2. Inputs Required From Operator

| Input | Example / Location | Secret? | Rule |
|---|---|---:|---|
| DNS record | `endpoint-agent-mtls.testai.acik.com` -> test edge | No | DNS must resolve before smoke |
| Server certificate | existing wildcard or dedicated cert | Private key = yes | Do not paste key/cert bodies into issues/docs |
| Client CA bundle | `/etc/nginx/mtls/endpoint-agent-client-ca.crt` | No private key | CA public cert only; private key never on edge |
| Test tenant UUID | injected as `X-Tenant-Id` | No, but environment-specific | Do not guess; obtain from backend/test tenant truth |
| Valid test machine certificate | PFX/cert on Windows test device | Private key = yes | Keep on test device only; never post raw cert/key |

## 3. Backend Contract

Backend controller:

- path: `POST /api/v1/endpoint-agent/endpoint-enrollments/auto`
- cert header: `X-Client-Cert`
- tenant header: `X-Tenant-Id`
- no cert error: `401 MTLS_CERT_MISSING`
- missing tenant error: `400 TENANT_HEADER_REQUIRED`

K8s profile enables forwarded-header mode through
`ENDPOINT_ADMIN_MTLS_FORWARD_HEADER_ENABLED=true`. Therefore the edge is the
trusted mTLS terminator and must enforce the stripping/injection discipline.

## 4. NGINX Host-Edge Template

This is a template. Replace tenant UUID and client CA path during activation.
Do not commit private keys.

```nginx
server {
  listen 443 ssl;
  http2 on;
  listen [::]:443 ssl;
  server_name endpoint-agent-mtls.testai.acik.com;

  ssl_certificate     /etc/nginx/tls/wildcard-acik-com.crt;
  ssl_certificate_key /etc/nginx/tls/wildcard-acik-com.key;

  ssl_client_certificate /etc/nginx/mtls/endpoint-agent-client-ca.crt;
  ssl_verify_client on;
  ssl_verify_depth 3;

  client_max_body_size 2m;
  proxy_read_timeout 60s;
  proxy_connect_timeout 10s;

  location = /healthz {
    access_log off;
    default_type text/plain;
    return 200 "ok\n";
  }

  location = /api/v1/endpoint-agent/endpoint-enrollments/auto {
    proxy_pass http://test_k3d_ingress;
    proxy_http_version 1.1;

    proxy_set_header Host              $host;
    proxy_set_header X-Real-IP         $remote_addr;
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header X-Forwarded-Host  $host;
    proxy_set_header X-Forwarded-Port  443;

    # Spoof guard + trusted edge injection: never forward caller-supplied
    # identity headers; overwrite them with edge-derived values only.
    proxy_set_header X-Client-Cert $ssl_client_escaped_cert;
    proxy_set_header X-Tenant-Id "<TEST_TENANT_UUID>";
  }

  location / {
    return 404;
  }
}
```

## 5. Activation Steps

1. Create DNS record for `endpoint-agent-mtls.testai.acik.com`.
2. Place the client CA public certificate on the edge host.
3. Mount the CA path read-only into the host-edge NGINX container.
4. Add the dedicated server block.
5. Run syntax check:

```bash
docker exec platform-edge-nginx nginx -t
```

6. Reload edge NGINX:

```bash
docker exec platform-edge-nginx nginx -s reload
```

7. Confirm DNS and TLS listener:

```bash
dig +short endpoint-agent-mtls.testai.acik.com
openssl s_client -connect endpoint-agent-mtls.testai.acik.com:443 \
  -servername endpoint-agent-mtls.testai.acik.com \
  -brief </dev/null
```

## 6. Acceptance Smoke

### 6.1 No-Cert Negative

Expected: TLS client-cert rejection or backend `401 MTLS_CERT_MISSING`.

```bash
curl -skS -X POST \
  https://endpoint-agent-mtls.testai.acik.com/api/v1/endpoint-agent/endpoint-enrollments/auto \
  -H 'Content-Type: application/json' \
  --data '{"machineFingerprint":"negative-no-cert","hostname":"NO-CERT","osName":"windows","agentVersion":"0.1.0-dev","schemaVersion":1}' \
  -w '\nhttp_code=%{http_code}\n'
```

### 6.2 Header Injection Negative

Expected: still rejected. A caller-supplied `X-Client-Cert` or `X-Tenant-Id`
must not be accepted.

```bash
curl -skS -X POST \
  https://endpoint-agent-mtls.testai.acik.com/api/v1/endpoint-agent/endpoint-enrollments/auto \
  -H 'Content-Type: application/json' \
  -H 'X-Client-Cert: spoofed' \
  -H 'X-Tenant-Id: 00000000-0000-0000-0000-000000000000' \
  --data '{"machineFingerprint":"negative-header-spoof","hostname":"SPOOF","osName":"windows","agentVersion":"0.1.0-dev","schemaVersion":1}' \
  -w '\nhttp_code=%{http_code}\n'
```

### 6.3 Valid Machine-Cert Positive

Run from the Windows test device or a controlled host that has the test machine
certificate private key. Do not paste the certificate body or private key into
issue comments.

```powershell
$Body = @{
  machineFingerprint = "standard-pc-mtls-smoke"
  hostname = $env:COMPUTERNAME
  osName = "windows"
  osVersion = [System.Environment]::OSVersion.VersionString
  architecture = $env:PROCESSOR_ARCHITECTURE
  agentVersion = "0.1.0-dev"
  schemaVersion = 1
} | ConvertTo-Json -Compress

Invoke-RestMethod `
  -Method Post `
  -Uri "https://endpoint-agent-mtls.testai.acik.com/api/v1/endpoint-agent/endpoint-enrollments/auto" `
  -CertificateThumbprint "<TEST_MACHINE_CERT_THUMBPRINT>" `
  -ContentType "application/json" `
  -Body $Body
```

Expected:

- HTTP 200 or the documented created/accepted response from backend.
- Response contains an enrollment credential path without a one-time token.
- Backend audit includes AutoEnroll event for the cert subject/SAN class.
- No raw cert, key, JWT, bearer, enrollment secret or HMAC secret is recorded.

## 7. Standard PC Bootstrap After Edge Gate

After this runbook passes, the one-command AutoEnroll bootstrap can be used.
The agent AutoEnroll client appends `/endpoint-enrollments/auto` to the base
URL, so `-AutoEnrollApiUrl` must use the external gateway base
`/api/v1/endpoint-agent`.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "iwr -UseBasicParsing https://testai.acik.com/artifacts/endpoint-agent/0.1.0-dev/bootstrap-package.ps1 -OutFile $env:TEMP\endpoint-agent-bootstrap.ps1; powershell.exe -NoProfile -ExecutionPolicy Bypass -File $env:TEMP\endpoint-agent-bootstrap.ps1 -PackageUrl 'https://testai.acik.com/artifacts/endpoint-agent/0.1.0-dev/EndpointAgent.zip' -ExpectedZipSha256 'c4f6f82a68f4eaa258df9406d12e2e9eb908d68f1cc0b9ea2c3ebe5bbfd3d109' -AutoEnroll -AutoEnrollApiUrl 'https://endpoint-agent-mtls.testai.acik.com/api/v1/endpoint-agent' -AutoEnrollCertSANURIPrefix 'adcomputer:' -WorkDir 'C:\Temp\EndpointEnes' -ZipPath 'C:\Temp\EndpointAgent.zip' -Start -Force"
```

Before the edge gate passes, use only the HMAC fallback bootstrap for the
two-device pilot and keep platform-agent #101 in `Needs Verify`.
