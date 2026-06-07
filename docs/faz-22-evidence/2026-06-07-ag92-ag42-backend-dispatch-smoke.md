# Faz 22 Evidence — AG-092 / AG-042 backend-to-agent dispatch smoke

Date: 2026-06-07

## Scope

This evidence records two local Parallels Windows 11 dispatch smokes against
the enrolled endpoint device `d0efb00a-681a-4e32-b7de-a27ef94f2977`
(`HALILKOOLUB735`):

- `LOCK_USER_LOGIN` command-specific dispatch with reserved built-in account
  guard validation.
- `CHANGE_LOCAL_PASSWORD` dispatch on a disposable local SAM account.

This is **testai + local Parallels Windows** evidence. It is not domain password
reset evidence, cached domain credential proof, M365/Entra reset evidence,
SMB/file action evidence, `acik.local` IT pilot evidence, or #1044 two-device
plus 24h observation evidence.

## Source / helper chain

| PR | Repo | Purpose | Result |
|---|---|---|---|
| #95 | `platform-agent` | Add AG-042 local password smoke helper and runbook | MERGED, checks PASS |
| #96 | `platform-agent` | Parse terminal `FAILED` guard results via `lastError` / result payload | MERGED, checks PASS |
| #97 | `platform-agent` | Fix macOS/bash report `printf --` handling | MERGED, checks PASS |
| #98 | `platform-agent` | Make synthetic Windows local-user creation description length safe | MERGED, checks PASS |
| #99 | `platform-agent` | Keep redacted smoke evidence JSON-valid | MERGED, checks PASS |

## AG-092 LOCK_USER_LOGIN dispatch smoke

| Field | Value |
|---|---|
| Evidence dir | `/tmp/faz22-live-smoke/ag92-lock-final-20260607T162200Z` |
| Report | `/tmp/faz22-live-smoke/ag92-lock-final-20260607T162200Z/report.md` |
| Command ID | `2825b275-4f31-4324-9ad6-a96e08d8b27e` |
| Command type | `LOCK_USER_LOGIN` |
| Target user | `Administrator` |
| Approval status | `APPROVED` |
| Terminal status | `FAILED` |
| Failure reason | `LOCK_USER_LOGIN username "Administrator" is a reserved built-in account and cannot be targeted by a remote command` |
| VM before/after | unchanged as expected |
| Issue | `platform-agent#92` acceptance comment added; issue state `CLOSED` |

Interpretation: the backend command reached the agent executor and the Windows
adapter enforced the reserved built-in Administrator guard without mutating the
VM account state.

## AG-042 CHANGE_LOCAL_PASSWORD dispatch smoke

| Field | Value |
|---|---|
| Evidence dir | `/tmp/faz22-live-smoke/ag42-local-password-final-20260607T163900Z` |
| Report | `/tmp/faz22-live-smoke/ag42-local-password-final-20260607T163900Z/report.md` |
| Command ID | `c06cd030-c62e-40da-814d-90956e960eaa` |
| Command type | `CHANGE_LOCAL_PASSWORD` |
| Target user | `ea-recovery-smoke` |
| Test account type | disposable local SAM account created by the smoke helper |
| Approval status | `APPROVED` |
| Terminal status | `SUCCEEDED` |
| Result summary | `CHANGE_LOCAL_PASSWORD applied` |
| VM before/after | changed as expected |
| Cleanup proof | `Get-LocalUser ea-recovery-smoke` returned `ABSENT` after helper cleanup |
| Issue | `platform-agent#94` post-close live evidence comment added |

Interpretation: the backend command reached the agent executor, the local
Windows password-change adapter applied the command to a disposable local user,
and the helper removed that user after collecting evidence.

## Secret hygiene

- Auth configs were passed as local `curl -K` files and were not printed.
- Temporary auth directory `/tmp/ag42-auth.bixUyo` was removed after the smokes.
- Evidence scan found no raw `Bearer`, JWT, `Authorization`, or local password
  material in the AG-092 / AG-042 evidence directories.
- Sensitive result fields are redacted and remain JSON-valid after PR #99.

## Remaining gates

- #1044 remains user-owned for two additional devices plus observation roll-up.
- #1037 / #1015 remain `acik.local` IT-pilot gates.
- Domain password / cached credential behavior remains a separate connector and
  pre-logon / VPN design lane; this evidence proves local Windows SAM command
  dispatch only.
