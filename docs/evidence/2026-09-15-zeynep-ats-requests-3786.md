# ATS Request Verification - 2026-09-15

Tracked by platform-k8s-gitops#3786; customer slice platform-web#953;
acceptance platform-web#965, platform-web#1184 and the role matrix in platform-web#992.

## TEST Authorization Matrix

Observed 2026-09-15T06:29:36.926Z through trusted HTTPS at
`https://testai.acik.com/api/ats/v1/recruiter/applications`.
Existing TEST Vault smoke client and personas were used in memory only.
No accounts, roles, credentials, application data or production settings changed.

| Persona | Token HTTP | Recruiter API HTTP | Expected |
| --- | --- | --- | --- |
| Recruiter with application.read | 200 | 200 | Allow |
| Authenticated roleless | 200 | 403 | Deny |
| ATS reader without application.read | 200 | 403 | Deny |
| ATS reviewer without application.read | 200 | 403 | Deny |
| Anonymous | n/a | 401 | Deny |
| Untrusted-origin preflight | n/a | 401, no ACAO | No cross-origin grant |

All four issued sessions were logged out (204), then their refresh tokens
were introspected (200, active=false). Token audiences included ats-api.
Response bodies were drained without being logged. This covers these exact
personas, not every platform role and not attended screen-reader acceptance.

