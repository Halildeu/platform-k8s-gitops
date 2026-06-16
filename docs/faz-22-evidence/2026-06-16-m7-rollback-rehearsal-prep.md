# Faz 22.5 M7 — Same-Day Rollback Rehearsal Prep Evidence

> **Date**: 2026-06-16
> **Issue**: #1379
> **Branch/worktree**: `codex/faz225-rollback-rehearsal-1379` /
> `.worktrees/faz225-rollback-rehearsal-1379`
> **Scope**: agent-doable prep for owner-approved 2-device rollback rehearsal.
> This is **not** full M7 closure.

## 1. Durable Fix Audit

The 2026-06-15/16 Windows pilot problems are now represented in persistent
source/runbook state rather than chat-only commands:

| Problem observed | Durable state |
|---|---|
| `install.ps1` / package friction on standard Windows PowerShell 5.1 | `docs/faz-22-software-deployment-plan.md` records platform-agent PR #102 as PS5.1-safe installer packaging with UTF-8 BOM handling. |
| Wrong/short AG-038 `configHash` and silent result-submit failures | `docs/faz-22-software-deployment-plan.md` records AG-038 full `configHash` and backend result-submit 4xx/5xx visibility as M0 hardening. |
| Temporary ZIP/manual token workflow was too fragile for 800 PCs | `docs/runbooks/RB-faz22-m1-artifact-host.md` and `docs/runbooks/RB-faz22.3-edge-mtls-autoenroll.md` document canonical `current` artifact host + one-command bootstrap shape. |
| mTLS DNS/edge path drift (`endpoint-agent-mtls...` vs `mtls.*`) | ADR-0029 and M2 runbooks now use `mtls.testai.acik.com` for test/pilot and `mtls.ai.acik.com` for prod. |
| Prod `mtls.ai.acik.com` needed ssl-passthrough activation | `docs/faz-22-evidence/2026-06-15-m2-prod-mtls-ai-activation.md` and current-state record PR #1593/#1594 evidence and ingress-nginx ssl-passthrough. |
| Rollback evidence collection was manual and scattered | This branch adds `scripts/faz22-mass-deployment/m7-rollback-rehearsal-collector.ps1` and runbook §0 same-day 2-device rehearsal lane. |

## 2. New Agent-Doable Artifact

`scripts/faz22-mass-deployment/m7-rollback-rehearsal-collector.ps1`

- PS5.1-compatible.
- Read-only evidence collector.
- Phases:
  - `baseline`
  - `rollback-clean`
  - `reinstall-continuity`
- Does not install, uninstall, decommission, reactivate, mutate GPO, read
  secrets, or submit data to backend.
- Writes JSON evidence to:

```text
C:\ProgramData\EndpointAgent\evidence\m7-rollback-rehearsal\*.json
```

## 3. Validation

```text
git diff --check
PowerShell parser OK:
[System.Management.Automation.Language.Parser]::ParseFile(
  "scripts/faz22-mass-deployment/m7-rollback-rehearsal-collector.ps1"
)
```

## 4. Remote Execution Boundary

Codex attempted to use the previously opened reverse-SSH path for live Windows
execution:

```text
ssh staging-sw / halil@10.9.10.53 -> connection refused or key rejected
localhost:22022 -> connection refused
localhost:22024 -> connection refused
```

Therefore this session could not execute the collector on Denetim PC or
ERP-MOBIL from the Codex host. This is not treated as a runtime pass.

Later in the same evidence window, the operator restored the Denetim PC reverse
SSH path through staging (`10.9.10.53`), and Codex stabilized local macOS SSH
access by exporting the launchd SSH agent socket. Subsequent Denetim PC runtime
evidence in sections 6 and 7 was collected over that restored path.

## 5. Local-Control Runtime Rehearsal Evidence

After the reverse-SSH route became unavailable, Codex used the local Parallels
Windows 11 VM (`HALILKOOLUB735`) as the safe local-control device. This does
not replace domain-GPO evidence, but it proves the same-day rollback collector,
preserve-config uninstall path, HMAC-preserving reinstall path, and
post-reinstall service continuity on a real Windows endpoint.

