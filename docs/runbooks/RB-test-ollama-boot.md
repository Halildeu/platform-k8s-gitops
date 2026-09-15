# TEST Ollama Boot Dependency

Tracked by [#3790](https://github.com/Halildeu/platform-k8s-gitops/issues/3790),
blocking Product Slice #3399 recording -> persisted analysis -> browser reopen.
This does not authorize production changes, model downloads, source upgrades,
historical analysis replay, or a second resident diarization model.

## Contract

- Use `scripts/faz24/test-ollama-boot.ps1` with Windows PowerShell 5.1 and
  explicit `-TestOnly`. `Install` and `Verify` never start the task.
- Pin executable SHA256, valid Authenticode signer thumbprint, launcher SHA256,
  existing model manifest SHA256, absolute model store, runtime home and local
  non-administrator SID. No unpinned auto-update or model selection change.
- `platform-ai-ollama-test` uses S4U, LeastPrivilege, startup trigger, unlimited
  execution, IgnoreNew and bounded scheduler restart cadence (one minute,
  999 retries). Existing conflicting definitions are rejected, not overwritten.
- The runtime checks the actual identity and elevated token, not only the
  task's displayed RunLevel. On the observed host, the administrator's S4U
  task still had an elevated token despite a Limited definition. Do not relax
  that guard or change host-wide UAC to work around it.
- Provision a dedicated non-administrator TEST account. Grant ReadAndExecute
  only on the approved executable directory, model store and launcher directory;
  grant Modify only on its isolated runtime home. Preserve all unrelated ACLs.
  The executable/launcher/model manifest remain read-locked while serving.
- The dedicated account also needs `SeBatchLogonRight`. Verify that exact
  account right through LSA; add only that right to the owned TEST account if
  absent and reread it. Preserve all existing rights and every explicit deny.
  Never grant Administrators/Backup Operators membership to solve a batch-logon
  failure. Task Scheduler event101 code `2147943785` is not successful startup.
- A local administrator provisioning another user's S4U task supplies an
  in-memory `SecureString` via `-RegistrationPassword`; it is passed only to
  Task Scheduler COM registration, never to a process command line or task
  action. S4U does not retain a logon password. See Microsoft's
  [task security contract](https://learn.microsoft.com/en-us/windows/win32/taskschd/security-contexts-for-running-tasks).
- Bind only `127.0.0.1:11434`. Remove inherited `OLLAMA_*` overrides; set the
  explicit existing model store, NOPRUNE and the isolated process home.
  Native output is discarded; failure metadata contains only fixed stage and
  UTC time in the isolated home's `ollama-test-failure.json`.

## Verification

1. Claim the issue and read the live source/config/task/model pins. Preserve the
   existing meeting configuration and STT listener owner. Run
   `scripts/faz24/tests/test-ollama-boot.ps1` on Windows PowerShell 5.1.
2. Install without starting, then reread XML and all artifact hashes. Confirm
   S4U, Limited, selected SID, exact arguments and the explicit owner marker.
   Verify the account's effective PowerShell policy in its actual S4U context.
   If Restricted blocks the launcher, stop and obtain approval for any scoped
   policy change. Do not use Bypass, encoded script execution, a different
   interpreter, or a machine/GPO change to bypass that decision. Metadata-only
   identity/policy diagnostics are not permission to execute the blocked service.
3. Start only the owned dependency task. Verify loopback listener ownership,
   non-administrator process identity, API version and existing model digest.
   Reconnect over SSH and prove the task survived the previous session.
4. Only then start the existing qualified TEST meeting task. Use its canonical
   action contract and `Test-MeetingAiDependencyReadiness`. Require delivery,
   consumer worker and Redis-group readiness, unchanged config/source, and an
   unchanged STT listener. Readiness is not functional acceptance.
5. Run a NEW synthetic recording through the existing canonical token/evidence
   chain; prove a newly persisted analysis, browser reopen and negative access.
   Read all temporary-user/role/token cleanup receipts. Never reanalyze an old
   rejected record to manufacture recovery evidence.

Task definition and a successful on-demand S4U run are not an observed reboot
test. A host reboot affects other users and STT: keep that claim unverified
until a coordinated reboot is actually observed.

## Rollback

Before stopping anything, validate the owned task description, principal,
action and pinned launcher. Disable and stop only `platform-ai-ollama-test`;
verify the exact owned process tree and listener are gone. Remove only that
owned definition when appropriate. Remove only the newly added account's ACL
entries; disable that dedicated account if its dependency is no longer used.
Do not delete the existing model store or alter other users/groups/tasks.
Never stop the existing STT task or change the approved Meeting AI config as
part of dependency rollback. Record that analysis availability is affected.
