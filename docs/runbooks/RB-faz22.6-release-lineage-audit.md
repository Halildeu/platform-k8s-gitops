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
with rollout readiness. HTTP fetches are bounded by `CURL_MAX_TIME` (default:
`20` seconds) and request no-cache semantics so metadata-only release repairs do
not leave the verifier reading stale CDN bytes.

## 1. Required Release Record

For broad rollout, the release record must bind:

1. Git tag and source commit.
2. GitHub release metadata (`isLatest`, draft/prerelease state, publish time).
3. Trusted release workflow/run or explicit signed provenance pointer.
4. Full asset SHA256 set, including `EndpointAgent.zip`,
   `EndpointAgent.zip.sha256`, and `release-manifest.json`.
5. `endpoint-agent.exe` SHA256.
6. Signer thumbprint, signing tier, and trust scope.
7. Artifact-host image tag plus immutable digest in the durable GitHub
   release manifest.
8. Artifact-host `current` manifest parity with the GitHub release manifest
   for served payload fields (tag, agent SHA, ZIP SHA, signer, tier).
9. Live `artifact-host` deployment and pod imageID digest match. The
   `current` manifest is not required to embed its own final image digest
   because writing that value into the image would itself change the digest.
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

Lineage boundary:

- The artifact-host `current` manifest is served from the same image whose
  final digest is only known after push. It is therefore not required to embed
  its own final image digest; the durable GitHub release manifest and live
  Kubernetes imageID provide that immutable digest binding.

Hygiene findings:

- The earlier GitHub release `SHA256SUMS` coverage debt is resolved as of the
  2026-06-23 in-place `v0.2.28` metadata repair. The main audit now reports
  both `CURRENT_SHA256SUMS_COVERAGE=pass assets=7` and
  `RELEASE_SHA256SUMS_COVERAGE=pass assets=7`, including
  `EndpointAgent.zip`, `EndpointAgent.zip.sha256`, and
  `release-manifest.json`. No binary, script, ZIP, tag, or
  `release-manifest.json` payload bytes changed for that repair.
- Release objects report `isImmutable=false`.
- The recent `v0.2.x` train is dense (`v0.2.9` through `v0.2.28` in the recent
  audit window). That is acceptable for pilot recovery, not broad rollout
  language without a lineage summary.

## 3. Audit Command

Run:

```bash
scripts/faz22-remote-ops/faz22-6-release-lineage-audit.sh
```

Mac/operator shells use `SSH_TARGET=staging-sw` by default for the live
artifact-host digest check. If TCP/22 or local SSH authentication to
`staging-sw` is unavailable, use the self-hosted runner path instead of
treating the Mac-side SSH failure as cluster truth:

```bash
RELEASE_LINEAGE_KUBECTL_MODE=local-kubectl SSH_TARGET=local \
  scripts/faz22-remote-ops/faz22-6-release-lineage-audit.sh
```

The canonical workflow is
`.github/workflows/faz22-6-release-lineage-audit.yml`. It is read-only, runs on
`[self-hosted, staging-sw, testai-deploy]`, uploads the audit output, and fails
if `ARTIFACT_HOST_LIVE_DIGEST=pass mode=local-kubectl` is not present. Because
the release and gate repositories are public, the workflow uses the
short-lived read-only `github.token` rather than a long-lived repository
secret.

Expected current posture:

```text
F22_6_RELEASE_LINEAGE=needs_hygiene
```

`needs_hygiene` means the live artifact-host and release payload agree, but
the release record is not complete enough for broad rollout claims. In the
2026-06-23 main audit, checksum coverage is no longer the source of that
posture; the remaining release-lineage hygiene items are the mutable GitHub
release object and the dense `v0.2.x` train without an owner-approved lineage
waiver.

## 4. Promotion Rule

Do not describe the current release line as 5-device, 50-device, 800-device, or
production rollout ready until the audit prints `F22_6_RELEASE_LINEAGE=pass`.

`F22_6_RELEASE_LINEAGE=pass` requires:

- release/latest/current/live artifact-host parity;
- full GitHub release `SHA256SUMS` coverage;
- artifact-host digest present in the durable GitHub release manifest and
  matching the live `artifact-host` imageID;
- current artifact-host manifest parity for served payload fields, without
  requiring a self-referential image digest;
- explicit source commit and workflow/run provenance in the release record;
- no unresolved dense-train hygiene item or an owner-approved release-lineage
  waiver for the bounded pilot only.

## 5. Bounded Pilot Waiver Contract

The release-lineage audit is fail-closed. A waiver is valid only when
`RELEASE_LINEAGE_WAIVER_REF` points to an open GitHub issue whose body contains
the exact machine-readable marker below. The default reference is
`Halildeu/platform-k8s-gitops#1901`.

The marker may waive only the current bounded-pilot metadata hygiene findings:
`GITHUB_RELEASE_IMMUTABLE` and `GITHUB_RELEASE_DENSE_TRAIN`. It does not
waive checksum coverage, manifest parity, signer parity, artifact-host digest,
live Kubernetes imageID, hardware attestation, VIEW_ONLY acceptance, or any
broad rollout gate.

```text
F22_6_RELEASE_LINEAGE_WAIVER: v1
waiver_scope: bounded-pilot-only
release_tag: v0.2.28
artifact_host_digest: sha256:36a81cb89294ef7f4d09350ab9f92a955b65b8132ba5330fcf1dcb7e365ab3e2
accepted_findings: GITHUB_RELEASE_IMMUTABLE,GITHUB_RELEASE_DENSE_TRAIN
forbidden_claims: 5-device,50-device,800-device,production,broad-rollout
owner_approved_by: <named owner>
approved_at: YYYY-MM-DD
expires_at: YYYY-MM-DD
```

If this marker is present, current, and matches the expected release tag and
artifact-host digest, the audit prints:

```text
RELEASE_LINEAGE_WAIVER=bounded_pilot_pass ...
F22_6_RELEASE_LINEAGE=bounded_pilot_pass
```

`bounded_pilot_pass` is deliberately not `pass`. It permits bounded pilot
evidence to proceed under the named waiver, but it still forbids 5-device,
50-device, 800-device, production, and broad rollout language. Full
`F22_6_RELEASE_LINEAGE=pass` remains reserved for the no-waiver path where
all release-lineage hygiene findings are resolved.
