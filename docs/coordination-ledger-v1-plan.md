# Coordination Ledger v1 — Parallel Agent Claim / Permission Gate Plan

Status: Partially implemented
Date: 2026-06-13
Tracked by: Halildeu/platform-k8s-gitops#1498
Authority: `AGENTS.md`, `docs/context-priority-rules.md`, `docs/board-protocol.md`, Project #2

## 1. Problem

Multiple AI agents can work at the same time on the same GitHub issue, branch, PR, or runtime gate. The current board protocol already requires claim-before-work, but the permission surface is still too dependent on mutable mirrors such as issue comments, issue body state, and Project fields.

The failure mode is not only duplicated work. The bigger risk is split-brain coordination:

- two agents both believe they own the same issue;
- a stale Project field says `In Progress` while the real claim expired;
- a PR body or issue comment claims ownership without a valid claim;
- Mavis/peer messages are accidentally treated as authority;
- a runtime PR auto-closes an issue with `Closes/Fixes/Resolves` instead of producing evidence through `Tracked by`.

## 2. Cross-AI Consensus

The plan is based on a provider-level ping-pong consultation completed on 2026-06-13.

| Reviewer | Final version | Verdict | Must-fix |
|---|---:|---|---|
| Claude CLI result | V16 | AGREE | NONE |
| Mavis result | V16 | AGREE | NONE |
| Codex CLI result | V16 | AGREE | NONE |

V13 and V14 were rejected for real blockers: ambiguous TTL/reaper behavior, incomplete event authority, Project mirror race, degraded-mode leakage, bootstrap ambiguity, Mavis authority leakage, and takeover/deny-audit gaps. V16 is the accepted specification.

### 2.1 Project GraphQL Budget Consensus

On 2026-06-13 the team ran a second provider-level consultation for the
GitHub Project v2 GraphQL exhaustion failure observed while closing PR #1500.

| Reviewer | Round 1 | Round 2 | Final must-fix |
|---|---|---|---|
| Claude CLI result | REVISE | AGREE | NONE |
| Mavis / MiniMax result | AGREE | AGREE | NONE |
| Codex sub-agent second opinion | REVISE | AGREE | NONE |

The accepted conclusion is narrow: REST fallback already exists for PR,
issue, comment, and check-run workflows. The remaining blocker is Project v2
GraphQL usage on the board hot path. Therefore the fix is not "use REST
more"; the fix is to make Project GraphQL budgeted, targeted, queue-aware for
low-risk mirror mutations, and fail-closed for critical operations.

## 3. Design Decision

Adopt an append-only coordination ledger as the replay source of truth, while keeping GitHub Project #2, issue body, materialized comments, and PR body as required visible mirrors.

The ledger does not replace Project #2. Project #2 remains the human-facing canonical roadmap surface. The ledger makes agent permission decisions deterministic and auditable.

## 4. Authority Order

1. `coordination-ledger` replay state, verified from genesis.
2. GitHub issue body coordination block mirror.
3. GitHub Project #2 fields mirror.
4. Materialized GitHub issue comments bound by ledger hashes.
5. PR body coordination block mirror, when a PR exists.
6. Mavis or peer messages only as notification hints; never authority.

Agents must never rely on raw labels, free-form comments, Mavis messages, or PR text alone.

## 5. Read-only Permission Gate

`board-sync require-claim` is a read-only fast path.

It must never:

- push a Git branch;
- create or edit a GitHub comment;
- edit Project fields;
- edit issue or PR body;
- append ledger events.

It verifies the latest ledger and mirrors, then returns a machine-readable allow or deny.

Required form:

```bash
scripts/board-sync.sh require-claim --issue <number> --session <session_id> --operation <operation_class>
```

Allowed operation classes:

```text
local_edit
file_write
stage
commit
push
pr_create
pr_update
live_mutation
release
deploy
issue_close
recovery
key_rotation
```

Agents must re-run the gate before crossing a stronger boundary. A `file_write` allow is not a `commit` allow. A `commit` allow is not a `push` allow.

## 6. Permission Predicate

Permission is true only when all conditions are true:

- Last valid ledger state says the issue/session has `permission_state=active_winner`.
- The issue exists and is a non-draft Project #2 item.
- Project #2 fields are present, non-empty, and valid: `Status`, `Faz`, `Track`, `Priority`, `Kind`.
- Project `Status=In Progress` is present only for the matching active winner.
- Issue body coordination block checksum matches the ledger state.
- Materialized event comment verifies by comment id, raw body hash, payload hash, author identity, and timestamp bounds.
- PR mirrors, if present, match issue/session/state.
- At most one open PR is active for the issue/session. Competing open PRs must be superseded by ledger-backed `PR_SUPERSEDED` or `SUPERSEDE_ISSUE`.
- Runtime/gate PRs use `Tracked by #N`, never `Closes/Fixes/Resolves #N`.
- Claim TTL has not expired.
- Heartbeat is fresh.
- No revoke, block, takeover, tombstone, mutation, invalid suffix, or secret scan failure supersedes the claim.
- Secret scan passes across coordination surfaces.

## 7. Canonical Active Tokens

Only these tokens are authoritative active indicators:

- `permission_state=active_winner`
- `coordination_state=active_winner`
- Project `Status=In Progress` with matching `claim_session`
- PR body `coordination_state=active_winner`

Any other text is UI-only.

## 8. Project #2 Field Contract