Probe source SHA256:
`61ea136c0b035b550e99794ceff7574811bc41a1a580b671c44ecfdfd76ef5f8`.
The probe was local and uncommitted; no credentials or tokens are evidence.
Initial matrix readback:
[web#992](https://github.com/Halildeu/platform-web/issues/992#issuecomment-5675727379).

## Runtime Baseline and Integration Boundary

At preflight, TEST frontend was Ready 1/1 at source
`c39b9df025c3b3391fd54c243cb1d2660e59bace`, digest
`sha256:f9b5ea13d6eba14414476eb432aec10891f6d7b571a7f72b13746342beeda845`.
This is the rollback baseline. TEST ATS ready pod imageID was
`ghcr.io/halildeu/ats-app-boot@sha256:e2b3229679175f74d1fee8c7fedb066e69368218e7ec9cec9b289a0864696299`.

Central Argo platform-test was Synced/Healthy at
`3e708405c0ed27bafb90bc607a953c39818a37f3`.
platform-eso-test was separately OutOfSync/Degraded due to
perf-alertmanager-teams-secrets; tracked by platform-k8s-gitops#3784.
All 42 platform-test ExternalSecrets reported Ready=True. This is not a
blanket infrastructure-health claim.

## Source Evidence

- PR1179 merged as `21da64d878c5e259ace5dc8c5c13cb558e55efb0` after
  source review and CI. Intermediate GitOps PR3785 and PR3787 were closed
  unmerged, superseded by the final combined pin PR3788.
- PR1180 exact reviewed head `5cff0397e5293e9f4381eff788c866475bbfc3e6`
  includes PR1182 and PR1183. Fixes isolate stale withdrawal/offer responses
  from the newly selected application and update only the originating,
  still-present matching session's list summary.
- PR1180 merged as `8265db52089f979cd4e598c4428f95fb29b059e3`;
  month-range PR1186 merged as `cc6ed8746962e0fd112990863bc6a99a9ca95aee`.
- Fresh final-main focused suite: 263/263 tests across nine files. Changed-file lint and
  production build passed. Full shell typecheck retains 543 baseline
  diagnostics; it is not reported passing.
- Mocked local browser tests and source CI are not actual TEST delivery;
  separate actual TEST evidence follows.

## Immutable TEST Rollout

PR3788 merged at `d20a32962a2d8832d7512379fdd1755707148a72` after 24 successful
checks and a fresh quota/registry preflight. Rollout run
[34940819768](https://github.com/Halildeu/platform-k8s-gitops/actions/runs/34940819768)
succeeded. Argo platform-test was Synced/Healthy at that revision.
Ready pod `frontend-688bb5d566-5hm62`, desired pin and runtime imageID matched
`sha256:db0a19fadc91a6e8a2c0e19b4d1e8a5629e08ddb7817f28efcb2ad3e5746818c`.
The official runtime verifier passed source/build-info/root module checks:
source `cc6ed8746962e0fd112990863bc6a99a9ca95aee`, asset `index-hLzQeYX0.js`.
The browser journey separately used trusted HTTPS without ignoreHTTPSErrors.
Production render before/after SHA256 was unchanged:
`31829fc97579253d381ab21045e7203b0cfe1549e7c721f2f02be5198833f5fc`.
Rollback is a GitOps pin reversion to the baseline above, not an imperative patch.

## Actual TEST Candidate and Recruiter Journey

Observed 2026-09-15T07:30:43.700Z, on the exact source/digest above.
This is an automated real TEST journey with synthetic data, not real-person
CV acceptance and not mocked/local-only delivery.

- A synthetic candidate found two existing synthetic jobs through the public
  careers UI and submitted both through real application endpoints (201).
- First reference `app_OrnRQ8YXgB0Lhw0ENvttx44Y`; second
  `app_NNfwDjtX0-yfQo0yNRP7dFCd`. Both receipts and candidate access worked.
- Switching/reloading preserved both sessions. Withdrawing the first left it
  WITHDRAWN and the second SUBMITTED, independently checked via candidate API.
- Second application imported a two-experience synthetic PDF using the
  supported uppercase section headings. Parsed `2022-09 - 2024-03` appeared
  correctly in separate month inputs. Candidate edited the end to `2024-04`;
  provenance showed the candidate edit. Submitted structured fields and the
  subsequent authenticated recruiter persisted read both retained that range.
- Removing the first local entry and reloading preserved the second access;
  the first server record remained WITHDRAWN. Single-entry list hiding was
  checked against the implemented UI, not mistaken for lost data.
- 1440px and 390px screenshots were inspected: zero horizontal overflow;
  no incoherent text overlap observed. Browser page errors: zero. Candidate
  keys were absent from URL and localStorage. Browser context destroyed.
- Recruiter logout returned 204; refresh-token introspection returned 200,
  active=false. Existing TEST credentials remained in memory only.

Harness SHA256 `d976aa1b85c43f44ed103e19fb66bd59d75b8ca620c9ac25a00d86b048bce3d1`.
Sanitized receipt SHA256 `2f4199ead3237641dbfc44d7fc2325928540ca07b233730bc280da6b54144c50`.
Local evidence directory: `/tmp/ats-965-test-evidence` (receipt.json and inspected PNGs).
Desktop PNG SHA256 `85373146b38307ea6af59987695a6ffac24beef5ff9a6494789b98002f994afc`;
mobile PNG SHA256 `c9b287d0f96384f072af897d7fd419b007c7c4d6e3807c9bbf43e35d45090a9c`.

Earlier harness runs are not hidden: wrong response path, unsupported fixture
heading style, single-entry list expectation and an unsupported audit page size
stopped earlier runs. Recruiter readback found eight synthetic applications
from these attempts, including the final two; they were retained, not deleted.
The first timed-out response listener did create a server record. No claim of
zero mutations is made for that attempt. Preflight import-only attempts created
no applications. Mixed-case header extraction remains in broad ats#213, which
this supported-layout month fix does not close.

## Scoped Request Readback

- [web#965](https://github.com/Halildeu/platform-web/issues/965#issuecomment-5676502511)
  and [web#1184](https://github.com/Halildeu/platform-web/issues/1184#issuecomment-5676504155):
  closed, Project2 Done and unclaimed, authoritative readback verified.
- Original web#1158/#966/#1003 and backend#1172 source review are also closed
  on their separately attributed evidence; this document does not enlarge
  their acceptance scope. Teams PR1171 remains draft and real tenant #3716 open.
- [mobile#25](https://github.com/Halildeu/platform-mobile/issues/25#issuecomment-5676489066):
  source review closed, Projects2/4 Done, unclaimed. PR26 merged only into
  PR24 feature branch at `6651da290ff6da5aac3d1d2b68dfa65f008d126a`.
  Local exact-head 228 tests/typecheck/lint and unit CI34941814910 passed.
  Prior native CI34938927883 tested checkout `9dab8d3` with identical merged
  source tree; APK SHA256 `d80e16af7dff03e7ae35f099f47600d78a696d7b1b5eac7dac329fdfb087a0f3`,
  Maestro2/2 and screenshots verified. New native34941814939 was still running
  at source closure, not reported successful. PR24/15 draft, real-device
  #8/GitOps#3673 open; no main merge or deployment.

Production promotion, real PII, legal acceptance and named human
screen-reader acceptance are outside this evidence.
