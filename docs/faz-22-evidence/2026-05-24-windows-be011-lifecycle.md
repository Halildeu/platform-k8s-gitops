# Faz 22 — Windows VM fresh smoke (AG-013 verified) + BE-011 lifecycle live evidence (2026-05-24)

> **Status**: PASS (AG-013 fresh Windows smoke + BE-011 real agent lifecycle SUCCEEDED)
> **Tracked by**: platform-agent #8 + platform-k8s-gitops handoff §5 P1 (BE-011 + Windows #8)
> **Scope sınırı**: Parallels Windows 11 VM (workgroup, NOT acik.local domain-joined). IT pilot 22.2 ayrı kapı (`docs/runbooks/RB-faz22-endpoint-pilot-it-owned.md`).
> **VM identity**: HALILKOOLUB735 (Windows 11, Parallels Desktop)
>
> **Reclassification note (2026-05-24 — user scope decision)**: Bu evidence başlangıçta "lab/CI rehearsal predecessor" olarak etiketlenmişti çünkü Faz 22.2 primary scope `acik.local` domain-joined IT pilot kabul ediliyordu. 2026-05-24 kullanıcı kararı ile Faz 22.2 primary scope **non-domain Windows yönetimi** (workgroup/standalone/BYOD) olarak yeniden tanımlandı (ADR-0012-EA "22.2 scope amendment" + Codex strategic thread `019e5afc-2ce2-7811-9d98-73ff6eac1434`). Bu evidence yeniden sınıflandırıldı: artık **22.2.A non-domain primary-scope substantive evidence**. Tarihsel boundary korunur (single VM / no soak / 1 device); production-ready / domain-wide rollout-ready iddiası DEĞİL. Yeni runtime evidence claim YOK; mevcut evidence retake YOK — sadece sınıf değişimi.

---

## 1. Amaç

Faz 22.1 lab foundation acceptance Pending listesinden **iki** kapıyı kapatma yan-kanıt + canlı smoke ile:
- **platform-agent#8** fresh Windows smoke (AG-013 capability fix sonrası executor coherence verify)
- **BE-011** real agent lifecycle smoke (enroll → heartbeat → command → result → audit)

## 2. Build provenance