The permission predicate must validate the item is on Project #2 and these fields are populated:

| Field | Required behavior |
|---|---|
| `Status` | `In Progress` only for matching active winner |
| `Faz` | non-empty allowed board option |
| `Track` | non-empty allowed board option |
| `Priority` | non-empty allowed board option |
| `Kind` | non-empty allowed board option |

If any required field is missing or invalid, `require-claim` denies.

## 9. TTL and Heartbeat

`CLAIM_ACCEPTED` records include:

- `claim_ttl_hours`
- `claim_expires_at`
- `heartbeat_interval_minutes=30`
- `heartbeat_grace_minutes=45`

Default claim TTL is 2 hours.

Absolute normal claim lifetime is max 6 hours from the original `CLAIM_ACCEPTED`, unless `OWNER_APPROVED` extended TTL exists.

Heartbeats may extend sliding `claim_expires_at` only up to the absolute normal lifetime cap. No implicit infinite heartbeat rollover is allowed.

Missing heartbeat maps to `CLAIM_STALE`. Expired claim maps to `CLAIM_EXPIRED`. Both revoke permission.

## 10. Invalid Ledger Suffix

`coordination_invalid_suffix` is a derived system state, not a ledger event.

If replay from genesis finds an invalid suffix after the last valid signed and gapless prefix:

- the entire coordination system is fail-closed;
- `require-claim` returns nonzero `invalid_ledger_suffix` for every operation class;
- older active claims from the last valid prefix are not revived;
- only read-only report and human/coordinator repair, tombstone, or supersede flows may continue.

The ledger event for this condition is `LEDGER_INVALID_SUFFIX`, appended by reaper or coordinator when safe. If safe append is impossible, consumers still deny locally.

## 11. Degraded Mode

Degraded mode is intentionally narrow.

It can apply only when GitHub comment verification is temporarily degraded, the ledger branch verifies, and a previously cached bound comment snapshot verifies.

Allowed only for:

- `local_edit`
- `file_write`

Denied for:

- `stage`
- `commit`
- `push`
- `pr_create`
- `pr_update`
- `live_mutation`
- `release`
- `deploy`
- `issue_close`
- `recovery`
- `key_rotation`

Degraded duration is:

```text
min(30 minutes, heartbeat_grace_remaining, claim_expiry_remaining)
```

If heartbeat grace or claim expiry is exhausted, degraded mode is denied.

No staged diff, commit, PR, release, deploy, live mutation, or closure may be produced while degraded.

## 12. Event Authority Table

| Event | Authorized writer | Replay effect |
|---|---|---|
| `CLAIM_REQUEST` | coordinator | candidate claim evidence |
| `CLAIM_ACCEPTED` | coordinator | pending/active claim per mirror rules |
| `CLAIM_LOST_RACE` | coordinator | losing claim denied |
| `CLAIM_RACE_LOST` | coordinator | losing CAS attempt denied; re-read required |
| `CLAIM_STALE` | reaper | revoke permission |
| `CLAIM_EXPIRED` | reaper | revoke permission |
| `HEARTBEAT_EVIDENCE` | coordinator | liveness evidence |
| `DENY_RECORDED` | coordinator or reaper | audit-only; never grants or revokes permission |
| `PR_SUPERSEDED` | coordinator | open PR no longer competes if body block matches |
| `MIRROR_DRIFT_DETECTED` | reaper | permission false until repair |
| `MIRROR_ORPHAN_DETECTED` | reaper | permission false until repair |
| `MIRROR_ORPHAN_REPAIR_DEFERRED` | reaper | audit/blocked repair debt |
| `ORPHAN_COMMENT_DETECTED` | reaper | audit/repair signal |
| `COORDINATION_LOG_MUTATION_DETECTED` | reaper | permission false |
| `LEDGER_INVALID_SUFFIX` | reaper or coordinator | derived invalid-suffix condition recorded when safe |
| `VERIFY_DEGRADED` | reaper or coordinator | degraded verification audit |
| `VERIFY_FAILED` | reaper, coordinator, or CI via coordinator identity | permission false / audit signal |
| `SECRET_SCAN_FAILED` | reaper or CI via coordinator identity | permission false |
| `OWNER_APPROVAL_EVIDENCE` | coordinator | evidence-only |
| `OWNER_APPROVED` | coordinator | approved scope only, bound to prior evidence |
| `TAKEOVER_REQUEST` | coordinator | takeover candidate |
| `TAKEOVER_ACCEPTED` | coordinator | old/new sessions both no-permission until commit |
| `TAKEOVER_COMMITTED` | coordinator | new session becomes active winner after mirror verification |
| `TAKEOVER_REJECTED` | coordinator | takeover denied |
| `REPAIR_MATERIALIZATION` | coordinator or reaper | mirror repair evidence |
| `BLOCKED_FAIL_CLOSED` | coordinator or reaper | issue blocked/fail-closed |
| `TOMBSTONE_CHAIN` | coordinator | old issue/chain cannot grant permission |
| `SUPERSEDE_ISSUE` | coordinator | superseding issue/PR relation |
| `AUDIT_MARKER` | coordinator or reaper | audit-only |
| `BOOTSTRAP_KEY_REGISTRY` | bootstrap path | initial key registry |
| `EMERGENCY_KEY_ROTATION` | emergency path | key recovery only |

All events not listed in the authority table are rejected at writer boundary. During replay, unknown or unauthorized event makes the suffix invalid.

