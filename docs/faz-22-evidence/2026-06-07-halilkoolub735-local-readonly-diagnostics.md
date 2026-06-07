# Faz 22.5 — HALILKOOLUB735 local Parallels read-only diagnostics evidence

> **Date**: 2026-06-07
> **Device**: `HALILKOOLUB735`
> **Scope**: Local Parallels Windows 11 only. Read-only diagnostics after AG-029 self-update activation. No command dispatch, install, uninstall, restart, account mutation, password change, domain join, SMB/file action, or production claim.

## 1. Purpose

This evidence records the current local Windows baseline used by the agent-only Faz 22 work. It strengthens the local lab acceptance surface while keeping the other-device work as a separate batch checklist.

The broader multi-device repeatability gate remains tracked in gitops issue #1044. A 2026-06-07 checklist comment was added there for the future batch run:

- https://github.com/Halildeu/platform-k8s-gitops/issues/1044#issuecomment-4641193725

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
| C: free space | Approximately 53.8 GB |
| Network IP | `10.211.55.3` |
| Running critical services | `EndpointAgent`, `EventLog`, `MpsSvc`, `WinDefend` |
| Stopped/manual services | `BITS`, `wuauserv` |

## 8. Interpretation

The local Parallels endpoint remains healthy after AG-029 activation, and the installed agent binary can provide read-only identity, user, software, WinGet, hardware, and service diagnostics.

This evidence supports the local-only development/testing phase. It does not satisfy the future multi-device batch gate, trusted production signing, domain-wide rollout, password reset, SMB/file action, or production acceptance.
