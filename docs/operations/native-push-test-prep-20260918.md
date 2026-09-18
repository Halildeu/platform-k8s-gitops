# Native notification TEST image preparation

Tracked by #3793 and Halildeu/platform-mobile#9. This is an image-only proposal, not a completed rollout or notification activation.

## Source and validation

All four images use backend source `f9ea16466933b14be8cf6439d55334527760db35` from draft PR1176, stacked on draft PR1174. Source/integration review remains a merge gate. Auth CI35330827130 and full CI35330824834 passed, including meeting/transcript/notification PostgreSQL tests. Image build runs below passed; GitHub attestation statements match the expected source and subjects. Independent OCI verification remains pending after registry authorization failed.

| Service | Build run | New SHA256 |
|---|---|---|
| auth-service | 35331525062 | ba06e6152a469c37c3daf88dcc424b01bcaec61eeba17b4f0ad23fa6dd912afa |
| meeting-service | 35331527896 | f29f3fa56772dbf5011c73c5b1bc1fb4fabc7896f6b2c3e9b7f2ae92ae9c47bd |
| transcript-service | 35331530753 | bc2c7c7142d30e7bd7d0a62c15f81c745972c19a1882f4b7c402b038109a7c5b |
| notification-orchestrator | 35331533582 | 13f349689780eb644296a9c6266d9c9e9b2de976cb7a5f8e1bdf8e8416a72ffd |

The rendered TEST delta is limited to these four Deployment images. Audio-gateway, meeting-ai, production, credentials, network policies and existing web notification settings are unchanged. These images include cumulative source changes since the previously deployed service versions; an image-only manifest diff does not imply a four-line application-code change.

## Runtime boundary

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