| Phase | File | Overall | Fail | Warn | SHA256 |
|---|---|---:|---:|---:|---|
| baseline | `.runtime-evidence/HALILKOOLUB735/20260616-080748Z-HALILKOOLUB735-baseline.json` | PASS-WITH-WARN | 0 | 1 | `b65967ba520a68e1b498fea5e5ae96bb81eaaca5a5450750f37234ad351912f1` |
| rollback-clean | `.runtime-evidence/HALILKOOLUB735/20260616-082315Z-HALILKOOLUB735-rollback-clean.json` | PASS | 0 | 0 | `aaea53e3e694bebe8ac75e497f01ef1d4a9105a3531d00fc184ff7d55071529f` |
| reinstall-continuity | `.runtime-evidence/HALILKOOLUB735/20260616-082338Z-HALILKOOLUB735-reinstall-continuity.json` | PASS | 0 | 0 | `92cc24b1601023ef7caebdb0b9211ee1aff5fa4b89ac7031ded7f8a96f77f06e` |

Rehearsal runner:

```text
.runtime-evidence/HALILKOOLUB735/m7-local-w11-rehearsal-runner.ps1
SHA256: 54592185df930307588a361455a15e361c45f2c80665693eb2f893ab9d4da220
```

Local Windows step log:

```text
2026-06-16T11:23:12+03:00 PRE-STATE
2026-06-16T11:23:12+03:00 BEGIN UNINSTALL-PRESERVE-CONFIG-LOGS
2026-06-16T11:23:13+03:00 END UNINSTALL-PRESERVE-CONFIG-LOGS exit=0
2026-06-16T11:23:13+03:00 BEGIN COLLECT-ROLLBACK-CLEAN
2026-06-16T11:23:15+03:00 END COLLECT-ROLLBACK-CLEAN exit=0
2026-06-16T11:23:15+03:00 BEGIN INSTALL-CURRENT-PRESERVE-HMAC
2026-06-16T11:23:16+03:00 END INSTALL-CURRENT-PRESERVE-HMAC exit=0
2026-06-16T11:23:36+03:00 BEGIN COLLECT-REINSTALL-CONTINUITY
2026-06-16T11:23:38+03:00 END COLLECT-REINSTALL-CONTINUITY exit=0
2026-06-16T11:23:38+03:00 POST-STATE
2026-06-16T11:23:38+03:00 END M7 local-control rollback rehearsal
```

Post-state:

```text
EndpointAgent service: Running / Automatic
endpoint-agent version: v0.2.5
```

Important boundary:

- This proves local-control rollback/reinstall continuity.
- This does **not** prove domain-GPO propagation or the 2-device denominator.
- Therefore #1379 remains open until domain-GPO/selected-pilot evidence is
  attached or the acceptance boundary is explicitly narrowed by the owner.

## 6. Denetim PC Domain-GPO Baseline Evidence

After the reverse-SSH route recovered, Codex ran the collector on the selected
domain-joined Denetim PC (`SRB-AIDENETIMPC`) in non-destructive baseline mode.
This proves the domain-GPO baseline is healthy, but does not execute the
rollback-clean or reinstall-continuity phases on that device.

| Phase | File | Overall | Fail | Warn | SHA256 |
|---|---|---:|---:|---:|---|
| baseline | `.runtime-evidence/SRB-AIDENETIMPC/20260616-083459Z-SRB-A_DENET_MPC-baseline.json` | PASS | 0 | 0 | `d64a3c7bdef87ec082e2ccae687b3e344b74c1b274233539bd58d924e3aa21e7` |

Runtime facts:

```text
Computer: SRB-AIDENETIMPC
Domain: acik.local
EndpointAgent service: Running / Automatic
Machine cert: CN=SRB-AIDENETIMPC.acik.local
Issuer: CN=Acik-Endpoint-CA, DC=acik, DC=local
Cert thumbprint: 1687D3C41443239A12ECA973E6EED87B0876B068
Executable signature: Valid, signer D68F4F530137EB65CE44E3405E82B46205E753E5
Backend TCP: PASS mtls.testai.acik.com:443
```

Important boundary:

- This proves a selected domain-GPO device baseline is ready.
- This does **not** prove backend enrollment revoke/decommission/reactivate.

## 7. Denetim PC Domain-GPO Rollback/Reinstall Evidence

Codex then ran the same-day rehearsal on the same domain-joined Denetim PC
(`SRB-AIDENETIMPC`). This was a real Windows runtime rollback/reinstall pass:

1. collect baseline
2. uninstall EndpointAgent with config/log preservation
3. collect rollback-clean
4. reinstall EndpointAgent with auto-enroll mode
5. collect reinstall-continuity

