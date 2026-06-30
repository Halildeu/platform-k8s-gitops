# RB-faz22.6 — Release Lineage Hygiene Audit

> Status: ACTIVE hygiene gate, 2026-06-24.
> Scope: EndpointAgent trusted `v0.3.x` release train plus the exact-pinned
> `v0.3.1` bounded-pilot artifact-host deploy evidence for Faz 22.6.
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

## 2. Current v0.3.1 Release Snapshot

Observed on 2026-06-24:

- GitHub latest release: `platform-agent` `v0.3.1`.
- GitHub Release metadata reports `isImmutable=true`, `isDraft=false`, and
  `isPrerelease=false`.
- Annotated tag object points to source commit
  `4a988afbb23320fd631a6e6aab629811e637aa1e`.
- GitHub release manifest records:
  - `release_tag=v0.3.1`
  - `release_class=rollout-candidate`
  - `previous_release=v0.3.0`
  - `workflow_run_id=28100776164`
  - `release-manifest.json` SHA256
    `3d74e3dbb057e0d23b25cf0f8fb93864db24749c7db3e2292946d9cf9b01545b`
  - `endpoint_agent_sha256=edcac7e2a78d8801c6d168bdb8d51f6ecc5e99bc4c4f9fdc8507943df321e1be`
  - `EndpointAgent.zip` SHA256
    `6791f6af5dbe0c4f2da8d87f33e5fa4165237d8b6a7aeb8121e29a88cbc5c2b7`
  - signer thumbprint
    `D68F4F530137EB65CE44E3405E82B46205E753E5`
  - signing tier `trusted-internal-ca`
  - artifact-host image
    `ghcr.io/halildeu/platform-agent-artifacts:v0.3.1@sha256:b83e39a0b08b54cd9e4dc094d8d36fb857b2cd253355ce5150aa33edb502eb27`
- GitOps PR #1943 pins the test `artifact-host` overlay to that immutable
  digest. The first post-merge self-hosted audit run `28101992243` saw live
  `artifact-host` still on `v0.3.0` while ArgoCD was reconciling. Follow-up
  audit run `28102175711` proved the live `k3d-test/platform-test`
  `artifact-host` deployment and both pod imageIDs now match the `v0.3.1`
  digest; the audit's `digest_hits=3` is the Deployment image field plus the
  two pod `imageID` fields.

Lineage boundary:

- The artifact-host `current` manifest is served from the same image whose
  final digest is only known after push. It is therefore not required to embed
  its own final image digest; the durable GitHub release manifest and live
  Kubernetes imageID provide that immutable digest binding.

Hygiene findings:

- Release workflow `28100776164` ran the post-publish verifier against
  `v0.3.1` and passed release archive, `SHA256SUMS`, manifest, ZIP, and
  artifact-host registry digest parity.
- The live self-hosted release-lineage audit run `28102175711` printed
  `GITHUB_RELEASE_IMMUTABLE=pass`, `MANIFEST_WORKFLOW_RUN_PARITY=pass`,
  `MANIFEST_PREVIOUS_RELEASE_PARITY=pass`, `ARTIFACT_HOST_LIVE_DIGEST=pass`,
  `RELEASE_LINEAGE_WAIVER=not_required`, and `F22_6_RELEASE_LINEAGE=pass`.
- Faz 22.6 #1939 reworked the release-train portion of the audit (see §3.2).
  The train is now evaluated against the latest STABLE release on the trusted
  `v0.3` series, decoupled from the deployed bounded-pilot `v0.3.1` pin. With
  the earlier live train (latest stable `v0.3.3`, four `v0.3.x` releases below
  the dense threshold, zero frozen-series regressions) the train checks printed
  `GITHUB_RELEASE_TRAIN_SERIES=pass`, `GITHUB_RELEASE_LATEST_POINTER=pass`,
  `GITHUB_RELEASE_FROZEN_SERIES_REGRESSION=pass`, and
  `GITHUB_RELEASE_ACTIVE_SERIES_DENSE=pass`.
- On 2026-07-01 the active trusted series reached the dense threshold with
  `v0.3.0` through `v0.3.7`. The audit now resolves
  `GITHUB_RELEASE_ACTIVE_SERIES_DENSE` through a non-waiver lineage audit:
  `ACTIVE_SERIES_DENSE_LINEAGE_AUDIT=pass trusted_series=v0.3 active_count=8
  threshold=8 first=v0.3.0 latest=v0.3.7 seed_nonimmutable_allowed=1
  last_previous_release=v0.3.6 last_manifest_tag=v0.3.7`, followed by
  `GITHUB_RELEASE_ACTIVE_SERIES_DENSE=pass ... resolved_by=lineage-audit`.
  This keeps dense-train hygiene fail-closed without requiring the bounded-pilot
  waiver path when the full trusted-series chain is machine-verifiable.
