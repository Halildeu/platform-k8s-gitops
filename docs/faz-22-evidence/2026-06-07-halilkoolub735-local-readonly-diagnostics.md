# Faz 22.5 — HALILKOOLUB735 local Parallels read-only diagnostics evidence

> **Date**: 2026-06-07
> **Device**: `HALILKOOLUB735`
> **Scope**: Local Parallels Windows 11 only. Read-only diagnostics after AG-029 self-update activation. No command dispatch, install, uninstall, restart, account mutation, password change, domain join, SMB/file action, or production claim.

## 1. Purpose

This evidence records the current local Windows baseline used by the agent-only Faz 22 work. It strengthens the local lab acceptance surface while keeping the other-device work as a separate batch checklist.

The broader multi-device repeatability gate remains tracked in gitops issue #1044. A 2026-06-07 checklist comment was added there for the future batch run:

- https://github.com/Halildeu/platform-k8s-gitops/issues/1044#issuecomment-4641193725
- 2026-06-07 08:01-08:08 Istanbul refresh comments:
  - https://github.com/Halildeu/platform-k8s-gitops/issues/1044#issuecomment-4641485096
  - https://github.com/Halildeu/platform-k8s-gitops/issues/1044#issuecomment-4641492946
  - https://github.com/Halildeu/platform-k8s-gitops/issues/1044#issuecomment-4641495206

## 2. Boundary

| Boundary | Result |
|---|---|
| Runtime mutation | None |
| Backend command dispatch | None |
| Install / uninstall | None |
| Service restart | None |
| Credential file content read | None |
| Password / account mutation | None |
| Domain / AD action | None |
| SMB / file action | None |
| Production readiness claim | None |

## 3. Agent binary and service

| Field | Evidence |
|---|---|
| VM | `Windows 11 / HALILKOOLUB735` |
| Service | `EndpointAgent` |
| Service state | `RUNNING` |
| Startup mode | `AUTO_DELAYED` |
| Version | `endpoint-agent 0.1.3-lab.1` |
| Binary SHA256 | `CFFD73CC86C27B727952E45083CF95047B9E2AAAC9C1ACC393CACD20122048FE` |

Log tail showed HMAC credential acceptance with the credential value redacted, followed by backend poll responses:

```text
device=d0efb00a-681a-4e32-b7de-a27ef94f2977 credential=<redacted>
no command available
```

The poll cadence was observed through `2026-06-07 02:28Z`.

## 4. Identity diagnostics

Command surface: installed agent binary `diagnose identity`.

| Field | Evidence |
|---|---|
| Hostname | `HALILKOOLUB735` |
| Domain | `WORKGROUP` |
| Workgroup | `WORKGROUP` |
| `partOfDomain` | `false` |
| `domainJoined` | `NO` |
| `azureAdJoined` | `NO` |
| `workplaceJoined` | `NO` |
| Domain probe | `SKIPPED_NOT_DOMAIN_JOINED` |
| Classification | `LOCAL` |

The logged-in account data was emitted as hashes/masks, not raw SID/account strings.

## 5. Local users diagnostics

Command surface: installed agent binary `diagnose local-users`.

| Account class | Count / result |
|---|---|
| Total local users returned | `5` |
| Built-in disabled accounts | `Administrator`, `DefaultAccount`, `Guest`, `WDAGUtilityAccount` |
| Active local user | One active local user observed |
| Locked out users | `0` observed |

No account state was changed.

## 6. Software and WinGet diagnostics

| Surface | Evidence |
|---|---|
| `diagnose software` | `supported=true`, `appCount=17`, registry sources `HKLM` and `HKLM_WOW6432` observed |
| 7-Zip current local presence | Not present in current local inventory |
| `diagnose winget` | `supported=true`, current context ready, `winget.exe` resolved |
| WinGet version | `1.28.240` |
| `diagnose winget-egress` | `timeout=false` |
| Sources | `msstore`, `winget`, `winget-font` |
| DNS/TCP/HTTPS egress | OK for Microsoft CDN / Store endpoints |

## 7. Hardware and services diagnostics

| Surface | Evidence |
|---|---|
| OS | Windows 11 Pro for Workstations |
| Architecture | ARM64 |
| Virtualization | Parallels ARM Virtual Machine |
| Domain state | `domainJoined=false` |
| C: free space | Approximately 53.8 GB in the first local refresh; approximately 47.7 GB in the later 08:06 Istanbul `diagnose hardware` refresh |
| Network IP | `10.211.55.3` |
| Running critical services | `EndpointAgent`, `EventLog`, `MpsSvc`, `WinDefend` |
| Stopped/manual services | `BITS`, `wuauserv` |

## 8. Later local refresh (2026-06-07 08:01-08:06 Istanbul)

A later local refresh was run against the same installed Windows service and
binary. This refresh was still read-only and did not dispatch backend commands,
install or uninstall software, restart the service, mutate accounts, change
passwords, join a domain, or perform SMB/file actions.

### 8.1 Service / CLI boundary

| Check | Evidence |
|---|---|
| VM | `Windows 11` running |
| Hostname | `HALILKOOLUB735` |
| Domain class | `WORKGROUP`, `PartOfDomain=false` |
| EndpointAgent service | `Running`, `Automatic` |
| Process | `endpoint-agent`, PID `13016` |
| Service path | `C:\Program Files\EndpointAgent\endpoint-agent.exe --service-run-name EndpointAgent` |
| Version | `endpoint-agent 0.1.3-lab.1` |
| Backend reachability from guest | `testai.acik.com:443` reachable |

The service log continued to show HMAC credential acceptance with credential
values redacted, followed by `no command available` poll responses at roughly
30-second cadence.

