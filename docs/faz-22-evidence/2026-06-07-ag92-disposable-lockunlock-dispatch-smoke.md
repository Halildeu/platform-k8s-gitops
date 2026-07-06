# Faz 22 Evidence - AG-092 disposable lock/unlock backend-to-agent smoke

Date: 2026-06-07

## Scope

This evidence records a backend-to-agent dual-control smoke for
`LOCK_USER_LOGIN` and `UNLOCK_USER_LOGIN` against a disposable local Windows
SAM account on the enrolled Parallels Windows 11 endpoint device
`d0efb00a-681a-4e32-b7de-a27ef94f2977` (`HALILKOOLUB735`).

This is **testai + local Parallels Windows** evidence. It proves local Windows
SAM lock/unlock dispatch and execution for a disposable local account. It is
not domain password reset evidence, cached domain credential proof, M365/Entra
reset evidence, SMB/file action evidence, `acik.local` IT pilot evidence,
#1044 two-device plus observation evidence, or pre-logon VPN evidence.

## Smoke setup

| Field | Value |
|---|---|
| Evidence dir | `/tmp/faz22-live-smoke/ag92-lockunlock-disposable-20260607T172110Z` |
| Report | `/tmp/faz22-live-smoke/ag92-lockunlock-disposable-20260607T172110Z/report.md` |
| API base | `https://testai.acik.com` |
| Device ID | `d0efb00a-681a-4e32-b7de-a27ef94f2977` |
| VM | `Windows 11` |
| Target local account | `ea-lockunlock-smoke` |
| Target account type | Disposable local SAM account created by the smoke helper |
| Auth model | Distinct proposer and approver personas with `can_manage module:endpoint-admin` tuples |
| Helper | `/tmp/faz22-live-smoke/ag92_lockunlock_disposable.sh` |

## LOCK_USER_LOGIN result

| Field | Value |
|---|---|
| Command ID | `a8dfaac1-1c3b-4f4f-84cd-77b62c2bd553` |
| Command type | `LOCK_USER_LOGIN` |
| Approval status | `APPROVED` |
| Terminal status | `SUCCEEDED` |
| Result summary | `LOCK_USER_LOGIN applied` |
| Result detail | `localUser.disabled=true`, `localUser.lockedOut=false` |
| VM state before | `Enabled=true`, `Present=true` |
| VM state after lock | `Enabled=false`, `Present=true` |

Interpretation: the backend command reached the agent executor, dual-control
approval was accepted, and the Windows local-account adapter disabled the
disposable local user.

## UNLOCK_USER_LOGIN result

| Field | Value |
|---|---|
| Command ID | `fd62b31e-c84a-4ee7-b1d0-e433c35768e1` |
| Command type | `UNLOCK_USER_LOGIN` |
| Approval status | `APPROVED` |
| Terminal status | `SUCCEEDED` |
| Result summary | `UNLOCK_USER_LOGIN applied` |
| Result detail | `localUser.disabled=false`, `localUser.lockedOut=false` |
| VM state after unlock | `Enabled=true`, `Present=true` |
| Cleanup proof | `net user ea-lockunlock-smoke` returned `The user name could not be found.` after helper cleanup |

Interpretation: the unlock command reached the same endpoint, the agent
re-enabled the disposable local user, and the helper removed that user after
collecting evidence.

## Secret hygiene

- Auth configs were passed as local `curl -K` files and were not printed.
- Evidence scan found no raw `Bearer`, JWT, `Authorization`, password, token,
  or secret material in `/tmp/faz22-live-smoke/ag92-lockunlock-disposable-20260607T172110Z`.
- The disposable local account was removed after the smoke.

## Remaining gates

- #1044 remains user-owned for two additional devices plus observation roll-up.
- #1037 / #1015 remain `acik.local` IT-pilot gates.
- Domain password / cached credential / pre-logon VPN behavior remains a
  separate identity connector and IT-pilot design lane; this evidence proves
  local Windows SAM lock/unlock command dispatch only.