## 13. Denial Audit

`require-claim` remains read-only. On denial it emits JSON including:

```text
deny_event_intent_id = sha256(issue|session|operation_class|deny_code|ledger_prefix_hash|10min_bucket|source_actor)
```

For pre-mutation operation classes, the wrapper must call:

```bash
scripts/board-sync.sh record-deny --intent <json>
```

Implementation slice RDQ-1 adds `record-deny` as a fail-closed local debt
queue while the CAS writer is still pending. It validates the deny intent,
dedupes by `deny_event_intent_id`, writes a local append-only
`coordination-audit-debt/v1` JSONL record, and returns nonzero
`blocked_audit_debt`. It intentionally does not call GitHub, Project GraphQL,
or append a ledger event.

If coordinator is unavailable:

- wrapper exits nonzero with `blocked_audit_debt`;
- no mutation happens;
- intent is written to a local append-only debt queue;
- after the CAS writer exists, the next successful writer/reaper invocation
  retries queued intents.

Dedupe key is `deny_event_intent_id`. At most one `DENY_RECORDED` is emitted per key.

During `coordination_invalid_suffix`, no new ledger `DENY_RECORDED` is attempted; denials are local debt until repair or tombstone restores safe append.

Default local queue path:

```text
.local/coordination-audit-debt.jsonl
```

Override:

```bash
COORDINATION_AUDIT_DEBT_QUEUE=/path/to/debt.jsonl \
  scripts/board-sync.sh record-deny --intent-file deny.json
```

CAS emission and automatic debt retry remain part of the coordinator writer /
reaper follow-up; RDQ-1 only guarantees the denial intent is not lost and that
the guarded mutation stays blocked.

## 14. Takeover Protocol

Takeover is two-phase.

1. `TAKEOVER_ACCEPTED`
   - Old claim becomes `superseded_takeover`.
   - New claim becomes `takeover_pending_mirror`.
   - Both old and new sessions have work permission false.

2. Mirror update
   - Coordinator updates issue body, Project fields, and PR mirrors to the takeover state revision.

3. `TAKEOVER_COMMITTED`
   - Emitted only after mirror verification.
   - New claim becomes `active_winner`.
   - Mirror checksums and comment ids are bound.

If mirror update fails, state remains `takeover_pending_mirror`; reaper may emit `MIRROR_ORPHAN_REPAIR_DEFERRED` or `BLOCKED_FAIL_CLOSED`. Old claim cannot regain permission without a fresh claim.

## 15. Owner Approval and Recovery

Extended TTL requires `OWNER_APPROVAL_EVIDENCE` referencing a GitHub issue comment authored by a human repo owner/admin.

Required evidence fields:

- comment id
- author id/login/type
- raw body hash
- payload hash
- approved issue/session
- approved ttl or `approved_until`
- approval scope
- expiry

`OWNER_APPROVED` must bind a prior valid `OWNER_APPROVAL_EVIDENCE` hash. Mavis, Claude, Codex, or other agent messages cannot serve this role.

Emergency/recovery records include:

- `admin_enumeration_query`
- `admin_count`
- `second_human_admin_check=true|false|n_a`
- `reviewer_login_or_null`
- `solo_owner_recovery=true|false`

`second_human_admin_check=n_a` is valid only when `admin_count == 1`.

If `admin_count > 1`, second human reviewer is mandatory. If `admin_count == 1`, solo-owner path is allowed, but all active claims remain blocked until post-recovery audit passes.

## 16. Timing and Ordering

Ledger record time, using signed commit committer timestamp verified monotonic across the valid prefix, is the only ordering clock for claim, heartbeat, takeover, and revoke state.

GitHub comment `created_at` and `updated_at` are evidence metadata only.

Materialized event comments must satisfy:

- timestamp within 5 minutes in normal mode;
- timestamp within 15 minutes in degraded/recovery mode;
- `updated_at == created_at`.

Edited materialized comments fail verification.

Equal ledger timestamps are ordered by git ancestry position in the linear valid prefix. Backwards time is rejected.

## 17. Runtime PR Auto-close Guard

Runtime/gate PRs must use:

```text
Tracked by #N
```

They must not use:

```text
Closes #N
Fixes #N
Resolves #N
```

Scan surfaces:

- PR body
- issue links
- commit messages
- merge commit title/body
- squash merge title/body
- release notes
- automation-generated PR/merge bodies

Any forbidden close keyword hit fails CI/permission until rewritten to `Tracked by #N`.

Implementation slice PR-CI-1 adds a trusted-base `pull_request_target` gate:

- scans PR title and body from the event payload;
- scans all PR commit messages through the read-only REST commits API;
- supports local `--text-file` scans for release-note / merge-body fixtures;
- matches close keywords only when followed by a GitHub issue reference, so
  safe prose such as "Closes the bug class" is not blocked.

The guard intentionally does not checkout PR head code. It runs the base-branch
copy of `scripts/ci/check-forbidden-close-keywords.mjs` and fails with a direct
rewrite instruction: replace `Closes/Fixes/Resolves #N` with `Tracked by #N`.

Implementation slice PR-CI-2 extends the same base-branch script to post-merge
surfaces:

- `push` to `main` scans `head_commit.message` and all event commit messages,
  covering automation-generated merge/squash commit bodies after merge.
