# RB-faz22.6 — Release Lineage Hygiene Audit

> Status: ACTIVE hygiene gate, 2026-06-23.
> Scope: EndpointAgent `v0.2.x` pilot recovery / bounded acceptance release
> lineage for Faz 22.6.
> Parent contract: `docs/runbooks/RB-faz22.6-autonomous-completion-contract.md`.

This runbook defines the release-lineage checks that must be clean before
using the current EndpointAgent release train as evidence for any 5-device or
broader rollout claim.

It does not replace `platform-agent` release workflows. It audits the published
release, the test artifact-host surface, and the live `artifact-host`
deployment so that a moving or partially-recorded release line is not confused
with rollout readiness.

## 1. Required Release Record

For broad rollout, the release record must bind:

1. Git tag and source commit.
2. GitHub release metadata (`isLatest`, draft/prerelease state, publish time).
3. Trusted release workflow/run or explicit signed provenance pointer.
4. Full asset SHA256 set, including `EndpointAgent.zip`,
   `EndpointAgent.zip.sha256`, and `release-manifest.json`.
5. `endpoint-agent.exe` SHA256.
6. Signer thumbprint, signing tier, and trust scope.
7. Artifact-host image tag plus immutable digest.
8. Artifact-host `current` manifest parity with the GitHub release manifest.
9. Live `artifact-host` deployment and pod imageID digest match.
10. Acceptance issue/workflow that consumed this exact release.

Missing metadata is not automatically a runtime no-go for the bounded pilot,
but it is a release-hygiene blocker for broader rollout language.

## 2. Current v0.2.28 Snapshot

Observed on 2026-06-23:

- GitHub latest release: `platform-agent` `v0.2.28`.
- Annotated tag object points to source commit
  `10361a60ca8ca1fb4c6efe3823b433297e16ae3a`.
- GitHub release manifest and artifact-host `current` manifest agree on:
  - `release_tag=v0.2.28`
  - `endpoint_agent_sha256=e99c05d0daf37b1d4e36807ab8a70194ab4be76f50a6225f1cedb82b2d31b7a4`
  - `EndpointAgent.zip` SHA256
    `e30ab27490dfcc565bd19f5da657739dfacb8e8d9f57770142575a03e607938a`
  - signer thumbprint
    `D68F4F530137EB65CE44E3405E82B46205E753E5`
  - signing tier `trusted-internal-ca`
- Live `artifact-host` deployment in `k3d-test/platform-test` runs:
  `ghcr.io/halildeu/platform-agent-artifacts:v0.2.28@sha256:36a81cb89294ef7f4d09350ab9f92a955b65b8132ba5330fcf1dcb7e365ab3e2`.

Hygiene findings:

- The GitHub release `SHA256SUMS` asset is narrower than the artifact-host
  `SHA256SUMS` surface. It omits `EndpointAgent.zip`,
  `EndpointAgent.zip.sha256`, and `release-manifest.json`.
- The artifact-host `current` manifest does not carry the artifact-host digest
  fields even though the GitHub release manifest does.
- Release objects report `isImmutable=false`.
- The recent `v0.2.x` train is dense (`v0.2.9` through `v0.2.28` in the recent
  audit window). That is acceptable for pilot recovery, not broad rollout
  language without a lineage summary.

## 3. Audit Command

Run:

```bash
scripts/faz22-remote-ops/faz22-6-release-lineage-audit.sh
```

Expected current posture:

```text
F22_6_RELEASE_LINEAGE=needs_hygiene
```

`needs_hygiene` means the live artifact-host and release payload agree, but
the release record is not complete enough for broad rollout claims.

## 4. Promotion Rule

Do not describe the current release line as 5-device, 50-device, 800-device, or
production rollout ready until the audit prints `F22_6_RELEASE_LINEAGE=pass`.

`F22_6_RELEASE_LINEAGE=pass` requires:

- release/latest/current/live artifact-host parity;
- full GitHub release `SHA256SUMS` coverage;
- artifact-host digest present in the current manifest;
- explicit source commit and workflow/run provenance in the release record;
- no unresolved dense-train hygiene item or an owner-approved release-lineage
  waiver for the bounded pilot only.