| Artifact | Value |
|---|---|
| platform-agent `main` HEAD | `2e49f8b` (BE-011 wire reconciliation, PR #9 squash) |
| Build pipeline | `scripts/build/windows-package.sh` (local Mac, post-AG-013 capability fix) |
| `endpoint-agent.exe` SHA256 | `53a45b637147145025b68c5ab1235ae6e6ee491cef9f6925f83a61fb7fb42669` |
| Transfer mechanism | Parallels `\\Mac\Home` shared folder (read-only from VM); no binary copy needed |

VM SHA verification:
```
PS> (Get-FileHash '\\Mac\Home\Documents\platform-agent\dist\windows\EndpointAgent\endpoint-agent.exe' -Algorithm SHA256).Hash
53A45B637147145025B68C5AB1235AE6E6EE491CEF9F6925F83A61FB7FB42669
```

## 3. VM pre-check

| Check | Result |
|---|---|
| Hostname | `HALILKOOLUB735` |
| Backend reachability | `Test-NetConnection testai.acik.com -Port 443 -InformationLevel Quiet` → **True** |
| DNS resolve | `testai.acik.com` → `212.115.26.190` |
| Previous install state | No `EndpointAgent*` service (önceki uninstall sonrası temiz); `C:\ProgramData\EndpointAgent` + `EndpointAgentCodexTest` log dirleri residue |

## 4. AG-013 fresh Windows smoke (windows-live.ps1 full pass)

Script: `scripts/test/windows-live.ps1` (executed via `prlctl exec "Windows 11" powershell ...`).

| Step | Result |
|---|---|
| Install | `EndpointAgentCodexTest` service installed |
| Delayed auto-start | `[SC] ChangeServiceConfig SUCCESS` |
| Failure restart policy | `[SC] ChangeServiceConfig2 SUCCESS` |
| Service SDDL | `[SC] SetServiceObjectSecurity SUCCESS` |
| Service start | `EndpointAgentCodexTest: RUNNING` |
| Event log source | Verified present |
| Tamper protection | Checks passed |
| **Read-only local users diagnostic** | 5 user JSON returned: |
| | - `Administrator` (disabled, no password required) |
| | - `DefaultAccount` (disabled, no password required) |
| | - `Guest` (disabled, no password required) |
| | - `WDAGUtilityAccount` (disabled, password required) |
| | - `halilkocoglu` (enabled, no lockout, no password required) |
| Stop service with maintenance token | `service stop ok: EndpointAgentCodexTest` → STOPPED |
| Log file present | `C:\ProgramData\EndpointAgentCodexTest\logs\endpoint-agent.log` (267 bytes) |
| Log content | `logger initialized logPath=... serviceMode=true` |
| Uninstall | Service removed, install dir removed, env vars cleared, logs cleared |
| **live smoke completed** | All steps green |

### AG-013 capability list verification (post-fix)

From `internal/inventory/inventory.go::RuntimeCapabilities`:

```go
capabilities := []protocol.CommandType{
    protocol.CommandCollectInventory,
    protocol.CommandGetLoggedInUser,
    protocol.CommandGetUserHomePaths,
}
if runtime.GOOS == "windows" {
    // DisableLocalUser/EnableLocalUser intentionally omitted: adapter not implemented in executor.
    capabilities = append(capabilities,
        protocol.CommandListLocalUsers,
    )
}
```

Windows capability list: `COLLECT_INVENTORY, GET_LOGGED_IN_USER, GET_USER_HOME_PATHS, LIST_LOCAL_USERS`.

**`DISABLE_LOCAL_USER` / `ENABLE_LOCAL_USER` correctly absent** (executor coherence guard `TestRuntimeCapabilitiesAllDispatchable` passing; AG-013 capability mismatch fixed source-side via platform-agent#7 MERGED `2e49f8b` chain).

## 5. BE-011 real agent lifecycle smoke

### Phase A — fresh install with enrollment token

Mac-side: minted enrollment token via persona JWT (`c5persona-admin-9001`, OpenFGA `can_manage module:endpoint-admin` tuple) → backend admin REST `POST /api/v1/endpoint-admin/endpoint-enrollments`:

```json
{
  "enrollmentId": "524a625f-1050-41d8-a182-c178fb3efbc7",
  "token": "<redacted>",
  "expiresAt": "2026-05-25T12:44:18.245713410Z"
}
```

VM-side: install.ps1 with `-ApiUrl 'https://testai.acik.com/api/v1/endpoint-agent' -EnrollmentToken <token> -Start`:

- Service `EndpointAgentLifecycle` installed + started → **RUNNING**

### Phase B — enroll + heartbeat

Agent log (`C:\ProgramData\EndpointAgentLifecycle\logs\endpoint-agent.log`):

```
2026/05/24 12:51:10 logger initialized logPath=... serviceMode=true
2026/05/24 12:51:10 agent enrolled: device=d0efb00a-681a-4e32-b7de-a27ef94f2977 credential=<redacted>
2026/05/24 12:51:11 no command available
2026/05/24 12:51:41 no command available
2026/05/24 12:52:11 no command available
2026/05/24 12:52:41 no command available
2026/05/24 12:53:11 no command available
2026/05/24 12:53:41 no command available
2026/05/24 12:54:11 command 8181f20a-27db-436b-aa1d-cf278d36a31b finished with SUCCEEDED
2026/05/24 12:54:41 no command available
```

- **Enroll**: 12:51:10 — `device=d0efb00a-681a-4e32-b7de-a27ef94f2977`
- **Heartbeat poll**: 30s interval, stable
- **Command poll → execute → result submit**: 12:54:11 — `8181f20a-... finished with SUCCEEDED`

### Phase C — command queue + lifecycle

Mac-side: `POST /api/v1/endpoint-admin/endpoint-devices/d0efb00a-.../commands` with persona JWT:

```json
{
  "type": "COLLECT_INVENTORY",
  "reason": "BE-011 lifecycle smoke 2026-05-24",
  "priority": 100,
  "idempotencyKey": "be011-collect-inv-20260524-001"
}
```

Backend response (initial QUEUE):
```json
{
  "id": "8181f20a-27db-436b-aa1d-cf278d36a31b",
  "tenantId": "00000000-0000-0000-0000-000000000001",
  "deviceId": "d0efb00a-681a-4e32-b7de-a27ef94f2977",
  "type": "COLLECT_INVENTORY",
  "status": "QUEUED",
  "approvalStatus": "NOT_REQUIRED",
  "priority": 100,
  "attemptCount": 0,
  "maxAttempts": 3,
  "issuedBySubject": "87b1d2c8-aeed-40af-8742-de8431efeee2",
  "issuedAt": "2026-05-24T12:53:06.934281429Z"
}
```

Backend response (final state, post-agent execution):
```json
{
  "id": "8181f20a-...",
  "status": "SUCCEEDED",
  "attemptCount": 1,
  "deliveredAt": "2026-05-24T12:53:24.454429Z",
  "startedAt": "2026-05-24T12:54:11.236722Z",
  "completedAt": "2026-05-24T12:54:11.236722Z",
  "result": {
    "id": "8686d0b8-895f-4528-a909-d3f9ab51aaa4",
    "status": "SUCCEEDED",
    "payload": {
      "claimId": "c52308a7-dc4f-4ee5-9197-a362df29a7f6",
      "details": {
        "inventory": {
          "osName": "windows",
          "hostname": "HALILKOOLUB735",
          "osFamily": "WINDOWS",
          "collectedAt": "2026-05-24T15:54:11.2367215+03:00",
          "agentVersion": "0.1.0-dev",
          "architecture": "amd64"
        }
      },
      "summary": "Inventory collected"
    }
  }
}
```

Total lifecycle time (queue → SUCCEEDED): **~65 seconds**.

### Phase D — backend audit row

`GET /api/v1/endpoint-admin/endpoint-audit-events?commandId=8181f20a-...&limit=50` (persona JWT):

```json
[
  {
    "id": "b3cf5210-fd4d-4fd9-821b-12981f55296a",
    "tenantId": "00000000-0000-0000-0000-000000000001",
    "deviceId": "d0efb00a-681a-4e32-b7de-a27ef94f2977",
    "commandId": "8181f20a-27db-436b-aa1d-cf278d36a31b",
    "eventType": "ENDPOINT_COMMAND_CREATED",
    "action": "CREATE_COMMAND",
    "performedBySubject": "87b1d2c8-aeed-40af-8742-de8431efeee2",
    "correlationId": "be011-collect-inv-20260524-001",
    "metadata": {
      "reason": "BE-011 lifecycle smoke 2026-05-24",
      "priority": 100,
      "commandType": "COLLECT_INVENTORY",
      "maxAttempts": 3,
      "issuerSubject": "87b1d2c8-aeed-40af-8742-de8431efeee2",
      "approvalStatus": "NOT_REQUIRED",
      "idempotencyKey": "be011-collect-inv-20260524-001",
      "requiresApproval": false
    },
    "beforeState": null,
    "afterState": {
      "status": "QUEUED",
      "approvalStatus": "NOT_REQUIRED"
    },
    "occurredAt": "2026-05-24T12:53:06.951909Z"
  }
]
```

Audit row count: **1** (only `ENDPOINT_COMMAND_CREATED` emitted for non-destructive `COLLECT_INVENTORY`; lifecycle state transitions captured directly on the command object's `deliveredAt`/`startedAt`/`completedAt` fields). BE-017 dual-control destructive command flow emits richer audit chain (separate evidence, formal 5-step matrix ayrı kapı).

### Phase E — cleanup

- Service stopped + `sc.exe delete` (manual force cleanup)
- Install dir `C:\Program Files\EndpointAgentLifecycle` removed
- Log dir `C:\ProgramData\EndpointAgentLifecycle` removed
- Event log registry key `HKLM:\...\EventLog\Application\EndpointAgentLifecycle` removed
- 7 ENDPOINT_AGENT_* machine env vars cleared
- Persona pw rotated to `openssl rand -base64 32` random unknown (HARD RULE residue cleanup)

## 6. D29-EA matrix kapsam

| Layer | Status | Evidence |
|---|:-:|---|
| **Up** | ✅ | VM Running; service RUNNING; backend pod READY 1/1 (gitops `current-state.md` truth) |
| **Functional** | ✅ | Agent enrolled + heartbeat + command lifecycle SUCCEEDED + result payload populated + audit row inserted |
| **Secured** | ✅ | persona JWT required for command queue (`c5persona-admin-9001` OpenFGA `can_manage module:endpoint-admin` tuple gerek); enrollment token TTL 24h |
| **Zanzibar-ready** | ✅ | Backend `@RequireModule(value=EndpointAdminAuthz.MODULE, relation=EndpointAdminAuthz.MANAGER)` enforce; FGA fail-closed prior chunks'ta zaten kanıtlandı |

## 7. Pending (ayrı kapı — bu smoke KAPATMAZ)

- **BE-017 formal dual-control matrix** — destructive command (e.g. `LOCK_USER_LOGIN`) için 5-step formal smoke (create → pending → self-approval deny → second-admin approve → audit insert with full chain); bu smoke `COLLECT_INVENTORY` (non-destructive, `approvalStatus=NOT_REQUIRED`) ile yapıldı, destructive flow yan-kanıt değil ayrı kapı.
- **IT pilot 22.2** — `acik.local` domain-joined 2 IT-owned PC; `RB-faz22-endpoint-pilot-it-owned.md` ready (gitops #1016 MERGED). Bu Parallels VM workgroup; domain pilot ayrı kapı.
- **Long-soak baseline** — 30+ gün stability + crash recovery + EDR/AV vendor interaction baseline prod-cutover öncesi gerek.
- **Trusted signing + EDR catalog update** — production code-signing cert + EDR vendor whitelist prod cutover scope'unda.

## 8. References

- `platform-agent` PR #10 — TRACKING-ROADMAP.md AG-013 row update (`Verified 2026-05-24`)
- `platform-agent` main HEAD `2e49f8b` — BE-011 wire reconciliation (PR #9)
- `platform-agent` PR #7 — AG-013 capability mismatch fix (executor coherence)
- `docs/runbooks/RB-faz22-endpoint-pilot-it-owned.md` — IT pilot 22.2 readiness (gitops #1016)
- `docs/state/current-state.md` 2026-05-24 Live Delta — Faz 22 Web RTK fetchFn unwrap + Faz 23 M7 truth-sync
- `docs/session-handoff-2026-05-24-faz22-faz23-m7.md` §5 P1 — operator queue list (now: BE-011 + #8 yan-kanıt yakalandı)
- `bootstrap/openfga/endpoint-admin-tuples.json` — persona tuple shape reference

## 9. Audit trail

- Implementer Claude (Anthropic); Reviewer Codex (OpenAI) — provider-level cross-AI HARD RULE per PR
- Evidence doc docs-only; no cluster manifest mutation
- Smoke operation level: state-mutation (test cluster) + credential-write (test persona pw reset + rotate to random unknown post-smoke); not operator login user
- **Boundary — no browser/UI verification required**: this smoke is a CLI-level agent service lifecycle (PowerShell `Get-Service`, `sc.exe`, agent binary stdout, backend REST API via `curl`, DB-side audit row via test persona JWT against `/api/v1/endpoint-admin/audit-events`). HARD RULE — "Tarayıcıdan Sonuç Doğrulanmadan İş Bitmedi" applies to frontend/UI changes; this PR carries zero frontend/UI delta and the underlying smoke does not exercise a browser flow. Faz 22 frontend RTK fetchFn unwrap browser smoke was captured separately in `docs/faz-22-evidence/2026-05-24-allow-path-browser-smoke.md` (gitops PR #1004 MERGED).
- Tracked by platform-agent#8 + gitops handoff §5 P1
