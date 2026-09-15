# TEST Meeting Dependency Recovery - 3790

Tracked by [#3790](https://github.com/Halildeu/platform-k8s-gitops/issues/3790).
Customer blocker: Product Slice #3399 recording -> durable analysis -> browser
reopen. This evidence does not close #3746 internal diarization integration.

## Discovery

At 07:39 UTC the existing Windows host had booted at 02:47:26Z. Meeting AI's
task was Ready, last result1 at02:47:52Z; port8300 was unreachable. Transcript-free
log markers identified Ollama readiness failure. No Ollama task, process or
port11434 listener was present. STT8200 remained ready on `e386b996`.

Preserved approved TEST pins:

- GPU source: `e386b996cae22f08294a83d840f0e92d4a82cd53`.
- Meeting config SHA256: `461497a2dc7ead5b128587ce88941366c0a1a860a87ffefa267a7fe662355637`.
- Existing model: `qwen3.8:27b`; manifest digest
  `22130167c4c20e20c7b71454612966ca8e8171e9b3cc8ab6ce8aa6cbfec79643`.
- Existing signed Ollama executable SHA256:
  `e4fe6bd835fe146659f5c969dccaff2e25a9de63d90ee204ca5d11b9034b0ca5`.

## Integration Findings

The initial transient process did not survive SSH disconnect and never exposed
the API. This was not a successful recovery. Initial task candidates also
failed integration: argument-array construction and omitted XML schema defaults
were corrected before acceptance. Windows PowerShell 5.1 native stderr behavior
was reproduced with a harmless local child and covered by native exit-code tests.

A fixed-stage diagnostic then proved runtime identity rejection. A separate
metadata-only S4U task confirmed the selected administrator still had an elevated
token despite its Limited definition; that diagnostic task was removed and
absence verified. The runtime guard was not relaxed; UAC was not changed.

A new dedicated `svc-ai-test` account was created without administrator
membership. Only approved executable/model/launcher directories received its
ReadAndExecute ACE; only its isolated runtime home received Modify. The account
was added to standard Users, not Administrators. Task event101 code2147943785
identified missing batch logon; only its `SeBatchLogonRight` was added through
LSA and reread, preserving existing rights and explicit denies. Initial account
creation validation errors occurred before account creation; successful identity
and ACL readbacks were performed afterwards.

Cross-account S4U registration required a one-time in-memory credential, as
specified by the Windows task security contract. The dedicated account's random
credential was not printed, persisted in a helper file, or passed on a process
command line. Registration uses COM with S4U; no logon password is retained by
the scheduled task. Existing account credentials were not changed.

## Source Verification

- Windows PowerShell5.1: **63 offline behavioral checks passed**, including
  actual native stderr and exit status, paths with spaces, separate argv tokens,
  default-normalized XML, collisions, identity denial, isolated home, inherited
  Ollama override removal and cross-account SecureString registration boundary.
- Launcher SHA256: `2fbf0fe431e6252071700fe9d98ce6061ceeba61cb4018d243294a8471eac890`.
- Test script SHA256: `9eabc68c9204777daa3e42338886dc1a256f2db24b9ec244d2db0c978d6de889`.
- New workflow YAML lint and `git diff --check` passed locally. CI is separate.
- [Operational contract and rollback](../runbooks/RB-test-ollama-boot.md).

## Acceptance Boundary

At08:40 UTC a second metadata-only S4U diagnostic verified the dedicated
account's non-elevated token and executable/model/launcher/parent-attribute
read access. Its effective PowerShell policy was `Restricted` (all five scopes
Undefined); a non-mutating launcher probe returned `PSSecurityException` /
`SecurityError`. The diagnostic task was removed and absence verified.
The owned dependency task is disabled while approval is pending for changing
only this new TEST account's CurrentUser policy to RemoteSigned. No execution
policy, GPO or UAC change has been applied; no Bypass fallback is permitted.

Recovery remains **unverified** until exact-source/config dependency readiness
and a NEW persisted/browser analysis pass. Failed starts did not restart the
existing Meeting AI task or mutate historical analyses. No production change,
new model download, provider-default change, STT restart, or raw audio capture
was performed in this recovery work. On-demand S4U acceptance is not a host
reboot test; coordinated reboot survival remains a distinct unverified claim.
