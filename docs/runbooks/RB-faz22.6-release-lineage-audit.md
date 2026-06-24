# RB-faz22.6 — Release Lineage Hygiene Audit

> Status: ACTIVE hygiene gate, 2026-06-23.
> Scope: EndpointAgent `v0.3.0` rollout-candidate / bounded acceptance
> release lineage for Faz 22.6.
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

## 2. Current v0.3.0 Release Snapshot

Observed on 2026-06-24:

- GitHub latest release: `platform-agent` `v0.3.0`.
- Annotated tag object points to source commit
  `ca662499ca13bb567d8b6bc6f02044e4a91579fa`.
- GitHub release manifest records:
  - `release_tag=v0.3.0`
  - `release_class=rollout-candidate`
  - `previous_release=v0.2.28`
  - `workflow_run_id=28087330255`
  - `endpoint_agent_sha256=424d7104a0e8614018a34d629f47713375778d85ff49c387f6de4197950aad6d`
  - `EndpointAgent.zip` SHA256
    `6139b0cc7b4fb3d745630354d2d49c61558c282360e92999057628fb5c7fd105`
  - signer thumbprint
    `D68F4F530137EB65CE44E3405E82B46205E753E5`
  - signing tier `trusted-internal-ca`
  - artifact-host image
    `ghcr.io/halildeu/platform-agent-artifacts:v0.3.0@sha256:00df8734b6a8d5121f9294af63a8e44ae9002298a1b5d05f7aaf44912183fbe6`
- GitOps PR #1940 pins the test `artifact-host` overlay to that immutable
  digest. Self-hosted audit run `28095182027` proved the live
  `k3d-test/platform-test` `artifact-host` deployment and both pod imageIDs
  now match the same digest; the audit's `digest_hits=3` is the Deployment
  image field plus the two pod `imageID` fields.

Lineage boundary:

- The artifact-host `current` manifest is served from the same image whose
  final digest is only known after push. It is therefore not required to embed
  its own final image digest; the durable GitHub release manifest and live
  Kubernetes imageID provide that immutable digest binding.

Hygiene findings:

- Release workflow `28087330255` ran the post-publish verifier against
  `v0.3.0` and passed release archive, `SHA256SUMS`, manifest, ZIP, and
  artifact-host registry digest parity.
- Release objects still report `isImmutable=false`. REST `Update a release`
  exposes `immutable` only in the response schema, not as a mutable request
  field; a tag ruleset protects tag movement but does not change this release
  metadata flag. This remains a hygiene finding unless GitHub release
  immutability is enabled through an available GitHub release setting or a
  bounded waiver is recorded.
- The historical dense `v0.2.x` pilot-recovery train is no longer the current
  expected release series. The policy now evaluates recent train hygiene
  against `v0.3`, where `v0.3.0` starts a clean minor line.

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
secret. A run started immediately after a GitOps merge can fail while ArgoCD is
still reconciling; rerun the workflow after the test Application catches up
instead of using direct `kubectl set image` or other imperative workload
patches.

Expected current posture:

```text
F22_6_RELEASE_LINEAGE=needs_hygiene
```

`needs_hygiene` now means the `v0.3.0` release payload, GitOps desired-state,
artifact-host `current` surface, and live pod imageIDs agree, but the GitHub
release object still reports `isImmutable=false`. The dense `v0.2.x` recovery
train is historical context, not the current release series for this policy.

## 3.1 Release Policy SSOT

The active bounded-pilot or rollout-candidate release identity and
release-train hygiene thresholds
are read from:

```text
config/faz22-6-endpoint-agent-release-policy.v1.json
```

This file is the single source of truth for the current bounded-pilot or
rollout-candidate
EndpointAgent tag, source commit, executable/ZIP SHA256 values, executable max
byte guard, release-manifest/install/bootstrap-package hashes, signer
thumbprint and certificate fingerprint, artifact-host digest, release-lineage
waiver ref, waiver accepted findings, and dense-train threshold. The audit,
bootstrap, update, evidence-verifier, and package helpers load it through
`scripts/faz22-remote-ops/endpoint-agent-release-policy.sh`.

Do not update `EXPECTED_AGENT_TAG`, artifact-host digest, bootstrap hashes,
update byte limits, signer fingerprints, or dense-train thresholds by editing
individual scripts or workflow defaults. Update the policy file and let the gate
validate the new shape:

```bash
scripts/faz22-remote-ops/check-endpoint-agent-release-policy.sh
```

The current policy intentionally freezes the `v0.2` recovery line as bounded
pilot history and records `v0.3.0` as the current trusted minor line. Moving to
a new trusted line must be represented in this policy first, then consumed by
the release workflows and audits.

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
- no unresolved release-lineage hygiene finding. A bounded-pilot waiver does
  not produce `F22_6_RELEASE_LINEAGE=pass`; it produces
  `F22_6_RELEASE_LINEAGE=bounded_pilot_pass` and keeps broad rollout language
  forbidden.

## 5. Bounded Pilot Waiver Contract

The release-lineage audit is fail-closed. A waiver is valid only when
`RELEASE_LINEAGE_WAIVER_REF` points to an open GitHub issue whose body contains
the exact machine-readable marker below. The default reference is
`Halildeu/platform-k8s-gitops#1901`.

The marker may waive only the current bounded-pilot metadata hygiene findings:
`GITHUB_RELEASE_IMMUTABLE` and `GITHUB_RELEASE_DENSE_TRAIN`. It does not
waive checksum coverage, manifest parity, signer parity, artifact-host digest,
live Kubernetes imageID, hardware attestation, VIEW_ONLY acceptance, or any
broad rollout gate. The following block is the contract template only; it is
not a recorded owner approval until the live #1901 issue body contains the
same shape with a named owner and valid dates.

```text
F22_6_RELEASE_LINEAGE_WAIVER: v1
waiver_scope: bounded-pilot-only
release_tag: v0.3.0
artifact_host_digest: sha256:00df8734b6a8d5121f9294af63a8e44ae9002298a1b5d05f7aaf44912183fbe6
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

Use the package helper to produce the exact marker from already-approved owner
metadata:

```bash
scripts/faz22-remote-ops/faz22-6-release-lineage-waiver-package.sh \
  --marker-out /path/to/release-lineage-waiver-marker.txt \
  --release-tag "$(jq -r '.current_bounded_pilot.release_tag' config/faz22-6-endpoint-agent-release-policy.v1.json)" \
  --artifact-host-digest "$(jq -r '.current_bounded_pilot.artifact_host_digest' config/faz22-6-endpoint-agent-release-policy.v1.json)" \
  --owner-approved-by "<named owner>" \
  --approved-at YYYY-MM-DD \
  --expires-at YYYY-MM-DD
```

The helper does not approve #1901, does not write to GitHub, and does not alter
release, tag, asset, artifact-host, Kubernetes, or endpoint state. It only
prevents hand-written marker drift after a real owner decision exists.

Marker parsing is fail-closed:

- fenced example markers are ignored;
- more than one live `F22_6_RELEASE_LINEAGE_WAIVER: v1` marker fails as
  `duplicate-marker`;
- owner cannot be empty, `TBD`, `none`, `n/a`, `na`, `placeholder`, `owner`, or
  the literal example `named-owner`;
- dates must parse as UTC `YYYY-MM-DD`;
- `approved_at` cannot be in the future;
- `expires_at` cannot be expired;
- `approved_at` cannot be after `expires_at`.
