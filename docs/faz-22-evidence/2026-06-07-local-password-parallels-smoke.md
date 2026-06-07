# Faz 22 AG-042 — Local Password / Lock / Unlock Parallels Smoke

**Date**: 2026-06-07 16:48 Istanbul / 13:48Z UTC
**Scope**: local Parallels Windows 11 only
**Device**: `HALILKOOLUB735` (`Windows 11`, local non-domain lab baseline)
**Repo source**: `platform-agent origin/main` at `690d39943404b6d458b44e9582a0e8589af2eb32`
**Test binary**: `endpoint-agent-users-localpwd.test.exe`
**Binary SHA256**: `8da4c6d2a225a8234314a2f43711b5678ad9ced5f5e821685c6d49ff4b95ecd8`

## Purpose

Prove the agent-side Windows SAM local-user mutation adapter on a disposable
local account:

- `LOCK_USER_LOGIN`
- `UNLOCK_USER_LOGIN`
- `CHANGE_LOCAL_PASSWORD`

This is **not** a backend/JWT/dual-control dispatch proof. It proves the
Windows agent adapter can mutate only a temporary local SAM account and that
password material is not echoed in the test result.

## Command

Mac side:

```bash
git worktree add /tmp/platform-agent-phase22-localpwd origin/main
cd /tmp/platform-agent-phase22-localpwd
go test ./internal/users ./internal/commands ./internal/inventory
GOOS=windows GOARCH=arm64 go test -c ./internal/users \
  -o /tmp/endpoint-agent-users-localpwd.test.exe
shasum -a 256 /tmp/endpoint-agent-users-localpwd.test.exe
cp /tmp/endpoint-agent-users-localpwd.test.exe \
  /Users/halilkocoglu/tmp/codex-faz22/endpoint-agent-users-localpwd.test.exe
prlctl exec "Windows 11" powershell.exe -NoProfile -ExecutionPolicy Bypass \
  -File "\\Mac\Home\tmp\codex-faz22\local-password-smoke.ps1"
```

Local Go unit checks:

```text
ok   platform-agent/internal/users      0.379s
ok   platform-agent/internal/commands   0.575s
ok   platform-agent/internal/inventory  0.957s
```

## Windows Result

The PowerShell harness created a temporary `ea-*` local account, ran the
Windows integration test, and removed the account in cleanup.

```json
{
  "status": "PASS",
  "userName": "ea-pwd-0607a",
  "binaryPath": "\\\\Mac\\Home\\tmp\\codex-faz22\\endpoint-agent-users-localpwd.test.exe",
  "binarySha256": "8da4c6d2a225a8234314a2f43711b5678ad9ced5f5e821685c6d49ff4b95ecd8",
  "created": true,
  "existedBeforeCleanup": true,
  "removedAfterCleanup": true,
  "exitCode": 0,
  "testOutput": "=== RUN   TestMutateLocalWindowsIntegration\n--- PASS: TestMutateLocalWindowsIntegration (0.04s)\nPASS",
  "secretEchoed": false
}
```

## D29 Interpretation

| Layer | Evidence | Verdict |
|---|---|---|
| Up | Parallels Windows 11 VM reachable through `prlctl exec`; shared Mac path readable; command ran elevated/admin-capable | PASS |
| Functional | Temporary local SAM user created; `LOCK_USER_LOGIN`, `UNLOCK_USER_LOGIN`, `CHANGE_LOCAL_PASSWORD` all passed through `TestMutateLocalWindowsIntegration` | PASS |
| Secured | Test refuses non-lab account names; adapter RID guard is present in source; temporary user removed; password result did not echo the new password | PASS for local adapter scope |
| Zanzibar / backend dispatch | Not exercised in this run | Pending separate backend/JWT/dual-control smoke |

## Boundaries

- This test mutates only a disposable local SAM account named `ea-pwd-0607a`.
- No domain, M365, Entra, AD, cached credential, pre-logon VPN, SMB/file action
  or production endpoint was touched.
- This does not satisfy `platform-agent#92`, which tracks operator-gated
  backend-to-agent `LOCK_USER_LOGIN` dispatch with two distinct admin JWTs.
- This does not satisfy gitops `#1044` multi-device + 24h observation; it is a
  local Parallels proof to speed development before the user-owned device batch.
