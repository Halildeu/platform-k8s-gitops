# TEST mobile outage recovery candidate — runtime acceptance pending

Tracked by gitops#3884 and platform-mobile#7. This is candidate preparation,
not evidence of a deployed fix. No phone identifiers or content are included.

## Source and artifact

- Backend PR1201, commit `637d7ebc`; mobile PR48, commit `43394cb`.
- Canonical image build: https://github.com/Halildeu/platform-backend/actions/runs/37463379188
- Candidate: `ghcr.io/halildeu/platform-backend-audio-gateway-service@sha256:f2541989a1a8be7fedcef538afb94d5a2ee256b4778b725dd99c2852034791bd`.
- Previous desired digest: `sha256:4e1f4431bd7ef7f78cd1cc934b8472ce6dd9ac84675dad2a9564dfe309ac4307`.
- Phone APK build: https://github.com/Halildeu/platform-mobile/actions/runs/37463375432

Provider receipts now precede mobile ACKs. The opt-in resume protocol retains one
provider connection across a bounded 60-second detach and replays missed finals
before queued PCM upload resumes. It is process-local: the existing TEST desired
gateway has one replica; restart, another pod or expired history cannot claim
continuity. Existing legacy clients retain their protocol. Mobile storage TTL and
encryption are unchanged. New transcript replay is bounded transient memory only.

## Evidence and remaining gates

Local tests: 505 gateway tests before final localized expiry hardening; final
retained-session tests 13 passed. Mobile 34 suites / 460 tests, typecheck and
changed-file lint passed. Independent source review approved. A real TCP provider
fixture plus the real registry covered 30-second detach and 264 queued frames,
exact PCM bytes/hash, one provider, lost receipt retry, detached final persistence
and terminal order. These are not deployed Speechmatics acceptance.

Read-only TEST metadata run 37453976829 remains queued as of candidate preparation.
No current runtime baseline, imageID, provider health or live rollback readiness
is asserted. Current actor cannot read Project2 or add an item to Project4; no
successful board claim is claimed. Resolve that tracking access before promotion.

Before merge/promotion: source checks must pass, inspect current runtime image and
single-replica routing, ensure no active test recordings, confirm rollback image
pullability, and use the existing ADR-0023 GitOps rollout process. Do not change
shared workloads imperatively. Observe deployment stability and exact imageID.

Then install the matching APK over the existing app and verify normal authenticated
capture, 30 seconds offline, reconnection, all three speech sections exactly once,
zero pending receipts, persisted transcript and confirmed recording closure. Test
source refusal still remains incomplete rather than silently inventing success.
Issue7 requires this acceptance and does not close from image build or PR merge.

Rollback: revert this TEST digest pin via GitOps to the previous desired digest
after checking it against the live baseline. Existing client fallback must not
present legacy reconnection as proved continuity. Production is outside scope.
