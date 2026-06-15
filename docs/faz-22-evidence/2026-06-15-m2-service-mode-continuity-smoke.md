# Faz 22.5 M2 Service-Mode Continuity Smoke Evidence

Date: 2026-06-15
Owner session: Codex `codex-m2-service-20260615T065608Z`
Board issue: `platform-k8s-gitops#1567`

## Scope

Bounded, domain-free service-mode continuity smoke for the ADR-0029 M2 tokenless
mTLS Endpoint Agent path:

- start a Windows service in `--auto-enroll` mode,
- enroll via client certificate over backend mTLS passthrough,
- persist tokenless DPAPI config,
- stop/start the service without deleting config,
- prove post-restart heartbeat / command poll continuity.

This is a service restart smoke, not an OS reboot or 24h soak.

## Source Revisions

| Component | Source |
|---|---|
| Agent | `platform-agent` worktree `codex/m2-service-continuity-smoke`, HEAD `473b3b8ce854bb6015a4e233dadc77feb6536f27` |
| Backend | `platform-backend` worktree `codex/m2-current-verify`, HEAD `47d29d5f` |
| GitOps evidence branch | `platform-k8s-gitops` `codex/m2-service-continuity-smoke` |

Agent binary built for Windows amd64:

```text
endpoint-agent.exe SHA256 e8f6415ab503fd75e32278a4dfca8a4b76c7ad727d5fee1748b829971d4c80a9
version 0.1.0-m2service.473b3b8ce854
```

Agent tests before build:

```text
go test ./internal/autoenroll ./internal/mtls ./internal/platform/windows/service ./cmd/endpoint-agent
ok platform-agent/internal/autoenroll
ok platform-agent/internal/mtls
ok platform-agent/internal/platform/windows/service
ok platform-agent/cmd/endpoint-agent
```

## Local Backend Harness

Backend ran from current `origin/main` source against a clean local Postgres
container:

- Postgres container: `m2-pg-service`, host port `55434`.
- HTTP port: `8097`.
- Management health port: `8098`.
- mTLS passthrough port: `9443`.
- Flyway schema: `endpoint_admin_service` migrated to v70.
- Fixed tenant: `00000000-0000-0000-0000-000000000001`.

Health/listener evidence:

```text
curl http://127.0.0.1:8098/actuator/health -> {"status":"UP"}
java LISTEN *:8097
java LISTEN *:8098
java LISTEN *:9443
```

The local server certificate covered `mtls.local.test` and `10.211.55.2`.
Windows reached the backend from Parallels NAT:

```text
Test-NetConnection mtls.local.test -Port 9443
RemoteAddress    : 10.211.55.2
TcpTestSucceeded : True
```

## Windows Service Smoke

Host:

```text
ComputerName: HALILKOOLUB735
ServiceName : EndpointAgentM2Smoke
Run account : LocalSystem
Client cert : CN=WIN11-TESTPC
Windows SHA1 thumbprint: ABE272A741D69CACE4BCC4549405DF9C1F9AE09F
Backend cert thumbprint SHA256: 00665df65ed881eb64b39dcd70547fe9a07f26d9d56273bca7129715385b2cc2
SAN URI: adcomputer:e89692cc-fb06-4843-9b77-4efefcfb66b1
API URL: https://mtls.local.test:9443/api/v1/endpoint-agent
```

Service ImagePath was isolated from the existing production-like
`EndpointAgent` service:

```text
"C:\Program Files\EndpointAgentM2Smoke\endpoint-agent.exe"
  --service-run-name EndpointAgentM2Smoke
  --auto-enroll
  --api-url https://mtls.local.test:9443/api/v1/endpoint-agent
```

Service environment used a separate config/log directory:

```text
ENDPOINT_AGENT_LOG_DIR=C:\ProgramData\EndpointAgentM2Smoke\logs
ENDPOINT_AGENT_AUTO_ENROLL_CERT_SUBJECT_SUFFIX=WIN11-TESTPC
ENDPOINT_AGENT_AUTO_ENROLL_CERT_SAN_URI_PREFIX=adcomputer:
ENDPOINT_AGENT_AUTO_ENROLL_CONFIG_PATH=C:\ProgramData\EndpointAgentM2Smoke\config\auto-enroll.dpapi
ENDPOINT_AGENT_COMMAND_POLL_INTERVAL=10s
ENDPOINT_AGENT_HEARTBEAT_INTERVAL=10s
```

First service loop:

```text
endpoint-agent 2026/06/15 07:16:14 logger initialized ... serviceMode=true
endpoint-agent 2026/06/15 07:16:14 agent mode=auto-enroll
endpoint-agent 2026/06/15 07:16:14 auto-enroll cert loaded: subject="WIN11-TESTPC" thumbprint_sha256=00665df65ed881eb64b39dcd70547fe9a07f26d9d56273bca7129715385b2cc2 not_after=2026-06-29T06:59:35Z
endpoint-agent 2026/06/15 07:16:16 auto-enroll enrolled: device_id=fe36d0c2-1ecc-4ccd-8fed-b41050b43f2c thumbprint=00665df65ed881eb64b39dcd70547fe9a07f26d9d56273bca7129715385b2cc2 (tokenless mTLS, ADR-0029 M2)
endpoint-agent 2026/06/15 07:16:17 no command available
```