| Phase | File | Overall | Fail | Warn | SHA256 |
|---|---|---:|---:|---:|---|
| baseline | `.runtime-evidence/SRB-AIDENETIMPC-domain-rehearsal/m7-denetim-domain-gpo-rehearsal-20260616-092304Z/baseline-collector-output.utf8.json` | PASS | 0 | 0 | `5466aaba5d4090a4f799588cfcb6aca1ed3e60ca6ab9850b06a8c21ae4c59a23` |
| rollback-clean | `.runtime-evidence/SRB-AIDENETIMPC-domain-rehearsal/m7-denetim-domain-gpo-rehearsal-20260616-092304Z/rollback-clean-collector-output.utf8.json` | PASS | 0 | 0 | `4622ce5cac50e6e4266f07c1dd26f5628405a80ea395351f2d01bae88ff568a9` |
| reinstall-continuity | `.runtime-evidence/SRB-AIDENETIMPC-domain-rehearsal/m7-denetim-domain-gpo-rehearsal-20260616-092304Z/reinstall-continuity-collector-output.utf8.json` | PASS | 0 | 0 | `21958ed92c5d784f1d7908c9d6ea3bed744fbb37a4f06aac362a53d24eab3b2a` |

Raw collector outputs are preserved as the remote PowerShell UTF-16LE files:

```text
77a26b70d462b3f61181d2e09e3cddf8033f0e5564b99c19230ab20f84ae0204  baseline-collector-output.json
2aee0b6dca9fdff471610c60e915a9d1dc8502fb68d8493c438eda9ce11df6de  rollback-clean-collector-output.json
baf8e555beee98449df7612a9fe9f9fee7d03717799dd3d9c3b7061047b9387b  reinstall-continuity-collector-output.json
```

Runtime step log:

```text
2026-06-16T12:23:04+03:00 PRE-STATE
2026-06-16T12:23:05+03:00 COLLECT-BASELINE
2026-06-16T12:23:11+03:00 BEGIN UNINSTALL-PRESERVE-CONFIG-LOGS
2026-06-16T12:23:12+03:00 END UNINSTALL-PRESERVE-CONFIG-LOGS
2026-06-16T12:23:12+03:00 COLLECT-ROLLBACK-CLEAN
2026-06-16T12:23:21+03:00 BEGIN INSTALL-AUTO-ENROLL
2026-06-16T12:23:26+03:00 END INSTALL-AUTO-ENROLL
2026-06-16T12:24:11+03:00 COLLECT-REINSTALL-CONTINUITY
2026-06-16T12:24:16+03:00 POST-STATE
2026-06-16T12:24:17+03:00 M7_DENETIM_DOMAIN_GPO_REHEARSAL_DONE
```

Key facts:

```text
EndpointAgent service: Running / Auto / LocalSystem after reinstall
endpoint-agent.exe SHA256: 5917B45B7BBB8EAA675B6E450961D75582BFC67BD4A01A76332CA1C507D91ABE
Machine cert thumbprint: 1687D3C41443239A12ECA973E6EED87B0876B068
Signer thumbprint: D68F4F530137EB65CE44E3405E82B46205E753E5
auto-enroll.dpapi: preserved across uninstall/reinstall
Remote evidence zip SHA256: 9BF1E05F98AA52718F370C9D3A6F158FEA287092C3E38245BC08882FB6FEE427
```

Important boundary:

- This proves selected domain-GPO device rollback-clean and
  reinstall-continuity.
- This does **not** prove backend enrollment revoke/decommission/reactivate.
- This does **not** prove GPO unlink/security-filter rollback propagation time.
- This does **not** close the 50-PC / M6 expansion denominator.

Issue evidence comment:

```text
https://github.com/Halildeu/platform-k8s-gitops/issues/1379#issuecomment-4716977942
```

## 8. Backend Lifecycle Evidence

Codex then ran a live backend lifecycle smoke against the `testai` /
`platform-test` endpoint-admin API using the existing test persona
`c5persona-admin-9001`. The script set a short-lived persona password, minted a
JWT in-process, rotated the persona password back to an unknown random value at
exit, and persisted only redacted evidence.

Target device:

```text
hostname: SRB-AIDENETIMPC
deviceId: 423b6fc3-7497-4083-bd2f-5e2fe543bfe9
preStatus: ONLINE
reactivate response status: OFFLINE
post-wait status: ONLINE
```

Flow:

1. `GET /api/v1/endpoint-admin/endpoint-devices` returned HTTP `200`.
2. Created a future-visible `COLLECT_INVENTORY` command so the real agent could
   not claim it during the smoke.
3. `POST /endpoint-devices/{id}/decommission` returned HTTP `200` and
   `status=DECOMMISSIONED`.
4. The future-visible command was cascade-cancelled:
   command `8bfe3af8-aba9-4100-9a55-15d365bebd5e` became `CANCELLED`.