- The historical dense `v0.2.x` pilot-recovery train and immutable=false
  `v0.3.0` release object remain historical evidence. They are no longer a
  release-lineage hygiene blocker: the rework only counts `v0.2.x` releases
  published at or after the trusted-lineage boundary
  (`2026-06-24T09:04:29Z`) as a regression, so the pre-boundary recovery train
  is never counted and is never deleted. The patch-zero trusted-series seed
  (`v0.3.0`) is the only allowed `isImmutable=false` trusted-series release,
  and only because it exactly matches the trusted-lineage boundary and points
  back to the frozen `v0.2` line. Every later trusted-series release must be
  immutable.

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
F22_6_RELEASE_LINEAGE=pass
```

`pass` currently means the release train has graduated to the trusted `v0.3`
series (§3.2), the bounded-pilot `v0.3.1` release object exists as a stable
release and is immutable, the release manifest binds source commit / workflow
run / previous release / signed asset hashes / artifact-host digest, the test
overlay consumes that immutable digest, the public `current` artifact surface
matches the release manifest, and the live `artifact-host` deployment plus pod
imageIDs match the expected digest. This is a release-lineage sub-gate only; it
does not close hardware attestation, VIEW_ONLY, or other Faz 22.6 acceptance
gates.

## 3.2 Release-Train Graduation vs Bounded-Pilot Deploy Pin (Faz 22.6 #1939)

The audit separates two distinct concerns that earlier conflated into a single
stale exact-pin (`EXPECTED_AGENT_LATEST_TAG=v0.2.28` + a crude `^v0\.2\.`
count), which false-blocked completion once the agent graduated to the signed
`v0.3` lineage:

- **Bounded-pilot deploy evidence** stays exact-pinned to
  `current_bounded_pilot.release_tag` (`v0.3.1`): manifest parity, artifact-host
  digest, SHA256SUMS, and `GITHUB_RELEASE_IMMUTABLE`. A new
  `GITHUB_BOUNDED_PILOT_RELEASE_PRESENT` check asserts the pinned tag exists as
  a stable (non-draft, non-prerelease) release — but does **not** require it to
  be GitHub's "latest", because the trusted train intentionally moves ahead of
  the deployed pilot.

- **Release-train graduation/hygiene** is evaluated by the pure, network-free
  `release_train_verdict` function against the live release list (or an injected
  `RELEASE_LIST_JSON` fixture for offline tests):
  - `GITHUB_RELEASE_TRAIN_SERIES` — the latest STABLE release (newest
    non-draft, non-prerelease) must match `trusted_series_regex` (`^v0\.3\.`).
    Otherwise the train has not graduated → `blocked` (and `blocked_empty` when
    there is no stable release at all).
  - `GITHUB_RELEASE_LATEST_POINTER` — if GitHub's `isLatest` pointer is a
    prerelease/draft (while the latest stable is still trusted), this is
    `needs_hygiene`, not a series block.
  - `GITHUB_RELEASE_FROZEN_SERIES_REGRESSION` — counts `^v0\.2\.` releases
    published at or after `trusted_lineage_started_at`
    (`2026-06-24T09:04:29Z`). Any such release is a regression off the trusted
    series → `needs_hygiene`. Historical `v0.2.x` before the boundary are fine
    and are never counted or deleted.
  - `GITHUB_RELEASE_ACTIVE_SERIES_DENSE` — if the count of trusted-series
    releases in the window is `>= active_series_dense_threshold` (`8`), the
    pure train verdict flags hygiene with reason
    `active-series-dense-requires-lineage-audit-or-waiver`. The live audit then
    runs `ACTIVE_SERIES_DENSE_LINEAGE_AUDIT`. It prints pass only when the
    trusted series is contiguous from patch zero, every non-seed release is a
    GitHub-immutable stable release, each release manifest points to the
    previous tag, required manifest fields are populated, signer/tier match the
    policy, artifact-host refs are digest-bound to the same tag, SHA256SUMS
    covers the required seven assets, manifest ZIP/executable hashes match
    SHA256SUMS, and tag source commits match manifest `source_commit`. If this
    audit passes, `GITHUB_RELEASE_ACTIVE_SERIES_DENSE=pass
    resolved_by=lineage-audit`; if it fails, the hygiene finding remains and
    requires the bounded-pilot waiver path. Dense active series is never
    auto-passed and never triggers delete.

`release_train_verdict` is offline-testable on its own
(`tests/faz22_remote_ops/test_faz22_6_release_train_verdict.sh`, gated by
`.github/workflows/gate-faz22-release-train-verdict.yml`). The
`check-endpoint-agent-release-policy.sh` verifier validates the SSOT shape
(including `trusted_lineage_started_at`, `active_series_dense_threshold`, and
the `trusted_series_regex`/`recent_release_series_regex` alias-drift guard); it
is **not** a substitute for the live-truth `F22_6_RELEASE_LINEAGE` gate.

## 3.1 Release Policy SSOT

The active bounded-pilot or rollout-candidate release identity and
release-train hygiene thresholds
are read from:

```text
config/faz22-6-endpoint-agent-release-policy.v1.json
```

This file is the single source of truth for the current bounded-pilot or
rollout-candidate EndpointAgent tag, source commit, workflow run id, previous
release, executable/ZIP SHA256 values, executable max byte guard,
release-manifest/install/bootstrap-package hashes, signer thumbprint and
certificate fingerprint, artifact-host digest, release-lineage waiver ref,
waiver accepted findings, and dense-train threshold. The audit, bootstrap,
update, evidence-verifier, and package helpers load it through
`scripts/faz22-remote-ops/endpoint-agent-release-policy.sh`.

Do not update `EXPECTED_AGENT_TAG`, artifact-host digest, bootstrap hashes,
update byte limits, signer fingerprints, or dense-train thresholds by editing
individual scripts or workflow defaults. Update the policy file and let the gate
validate the new shape:

```bash
scripts/faz22-remote-ops/check-endpoint-agent-release-policy.sh
```

The current policy intentionally freezes the `v0.2` recovery line as bounded
pilot history and records `v0.3.1` as the current trusted minor-line release.
Moving to a new trusted line must be represented in this policy first, then
consumed by the release workflows and audits.

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
- if the trusted active series reaches the dense threshold, a passing
  `ACTIVE_SERIES_DENSE_LINEAGE_AUDIT` or a bounded-pilot-only waiver;
- no unresolved release-lineage hygiene finding. A bounded-pilot waiver does
  not produce `F22_6_RELEASE_LINEAGE=pass`; it produces
  `F22_6_RELEASE_LINEAGE=bounded_pilot_pass` and keeps broad rollout language
  forbidden.

If repo-level release immutability was enabled only after a release was
published and that release still reports `isImmutable=false`, do not treat the
setting as a no-waiver pass. The no-waiver path requires either a later live
audit proving the same release object is immutable or a new trusted release
published under the enabled setting and consumed through the release policy.
`RELEASE_LINEAGE_WAIVER=blocked` means the audit did not find valid waiver
evidence on the configured issue. It is not itself owner refusal; a named owner
can still add the bounded-pilot marker through the separate approval path.

## 5. Bounded Pilot Waiver Contract

No waiver is required for the current `v0.3.1` release-lineage state because
the no-waiver audit prints `F22_6_RELEASE_LINEAGE=pass`. This section remains
the fail-closed contract for a future bounded-pilot-only hygiene regression.

The release-lineage audit is fail-closed. A waiver is valid only when
`RELEASE_LINEAGE_WAIVER_REF` points to an open GitHub issue whose body contains
the exact machine-readable marker below. The default reference is
`Halildeu/platform-k8s-gitops#1901`.

