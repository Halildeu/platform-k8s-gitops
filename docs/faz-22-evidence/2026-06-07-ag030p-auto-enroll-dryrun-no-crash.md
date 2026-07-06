# Faz 22.3 / AG-030P — auto-enroll dry-run certstore crash hardening

> **Date**: 2026-06-07
> **Scope**: Local Parallels Windows 11 (`HALILKOOLUB735`) auto-enroll dry-run
> preflight. This evidence proves a source fix plus local-lab no-crash behavior
> for the mTLS preflight path. It does **not** prove domain join, AD CS
> certificate provisioning, trusted production signing, domain-wide rollout,
> installed-service distribution of PR #77, or production readiness.

## 1. Trigger

The local Parallels Windows VM exposed a real crash while checking the
auto-enroll dry-run path:

```powershell
C:\Program Files\EndpointAgent\endpoint-agent.exe -auto-enroll -dry-run
```

Observed failure:

```text
Exception 0xc0000005
github.com/google/certtostore.(*WinCertStore).CertKey
platform-agent/internal/platform/windows/certstore.acquireSigner
platform-agent/internal/platform/windows/certstore.(*Provider).LoadEligibleCert
main.runAutoEnrollDryRun
```

Interpretation: the broad default cert filter (`ClientAuth` + valid + private
key) could enumerate an arbitrary `LocalMachine\My` certificate on a workgroup
Windows host and enter native key acquisition on an unsuitable cert.

## 2. Source Fix

| Item | Evidence |
|---|---|
| Repo | `Halildeu/platform-agent` |
| Issue | [platform-agent #76](https://github.com/Halildeu/platform-agent/issues/76) |
| PR | [platform-agent #77](https://github.com/Halildeu/platform-agent/pull/77) |
| Merge commit | `1ec4a5a98665eb06f4940cb3e9cd7624ac46316c` |
| Branch | `codex/ag030p-auto-enroll-dryrun-crash` |
| Commit before squash | `f1da8c7` |

Implemented behavior:

- `newAutoEnrollRunner` and `runAutoEnrollDryRun` reject startup when both cert
  filters are empty.
- Required operator filters:
  - `ENDPOINT_AGENT_AUTO_ENROLL_CERT_SUBJECT_SUFFIX`
  - `ENDPOINT_AGENT_AUTO_ENROLL_CERT_SAN_URI_PREFIX`
- `certstore.acquireSigner` checks private-key association metadata before
  invoking `certtostore.CertKey`.
- Regression tests cover:
  - broad/default filter rejected,
  - subject suffix accepted,
  - SAN URI prefix accepted.

## 3. CI and Review

PR #77 passed:

```text
BG-EA-1 boundary declaration validate    pass
Generate SBOM (Syft, SPDX format)        pass
Lab-only-evidence signing                pass
Test, lint, cross-build                  pass
Windows Go test                          pass
gitleaks secret scan                     pass
```

Local pre-PR verification:

```text
go test ./internal/autoenroll ./internal/mtls ./cmd/endpoint-agent       PASS
GOOS=windows GOARCH=amd64 go test -c ./cmd/endpoint-agent ./internal/platform/windows/certstore ./internal/autoenroll  PASS
GOOS=windows GOARCH=amd64 go vet ./cmd/endpoint-agent ./internal/platform/windows/certstore ./internal/autoenroll       PASS
./scripts/test/local.sh                  PASS
./scripts/build/local.sh                 PASS
./scripts/build/windows-package.sh       PASS
```

Cross-AI review:

```text
Reviewer: Claude CLI
Verdict: AGREE -- merge-ready, zero must-fix
```

Claude specifically accepted:

- requiring `SubjectSuffix` or `SANURIPrefix` as fail-closed behavior,
- the private-key property precheck as defense-in-depth,
- the local VM no-crash evidence as sufficient for PR merge.

## 4. Local Parallels Evidence

Patched temp binary:

```text
C:\Temp\endpoint-agent-ag030p.exe
SHA256: 0AC89B8B02F20F5C6550D10EC74076E29D7F79D9320E569E2D390B917A750154
```

No-filter dry-run:

```text
endpoint-agent ... agent mode=auto-enroll
endpoint-agent ... auto-enroll dry-run failed: auto-enroll cert filter requires ENDPOINT_AGENT_AUTO_ENROLL_CERT_SUBJECT_SUFFIX or ENDPOINT_AGENT_AUTO_ENROLL_CERT_SAN_URI_PREFIX
EXIT=1
```

SAN URI prefix dry-run:

```powershell
$env:ENDPOINT_AGENT_AUTO_ENROLL_CERT_SAN_URI_PREFIX="adcomputer:"
C:\Temp\endpoint-agent-ag030p.exe -auto-enroll -dry-run
```

```text
endpoint-agent ... agent mode=auto-enroll
endpoint-agent ... auto-enroll dry-run failed: cert load: no eligible machine certificate found
EXIT=1
```

Subject suffix dry-run:

```powershell
$env:ENDPOINT_AGENT_AUTO_ENROLL_CERT_SUBJECT_SUFFIX=".acik.local"
C:\Temp\endpoint-agent-ag030p.exe -auto-enroll -dry-run
```

```text
endpoint-agent ... agent mode=auto-enroll
endpoint-agent ... auto-enroll dry-run failed: cert load: no eligible machine certificate found
EXIT=1
```

Result: all three paths returned clean process exit behavior. No native access
violation was observed after the patch.

## 5. Installed Service Boundary

The installed local service was not replaced during this proof:

```text
EndpointAgent: RUNNING
endpoint-agent 0.1.3-lab.1
SHA256: CFFD73CC86C27B727952E45083CF95047B9E2AAAC9C1ACC393CACD20122048FE
```

This matters because AG-030P is a source + temp-binary preflight proof. A later
self-update or installer distribution path must move the merged fix into the
installed service if the local baseline needs to exercise PR #77 from
`C:\Program Files\EndpointAgent\endpoint-agent.exe`.

## 6. Other-Device Checklist Impact

GitOps issue [#1044](https://github.com/Halildeu/platform-k8s-gitops/issues/1044)
received an AG-030P addendum for later batch testing:

- run post-#77 binary with no cert filter and expect fail-closed filter
  requirement, not crash;
- run with dummy `ENDPOINT_AGENT_AUTO_ENROLL_CERT_SAN_URI_PREFIX=adcomputer:`
  on non-domain machines and expect clean `no eligible machine certificate
  found`, not arbitrary cert acquisition or crash;
- confirm installed service remains running and unchanged unless that device is
  explicitly selected for self-update/install testing.

The addendum comment is
`https://github.com/Halildeu/platform-k8s-gitops/issues/1044#issuecomment-4641247708`.

## 7. Remaining Gates

- AD CS certificate provisioning for domain mTLS enrollment remains separate.
- The endpoint must be configured with a disambiguating cert filter before
  auto-enroll can start.
- Multi-device acceptance remains open under #1044.
- Trusted production signing and domain-wide rollout remain separate Faz 22.3 /
  22.5.8 gates.