Direct foreground `endpoint-agent.exe --once` was deliberately not used as an
acceptance proof. It returned exit code `1` because no foreground enrollment
token was supplied:

```text
agent run failed: agent is not enrolled and ENDPOINT_AGENT_ENROLLMENT_TOKEN is empty
```

This did not affect the installed service; the service remained `Running` and
continued backend polling. The distinction matters for future runbooks:
service-mode persisted credential state and ad-hoc foreground CLI state are not
the same proof surface.

### 8.2 Public fail-closed checks

No-JWT requests through `testai.acik.com` returned HTTP `401` with the
expected Turkish JWT-required message:

| URL class | Result |
|---|---|
| `/api/v1/endpoint-admin/endpoint-devices` | HTTP `401`, `JWT token zorunludur.` |
| `/api/v1/endpoint-admin/endpoint-devices/{HALILKOOLUB735}/software-inventory/latest` | HTTP `401`, `JWT token zorunludur.` |

Public `/actuator/health` also returns `401` in this setup; cluster-internal
readiness remains the correct source for service `Up` evidence. The local Mac
did not have a usable `k3d-test` kube context during this refresh, so no new
cluster-internal readiness claim is made here.

### 8.3 Read-only diagnose refresh

All installed-agent read-only diagnose surfaces below returned exit code `0`.

| Command | Evidence summary |
|---|---|
| `endpoint-agent diagnose identity` | `classification=LOCAL`; `partOfDomain=false`; `domain=WORKGROUP`; `azureAdJoined=NO`; `domainJoined=NO`; `workplaceJoined=NO`; logged-in account fields were hash/mask only. |
| `endpoint-agent diagnose winget` | `supported=true`; `availableInCurrentContext=true`; `systemContextReady=true`; WinGet resolved from `Microsoft.DesktopAppInstaller_1.28.239.0_arm64__8wekyb3d8bbwe`; version `1.28.240`. |
| `endpoint-agent diagnose winget-egress` | Fixed package query `7zip.7zip` found; DNS/TCP/HTTPS checks OK for Microsoft WinGet CDN/Store endpoints; proxy not configured. |
| `endpoint-agent diagnose software` | HKLM software inventory supported; `appCount=17`; 7-Zip not present in the current local inventory. |
| `endpoint-agent diagnose hardware` | Windows 11 Pro for Workstations ARM64 Parallels VM; `domainJoined=false`; C: free space approximately 47.7 GB; read-only hardware posture returned. |
| `endpoint-agent diagnose services` | `EndpointAgent`, `EventLog`, `MpsSvc`, `WinDefend` running; `BITS` and `wuauserv` stopped/manual. |
| `endpoint-agent diagnose local-users` | 5 local accounts observed; built-in disabled accounts present; one active local user observed; no elevated lockout count in this summary. Raw username omitted from this document. |

Important WinGet boundary: a raw SYSTEM PowerShell `Get-Command winget` did not
resolve `winget` from PATH, but the agent's own WinGet locator did resolve the
App Installer ARM64 package path and reported `systemContextReady=true`. The
agent locator is the authority for the agent execution context; shell PATH is
not the acceptance authority.

## 9. Single-device SELECT-only rollup precheck (2026-06-07 08:08 Istanbul)

Canonical helper `scripts/faz22-non-domain/a1-soak-rollup.sh` from
`origin/main` was run in `--execute` mode for this device through SSH to the
staging host. The helper ran SELECT-only SQL against the test database and did
not mutate database rows.

Device:

```text
hostname=HALILKOOLUB735
device_id=d0efb00a-681a-4e32-b7de-a27ef94f2977
```

Rollup facts:

| Field | Value |
|---|---:|
| Window | 24h |
| Heartbeats | 1817 |
| Expected heartbeats | 2880 |
| Heartbeat ratio | 63.09% |
| First seen in window | 2026-06-06 13:56:28Z |
| Last seen in window | 2026-06-07 05:06:12Z |
| Max heartbeat gap | 296.83s |
| Gaps over 30m threshold | 0 |
| Commands in window | 14 |
| Terminal commands | 13 |
| Succeeded commands | 5 |
| Nonterminal commands | 1 |
| Helper verdict | `COMMAND_REVIEW` |

Command status rollup:

| Command type | Status | Count |
|---|---|---:|
| `COLLECT_INVENTORY` | `SUCCEEDED` | 3 |
| `COLLECT_INVENTORY` | `DELIVERED` | 1 |
| `UPDATE_AGENT` | `SUCCEEDED` | 2 |
| `UPDATE_AGENT` | `FAILED` | 8 |

Nonterminal command detail:

```text
id=5d7fe2d1-5f61-4317-b29d-3256032d0c02
command_type=COLLECT_INVENTORY
status=DELIVERED
issued_at=2026-06-06 21:04:32Z
delivered_at=2026-06-06 21:07:11Z
started_at=(null)
completed_at=(null)
```

Interpretation:

- This is useful precheck evidence, not a #1044 PASS.
- The current evidence is still a single-device view (`1/3` devices).
- The 24h window is incomplete for the current device (`63.09%` heartbeat
  ratio).
- One nonterminal command remains in the current 24h window, so
  `COMMAND_REVIEW` is the correct helper verdict.
- For final 3-device acceptance, start the 24h evidence window after this stale
  command is outside the window or document a deliberate review note; avoid
  dispatching new commands during the soak except planned non-destructive smoke
  commands.

## 10. Interpretation

The local Parallels endpoint remains healthy after AG-029 activation, and the installed agent binary can provide read-only identity, user, software, WinGet, hardware, and service diagnostics.

This evidence supports the local-only development/testing phase. It does not satisfy the future multi-device batch gate, trusted production signing, domain-wide rollout, password reset, SMB/file action, or production acceptance.