- `release` `published` / `edited` scans release name and release notes.
- Local regression tests cover PR metadata, PR commits, text-file fixtures,
  push event merge body, and release event notes.

## 18. Event UUID Idempotency

Duplicate `event_uuid` with different payload or hash invalidates the suffix.

Exact duplicate retry is idempotent only when payload, hash, signature, and comment binding are byte-identical.

Implementation slice LDG-1 adds an offline replay verifier:

```text
scripts/coordination/verify-ledger-replay.py
scripts/coordination/append-ledger-event.py
docs/coordination/coordination-ledger-event-v1.schema.json
.github/workflows/gate-coordination-ledger-replay.yml
```

The verifier reads JSONL events from genesis, checks the event authority
fixture, writer role, `payload_hash`, `previous_event_hash`, `event_hash`,
timestamp monotonicity, and exact duplicate retry semantics. It fails on the
first invalid suffix and reports the last valid prefix hash.

LDG-1 is deliberately read-only and offline. It does not append ledger events,
mutate GitHub issue bodies/comments, mutate Project #2 fields, or replace the
current `board-sync require-claim` mirror checks by itself. CAS writer,
materialized comment binding, and runtime permission integration are separate
slices.

Implementation slice LDG-2 adds a local/offline CAS append writer foundation:

```bash
python3 scripts/coordination/append-ledger-event.py \
  --ledger .local/coordination-ledger.jsonl \
  --expect-previous-hash GENESIS \
  --event-type BOOTSTRAP_KEY_REGISTRY \
  --writer-role bootstrap_path \
  --payload-json '{"key_id":"coordination-bootstrap-v1"}'
```

The writer obtains a local ledger lock, replays the existing JSONL ledger from
genesis, refuses existing invalid suffixes, enforces `--expect-previous-hash`
as a compare-and-swap guard, builds canonical `payload_hash`,
`previous_event_hash`, and `event_hash`, validates the candidate ledger in a
temp file, appends exactly one JSONL event, and replays again after write.

LDG-2 still does not mutate GitHub issues, Project #2 fields, PR bodies, or
materialized comments. Remote branch CAS, materialized comment binding, issue
body / Project / PR mirror writes after CAS, and `record-deny` debt retry remain
Slice 3 work.

Implementation slice LDG-3 adds materialized comment binding validation to the
offline replay verifier. When an event includes `comment_binding`, replay now
requires a structured GitHub issue comment binding:

- `surface=github_issue_comment`;
- repository, issue, comment id, author id/login/type;
- `raw_body_hash`;
- binding `payload_hash` equal to the event payload hash;
- `updated_at == created_at` so edited materialized comments fail;
- `verification_mode` with timestamp tolerance (`normal=5m`,
  `degraded/recovery=15m`);
- comment timestamp within the declared tolerance of `committed_at`.

LDG-3 still does not fetch, create, or edit GitHub comments. The actual
materialized comment writer/fetch verifier and mirror mutation path remain
Slice 3 work after remote/branch CAS coordination.

Implementation slice LDG-4 adds a remote branch CAS append wrapper:

```bash
scripts/coordination/append-ledger-branch.sh \
  --remote origin \
  --branch coordination-ledger \
  --ledger-path coordination-ledger/events.jsonl \
  --commit-title "coordination ledger append" \
  --commit-message "Tracked by #1498" \
  -- \
  --expect-previous-hash sha256:<last-ledger-event-hash> \
  --event-type HEARTBEAT_EVIDENCE \
  --writer-role coordinator \
  --payload-json '{"issue":1498,"session":"..."}'
```

The wrapper fetches the existing ledger branch into a temporary ref, creates a
detached temporary worktree, runs the local append writer, commits exactly the
ledger JSONL diff, and pushes with `--force-with-lease` against the fetched
branch OID. A competing branch update fails as `remote_cas_mismatch`; a missing
ledger branch fails closed and points to the bootstrap runbook.

LDG-4 still does not write issue bodies, Project fields, PR bodies, or GitHub
comments. CAS-backed mirror-safe emission and local denial debt retry remain
Slice 3 follow-up work.

Implementation slice LDG-5 adds the GitHub materialized comment render/fetch
verification path:

```bash
python3 scripts/coordination/materialize-ledger-comment.py render \
  --repo Halildeu/platform-k8s-gitops \
  --issue 1498 \
  --event-uuid <uuid> \
  --event-type HEARTBEAT_EVIDENCE \
  --writer-role coordinator \
  --payload-hash sha256:<event-payload-hash>

python3 scripts/coordination/materialize-ledger-comment.py verify \
  --repo Halildeu/platform-k8s-gitops \
  --issue 1498 \
  --event-uuid <uuid> \
  --event-type HEARTBEAT_EVIDENCE \
  --writer-role coordinator \
  --payload-hash sha256:<event-payload-hash> \
  --committed-at <ledger-committed-at> \
  --comment-json fetched-comment.json
```

`post` is also available for the coordinator path: it creates the GitHub issue
comment via `gh api`, fetches it back, verifies marker/body/timestamp rules, and
emits the `comment_binding` JSON object for the ledger writer. Offline tests use
fixtures only; the CI gate does not mutate GitHub.

LDG-5 does not append ledger events and does not mutate issue bodies, Project
fields, or PR bodies. Mirror-safe emission still remains the orchestrated path:
materialize comment, append remote branch CAS event with the emitted
`comment_binding`, then update visible mirrors only after CAS success.

