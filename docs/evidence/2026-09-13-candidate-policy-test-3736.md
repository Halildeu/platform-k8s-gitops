# Candidate Policy TEST Evidence - 2026-09-13

Tracked by platform-k8s-gitops#3736, platform-web#1003 and ats#268.

## Scope and Immutable Artifacts

- TEST only; agent-initiated under owner authorization, GitHub actor Halildeu.
- ATS PR269 merge `9b51a4fb5bcc432e1b4c48f0e57f3104e04c388d`;
  build/CRITICAL scan/SBOM/push [34755456164](https://github.com/Halildeu/ats/actions/runs/34755456164) succeeded.
  Registry and ready pod imageID both match
  `sha256:e2b3229679175f74d1fee8c7fedb066e69368218e7ec9cec9b289a0864696299`.
- Web PR1174 merge `5f10941e3e7b59e780d9d05aaa403a6aa9bf81dc`;
  image/SBOM/signed provenance [34756389782](https://github.com/Halildeu/platform-web/actions/runs/34756389782) succeeded.
  Source OSV gate passed; no separate frontend runtime-image vulnerability scan is claimed.
  Registry linux/amd64 child and ready pod imageID both match
  `sha256:b6acdfa146a0d68d52115666b0ce99d830a2a5fc0afb575244adcbc33f8857e2`.
- Backend GitOps PR3737 -> `c67f0b94a8e6714cbf9734616ffba75a12c57cfc`,
  explicit canonical reconciliation [34756278485](https://github.com/Halildeu/platform-k8s-gitops/actions/runs/34756278485) succeeded.
  Backend policy/pod verification preceded frontend release.
- Frontend GitOps PR3738 -> `1cf8a5adb7158de0c33ced36e106e98c00584e1b`,
  automatic reconciliation [34756720058](https://github.com/Halildeu/platform-k8s-gitops/actions/runs/34756720058) succeeded.
  Argo platform-test Synced/Healthy, operation Succeeded at that exact revision.
  Trusted HTTPS build-info reports exact source `5f10941e3e7b59e780d9d05aaa403a6aa9bf81dc`.
- Structured overlay before/after comparison: only TEST ATS/frontend images change;
  production render, configuration, roles, secrets and policy mode are unchanged.

## Actual TEST Customer Journey

Observed at 12:22-12:23 UTC on `https://testai.acik.com`, Chromium, no API mocks.
Persona: synthetic external candidate, no employee/admin identity or real CV used.

1. Open public tenant job `careers/acik/jobs/urun-yoneticisi`; follow application link.
2. See server-enforced `real-allowed` disclosure separately from consent text.
3. Acknowledge CV notice and upload an actual generated synthetic PDF. Server
   creates CV import with `candidate-resume-import-v2`; candidate accepts field proposals.
4. Review imported fields and manually complete summary/skills. The first harness
   attempt stopped at required-field validation, not at submission; this was not
   counted as success. The subsequent full journey included normal manual completion.
5. Confirm application with `kvkk-application-v2`; POST returns 201/SUBMITTED.
6. Receipt `app_ARUDU72shQn9d2h215M8SXSN` opens in Candidate Area, survives browser
   reload, and authenticated candidate API independently returns the same status.
7. Read exact row from TEST PostgreSQL: notice `kvkk-application-v2`, status
   `SUBMITTED`, notice/accuracy timestamps present, email is synthetic `.test`.
   CV-import GET independently retains the v2 notice. Raw PDF/token/PII are not evidence.
8. Same receipt without candidate key returns 404. Unknown application and CV
   notice v999 each return 400. Neither negative test is a successful intake.

No browser page errors; no horizontal overflow at 390/1440px. Actual TEST screenshots
were inspected. The earlier local browser policy matrix and 10 mock browser tests
remain local/synthetic test evidence, not substitutes for this TEST journey.

## Source Verification and Limits

- ATS exact postcommit full Maven verify: 954 tests, zero failures/errors, one skip.
- Web: 134 focused tests, 10 mock browser regressions, changed-file ESLint and Vite
  build passed. Full shell typecheck still has 543 baseline diagnostics, with no
  added/removed normalized diagnostics. It is not reported as a passing typecheck.
- All source PR and GitOps promotion PR checks passed before merge.
- Existing 52 v1 application records were still present before synthetic v2 intake.
  Existing legal notice text and retention/data-mode settings were not changed.
- This is TEST applicant CV/receipt acceptance, not legal approval, production go,
  a new recruiter-role acceptance, or Zeynep's separate accessibility acceptance.

## Rollback

Use reviewed GitOps only, frontend first: source `b013af1eb030864799dc50c8c1907a19b056551c`,
frontend digest `sha256:b60d1b06813f31fe7dfbf838938fcf3b1f26dfc14d5065ae75b65b8ec0d15c57`.
Then ATS digest `sha256:c2baf0e6cedeada526f4f9814727bbd002ff4eb6b7f6d7dd9138c2977b7f5cec`
with acceptance/recovery/D29 pins aligned. No imperative shared-workload patch.

## Communication and Outstanding Owner Inputs

Approved email from ai mailbox to the employee (CC current operator) was sent once,
then exact Sent copy read back at 11:24:50 UTC. Evidence:
[3730 sent-message verification](https://github.com/Halildeu/platform-k8s-gitops/issues/3730#issuecomment-5652963853).
No later incoming message was found in the subsequent mailbox check.

VPN client/OS, desktop package source/reopen retest and Teams TEST organizer still
need recipient input. Mobile PR22's unit/Android build/Maestro checks passed at
`556a8036b5081e8e0fde41de4d520b308056d19e`; its separate owner still holds real-device
acceptance. Teams callback/source wiring remains tracked by #3716; none of these
unrelated journeys is claimed delivered by the candidate-policy change.