Persisted DPAPI config after first loop:

```text
ConfigPath    : C:\ProgramData\EndpointAgentM2Smoke\config\auto-enroll.dpapi
Length        : 566
Sha256        : 7959F1923F59C73B0F5A1667FE42BA35110B2FDA06AB91570540251759269D88
```

Stop/start continuity loop:

```text
Stop-Service EndpointAgentM2Smoke
Start-Service EndpointAgentM2Smoke
```

Post-restart service loop:

```text
endpoint-agent 2026/06/15 07:17:03 logger initialized ... serviceMode=true
endpoint-agent 2026/06/15 07:17:03 agent mode=auto-enroll
endpoint-agent 2026/06/15 07:17:03 auto-enroll cert loaded: subject="WIN11-TESTPC" thumbprint_sha256=00665df65ed881eb64b39dcd70547fe9a07f26d9d56273bca7129715385b2cc2 not_after=2026-06-29T06:59:35Z
endpoint-agent 2026/06/15 07:17:05 no command available
endpoint-agent 2026/06/15 07:17:16 no command available
endpoint-agent 2026/06/15 07:17:26 no command available
endpoint-agent 2026/06/15 07:17:36 no command available
endpoint-agent 2026/06/15 07:17:46 no command available
```

DPAPI config remained stable across service restart:

```text
ConfigHashBefore : 7959F1923F59C73B0F5A1667FE42BA35110B2FDA06AB91570540251759269D88
ConfigHashAfter  : 7959F1923F59C73B0F5A1667FE42BA35110B2FDA06AB91570540251759269D88
HashStable       : True
```

`no command available` is the cert-auth heartbeat + command-poll success path:
the runner calls heartbeat before polling `/commands/next`; a 204 command poll
logs this message.

## Backend DB Evidence

Device row:

```text
id                  : fe36d0c2-1ecc-4ccd-8fed-b41050b43f2c
tenant_id           : 00000000-0000-0000-0000-000000000001
hostname            : HALILKOOLUB735
os_type             : WINDOWS
agent_version       : 0.1.0-m2service.473b3b8ce854
status              : ONLINE
last_seen_at        : 2026-06-15 07:18:16.311828+00
enrolled_at         : 2026-06-15 07:16:16.114223+00
```

Machine certificate row:

```text
device_id           : fe36d0c2-1ecc-4ccd-8fed-b41050b43f2c
san_uri             : adcomputer:e89692cc-fb06-4843-9b77-4efefcfb66b1
object_guid         : e89692cc-fb06-4843-9b77-4efefcfb66b1
cert_thumbprint     : 00665df65ed881eb64b39dcd70547fe9a07f26d9d56273bca7129715385b2cc2
cert_subject        : CN=WIN11-TESTPC
cert_issuer         : CN=Faz22 M2 Test CA
revoked_at          : NULL
```

Heartbeat rows after restart:

```text
received_at                   agent_version                  ip_address
2026-06-15 07:18:26.488959+00 0.1.0-m2service.473b3b8ce854  10.211.55.3
2026-06-15 07:18:16.311828+00 0.1.0-m2service.473b3b8ce854  10.211.55.3
2026-06-15 07:18:06.39439+00  0.1.0-m2service.473b3b8ce854  10.211.55.3
2026-06-15 07:17:56.313412+00 0.1.0-m2service.473b3b8ce854  10.211.55.3
2026-06-15 07:17:46.358978+00 0.1.0-m2service.473b3b8ce854  10.211.55.3
```

Audit:

```text
MACHINE_CERT_AUTO_ENROLL_SUCCESS = 1
```

## Cleanup

After evidence capture:

- temporary `EndpointAgentM2Smoke` service removed,
- temporary `mtls.local.test` hosts entry removed,
- local test root CA and client cert removed from LocalMachine stores,
- temporary install/log directories removed,
- existing normal `EndpointAgent` service remained running and untouched.

## Discovered Follow-Up

The same run discovered a separate dry-run-only agent crash:

```text
--auto-enroll --dry-run loaded WIN11-TESTPC cert and TLS config,
then crashed in cngSigner.Close -> CertFreeCertificateContext
Exception 0xc0000005
```

This is tracked separately as `platform-agent#165`. It did not block the
service-mode acceptance path in this evidence because the service loop enrolled,
persisted config, restarted, and continued heartbeats/polls successfully.

## Boundary

This evidence proves bounded Windows service-mode continuity for tokenless mTLS
using a local test CA and `mtls.local.test` host alias. It does not prove:

- AD CS-issued cert service continuity on a domain host,
- durable no-hosts AD DNS,
- signed MSI/GPO install,
- OS reboot continuity,
- 24h soak,
- 5-PC / 50-PC / 800-PC staged rollout,
- production `mtls.ai.acik.com`.

Those gates remain under `#1359` / `#1376` and related rollout issues.
