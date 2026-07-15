# RB-faz24-wg-bplus-i3-management-audit-drift-monitor

> Scope: [#1864](https://github.com/Halildeu/platform-k8s-gitops/issues/1864)
> / [#2434](https://github.com/Halildeu/platform-k8s-gitops/issues/2434) /
> Faz 24 WG-B+ I3. This runbook proves the Denetim Windows management-audit
> controls without making the SSH transport account an administrator. It does
> not prove direct-STT, app-mTLS, product quality, pilot acceptance, or any
> production gate.

## 1. Current Boundary

The canonical path has two identities:

| Identity | Allowed role | Explicitly not allowed |
|---|---|---|
| `SYSTEM` scheduled task | Read protected policies/logs/services/firewall and atomically write the bounded snapshot | Network transport, GitHub access, raw evidence export |
| `svc-denetim-agent` | Read the bounded snapshot over the existing WireGuard + SSH path | Administrator membership; policy, Security log, WireGuard, firewall, scheduled-task, transcript or snapshot writes |

This split implements least privilege. Adding `svc-denetim-agent` to local
Administrators, granting it firewall/task/policy mutation rights, or restoring
direct protected-log queries is not an accepted shortcut.

The source contract is fail closed:

- missing or malformed snapshot: fail,
- unknown contract/schema: fail,
- age above canonical `900` seconds at validation time: fail,
- artifact-declared thresholds that differ from canonical policy: fail,
- non-`none` error class: fail,
- status/verdict mismatch: fail,
- a syntactically passing but semantically weak observation: fail.

## 2. Required Controls

The bundle schema is `faz24.wg-bplus.i3.audit.v2`, the remote snapshot schema
is `faz24.windows-audit-snapshot.v2`, and every check carries
`control.contractVersion=faz24.windows-audit-control.v2` with these fields:

- `expected`: declared machine-readable threshold,
- `observed`: bounded machine-readable measurement,
- `verdict`: `pass` or `fail`,
- `source.kind` and `source.locator`,
- `collectedAt`, `maxAgeSeconds`, `ageSeconds`, `fresh`,
- `errorClass`.

| Check id | Required semantic proof |
|---|---|
| `openssh-event-log` | OpenSSH Operational log query succeeds and the lookback contains at least one event |
| `powershell-transcription` | Transcription and invocation header are enabled; transcript, snapshot directory and snapshot file ACLs exactly restrict write access to SYSTEM/Administrators and give the transport account read-only access only to the snapshot; transcript retention rejects descendant reparse points before traversal and is enforced at no more than 14 days and 1 GiB without exporting names/content |
| `powershell-script-block` | Script-block policy is enabled, log query succeeds and at least one 4104 event exists; content is omitted |
| `failed-login` | Security log is queryable and native Windows Logon failure-audit bit is enabled; zero 4625 events is valid |
| `wireguard-health` | `wg show all dump` succeeds, tunnel service/interface/peer exist and latest handshake is within threshold |
| `eset-firewall-drift` | All WireGuard-scoped rules exactly match Enabled/Direction/Action/Protocol/LocalPort/RemoteAddress/Profile/LocalAddress/Program/Service; the hard-block count is zero for broad protected-port rules whose Program and Service filters are both unconstrained; every broad rule with a concrete Program or Service is explicitly reviewed and its current count equals the count persisted at Apply; ESET core services are running |
| `time-sync` | `w32time` is running, status/source queries succeed, the language-independent registry sync type is one of `NTP`/`NT5DS`/`AllSync`, the source is not local/free-running, and a Time-Service success event is fresh |
| `staging-connection-log` | The exact canonical target is reached, its route-device hash equals the selected WireGuard-interface hash, staging WireGuard metadata has at least one peer, socket query is available, and a metadata-only audit record matches only the current SSH attempt's random correlation id within 180 seconds |

The verifier checks values, not only labels. For example, a check cannot pass
with `broadConflictCount>0`, a constrained-rule count that differs from the
persisted approval count, an absent handshake, a stale time event, or a
failed-login count whose audit policy was not proven. Snapshot/control v1
evidence predates this approval binding and is intentionally rejected; collect
fresh v2 evidence rather than rewriting historical artifacts.
The collector and verifier also bind `remoteSnapshotPathHash` to the canonical
`C:\ProgramData\Acik\Faz24\I3\audit-controls\snapshot\audit-snapshot.json`
path; a bundle cannot rebind the read-only transport to another snapshot path.

## 3. Redaction Contract

Allowed in the exported bundle:

- bounded counts, booleans, timestamps, exit codes and error classes,
- stable hashes for target/path correlation,
- fixed control/rule/log source names,
- relative evidence references.

Never export:

- passwords, cookies, JWT/bearer values, private keys or certificates,
- event messages, user identities from Security events or raw event records,
- PowerShell command/script/transcript contents,
- WireGuard private/public keys or endpoint addresses from `wg dump`,
- audio, transcript or meeting content,
- raw SSH stderr.

The local transcript directory remains readable only by SYSTEM and local
Administrators. `svc-denetim-agent` receives read-only access to the snapshot
directory, not to transcripts or privileged logs.

## 4. Build The Operator Package

From canonical `main` after the source PR is merged:

```bash
gh workflow run faz24-i3-denetim-audit-controls-package.yml \
  --repo Halildeu/platform-k8s-gitops \
  --ref main \
  -f target_user=svc-denetim-agent \
  -f management_address=10.99.0.1
```

Download `RESTRICTED-faz24-i3-denetim-audit-controls-<run_id>` and verify every
entry in `SHA256SUMS` before copying it to Denetim PC. The artifact is a
restricted operator configuration: it contains target identity metadata but no
secret material, has one-day Actions retention, and must not be posted to an
issue, chat or public file store. The package contains:

- `collect-audit-snapshot.ps1`,
- `install-audit-controls.ps1`,
- `rollback-audit-controls.ps1`,
- `baseline.json`,
- `package-manifest.json`,
- `README.md`,
- `SHA256SUMS`.

Building the artifact does not connect to or mutate Denetim PC.

## 5. Elevated Apply And Rollback

Run only from an approved elevated local PowerShell 5.1 session. Do not run
from a network share.

First apply the policies, exact rules, protected ACLs and SYSTEM task without
disabling pre-existing broad rules:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\install-audit-controls.ps1 `
  -Mode Apply
```

If preflight reports only constrained broad rules, first review their owner and
dependency impact, then bind that exact observed count to the transaction:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\install-audit-controls.ps1 `
  -Mode Apply `
  -ApprovedConstrainedBroadRuleCount <reviewed-count>
```

`Apply` binds the rollback state to the immutable package fingerprint and,
before mutation, captures the initial registry, scoped Logon audit bits, exact
firewall rule existence, scheduled task, ACL state and any pre-existing managed
collector/baseline/snapshot files. It seeds the first snapshot, reapplies the
exact protected ACL to the new file and then collects a second snapshot so
directory/file ACL proof comes from live state. Partial failure automatically
restores the captured state. An incomplete transaction or a different package
fingerprint requires explicit rollback before retry; same-package re-Apply is
validation-only and does not mutate.
If a reserved exact rule already exists, its address/port semantics must match
exactly; the package never rewrites it. Rollback removes only exact rules that
did not exist before Apply. A protected-port rule with a broad remote address
is a hard block when both its Program and Service filters are unconstrained. A
rule with at least one concrete Program or Service remains an explicit review
item: Apply requires the exact reviewed count, persists it in protected rollback
state and rejects a changed count. The exported snapshot contains only the
bounded counts and approval boolean, not rule names. A non-zero result with
`broad-firewall-conflicts-require-separate-reviewed-remediation` means an old
inbound rule with unconstrained Program and Service still covers `22`, `8200`
or `8243`. Stop before mutation and open a separate reviewed operation that
identifies rule owner, dependencies, impact and its own rollback. This package
has no broad-rule disable switch and never changes pre-existing broad rules.

Validate the generated snapshot:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\install-audit-controls.ps1 `
  -Mode Validate
```

Rollback restores the initial captured state. It restores only the captured
Windows Logon audit success/failure bits, never the full machine audit policy:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\rollback-audit-controls.ps1
```

For the first package qualification, perform the rollback drill after a clean
Validate, verify the restored connectivity/baseline, then run Apply and
Validate again before collecting repository evidence. Rollback is also
mandatory if SSH/WireGuard/STT/mTLS connectivity regresses, the
SYSTEM task cannot produce a bounded snapshot, or an exact rule blocks an
approved management path. After rollback, collect fresh connectivity evidence
before attempting another apply.

## 6. Pin The Denetim SSH Host Key

The self-hosted runner must have an independently verified Denetim OpenSSH host
key in the runner-local file below before the evidence workflow starts:

```text
${GITHUB_WORKSPACE}/../.faz24-i3-ssh/faz24-i3-denetim_known_hosts
```

The file must be a non-empty regular file, not a symlink, no larger than 1 MiB
and not writable by group/other. Establish or rotate the fingerprint through an
approved out-of-band Windows/operator channel; `ssh-keyscan` reachability alone
is not identity proof. The collector uses `StrictHostKeyChecking=yes`, this
single `UserKnownHostsFile`, and `GlobalKnownHostsFile=/dev/null`. TOFU and
`accept-new` are not allowed. Evidence contains only file/path hashes and
bounded status metadata, never the host key itself.

## 7. Repository Evidence Run

After elevated validation succeeds, rerun the self-hosted collector:

```bash
gh workflow run faz24-wg-bplus-i3-evidence.yml \
  --repo Halildeu/platform-k8s-gitops \
  --ref main \
  -f denetim_ssh_target=svc-denetim-agent@10.99.0.2 \
  -f lookback_hours=2 \
  -f wg_interface=auto
```

The self-hosted `staging-sw` runner uses the existing private key and pinned
known-hosts file locally. The artifact records only key/path fingerprints and
target hashes. Rejected collector/verifier output remains visible only in the
bounded workflow summary; no downloadable artifact is uploaded unless both
collector and verifier return zero. Never override the verifier result.

Run the verifier locally only against the downloaded bounded JSON:

```bash
python3 scripts/faz24/verify-wg-bplus-i3-evidence.py \
  /protected/path/wg-bplus-i3-evidence.json
```

## 8. Acceptance Sequence

All of the following are required for bounded I3 review:

1. Restricted package was built from exact canonical `main`; its one-day
   artifact was handled as identity-bearing configuration and `SHA256SUMS`
   passed.
2. An explicit firewall impact decision found zero unconstrained hard-block
   rules; any constrained broad rules were reviewed and their exact current
   count was bound to the protected Apply state.
3. Elevated `Apply` captured rollback state before mutation and its internal
   validation reported zero failed controls.
4. Separate elevated `Validate` reported zero failed controls.
5. Rollback drill restored the baseline; connectivity was verified; a second
   Apply and Validate established the final candidate state.
6. `svc-denetim-agent` remains non-admin and cannot write the snapshot.
7. The independently verified pinned SSH host key passed strict checking.
8. Fresh self-hosted evidence workflow completed successfully and was uploaded
   only after collector and verifier both returned zero.
9. Artifact schema v2, snapshot schema v2 and control contract v2 passed the
   semantic verifier and redaction scan; historical v1 evidence was not reused.
10. Reviewer accepted the bounded evidence on #1864/#2434.

Passing I3 does not advance direct-STT, I7, product-value, legal, pilot or
production acceptance by implication.

## 9. Standards And Product Posture

This control set is vendor-neutral and maps to commonly used enterprise
expectations:

| Practice | Mapping applied here |
|---|---|
| NIST SP 800-53 AC-6 | Privileged collection is separated from read-only transport |
| NIST SP 800-53 AU-2/AU-3/AU-6 | Defined event sources, bounded evidence fields and machine evaluation |
| NIST SP 800-53 CM-3/CM-6 | Versioned baseline, drift checks, deliberate apply and rollback |
| CIS/Microsoft Windows security baseline | PowerShell logging, failed-logon auditing, host firewall and time service checks |
| SOC 2 CC6/CC7 engineering evidence | Access restriction, monitored changes, fresh and reviewable evidence |

Enterprise meeting products commonly expose administrative audit/compliance
surfaces. Faz 24 does not copy a vendor-specific model: the evidence contract
is reusable across ERP/CRM integrations and audio sources, while product
quality, privacy and operational gates remain independent. Workcube can be a
pilot vocabulary/integration context but is not embedded as a product
dependency in this control plane.

## 10. Troubleshooting

| Evidence | Interpretation | Next action |
|---|---|---|
| `sshFailureClass=ssh-auth-publickey` | Transport identity not authorized | Use the existing public-key-only I3 authorization package; never export the private key |
| `snapshot-control-missing` | SYSTEM task wrote an incomplete contract | Inspect local task history and collector hash; do not loosen verifier |
| `stale-or-invalid-snapshot` | Task stopped or snapshot exceeded 15 minutes | Repair SYSTEM task execution and collect a new snapshot |
| `broadConflictCount>0` or hard-block preflight error | A broad protected-port rule has both Program and Service unconstrained | Stop package Apply; use a separate reviewed remediation with owner/dependency evidence and independent rollback |
| constrained broad-rule approval required or count changed | At least one broad protected-port rule has a concrete Program or Service, but the current set was not reviewed under the current count | Review owner/dependencies, rerun Apply with the exact current count, and stop if the count changes; the package does not alter these rules |
| snapshot/control contract v1 | Evidence predates count-bound constrained-rule approval | Generate a fresh v2 snapshot and bundle; do not edit or relabel the historical artifact |
| failed-login count `0` with both proofs true | No failures in lookback | Valid; do not synthesize an event |
| `auditFailureEnabled=false` | Windows failure-audit bit is disabled | Re-apply elevated package; verify native audit policy |
| handshake age above threshold | WireGuard peer is stale | Repair tunnel/keepalive before rerun |
| time event stale, `syncTypeConfigured=false`, source absent or `sourceSynchronized=false` | Audit timestamp correlation is weak, `NoSync`, or bound to a local/free-running clock | Repair w32time/upstream source, set a supported sync type and wait for a fresh ID 35 success event |
| `routeUsesSelectedWireGuardInterface=false` | TCP/22 may be reachable outside the canonical WireGuard management path | Repair route selection/interface binding; do not accept generic reachability |
| current-attempt audit record missing or socket query unavailable | Staging proof came from an old/unrelated journal line or could not inspect the path | Repair the metadata-only `logger`/`journalctl` or socket-query prerequisite; never widen the lookback to manufacture a pass |

Do not use local-language event messages, human-formatted `wg show`, or
non-empty command output as pass criteria. The implementation relies on event
IDs, native audit-policy bits, tabular WireGuard dump fields, exact rule
properties, service states, exit codes and numeric freshness thresholds.
