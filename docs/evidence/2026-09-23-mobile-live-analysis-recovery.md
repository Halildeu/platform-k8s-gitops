# Mobile live-analysis TEST recovery — 23 September 2026

Tracked by platform-mobile#8 and GitOps#3440. User requirement: show decisions
and actions while recording; post-stop analysis is a separate requirement.
Agent-initiated under Zeynep's existing instruction to verify and continue the
independent mobile work. No independent human review or production approval
is implied.

## Cause and repair

Before repair, run [35823107425](https://github.com/Halildeu/platform-k8s-gitops/actions/runs/35823107425)
acknowledged all audio but received zero analyses over public SSE.
[35823384610](https://github.com/Halildeu/platform-k8s-gitops/actions/runs/35823384610)
matched that meeting's upstream failures before HTTP in 39–43ms.
[35824331148](https://github.com/Halildeu/platform-k8s-gitops/actions/runs/35824331148)
proved TCP reachable but TLS rejected expiry. GPU certificate metadata identified
the server leaf expiry at 2026-09-20T19:27:29Z; the mounted gateway client and CA
were still valid. This does not attribute earlier September incidents to the
same certificate.

[PR3796](https://github.com/Halildeu/platform-k8s-gitops/pull/3796) merged after
17 checks. [Dry-run35826053223](https://github.com/Halildeu/platform-k8s-gitops/actions/runs/35826053223)
and [apply35826163190](https://github.com/Halildeu/platform-k8s-gitops/actions/runs/35826163190)
renewed only the expired TEST leaf, retaining CA, key, subject, SAN and ACL.
New public leaf SHA256 is
`81ba80219fba76cef7a2faf41220c869f9c4b9cd1ffc86996c9a31ec0e4c5b4a`, valid until
2026-12-22T06:19:02Z. Only the existing Caddy task restarted; its admin API stayed
disabled. Keys remained on the host. Application images, client/Vault identity
and production were unchanged. Both actual gateway mTLS probes passed
curl0/SSL0/HTTP200. Rollback procedure remains in
[the runbook](../runbooks/RB-mobile-live-mtls-leaf-renewal.md).

Post-repair run [35826264475](https://github.com/Halildeu/platform-k8s-gitops/actions/runs/35826264475)
received two valid live snapshots (first at 44.147s), with summary and one action
but no decision. It correctly failed total product acceptance.
[Metadata35826419855](https://github.com/Halildeu/platform-k8s-gitops/actions/runs/35826419855)
confirmed two new successful upstream requests and no recent errors. The old
15s keyword fixture has no checked-in reference transcript, so its missing
decision did not establish failure on a known positive decision example.

## Explicit-decision acceptance

[PR3798](https://github.com/Halildeu/platform-k8s-gitops/pull/3798), merge
`a4a131f5d9ba316c9e09ffe071a14ab63cd32a02`, selects the existing synthetic
76.696s two-voice fixture only for optional live acceptance. The reference
includes accepted decisions and assigned tasks. Both audio and reference
hashes are enforced. Before-EOF and saved-result criteria are unchanged.
17 CI checks passed, including 53 Linux recorder/cleanup tests, 13 SSE/fixture
tests, 10 speaker tests and 2 SSH metadata tests. An earlier Windows invocation
of the Linux/Bash suite failed on environment/path/tool execution; the actual
Linux suite passed rather than being skipped or weakened.

[Run35827619982](https://github.com/Halildeu/platform-k8s-gitops/actions/runs/35827619982)
passed at 2026-09-23T06:45:53Z. Downloaded artifact10736241063 was inspected.

| Check | Observed result |
|---|---|
| Public gateway SSE | HTTP200, three accepted analyses, six heartbeats, zero rejected/malformed events |
| First live event | 31.510s from audio start |
| Usable snapshot before EOF | Verified visible summary, two decisions, one action at 76.186s |
| Audio/STT | 767/767 frame ACKs; 166 partial/112 final events; 6/7 keywords |
| Termination | eof ACK, drained and FINISHED; no terminal timeout |
| Persisted product | Verified 142-character summary, four decisions, three actions; 112 transcripts |
| Readback/reopen/source | Same meeting/session, HTTP200 and unchanged fingerprint |
| Temporary state | User deleted; direct grants and transcript scope restored; token removed |
| Artifact privacy | Secret scan passed; no audio, transcript, analysis payload or bearer included |

Meeting: `f60506d5-4fd5-497a-b688-3e512a06f4c9`.
Gateway session: `SES-830674de-7904-4dbd-96b8-cd9999e5c9b7`.
Canonical session: `c413649a-c88e-49c0-9e11-d0745c5f0945`.
Result fingerprint:
`8fe0d3bcef17d4dbb1f06613eacb1669625c0e3ef096b7ee538a1555dfb1c7ca`.
Audio hash:
`702c3a94e34ca09915237e3fabf11a037602514bb93cec13555ecd3ab7fe2676`.
Reference hash (LF):
`8b1c2807dbccdef85f9c6f44c16e48c88fca8e5abba054c32af521627bf02204`.

## Remaining acceptance

This is real TEST transport/inference/readback with synthetic speech. It is not
physical Android/iOS UI, microphone, lock/background, network recovery, push,
speaker identity, complete semantic precision/recall or a general latency SLA.
Mobile PR45 source `bcca59bac4a0048feba3e889f8de8b36ac1df22a` has 487 local
tests/type/lint and a verified ARM64 APK, SHA256
`45eb251d0f426cad29892829de0534ef49bf7c7b2ca140bd8211a8b7937349de`.
The phone must receive that package before its text/PDF/tab fixes are accepted.
Previously attended recording/reopen/isolation checks need not be repeated as
a full phone tour. Native push and iOS remain separate; this APK has FCM TEST off.
No mobile issue is closed by this result.

Future unattended certificate renewal and expiry alerting remain tracked by
#3440. The gateway client expires 2026-10-21T11:42:41Z, earlier than the renewed
server leaf; CA expiry is 2027-06-22T19:27:29Z. One-shot recovery does not prove
automatic rotation. Project board writes were unavailable with the existing
project scope and are not claimed successful; no credential scope was expanded.