Implementation slice LDG-6 adds the first mirror-safe emission helper:

```bash
scripts/coordination/emit-ledger-event.sh \
  --repo Halildeu/platform-k8s-gitops \
  --issue 1498 \
  --expect-previous-hash sha256:<last-ledger-event-hash> \
  --event-type HEARTBEAT_EVIDENCE \
  --writer-role coordinator \
  --payload-json '{"issue":1498,"session":"..."}' \
  --post-comment
```

The helper computes the canonical payload hash, materializes and verifies the
GitHub issue comment, then calls the remote branch CAS writer with the emitted
`comment_binding`. It emits a single JSON result after the ledger event is
pushed with `--force-with-lease`. It deliberately does not mutate issue bodies,
Project #2 fields, or PR bodies; those mirrors remain a later post-CAS step.
If remote CAS fails after a live `--post-comment`, the comment is an orphan
candidate, is not authoritative, and must be handled by the reaper/orphan path.
Offline CI uses `--comment-json` fixtures and does not mutate GitHub.

Implementation slice LDG-7 adds the read-only reaper detector:

```bash
python3 scripts/coordination/reap-ledger-state.py \
  --ledger coordination-ledger/events.jsonl \
  --mirror-json mirror-snapshot.json \
  --audit-debt-jsonl .local/coordination-audit-debt.jsonl
```

The detector replays the ledger and fails closed on invalid suffixes by
emitting a `LEDGER_INVALID_SUFFIX` finding. On valid ledgers it reports
candidate `CLAIM_STALE`, `CLAIM_EXPIRED`, `MIRROR_DRIFT_DETECTED`,
`MIRROR_ORPHAN_DETECTED`, and `ORPHAN_COMMENT_DETECTED` findings from an
explicit mirror snapshot. It also scans the local audit-debt queue with bounded
dedupe and reports the CAS-backed retry command. LDG-7 itself does not append
ledger events or mutate GitHub/Project mirrors.

Implementation slice LDG-8 adds the takeover/recovery runtime flow planner:

```bash
python3 scripts/coordination/takeover-recovery-flow.py \
  --ledger coordination-ledger/events.jsonl \
  --phase accept \
  --repo Halildeu/platform-k8s-gitops \
  --issue 1498 \
  --old-session old-session \
  --new-session new-session
```

The helper enforces two-phase takeover: `TAKEOVER_ACCEPTED` plans put both old
and new sessions into no-permission pending-mirror state, while
`TAKEOVER_COMMITTED` is refused unless explicit issue-body, Project, and PR
mirror verification is supplied. Recovery planning emits
`OWNER_APPROVAL_EVIDENCE` before `OWNER_APPROVED` and requires owner approval
JSON with comment id, approver identity, scope, reason, and expiry. LDG-8 is
read-only; the returned event plans must still be appended through the
CAS-backed emitter.

Implementation slice LDG-9 wires ledger replay into the `board-sync
require-claim` permission predicate as an optional read-only input:

```bash
COORDINATION_LEDGER_PATH=coordination-ledger/events.jsonl \
  bash scripts/board-sync.sh require-claim \
  --issue 1498 \
  --session "$BOARD_SESSION_ID" \
  --operation commit
```

When `COORDINATION_LEDGER_PATH` is unset, `require-claim` keeps the existing
Project + issue-body mirror predicate. When it is set, `scripts/board-sync.sh`
calls `scripts/coordination/ledger-claim-state.py`, replays the ledger from
genesis through the authority verifier, derives the latest issue/session state,
and includes a `ledger` object in the JSON response. Ledger denial codes join
the normal mirror-denial list. Invalid suffixes fail closed with
`invalid_ledger_suffix` in both the normal Project path and the
GraphQL-exhausted REST-only low-risk path.

LDG-9 is still read-only: it does not append ledger events, record
`DENY_RECORDED`, mutate issue bodies, mutate Project #2, mutate PR mirrors, or
repair drift. Those remain CAS-backed follow-up slices.

Implementation slice LDG-10 adds the post-CAS mirror writer:

```bash
python3 scripts/coordination/apply-ledger-mirrors.py \
  --cas-result emit-result.json \
  --plan mirror-write-plan.json \
  --apply
```

The helper refuses all mirror writes unless `emit-result.json` proves
`status=ledger_event_emitted_after_remote_cas` and the expected
`event_uuid/event_hash` from the mirror plan matches the appended ledger event.
It validates issue body `agent-state:v1`, Project current fields, and PR mirror
markers before applying any mutation. Project writes use the repo field catalog
and enforce no-downgrade status semantics. PR writes are bounded to the
`coordination-ledger-pr-mirror:v1` marker block. Partial write failures emit
`mirror_write_failed_repair_required` with bounded repair debt and never grant
permission.

LDG-10 still does not append new ledger events for `DENY_RECORDED`, audit debt
retry, PR mirror validation gates, branch protection, secret scanning, or
tombstone/supersede flows. LDG-11 covers `DENY_RECORDED` audit-debt retry;
the remaining gates stay as follow-up slices.

Implementation slice LDG-11 adds CAS-backed audit-debt retry:

```bash
python3 scripts/coordination/retry-audit-debt.py \
  --queue .local/coordination-audit-debt.jsonl \
  --remote origin \
  --branch coordination-ledger \
  --ledger-path coordination-ledger/events.jsonl \
  --post-comment \
  --limit 20
```

