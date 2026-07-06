# Faz 22.5 P1 Visibility — Local Parallels Probe Smoke

**Date**: 2026-06-07 21:28 Istanbul / 18:28Z UTC
**Device**: local Parallels Windows 11 VM `HALILKOOLUB735`
**Execution identity**: `nt authority\system` via `prlctl exec`
**Source baseline**: `platform-agent origin/main@eebd198` (`docs(agent): refresh Faz 22 tracking roadmap truth #100`)
**Evidence class**: local lab probe smoke. This is not #1044 two-device repeatability, not 24h observation, not `acik.local` domain pilot, not production rollout, and not browser/backend ingest acceptance.

## Scope

This smoke uses a temporary Windows ARM64 probe binary built from current
`platform-agent` source to exercise the P1 read-only inventory collectors on
the local Windows VM:

- `AG-030` pending reboot detection
- `AG-031` Defender / Firewall / BitLocker posture
- `AG-032` local Administrators membership summary
- `AG-033` disk / RAM / uptime health snapshot
- `AG-036` outdated software inventory opt-in
- `AG-037` hotfix posture opt-in
- `AG-038` agent diagnostics opt-in
- `AG-039` critical services inventory
- `AG-040` startup exposure summary

The probe is temporary and uncommitted. It calls the same internal
`inventory.CollectWithOptions` collector path with explicit opt-in flags. It
does not mutate service state, users, software, registry policy, firewall,
BitLocker, startup entries or files.

## Commands

```bash
git -C /Users/halilkocoglu/Documents/platform-agent fetch origin --prune
git -C /Users/halilkocoglu/Documents/platform-agent worktree add \
  /tmp/platform-agent-p1-probe-smoke-20260607 origin/main

GOOS=windows GOARCH=arm64 go build \
  -o /Users/halilkocoglu/tmp/faz22-p1-probe-smoke-20260607/p1-probe-smoke-arm64.exe \
  ./cmd/p1-probe-smoke

prlctl exec "Windows 11" powershell -NoProfile -ExecutionPolicy Bypass -Command \
  "& '\\Mac\Home\tmp\faz22-p1-probe-smoke-20260607\p1-probe-smoke-arm64.exe' | Out-File -Encoding utf8 '\\Mac\Home\tmp\faz22-p1-probe-smoke-20260607\p1-probe-output.json'"
```

## Artifact Hashes

| Artifact | Path | SHA256 |
|---|---|---|
| Probe binary | `/Users/halilkocoglu/tmp/faz22-p1-probe-smoke-20260607/p1-probe-smoke-arm64.exe` | `03f5a3fc38f3f59c2d410cffb00f4b6bb4ffab914574b068f10bfaa07e71d53c` |
| Probe output | `/Users/halilkocoglu/tmp/faz22-p1-probe-smoke-20260607/p1-probe-output.json` | `e3713fb0f332f11fb9d7cab1268d23b88bd0bfa70a8e220ca3dfa03e1c54f178` |

Output size: `39594` bytes.

## Observed Top-Level Shape

```text
agentVersion, architecture, collectedAt, deviceHealth, diagnostics, hostname,
hotfixPosture, identity, localAdminGroup, osFamily, osName, outdatedSoftware,
pendingReboot, securityPosture, services, startupExposure
```

Top-level identity:

```text
hostname=HALILKOOLUB735
osName=windows
architecture=arm64
agentVersion=p1-probe-smoke
```

## Result Matrix

| Slice | Observed result | Hukum |
|---|---|---|
| `AG-030` pending reboot | `supported=true`, `probeComplete=true`, `pendingReboot=true`; sources: `CBS_REBOOT_PENDING`, `PENDING_FILE_RENAME_OPERATIONS`; Windows Update / computer-name / Netlogon join flags false | Local lab read-only probe PASS; VM currently has reboot indicators |
| `AG-031` security posture | Defender present; Domain/Private/Public firewall enabled; BitLocker system drive present but encrypted/protected/active flags false; no recovery key material emitted | Local lab read-only probe PASS; posture is observable without secret leakage |
| `AG-032` local admin group | `supported=true`, `probeComplete=true`, `sourceUsed=netapi`, local member count `2`, domain member count `0`; no raw SID/name list in evidence | Local lab read-only probe PASS; summary-only contract preserved |
| `AG-033` device health | One fixed disk; physical memory `21468217344` bytes, available `16614338560`, used percent `22`; uptime `232993` seconds / `2` days; no pressure warning | Local lab read-only probe PASS |
| `AG-036` outdated software | Key present in output under explicit opt-in | Local lab shape evidence only; backend/browser outdated flow already covered separately by #1164 |
| `AG-037` hotfix posture | Key present in output under explicit opt-in | Local lab shape evidence only; full AG-037 live chain already covered by 2026-06-01 evidence |
| `AG-038` diagnostics | `supported=true`, `probeComplete=false`, config hash emitted; `BACKEND_HOST_UNRESOLVED` because the temp binary had no backend API URL / service environment | Collector executes and fails closed when service config is absent; this is not backend connectivity acceptance |
| `AG-039` services | `supported=true`, `probeComplete=true`; 6 canonical services observed: `BITS`, `EndpointAgent`, `EventLog`, `MpsSvc`, `WinDefend`, `wuauserv`; `EndpointAgent`, `EventLog`, `MpsSvc`, `WinDefend`, `wuauserv` running; `BITS` stopped/manual | Local lab read-only probe PASS |
| `AG-040` startup exposure | `supported=true`, `probeComplete=false`; `startupAppCount=38`, `rdpEnabled=false`, `windowsFirewallEventLogEnabled=false`; probe errors were redaction guard entries for task scheduler names | Collector executes with redaction guard; this is not full startup-exposure browser/backend acceptance |

## Secret / PII Guard

The output was scanned for common raw secret and path patterns:

```bash
grep -RIE 'Bearer [A-Za-z0-9._-]+|Authorization:|eyJ[A-Za-z0-9_-]+\.|password|token|secret|C:\\Users\\[^\\]+' \
  /Users/halilkocoglu/tmp/faz22-p1-probe-smoke-20260607/p1-probe-output.json || true
```

Observed output: empty.

## Boundary

- This evidence reduces the local-lab gap for `AG-030`, `AG-031`, `AG-032`,
  `AG-033`, and `AG-039`.
- `AG-038` and `AG-040` are intentionally recorded as fail-closed/incomplete
  in this temp-binary context; their full backend/browser acceptance remains a
  separate evidence class unless a service-configured agent run emits fresh
  backend rows and UI proof.
- #1044 remains user/operator-owned for the two additional computers and
  observation roll-up.
- No raw JWT, bearer token, password, local recovery secret, SID list,
  BitLocker recovery key, product key or user profile path is recorded here.
