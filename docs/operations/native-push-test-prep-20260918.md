# Native notification TEST image preparation

Tracked by #3793 and Halildeu/platform-mobile#9. This is an image-only proposal, not a completed rollout or notification activation.

## Source and validation

Auth and orchestrator images use backend source `f9ea16466933b14be8cf6439d55334527760db35`. Meeting and transcript images use `5e6b0aedec409aef8f59b32d970dcd47c47cfab4` from draft PR1176, stacked on draft PR1174. Only those two modules changed; the source references are intentionally recorded separately. Source/integration review remains a merge gate. Auth CI35330827130 and full CI35330824834 passed, including meeting/transcript/notification PostgreSQL tests. Image build runs below passed; Original image attestation statements matched their expected source and subjects; the two replacement builds emitted their source-bound attestations, with independent verification still pending. Independent OCI verification remains pending after registry authorization failed.

| Service | Build run | New SHA256 |
|---|---|---|
| auth-service | 35331525062 | ba06e6152a469c37c3daf88dcc424b01bcaec61eeba17b4f0ad23fa6dd912afa |
| meeting-service | 35337078778 | 2f4c69b80d21c8acabf084563fd8f41128365aa2c0db69cf3d43022c31608c02 |
| transcript-service | 35337081731 | 9b068141746efc6f89c3efa0e83bcacc3760df05c4800fc443da6898d53b7835 |
| notification-orchestrator | 35331533582 | 13f349689780eb644296a9c6266d9c9e9b2de976cb7a5f8e1bdf8e8416a72ffd |

The rendered TEST delta is limited to these four Deployment images. Audio-gateway, meeting-ai, production, credentials, network policies and existing web notification settings are unchanged. These images include cumulative source changes since the previously deployed service versions; an image-only manifest diff does not imply a four-line application-code change.

## Runtime boundary

CI exposed an existing finalization contract gate: `verify-faz24-finalization-rollout.py`
pins the old auth/meeting/transcript digests, and `faz24-transcript-ready-pre-enable-policy.v1.json`
binds the transcript producer to exact source, event-contract and runtime remediation
evidence. New image pullability is verified by PR CI, but the old producer evidence
must not be relabeled as evidence for the new image. Keep this proposal draft until
the new producer capability and applicable finalization verification are recorded.
No guard, runtime permit or old evidence was weakened/rewritten to obtain a pass.

Normal merge of a TEST digest change triggers `verify-testai-backend-rollout.yml`
and Argo auto-sync. The verifier extracts the full current map, so a narrow four-image
PR does not require inventing thirteen new builds. Its protected environment and
live post-rollout checks still apply. Do not merge this preparation to bypass its
open source/provenance/finalization gates.

Native registry/sender and new native producers retain disabled source defaults. Verify no live secret/env override enables them before rollout. No provider credential file mounts, Firebase configuration or APNs signing setup are supplied by this proposal. Existing meeting in-app notifications remain enabled.

Before merging: verify source/integration review, exact OCI provenance, GitOps checks and supported four-service reconciliation path. The generic promotion workflow expects a full 13-service map; do not invent missing digests or misattribute older images to this source SHA. Never use imperative workload patch/set-image.

After normal GitOps reconciliation, verify actual pod imageID for all four digests, Argo sync/health, Flyway and startup, then authenticated existing meeting/result and notification smoke. Public TEST root/OIDC 200 and unauthenticated API 401 checks passed from the personal DEV account; these do not prove the new images are deployed. That account has no personal kubeconfig.

Only after institution-owned provider references and a matching phone package are configured may native activation proceed. Acceptance covers authorized summary-ready/action-assigned/transcript-ready delivery, foreground/background/closed app, meeting deep link, token rotation, logout/account switching and duplicate events. Provider acceptance is not physical device receipt.

## Rollback

Revert this image-only GitOps change and reconcile; preserve migration history and token data. Review additive schema compatibility before rollback. Previous digest suffixes:

- auth-service: ffd2bff1d2fe62872cde8e14f7b9f7e3ef66d6debf2b5982f9f81dce7b30c7d8
- meeting-service: 4fe09e4da3d5ce5d128c8e8de53ef7714e3552fcdd09e54c63029bcf0fdbac11
- transcript-service: 191eecbc72dbd18eaa6d8e6951921bc093a4899cb8c080b7481abbd3382a6496
- notification-orchestrator: abc24cce84bef64be2040b9c48d8ee94a03339b83355cb44066c5fc8d2f54f20

## Coordination exception

The current account can read/write this repository but cannot resolve configured Project #2. Zeynep explicitly authorized issue/PR tracking for this work and recording it for later Halil review. This does not change access controls, review gates, repository policies or acceptance criteria. No Project status, human approval, merge or live delivery is claimed.

## Notification isolation follow-up

The original source coupled successful Redis publication to notification HTTP retries. Source5e6b0aed separates delivery into a durable per-service notification queue with an atomic fenced handoff, independent attempts and scheduling, single-job transactional locking and source-erasure cascade. Summary flag deactivation pauses pending summary jobs.33focused tests and separate Codex source review passed; CI35336353037 meeting432/transcript235 tests passed with zero failures or skips, including PostgreSQL rollback/concurrency/erasure regressions. The complete CI run still has an unrelated service check pending at the time of this update. Two replacement image builds succeeded. The older two module images must not be promoted as if they included this correction.

No old finalization evidence was rewritten. New producer capability acceptance and runtime validation remain required. FCM/APNs institution configuration has not arrived, as explicitly confirmed by the user; actual device delivery remains unverified.