The helper drains bounded `coordination-audit-debt/v1` local queue records into
`DENY_RECORDED` ledger events through the existing mirror-safe emitter and
remote branch CAS path. The local queue remains append-only: successful retry
or already-present ledger state is recorded by appending terminal markers
instead of editing historical debt records.

Safety rules:

- Invalid existing ledger suffix fails closed before any retry append.
- Missing or invalid materialized comment evidence fails closed before ledger
  mutation in fixture mode; live mode must use `--post-comment`.
- Event UUIDs are deterministic per `deny_event_intent_id`, so reruns are
  idempotent and do not grow the ledger.
- The emitted event is audit-only. It never grants permission, revokes another
  session, edits issue bodies, mutates Project #2, or updates PR mirrors.

Implementation slice LDG-12 adds the final MVP hardening gates:

```bash
python3 scripts/coordination/validate-pr-mirrors.py \
  --ledger coordination-ledger/events.jsonl \
  --snapshot pr-mirror-snapshot.json

python3 scripts/coordination/enforce-append-only-ledger.py \
  --old old-events.jsonl \
  --new new-events.jsonl

python3 scripts/coordination/scan-coordination-secrets.py

python3 scripts/coordination/tombstone-supersede-flow.py \
  --ledger coordination-ledger/events.jsonl \
  --phase supersede \
  --repo Halildeu/platform-k8s-gitops \
  --issue <old-issue> \
  --new-issue <new-issue> \
  --mirror-verification-json mirror-verification.json \
  --reason "<reason>"
```

The PR mirror validator rejects missing, stale, forged, or session-mismatched
`coordination-ledger-pr-mirror:v1` marker blocks unless they reference a valid
ledger event hash. The append-only gate enforces exact prefix preservation for
`coordination-ledger/**/*.jsonl` changes in CI before replaying the candidate
ledger. The coordination secret scanner adds a high-confidence, coordination
surface-specific token/key scan in addition to the repository-wide gitleaks
gate. The tombstone/supersede planner emits read-only event plans for
`TOMBSTONE_CHAIN` and `SUPERSEDE_ISSUE` and requires mirror verification before
supersede planning.

LDG-12 remains permission-conservative: validators and planners never grant
permission, never mutate GitHub/Project mirrors directly, and fail closed on
invalid ledgers, missing mirror evidence, append-only violations, or
high-confidence secret findings.

## 19. Project GraphQL Budget / Mirror Queue Hardening

GitHub Project v2 custom fields are GraphQL-only. This includes Project #2
`Status`, `Faz`, `Track`, `Priority`, `Kind`, Project item ids, and Project
field mutations. REST fallback is available for PRs, issues, issue comments,
issue body edits, and check-runs, but not for Project v2 field truth.

The system must keep Project GraphQL out of the high-frequency path whenever
possible, without pretending that an issue body, PR body, or queue item is the
Project board.

### 19.1 Field Catalog

Project-level field ids and option ids are stored in a repo-level field catalog
fixture. They are not copied into every issue body.

Implemented fixture:

```text
docs/coordination/project-field-catalog-v1.json
```

The catalog records:

- Project id.
- Required field ids: `Status`, `Faz`, `Track`, `Priority`, `Kind`.
- Option-name to option-id mapping for each single-select field.
- `catalog_version` and a fingerprint.

If a Project field or option id drifts, direct mutation helpers fail or refresh
the catalog. They must not perform blind best-effort writes with stale option
ids.

### 19.2 Project Item Locator Cache

Issue body or coordination blocks may hold `project_item_id`, but only as a
locator cache. It is not truth and does not replace a fresh Project read for
critical operations.

Schema:

```text
docs/coordination/project-item-locator-cache-v1.schema.json
```

The locator cache records:

- `project_id`
- `project_item_id`
- issue repo, issue number, and issue URL
- last seen `Status/Faz/Track/Priority/Kind`
- `refreshed_at`
- `catalog_fingerprint`

When `project_item_id` is missing, the bootstrap path performs a targeted
Project lookup for that issue. Full-board scans are not allowed on hot-path
claim, release, verify, or permission checks.

### 19.3 GraphQL Budget Guard

Project GraphQL calls first check the REST rate-limit endpoint:

```bash
gh api rate_limit --jq '.resources.graphql'
```

If remaining GraphQL budget is exhausted, no additional GraphQL probe is made.
The guard emits machine-readable JSON with:

- remaining budget
- reset time
- operation class
- decision: `continue`, `defer`, or `fail`

The guard policy is operation-class aware. Low-risk Project mirror mutations
may be deferred; critical operations fail closed.

Implementation command:

```bash
bash scripts/board-sync.sh graphql-budget \
  --operation pr_update \
  --mutation-risk low-risk
```

`scripts/board-sync.sh verify` uses the same guard. When Project GraphQL is
exhausted, it does not rewrite `agent-state.status` to `needs-verify` and does
not pretend Project #2 moved. It posts GitHub-visible `PROJECT-DEFERRED v1`
evidence for the low-risk `PR merged -> Needs Verify` mirror mutation.

### 19.4 Direct ProjectV2 Mutation Helper

Hot-path Project mutation must use a narrow helper around
`updateProjectV2ItemFieldValue`, not opaque `gh project item-edit` wrappers.
The helper receives known `item_id`, `field_id`, and option name/id from the
catalog, validates catalog freshness, and emits distinct error classes for:

