# Faz 22.5 — platform-agent #101 Parallels Standard-PC Bootstrap Smoke

> **Date**: 2026-06-08
> **Device**: local Parallels Windows 11 `HALILKOOLUB735`
> **Tracked by**: platform-agent #101
> **Related follow-up**: platform-agent #109
> **Boundary**: HMAC fallback bootstrap only. This is not tokenless/domain
> AutoEnroll, not edge mTLS, not MSI/GPO rollout, not two-device/24h soak and
> not production Trusted Signing evidence.

## 1. Artifact Under Test

The smoke used the canonical `platform-agent` #107 test artifact published
through the test artifact host:

| Artifact | Value |
|---|---|
| ZIP URL | `https://testai.acik.com/artifacts/endpoint-agent/0.1.0-dev/EndpointAgent.zip` |
| ZIP SHA256 | `9dcf6c2cab5a7dd1fef16a230f065540e1f2d639e0031038e3fbd8d0a9d26029` |
| standalone bootstrap SHA256 | `7ac13aad5c910a74c59862dfc7faafc3c88187c541b9b5f7af64172427335859` |
| Installed binary SHA256 | `EC7875D2C39ABCD0C08364C78767DB86AF91857A71817A11AF5045E9255BD60C` |
| API URL | `https://testai.acik.com/api/v1/endpoint-agent` |

The package was downloaded directly from the public HTTPS artifact URL,
verified by SHA256, extracted locally and installed from the downloaded
package. No manual ZIP transfer was used for the accepted smoke path.

## 2. First Run Finding: Existing HMAC Store Reuse

The first rerun used `-Force` with a fresh one-time enrollment token on a
machine that already had an EndpointAgent DPAPI HMAC credential store. The
service started, but the agent loaded the existing stored credential instead
of using the newly supplied token:

- prior enrolled device identity was reused from the local HMAC store
- old binary was replaced by the current package
- the fresh enrollment token was not the credential source for that run

This behavior is useful for upgrade continuity, but ambiguous for an operator
who intends a fresh re-enrollment. It is tracked separately by platform-agent
#109:

- existing enrolled machine + normal `-Force` should preserve/upgrade clearly
- existing enrolled machine + `-EnrollmentToken` should either fail fast with a
  clear message or require an explicit reset/fresh-enroll flag
- explicit reset/fresh-enroll should back up/remove the old store, enroll with
  the supplied token, confirm HMAC and clean token material

The first run is therefore **not** counted as the clean #101 acceptance path.

## 3. Accepted Fresh-Store Run

For the accepted standard-PC rerun, the old DPAPI HMAC credential store was
backed up and removed before the public bootstrap was executed with the same
canonical #107 package.

Observed installer/service signals:

| Signal | Evidence |
|---|---|
| Old store handling | credential store backed up and removed before rerun |
| Service | `EndpointAgent` status `Running`; startup type `Automatic`; account `LocalSystem` |
| Process | `endpoint-agent` PID `1120`; path `C:\Program Files\EndpointAgent\endpoint-agent.exe` |
| Binary hash | `EC7875D2C39ABCD0C08364C78767DB86AF91857A71817A11AF5045E9255BD60C` |
| Enroll log | `2026/06/08 14:50:27 agent enrolled` with credential redacted |
| HMAC confirm log | `2026/06/08 14:50:28 hmac credential confirmed` with credential redacted |
| Service env keys after install | `ENDPOINT_AGENT_API_URL`, `ENDPOINT_AGENT_LOG_DIR`, `Path`, `ProgramData`, `SystemRoot`, `TEMP`, `TMP`, `windir` |
| Token cleanup | no `ENDPOINT_AGENT_ENROLLMENT_TOKEN` service env key; temporary token file absent |

No raw enrollment token, JWT, bearer token or HMAC secret is recorded in this
evidence file.

## 4. Backend Device Evidence

Admin API device list showed the Parallels device online after the accepted
run:

```json
{
  "id": "d0efb00a-681a-4e32-b7de-a27ef94f2977",
  "hostname": "HALILKOOLUB735",
  "status": "ONLINE",
  "agentVersion": "0.1.0-dev",
  "updatedAt": "2026-06-08T14:53:22.885723Z"
}
```

