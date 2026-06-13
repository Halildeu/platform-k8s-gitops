# Coordination Ledger v1 — Parallel Agent Claim / Permission Gate Plan

Status: Planned
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

If coordinator is unavailable:

- wrapper exits nonzero with `blocked_audit_debt`;
- no mutation happens;
- intent is written to a local append-only debt queue;
- next successful `board-sync` invocation retries queued intents.

Dedupe key is `deny_event_intent_id`. At most one `DENY_RECORDED` is emitted per key.

During `coordination_invalid_suffix`, no new ledger `DENY_RECORDED` is attempted; denials are local debt until repair or tombstone restores safe append.

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

## 18. Event UUID Idempotency

Duplicate `event_uuid` with different payload or hash invalidates the suffix.

Exact duplicate retry is idempotent only when payload, hash, signature, and comment binding are byte-identical.

## 19. Implementation Slices

### Slice 1 — Docs and schema

- Add this plan.
- Reference it from `docs/board-protocol.md`.
- Define ledger event JSON schema.
- Define event authority table as machine-readable fixture.

### Slice 2 — Read-only verifier

- Add ledger replay verifier.
- Add `require-claim --operation` operation classes.
- Add machine-readable deny codes.
- Add Project #2 field validation.

### Slice 3 — Coordinator writer

- Add CAS append path.
- Add materialized comment binding.
- Add issue body / Project / PR mirror writes after CAS.
- Add `DENY_RECORDED` record-deny handoff.

### Slice 4 — Reaper

- Add stale/expired claim detection.
- Add mirror drift/orphan detection.
- Add invalid suffix fail-closed behavior.
- Add audit debt retry and bounded dedupe.

### Slice 5 — PR/CI gates

- Add forbidden close keyword scan.
- Add PR mirror validation.
- Add branch protection/append-only ledger CI.
- Add secret scan across coordination surfaces.

### Slice 6 — Takeover/recovery

- Add two-phase takeover.
- Add owner approval evidence binding.
- Add solo-owner recovery audit gate.
- Add tombstone/supersede flow.

## 20. Acceptance Criteria

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

## 21. Follow-up Work

- Implement `board-sync` verifier library.
- Add Project #2 field schema fixture.
- Add ledger branch bootstrap runbook.
- Add CI guard for runtime close keywords.
- Add Mavis boundary section to agent onboarding docs.