- rate limit exhausted
- stale or missing item id
- field or option drift
- already target state
- no-downgrade skip
- mutation failed

First implementation is wired through `set_board_status`, which now calls a
direct `updateProjectV2ItemFieldValue` mutation for `Status` writes after the
REST budget guard passes.

### 19.5 Deferred Project Mutation Queue

Deferred Project mutation is allowed only for low-risk board mirror repair.
It is never authority and never replaces Project #2 truth.

The canonical marker is GitHub-visible:

```text
PROJECT-DEFERRED v1 key=<stable-id>
```

Local files may cache pending work, but local files are not canonical. Queue
items are idempotent and include enough data for `drain-project-queue` to
detect duplicates, stale state, and drift.

Allowed low-risk deferred mutations:

- PR merge evidence -> `Needs Verify`
- release after accepted work -> `Todo` reconcile

Rejected deferred mutation:

- `backlog-add` Kind/Status reconcile. This operation creates a new GitHub
  issue and adds it to Project #2; queueing only the field/status part would
  risk a durable orphan issue that looks captured but is not on the board. If
  Project GraphQL budget is exhausted, `backlog-add` fails closed before issue
  creation. Operator/agent retries after GraphQL budget returns.

Forbidden deferred mutations:

- `Done`
- `issue_close`
- `live_mutation`
- `deploy`
- `recovery`
- `key_rotation`

`agent-state.status` must not be silently changed to a value that conflicts
with Project #2. If the board could not be updated, the body records an
explicit deferred marker rather than pretending the board state changed.

### 19.6 Drain Semantics

`drain-project-queue` is:

- idempotent
- bounded per batch
- rate-aware
- no-downgrade
- safe when the target is already in the desired state
- fail/refresh on option drift

During drain, each item re-checks the current Project item state. If the item
changed since the queued marker was created, drain skips that item and records
a stale-skip audit marker instead of overwriting the board.

### 19.7 Operation Policy

| Operation class | GraphQL exhausted behavior |
|---|---|
| `local_edit`, `file_write` | May continue using REST issue-body claim/lease evidence only. No board mutation is implied. |
| `commit`, `push`, `pr_create`, `pr_update` | May continue if issue/PR REST evidence is valid. `require-claim` uses REST issue-body claim/lease evidence; Project mutation is deferred only when the mutation is low-risk. |
| `release` | May release the issue-body claim through REST and enqueue low-risk `Status -> Todo` Project reconcile as `PROJECT-DEFERRED`; never marks Project truth changed until drained. |
| `backlog-add` | Fail closed before GitHub issue creation when Project GraphQL budget is exhausted; no deferred queue is used. |
| `claim`, `list`, `sync-state`, `reap` | No claim or authoritative board mutation without fresh Project truth. Read-only stale mirror output is allowed if clearly labeled. |
| `live_mutation`, `deploy`, `issue_close`, `recovery`, `key_rotation` | Fail closed unless fresh Project truth and valid claim are verified. |

Fresh Project truth for critical operations means the Project item lookup
records `refreshed_at_epoch` and `age_seconds <= PROJECT_TRUTH_TTL_SECONDS`
(default 300 seconds). `require-claim` reports this in `project_truth`. If
truth is stale, missing, in the future, or impossible to refresh because
GraphQL budget is exhausted, critical operations fail closed.

### 19.8 Status Reconciliation Barrier

`docs/board-protocol.md` §4.1 defines the status reconciliation barrier. In
ledger terms this is not a new event family. It is a permission predicate over
existing mirrors:

- Project #2 `Status`
- issue body `agent-state:v1 status`
- latest relevant taxonomy comment (`PROGRESS`, `EVIDENCE`, `BLOCKED`,
  `READY-FOR-VERIFY`, `DONE-CANDIDATE`, `HANDOFF`)

If new evidence changes the status interpretation, those three mirrors must be
reconciled before any strong operation crosses the boundary. Strong operations
are `stage`, `commit`, `push`, `pr_create`, `pr_update`, `live_mutation`,
`deploy`, `release`, `issue_close`, `recovery`, and `key_rotation`.

When the mirrors disagree, replay treats the item as mirror drift:

- emit or honor `MIRROR_DRIFT_DETECTED`
- deny strong operations until repair
- use `REPAIR_MATERIALIZATION` after body, Project status, and comment truth are
  synchronized
- allow only degraded `local_edit` / `file_write` while repair is pending

GraphQL exhaustion does not waive the barrier. Low-risk Project mutations may
queue a `PROJECT-DEFERRED v1` marker, but the marker is not truth and does not
grant permission to proceed past strong operation boundaries. Critical
operations remain fail-closed until fresh Project truth and synchronized mirrors
are available.

`Blocked` is a valid reconciled state. If operator gates, external dependencies
or follow-up runtime gates remain, PR merge or live-smoke evidence updates the
comment/body explanation but must not promote the issue to `Needs Verify`.

## 20. Implementation Slices

### Slice 1 — Docs and schema

- Add this plan.
- Reference it from `docs/board-protocol.md`.
- Define ledger event JSON schema.
- Define event authority table as machine-readable fixture.

### Slice 1B — Project GraphQL budget / mirror queue hardening

This slice is inserted before the full ledger replay/writer path because it
removes the current Project GraphQL hot-path blocker for agent coordination.

#### Slice 1B-a — Budget and direct mutation foundation

