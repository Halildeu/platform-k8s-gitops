# RB-Faz22.3 — Endpoint Agent Edge mTLS AutoEnroll Host Activation

> Scope: activate the tokenless standard-PC AutoEnroll path for Endpoint
> Agent. This runbook covers DNS + host-edge mTLS + spoof-safe forwarding to
> `endpoint-admin-service`. It does not replace the HMAC enrollment-token
> fallback used for immediate two-device pilot installs.
>
> **Canonical path note (2026-06-14)**: the current owner-approved M2 path is
> TLS passthrough in
> [`RB-faz22-M2-edge-mtls-activation.md`](./RB-faz22-M2-edge-mtls-activation.md),
> where the backend terminates mTLS and derives identity from the TLS client
> certificate. This file remains as a forward-header/edge-termination fallback
> template only; using it as the primary path requires an ADR-0029 change.

## 1. Boundary

Tokenless AutoEnroll is accepted only when all of these are true:

- `mtls.testai.acik.com` resolves to the test edge (`mtls.ai.acik.com` is the
  prod counterpart and is not used until test acceptance passes).
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
| DNS record | `mtls.testai.acik.com` -> test edge; `mtls.ai.acik.com` -> prod edge | No | Public DNS was created 2026-06-14; verify from the target corp resolver before smoke |
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

### 4.1 Current `staging-sw` Edge Topology

Live read-only inspection on 2026-06-08 showed the current test/public edge is
not a separate `platform-edge-nginx` container. The active host edge for
`testai.acik.com` is:

| Item | Current value |
|---|---|
| Public edge container | `platform-web-nginx` |
| Config file on host | `/home/halil/platform/web/nginx/default.conf` |
| Config file in container | `/etc/nginx/conf.d/default.conf` |
| Test TLS cert mount | `/home/halil/platform/tls/ai.acik.com/fullchain.pem -> /etc/nginx/tls/tls.crt` |
| Test TLS key mount | `/home/halil/platform/tls/ai.acik.com/privkey.pem -> /etc/nginx/tls/tls.key` |
| Current `testai.acik.com` `/api/` upstream | `http://127.0.0.1:31080` |
| Stage artifact helper container | `platform-web-nginx-stage` on `https://127.0.0.1:5545` |

Therefore, for the current topology the activation patch is applied to the
host file above and the test ingress upstream in the template should be
`http://127.0.0.1:31080`. The syntax/reload commands are:

```bash
docker exec platform-web-nginx nginx -t
docker exec platform-web-nginx nginx -s reload
```

`mtls.testai.acik.com` and `mtls.ai.acik.com` resolve publicly to
`212.115.26.190` as of 2026-06-14. If a specific Windows/corp resolver still
returns NXDOMAIN, treat that as split-DNS/cache drift and do not start public
acceptance from that network yet. Operators may still use `curl --resolve` only
for local edge diagnostics; it does not satisfy the end-user DNS gate.

```nginx
server {
  listen 443 ssl;
  http2 on;
  listen [::]:443 ssl;
  server_name mtls.testai.acik.com;

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
    proxy_pass http://127.0.0.1:31080;
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

1. Confirm DNS records for `mtls.testai.acik.com` and `mtls.ai.acik.com`
   resolve from the relevant corp/client network.
2. Place the client CA public certificate on the edge host.
3. Mount the CA path read-only into the host-edge NGINX container.
4. Add the dedicated server block to the current host edge config
   (`/home/halil/platform/web/nginx/default.conf` on `staging-sw`) unless the
   edge topology has deliberately changed.
5. Run syntax check:

```bash
docker exec platform-web-nginx nginx -t
```

6. Reload edge NGINX:

```bash
docker exec platform-web-nginx nginx -s reload
```

7. Confirm DNS and TLS listener:

```bash
dig +short mtls.testai.acik.com
openssl s_client -connect mtls.testai.acik.com:443 \
  -servername mtls.testai.acik.com \
  -brief </dev/null
```

## 6. Acceptance Smoke

### 6.1 No-Cert Negative

Expected: TLS client-cert rejection or backend `401 MTLS_CERT_MISSING`.

```bash
curl -skS -X POST \
  https://mtls.testai.acik.com/api/v1/endpoint-agent/endpoint-enrollments/auto \
  -H 'Content-Type: application/json' \
  --data '{"machineFingerprint":"negative-no-cert","hostname":"NO-CERT","osName":"windows","agentVersion":"0.1.0-dev","schemaVersion":1}' \
  -w '\nhttp_code=%{http_code}\n'
