# Faz 22.2.A — Parallels Windows 11 CI pilot rehearsal workflow_dispatch evidence

> **Date**: 2026-06-07
> **Scope**: Local Parallels Windows 11 VM (`HALILKOOLUB735`) repeatable lab
> rehearsal through a GitHub Actions self-hosted macOS runner. This evidence
> proves the platform-agent #12 workflow_dispatch path can reach the local
> Parallels VM, run the Windows service smoke, upload sanitized evidence, and
> remove the ephemeral runner. It does **not** prove `acik.local` domain pilot
> acceptance, domain-wide rollout, production readiness, password-reset
> readiness, trusted production signing, or multi-device/24h soak.

## 1. Source and Workflow

| Item | Evidence |
|---|---|
| Repo | `Halildeu/platform-agent` |
| Tracking issue | [platform-agent #12](https://github.com/Halildeu/platform-agent/issues/12) |
| Harness hardening PR | [platform-agent #78](https://github.com/Halildeu/platform-agent/pull/78) |
| Merge commit | `ea3abc7c035f8aa03d2a590fa3f756892970c4ca` |
| Workflow | `Parallels Windows 11 CI pilot rehearsal` |
| Workflow file | `.github/workflows/parallels-windows11-smoke.yml` |
| Run | [27081667910](https://github.com/Halildeu/platform-agent/actions/runs/27081667910) |
| Job | [79928639993](https://github.com/Halildeu/platform-agent/actions/runs/27081667910/job/79928639993) |
| Event | `workflow_dispatch` |
| Head branch / SHA | `main` / `ea3abc7c035f8aa03d2a590fa3f756892970c4ca` |

PR #78 hardened the rehearsal scripts before this run:

- removed `--without-shell` usage that fails on the current Parallels 26 setup,
- avoided stdin-based PowerShell command execution where this environment can
  return empty output,
- treated empty `windows-live.ps1` output as a false-green risk,
- made the A1-A4 classifier fail the main harness when it returns nonzero,
- stripped PowerShell CLIXML/progress noise before JSON parsing,
- fixed `PartOfDomain=false` being parsed as `unknown` through jq fallback
  semantics,
- preserved post-write secret scan behavior.

Cross-AI review for PR #78:

```text
Reviewer: Claude CLI 2.1.87
Verdict: AGREE
Must-fix: none
```

## 2. Ephemeral Self-hosted Runner

The repository initially had no self-hosted runners:

```json
{"runners":[],"total_count":0}
```

An ephemeral runner was registered for this single run:

```text
name: codex-parallels-w11-Halil-MacBook-Pro.local-20260607033348
labels: self-hosted, macOS, ARM64, parallels, windows11
runner: actions-runner-osx-arm64-2.334.0
```

Runner listener accepted the job:

```text
2026-06-07 03:35:12Z: Listening for Jobs
2026-06-07 03:35:35Z: Running job: Parallels W11 smoke (self-hosted Mac + prlctl)
```

After the job, the ephemeral runner removed its local registration material and
the repository runner list returned to empty:

```text
2026-06-07 03:35:56Z: Job Parallels W11 smoke ... completed with result: Succeeded
√ Removed .credentials
√ Removed .runner
Runner listener exit with 0 return code
```

```json
{"runners":[],"total_count":0}
```

## 3. GitHub Actions Result

Run `27081667910` result:

```json
{
  "status": "completed",
  "conclusion": "success",
  "createdAt": "2026-06-07T03:35:31Z",
  "updatedAt": "2026-06-07T03:35:56Z",
  "workflowName": "Parallels Windows 11 CI pilot rehearsal"
}
```

Job `79928639993` result:

| Step | Status |
|---|---|
| Set up job | success |
| Checkout platform-agent | success |
| Runner self-check (preflight) | success |
| Run Parallels W11 CI rehearsal script | success |
| Verify no residual secrets in evidence | success |
| Upload evidence artifact | success |
| Summary boundary reminder | success |
| Complete job | success |

Uploaded artifact:

```json
{
  "name": "parallels-w11-ci-evidence-27081667910",
  "size_in_bytes": 8837,
  "created_at": "2026-06-07T03:35:51Z",
  "expired": false
}
```

Downloaded artifact files:

```text
SHA256SUMS
build.txt
classify/classification.json
classify/run.log
precheck.ps1
precheck.txt
run.log
windows-live.txt
```

## 4. VM Precheck

Runner preflight:

```text
prlctl version 26.3.1 (57396)
```

Workflow precheck captured:

```json
{
  "Hostname": "HALILKOOLUB735",
  "UserName": "WORKGROUP\\HALILKOOLUB735$",
  "Domain": "WORKGROUP",
  "PartOfDomain": false,
  "Workgroup": "WORKGROUP",
  "OSVersion": "10.0.26200",
  "OSBuild": "26200"
}
```

Backend reachability:

```json
{
  "Target": "testai.acik.com:443",
  "Reachable": true
}
```

## 5. A1-A4 Classification

Classifier output:

```json
{
  "tier": "A1",
  "tier_reason": "PartOfDomain=false, ownership=corporate (default) → A1 workgroup/standalone",
  "detection_fields": {
    "PartOfDomain": "false",
    "AzureAdJoined": "NO",
    "WorkplaceJoined": "NO",
    "DomainJoined": "NO",
    "TenantIdHash": "(n/a)",
    "DeviceIdHash": "(n/a)",
    "TenantNameMask": "(n/a)",
    "DeviceNameMask": "(n/a)",
    "MdmEnrolled": "true",
    "MdmDeviceClientIdHash": "(n/a)",
    "MdmOEMVersion": ""
  },
  "machine_baseline": {
    "Hostname": "HALILKOOLUB735",
    "Domain": "WORKGROUP",
    "PartOfDomain": false,
    "Workgroup": "WORKGROUP",
    "OSCaption": "Microsoft Windows 11 Pro for Workstations",
    "OSVersion": "10.0.26200",
    "OSBuild": "26200"
  }
}
```

Classifier secret scan:

```text
post-write secret scan: clean (no JWT/Bearer/password/token/raw-GUID/email/raw-SID)
```

## 6. Build / Package Evidence

The workflow ran `./scripts/build/windows-package.sh` and uploaded
`SHA256SUMS`:

```text
9491b41f7be4d172d4b6e00f13f1050abb4e657ff2593361a075ce5001f2463e  endpoint-agent.exe
a882546bf83946e4db3e06d9841c55320fb58e10bb07f84f4f8d002a351fceb0  install.ps1
317a6d5aa526a4da483b66cf3746a473ac24126fcfdba9797e455998ff18767c  uninstall.ps1
b535271df8cea2848c810769053d1fd24ebf63cb0da3bf5c4913ee1d01f46935  README.md
```

## 7. Windows Service Smoke

`windows-live.ps1` ran through `prlctl exec` and produced non-empty evidence
(`86` lines). Key output:

```text
EndpointAgentCodexTest: RUNNING
[endpoint-agent-live] event log source exists: EndpointAgentCodexTest
[endpoint-agent-live] tamper protection checks
[endpoint-agent-live] read-only local users diagnostic
[endpoint-agent-live] stop service with maintenance token
service stop ok: EndpointAgentCodexTest
EndpointAgentCodexTest: STOPPED
[endpoint-agent-live] live smoke completed
[endpoint-agent-live] cleanup
[endpoint-agent] maintenance token validated
[endpoint-agent] uninstalling service: EndpointAgentCodexTest
service uninstall ok: EndpointAgentCodexTest
[endpoint-agent] removing install directory: C:\Program Files\EndpointAgentCodexTest
[endpoint-agent] removing logs: C:\ProgramData\EndpointAgentCodexTest\logs
[endpoint-agent] uninstall completed
```

The smoke used a temporary service name (`EndpointAgentCodexTest`) and cleaned
it up before the workflow ended.

## 8. BE-011 Hook Boundary

The workflow script reached the optional BE-011 helper step, but no helper was
present in this source tree:

```text
Step 5: BE-011 lifecycle smoke (optional helper)
no helper present at scripts/test/be011-lifecycle-helper.sh — skipping (manual BE-011 flow per gitops PR #1021 §5)
```

Therefore this run proves the self-hosted runner + Parallels + Windows service
smoke path. It does not add a new backend command id / result id / audit row id
for BE-011. The predecessor manual BE-011 lifecycle evidence remains
`docs/faz-22-evidence/2026-05-24-windows-be011-lifecycle.md`.

## 9. D29 Matrix

| Layer | Evidence | Hukum |
|---|---|---|
| Up | Self-hosted runner online, Parallels VM found/running, `prlctl exec` usable | Local rehearsal host and VM reachable |
| Functional | Build/package, A1 classifier, Windows service install/start/status/diagnose/maintenance-token stop/uninstall all passed | Local Windows agent service smoke is repeatable through workflow_dispatch |
| Secured | Post-write secret scans clean; maintenance token required for service stop in `windows-live.ps1` | Evidence sanitization and maintenance-token guard exercised locally |
| Zanzibar-ready | Not in scope for this workflow | OpenFGA persona/tuple authorization remains covered by separate endpoint-admin evidence |

## 10. Remaining Gates

- `acik.local` domain pilot remains separate: domain join, EndpointPilot OU,
  IT-owned device, EDR allowlist and trusted signing are not proven here.
- Multi-device / 24h soak remains open under gitops
  [#1044](https://github.com/Halildeu/platform-k8s-gitops/issues/1044).
- The workflow did not dispatch a fresh BE-011 backend command because the
  optional helper is not present; this is a known boundary, not hidden success.
- Production readiness, password reset readiness and domain-wide rollout
  readiness remain separate gates.