- [x] Add repo-level Project field catalog fixture.
- [x] Add `project_item_id` locator cache schema.
- [x] Add targeted item bootstrap lookup.
- [x] Add REST rate-limit based GraphQL budget guard.
- [x] Add direct ProjectV2 mutation helper for `Status` writes.
- [x] Detect stale item ids and field/option drift before direct mutation where the local catalog can validate field/option ids; direct mutation still fails closed on stale item ids.

#### Slice 1B-b — Deferred queue for low-risk Project mutations

- [x] Add `PROJECT-DEFERRED v1` GitHub-visible marker for `verify`.
- [x] Add idempotent, durable deferred mutation records via GitHub-visible marker + terminal `PROJECT-DRAINED` / `PROJECT-STALE-SKIP` comments.
- [x] Add issue-scoped `drain-project-queue`.
- [x] Queue only low-risk mirror repair mutations for `verify`.
- [x] Queue low-risk `release` Project mirror repair as `Status -> Todo`
  while updating claim state only through REST.
- [x] Ensure queued `Needs Verify` prevents a new claim until drained or resolved.
- [x] Reject `backlog-add` queueing; it fails closed before issue creation when
  Project GraphQL is exhausted, avoiding board-orphan capture records.

#### Slice 1B-c — Critical operation fail-closed integration

- [x] Enforce operation policy in scripts, not only docs, through `graphql-budget` and preflight classes.
- [x] Require fresh Project truth for `live_mutation`, `deploy`, `issue_close`,
  `recovery`, and `key_rotation` by validating `refreshed_at_epoch` age in
  `require-claim`.
- [x] Deny critical operations when Project truth is stale and GraphQL budget is
  exhausted.
- [x] Preserve REST-only continuation for local edit, file write, and permitted
  PR/issue evidence paths.

### Slice 2 — Read-only verifier

- [x] Add ledger replay verifier.
- [x] Add event schema for verifier input records.
- [x] Wire ledger replay state into `require-claim` permission predicate as an
  optional read-only gate (`COORDINATION_LEDGER_PATH`), after CAS append writer
  and materialized comment binding foundations exist.
- [x] Add `require-claim --operation` operation classes.
- [x] Add machine-readable deny codes.
- [x] Add Project #2 field validation.

### Slice 3 — Coordinator writer

- [x] Add local/offline CAS append writer foundation.
- [x] Add remote/branch CAS append coordination foundation.
- [x] Add mirror-safe emission after remote CAS.
- [x] Add materialized comment binding verifier foundation.
- [x] Add GitHub materialized comment writer/fetch verification path.
- [x] Add issue body / Project / PR mirror writes after CAS.
- [x] Add fail-closed `record-deny` local audit debt queue while CAS writer is
  unavailable.
- [x] Add CAS-backed `DENY_RECORDED` emission and debt retry after CAS writer
  exists.

### Slice 4 — Reaper

- [x] Add stale/expired claim detection.
- [x] Add mirror drift/orphan detection.
- [x] Add invalid suffix fail-closed behavior.
- [x] Add audit debt bounded dedupe report.
- [x] Add CAS-backed audit debt retry.

### Slice 5 — PR/CI gates

- [x] Add forbidden close keyword scan for PR title/body, PR commit messages,
  and local text-file release/merge fixtures.
- [x] Add post-merge forbidden close keyword scan for push-to-main commit
  messages and release published/edited notes.
- [x] Add PR mirror validation.
- [x] Add branch protection/append-only ledger CI enforcement.
- [x] Add secret scan across coordination surfaces.

### Slice 6 — Takeover/recovery

- [x] Add two-phase takeover.
- [x] Add owner approval evidence binding.
- [x] Add solo-owner recovery audit gate.
- [x] Add tombstone/supersede flow.

## 21. Acceptance Criteria

- Project #2 issue exists and is field-complete.
- `docs/board-protocol.md` references this plan.
- Ledger replay rejects unknown/unauthorized events.
- Invalid suffix denies all operation classes.
- `require-claim` is read-only.
- `require-claim --operation file_write` cannot be reused for `commit`, `push`, or `pr_update`.
- Degraded mode allows only local edit/file write and never stage/commit/push/PR/live mutation.
- Project fields `Status/Faz/Track/Priority/Kind` are required for permission.
- Mavis messages cannot grant claim, approval, recovery, or closure.
- Runtime PRs are blocked on forbidden close keywords and must use `Tracked by #N`.
- Takeover grants new active winner only after `TAKEOVER_COMMITTED`.
- Denials before mutation generate `DENY_RECORDED` or local audit debt; mutation remains blocked.
- GraphQL budget exhaustion for low-risk PR evidence queues a Project mirror
  mutation instead of silently dropping it.
- GraphQL budget exhaustion for `live_mutation`, `deploy`, `issue_close`,
  `recovery`, or `key_rotation` fails closed.
- `project_item_id` is treated only as a locator cache, never as Project truth.
- Stale or already drained `PROJECT-DEFERRED` markers do not permanently block
  eligible work.
- Queued `Needs Verify` prevents a new claim until drain/reconcile resolves it.
- Option id drift fails or refreshes before mutation; stale option ids are not
  blindly written.

## 22. Follow-up Work

- Implement `board-sync` verifier library.
- Add ledger branch bootstrap runbook.
- Add CI guard for runtime close keywords.
- Add Mavis boundary section to agent onboarding docs.