5. A new command-create attempt while the device was decommissioned returned
   HTTP `409` with:

```text
Endpoint device is decommissioned; reactivate it before creating new operations.
```

6. `GET /endpoint-audit-events?...ENDPOINT_DEVICE_DECOMMISSIONED` returned
   HTTP `200` and showed `ONLINE -> DECOMMISSIONED`.
7. `POST /endpoint-devices/{id}/reactivate` returned HTTP `200` and
   `status=OFFLINE`.
8. After a short wait, the real agent heartbeat returned the device to
   `ONLINE`.
9. `GET /endpoint-audit-events?...ENDPOINT_DEVICE_REACTIVATED` returned
   HTTP `200` and showed `DECOMMISSIONED -> OFFLINE`.

Evidence summary:

```text
.runtime-evidence/backend-lifecycle/m7-backend-lifecycle-20260616-093940Z/summary.json
SHA256: 396f6b15f3bab2b63ff0af4bb08e5e63bed172960610ef31a4cb8824f0e20824
overall: PASS
```

Main-tracked LF-normalized, scanner-safe JSON evidence copies:

```text
docs/faz-22-evidence/raw/2026-06-16-m7-rollback-rehearsal/HALILKOOLUB735-baseline.json
docs/faz-22-evidence/raw/2026-06-16-m7-rollback-rehearsal/HALILKOOLUB735-rollback-clean.json
docs/faz-22-evidence/raw/2026-06-16-m7-rollback-rehearsal/HALILKOOLUB735-reinstall-continuity.json
docs/faz-22-evidence/raw/2026-06-16-m7-rollback-rehearsal/SRB-AIDENETIMPC-baseline.json
docs/faz-22-evidence/raw/2026-06-16-m7-rollback-rehearsal/SRB-AIDENETIMPC-rehearsal-baseline.json
docs/faz-22-evidence/raw/2026-06-16-m7-rollback-rehearsal/SRB-AIDENETIMPC-rollback-clean.json
docs/faz-22-evidence/raw/2026-06-16-m7-rollback-rehearsal/SRB-AIDENETIMPC-reinstall-continuity.json
docs/faz-22-evidence/raw/2026-06-16-m7-rollback-rehearsal/SRB-AIDENETIMPC-backend-lifecycle-summary.json
```

Main-tracked JSON SHA256 index:

```text
7a4ed9852c09a674ed12854306218cb3f64aaa39394a30789f3ffe211e6bce01  HALILKOOLUB735-baseline.json
ac8a2bbdeb712f74696110d485243b09300b50d9fa32526d374c9969f6e7930e  HALILKOOLUB735-rollback-clean.json
7ec049fd9e934f20c1e3350cc673cb1298dd3fea1b79a6eea05a21a8b28fcd6f  HALILKOOLUB735-reinstall-continuity.json
8f7f5d4b92731d07a3e4570e46656afa586d6cf42ec11e136d225f3978ab8bb2  SRB-AIDENETIMPC-baseline.json
19560554baba1cadb2eb8b59926fc1bbbc6d055768af8a8b5d5e19b8d091eab5  SRB-AIDENETIMPC-rehearsal-baseline.json
62b0de10351de71d6a607ee624f8155ef55203c5a7d6b8029b1cda951076e1d2  SRB-AIDENETIMPC-rollback-clean.json
660dc65f1d3e31d8bbef1a10ff4954c0d7391ec79d22f49fcc8ebfeda5562299  SRB-AIDENETIMPC-reinstall-continuity.json
eb7e4727f28d1a16676cb197826194a3430e3e9ad7330c5d0c63c848e0208855  SRB-AIDENETIMPC-backend-lifecycle-summary.json
```

Raw evidence hash highlights:

```text
c610d69d628fe948ac2b4963e55b26bb037550b15c16fa89f3af83585a0fe926  audit-decommission.json
bc04f82f56cf3474be413611b73c1ef2e3148613c7ff2b750e0a97d5de45199b  audit-reactivate.json
03e740ccb1ec4997bb9f7ec1eb5b296759d557fce3715ee6c0c7013a223a77b6  command-after-decommission.json
71837d93cdd0ca42a6eab77f2bde25614883743d15580d21ee194b626fd30602  create-command-while-decommissioned-response.json
4794e6852e5a8dfe6c3dba6a77d42b017c902d38562d87cde93ce313efc40a85  decommission-response.json
5d16f6918fd35b5a9b92a00f811bede2b9775d01900f1b3fb2144ad427e0c5de  reactivate-response.json
```