```

### 6.2 Header Injection Negative

Expected: still rejected. A caller-supplied `X-Client-Cert` or `X-Tenant-Id`
must not be accepted.

```bash
curl -skS -X POST \
  https://mtls.testai.acik.com/api/v1/endpoint-agent/endpoint-enrollments/auto \
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
  -Uri "https://mtls.testai.acik.com/api/v1/endpoint-agent/endpoint-enrollments/auto" `
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

The current canonical pilot package is the `platform-agent` v0.2.3 artifact
published through the test artifact host. Use `/current/` for pilot bootstrap
so the command follows the live artifact-host pointer; `/v0.2.3/` is the
immutable equivalent.

- `EndpointAgent.zip` SHA256:
  `e03618da2c6afe06ef5d674a759ea3a43614cdac7f16c27aaaabb9d05ba51b14`
- standalone `bootstrap-package.ps1` SHA256:
  `fa11ded2ad2e81587f6de1adc323b81f852918021872fdda27376a176432718a`

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "iwr -UseBasicParsing https://testai.acik.com/artifacts/endpoint-agent/current/bootstrap-package.ps1 -OutFile $env:TEMP\endpoint-agent-bootstrap.ps1; powershell.exe -NoProfile -ExecutionPolicy Bypass -File $env:TEMP\endpoint-agent-bootstrap.ps1 -PackageUrl 'https://testai.acik.com/artifacts/endpoint-agent/current/EndpointAgent.zip' -ExpectedZipSha256 'e03618da2c6afe06ef5d674a759ea3a43614cdac7f16c27aaaabb9d05ba51b14' -AutoEnroll -AutoEnrollApiUrl 'https://mtls.testai.acik.com/api/v1/endpoint-agent' -AutoEnrollCertSANURIPrefix 'adcomputer:' -WorkDir 'C:\Temp\EndpointEnes' -ZipPath 'C:\Temp\EndpointAgent.zip' -Start -Force"
```

## 8. HMAC Fallback Bootstrap Before Edge Gate

Before the edge gate passes, use only the HMAC fallback bootstrap for the
two-device pilot. This path still requires a short-lived one-time enrollment
token, but the token is not placed on the command line; the bootstrap prompts
with hidden input.

> **Existing enrollment guard (2026-06-08)**: if the target already has an
> EndpointAgent DPAPI HMAC credential store, a normal `-Force` reinstall can
> preserve and reuse that existing credential. That is the right upgrade
> default, but it is not the same thing as a fresh re-enrollment. Until
> platform-agent #109 adds an explicit fresh-enroll/reset guard, do not count a
> rerun with a supplied enrollment token as fresh enrollment unless the old
> credential store was intentionally backed up/removed and the post-install
> evidence shows HMAC confirmation plus token cleanup.

```powershell
$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$BootstrapUrl = "https://testai.acik.com/artifacts/endpoint-agent/current/bootstrap-package.ps1"
$PackageUrl = "https://testai.acik.com/artifacts/endpoint-agent/current/EndpointAgent.zip"
$ExpectedZipSha256 = "e03618da2c6afe06ef5d674a759ea3a43614cdac7f16c27aaaabb9d05ba51b14"
$BootstrapPath = "$env:TEMP\endpoint-agent-bootstrap.ps1"

Invoke-WebRequest -UseBasicParsing -Uri $BootstrapUrl -OutFile $BootstrapPath

powershell.exe -NoProfile -ExecutionPolicy Bypass -File $BootstrapPath `
  -PackageUrl $PackageUrl `
  -ExpectedZipSha256 $ExpectedZipSha256 `
  -ApiUrl "https://testai.acik.com/api/v1/endpoint-agent" `
  -WorkDir "C:\Temp\EndpointEnes" `
  -ZipPath "C:\Temp\EndpointAgent.zip" `
  -Start `
  -Force
```

Post-install minimum evidence:

```powershell
Get-CimInstance Win32_Service |
  Where-Object { $_.Name -eq "EndpointAgent" } |
  Select-Object Name, DisplayName, State, StartMode, StartName, PathName |
  Format-List

Get-Process endpoint-agent -ErrorAction SilentlyContinue |
  Select-Object ProcessName, Id, StartTime, WorkingSet64, Path |
  Format-List

Get-Content "C:\ProgramData\EndpointAgent\logs\*.log" -Tail 200 -ErrorAction SilentlyContinue
```