The marker may waive only bounded-pilot metadata / release-train hygiene
findings. The policy SSOT `bounded_pilot_waiver.accepted_findings` enumerates
the waiver-eligible labels: `GITHUB_RELEASE_IMMUTABLE`,
`GITHUB_RELEASE_DENSE_TRAIN` (legacy), and the Faz 22.6 #1939 release-train
labels `GITHUB_RELEASE_LATEST_POINTER`,
`GITHUB_RELEASE_FROZEN_SERIES_REGRESSION`, and
`GITHUB_RELEASE_ACTIVE_SERIES_DENSE`. It does not waive checksum coverage,
manifest parity, signer parity, artifact-host digest, live Kubernetes imageID,
`GITHUB_RELEASE_TRAIN_SERIES` (a hard series block, not a hygiene finding),
hardware attestation, VIEW_ONLY acceptance, or any broad rollout gate.

Because the #1939 rework renamed the release-train hygiene findings, an
existing #1901 waiver marker that lists only the two legacy findings will
**not** silently waive a new regression/dense/pointer finding: the marker's
`accepted_findings` must list the finding actually raised by the live audit.
Refresh the marker (or regenerate it from the updated policy) before a new
release-train hygiene finding can resolve to `bounded_pilot_pass`. The
following block is the contract template only; it is not a recorded owner
approval until the live #1901 issue body contains the same shape with a named
owner and valid dates.

```text
F22_6_RELEASE_LINEAGE_WAIVER: v1
waiver_scope: bounded-pilot-only
release_tag: <current policy release tag>
artifact_host_digest: <current policy artifact_host_digest>
accepted_findings: <findings actually raised by the live audit, e.g. GITHUB_RELEASE_IMMUTABLE,GITHUB_RELEASE_FROZEN_SERIES_REGRESSION>
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