## 5. Command Lifecycle Smoke

A non-destructive `COLLECT_INVENTORY` command was queued through the
endpoint-admin API and completed through the live agent:

| Field | Value |
|---|---|
| Command ID | `5482af96-b480-463f-a5a1-2d8b3bcd6aa4` |
| Type | `COLLECT_INVENTORY` |
| Idempotency key | `ea101-collect-20260608T145507Z` |
| Approval | `NOT_REQUIRED` |
| Issued | `2026-06-08T14:54:00.335220230Z` |
| Delivered | `2026-06-08T14:54:22.855644Z` |
| Started | `2026-06-08T14:55:29.702163Z` |
| Completed | `2026-06-08T14:55:49.748484Z` |
| Terminal status | `SUCCEEDED` |
| Result row | `a5bd419c-f5b2-45c6-8679-0dea6638e0db` |

Result payload highlights:

| Field | Value |
|---|---|
| Summary | `Inventory collected` |
| Hostname | `HALILKOOLUB735` |
| OS family | `WINDOWS` |
| Agent version | `0.1.0-dev` |
| Software app count | `17` |
| WinGet ready | `true` |
| WinGet version | `1.28.240` |
| WinGet egress package query | `7zip.7zip` found |
| Hardware supported | `true` |
| Domain joined | `false` |
| Model | `Parallels ARM Virtual Machine` |
| Diagnostics configHash | `0b637676053e2acaf4557ac4344e0ced79e48e63d60850203ebfbd61747a12b5` |
| Backend DNS reachable | `true` |
| Backend TLS valid | `true` |

Additional payload facts observed but not used as pass/fail gates:

- `deviceHealth.anyLowDisk=true` because the VM `C:` drive had low free space
- Windows Defender definition update `KB2267602` was pending
- `startupExposure.probeComplete=false` with redacted probe errors

## 6. Audit Evidence

Two relevant audit events were observed:

| Event | Audit ID | Timestamp | Evidence |
|---|---|---|---|
| `ENDPOINT_COMMAND_CREATED` | `9711ee57-9d47-4945-8a74-b0adbf415dd5` | `2026-06-08T14:54:00.340201Z` | command type `COLLECT_INVENTORY`, idempotency key `ea101-collect-20260608T145507Z`, approval `NOT_REQUIRED` |
| `ENDPOINT_SOFTWARE_INVENTORY_REPLACED` | `f221ad3a-b428-4d17-a9cd-cd64ea97dc1d` | `2026-06-08T14:54:43.229729Z` | appCount `17`, appsStoredCount `17`, wingetReady `true`, wingetEgressIngested `true`, commandResultId `a5bd419c-f5b2-45c6-8679-0dea6638e0db` |

## 7. Projection Note

The command response contained the full result payload under
`result.payload`, including `payload.summary="Inventory collected"` and
inventory details. The top-level projection fields `resultSizeBytes` and
`result.summary` were still `null` in the API response. This did not block the
command lifecycle or inventory ingest, but it is worth tracking separately if
the UI/runbook expects those projection fields to be populated.

## 8. D29 Interpretation

| Layer | Evidence | Judgment |
|---|---|---|
| Up | Windows service `Running`; process alive; backend device `ONLINE` | PASS for HMAC fallback standard-PC smoke |
| Functional | public artifact download + SHA verify + install + enroll + HMAC confirm + token cleanup + `COLLECT_INVENTORY` `SUCCEEDED` | PASS for #101 standard-PC rerun |
| Secured / Zanzibar-ready | Admin API used role-bearing endpoint-admin JWT; no raw token stored in docs; command was non-destructive | Limited to existing endpoint-admin auth path, not a new Zanzibar persona smoke |
| D30 / rollout | Artifact hash recorded; no MSI/GPO/domain AutoEnroll path used | Does not prove 800-PC rollout |

## 9. Remaining Boundaries

- platform-k8s-gitops #1359 remains blocked on DNS/edge mTLS activation for
  tokenless domain AutoEnroll.
- platform-agent #109 tracks the existing-credential-store reinstall guard.
- #1044 two-device/24h soak remains a separate user/operator-owned evidence
  gate.
- Snapshot rollback was not taken before this Parallels run because the local
  host did not have enough free disk for a VM snapshot.