Secret hygiene:

```text
TOKEN_TMP_REMOVED
SECRET_SCAN_OK
```

Targeted backend source tests also passed locally:

```text
./mvnw -pl endpoint-admin-service \
  -Dtest=EndpointDeviceDecommissionLifecyclePostgresIntegrationTest,EndpointDeviceDecommissionedWriteGuardPostgresIntegrationTest,MachineCertAutoEnrollServiceTest \
  test

Tests run: 23, Failures: 0, Errors: 0, Skipped: 0
```

Important boundary:

- This proves backend decommission/reactivate, cascade-cancel, command-create
  409 fail-close, and lifecycle audit visibility on the selected device.
- This does **not** prove GPO unlink/security-filter rollback propagation time.
- This does **not** close the 50-PC / M6 expansion denominator.

## 9. GPO Propagation Mutation Boundary

Codex attempted the next agent-doable M7 layer: a temporary GPO marker smoke
that would create a short-lived GPO, link it to `OU=EndpointTest`, force
computer policy on `SRB-AIDENETIMPC`, verify the marker appeared, unlink the
GPO, force policy again, and verify the marker disappeared.

The mutation was attempted from the domain-joined Windows Server
`ERP-MOBIL` over SSH as `acik\ca.setup`, which is a Domain Admin and
Enterprise Admin member. The account identity and local admin token were
present, but the SSH logon did not carry usable network credentials to the DC.
This made GPO/SYSVOL operations fail before any temporary GPO could be
created.

Observed failure signals:

```text
whoami: acik\ca.setup
whoami /upn: ca.setup@acik.local
groups: ACIK\Domain Admins, ACIK\Enterprise Admins, BUILTIN\Administrators

klist get ldap/ACIKDC01.acik.local:
  0x8009030e / No credentials are available in the security package

klist get cifs/ACIKDC01.acik.local:
  0x8009030e / No credentials are available in the security package

Test-Path \\ACIKDC01.acik.local\SYSVOL\acik.local\Policies:
  False

Get-GPO -All -Domain acik.local -Server ACIKDC01.acik.local:
  E_ACCESSDENIED / Access is denied
```

Interpretation:

- This is a Windows SSH/Kerberos network-credential boundary, not evidence that
  the GPO design is wrong.
- The current Codex-controlled SSH channel is sufficient for local host checks,
  service state, file evidence, agent rollback/reinstall, and backend API
  lifecycle tests.
- It is not sufficient for DC-backed GroupPolicy mutation from `ERP-MOBIL`
  because the SSH session lacks usable LDAP/CIFS tickets for `ACIKDC01`.
- The remaining GPO unlink/security-filter propagation smoke therefore needs a
  DC/RDP/interactive domain-admin execution path, a proper WinRM/CredSSP-style
  delegated credential path, or a pre-authorized DC-side runner.

Partial attempt artifacts:

```text
.runtime-evidence/gpo-propagation/m7-gpo-propagation-20260616-094745Z/erp-create.ps1
.runtime-evidence/gpo-propagation/m7-gpo-propagation-20260616-094745Z/erp-create.json  # empty because create failed before JSON output
```

## 10. Status

| Gate | Status |
|---|---|
| #1379 board status | Blocked/open; local-control drill + Denetim domain-GPO rollback/reinstall + backend lifecycle evidence attached |
| M7 full closure | Not closed |
| Local-control rollback/reinstall drill | PASS on HALILKOOLUB735 |
| Domain-GPO baseline | PASS on SRB-AIDENETIMPC |
| Domain-GPO rollback/reinstall drill | PASS on SRB-AIDENETIMPC |
| Backend decommission/reactivate | PASS on SRB-AIDENETIMPC via testai/platform-test |
| GPO unlink/security-filter rollback propagation | Pending; Codex SSH path is blocked by no DC network credentials for GroupPolicy/SYSVOL |
| 50-PC/M6 dependency | Still open under #1378 |

## 11. Next Runtime Command Shape

On a selected Windows device with the repo script available:

```powershell
.\m7-rollback-rehearsal-collector.ps1 -Phase baseline -DeviceRole domain-gpo -RequireMachineCert -Json
.\m7-rollback-rehearsal-collector.ps1 -Phase rollback-clean -DeviceRole domain-gpo -Json
.\m7-rollback-rehearsal-collector.ps1 -Phase reinstall-continuity -DeviceRole domain-gpo -RequireMachineCert -Json
```

Attach the three JSON files to #1379 before any `Needs Verify` or closure move.
