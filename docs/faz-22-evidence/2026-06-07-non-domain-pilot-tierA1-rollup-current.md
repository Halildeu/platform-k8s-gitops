# Faz 22.2.A non-domain pilot rollup — Tier A1 multi-device

> **Status**: PARTIAL
> **Tracked by**: #1044
> **Tier**: A1
> **Scope**: 1 device(s)
> **Soak window**: 2026-06-06T06:04Z -> 2026-06-07T06:04Z
> **Codex thread**: PENDING
> **Generated at**: 2026-06-07T06:06:32Z
> **Source soak output**: `/tmp/faz22-a1-current-soak-rollup.txt`

## 1. Device summary table

| # | Hostname (or pseudonym) | Device ID | Tier | Per-device evidence doc | Status | Helper verdict |
|---|---|---|---|---|---|---|
| 1 | HALILKOOLUB735 | `d0efb00a-681a-4e32-b7de-a27ef94f2977` | A1 | [link](./2026-06-07-non-domain-pilot-tierA1-HALILKOOLUB735-current.md) | PARTIAL | COMMAND_REVIEW |

## 2. Aggregate metrics (per §14.5 formula)

| Metric | Value | Acceptance threshold | Verdict |
|---|---|---|---|
| Heartbeat success rate (pilot-wide) | 67.12% (1933/2880) | ≥99% | REVIEW |
| Command terminal/accounted rate (pilot-wide) | 86.67% (13/15) | 100% | REVIEW (nonterminal=2) |
| Command success rate (pilot-wide) | 33.33% (5/15) | ≥95% | REVIEW |
| Soak gap incidents (unexplained > 30m) | 0 | 0 required | PASS |
| Repeatability gate | REVIEW: pass_devices=0/1, required_for_partial=1 | per §14.5 rule | REVIEW |

## 3. Acceptance verdict

**Verdict**: PARTIAL

**Rationale**:
- This generator summarizes helper facts; it does not decide final #1044 acceptance by itself.
- Set final PASS/PARTIAL/FAIL only after per-device evidence docs, planned command facts, and operator-reviewed soak notes are complete.

## 4. Command status rollup

| Device ID | Command type | Status | Count | First issued | Last issued | Max duration |
|---|---|---|---:|---|---|---|
| `d0efb00a-681a-4e32-b7de-a27ef94f2977` | COLLECT_INVENTORY | DELIVERED | 2 | 2026-06-06 21:04:32.091507+00 | 2026-06-07 05:43:48.56862+00 | (null) |
| `d0efb00a-681a-4e32-b7de-a27ef94f2977` | COLLECT_INVENTORY | SUCCEEDED | 3 | 2026-06-06 14:07:22.73795+00 | 2026-06-06 14:45:58.132388+00 | 00:01:24.777253 |
| `d0efb00a-681a-4e32-b7de-a27ef94f2977` | UPDATE_AGENT | FAILED | 8 | 2026-06-06 20:53:08.953405+00 | 2026-06-07 01:14:45.918158+00 | 00:04:49.916669 |
| `d0efb00a-681a-4e32-b7de-a27ef94f2977` | UPDATE_AGENT | SUCCEEDED | 2 | 2026-06-07 01:22:35.883274+00 | 2026-06-07 02:01:13.472271+00 | 00:01:30.725451 |

## 5. Recent command detail

| Device ID | Command type | Status | Issued | Delivered | Started | Completed | Duration |
|---|---|---|---|---|---|---|---|
| `d0efb00a-681a-4e32-b7de-a27ef94f2977` | COLLECT_INVENTORY | DELIVERED | 2026-06-07 05:43:48.56862+00 | 2026-06-07 05:44:13.447423+00 | (null) | (null) | (null) |
| `d0efb00a-681a-4e32-b7de-a27ef94f2977` | UPDATE_AGENT | SUCCEEDED | 2026-06-07 02:01:13.472271+00 | 2026-06-07 02:01:38.072661+00 | 2026-06-07 02:02:42.954286+00 | 2026-06-07 02:02:44.197722+00 | 00:01:30.725451 |
| `d0efb00a-681a-4e32-b7de-a27ef94f2977` | UPDATE_AGENT | SUCCEEDED | 2026-06-07 01:22:35.883274+00 | 2026-06-07 01:22:55.808386+00 | 2026-06-07 01:24:00.656263+00 | 2026-06-07 01:24:01.580558+00 | 00:01:25.697284 |
| `d0efb00a-681a-4e32-b7de-a27ef94f2977` | UPDATE_AGENT | FAILED | 2026-06-07 01:14:45.918158+00 | 2026-06-07 01:14:48.977222+00 | 2026-06-07 01:15:53.819566+00 | 2026-06-07 01:15:54.63064+00 | 00:01:08.712482 |
| `d0efb00a-681a-4e32-b7de-a27ef94f2977` | UPDATE_AGENT | FAILED | 2026-06-07 00:53:17.70533+00 | 2026-06-07 00:53:30.603343+00 | 2026-06-07 00:54:35.450593+00 | 2026-06-07 00:54:36.293416+00 | 00:01:18.588086 |
| `d0efb00a-681a-4e32-b7de-a27ef94f2977` | UPDATE_AGENT | FAILED | 2026-06-07 00:17:20.988374+00 | 2026-06-07 00:17:31.73162+00 | 2026-06-07 00:18:36.523636+00 | 2026-06-07 00:18:38.551575+00 | 00:01:17.563201 |
| `d0efb00a-681a-4e32-b7de-a27ef94f2977` | UPDATE_AGENT | FAILED | 2026-06-07 00:14:22.239808+00 | 2026-06-07 00:14:31.933557+00 | 2026-06-07 00:15:36.722642+00 | 2026-06-07 00:15:38.883972+00 | 00:01:16.644164 |
| `d0efb00a-681a-4e32-b7de-a27ef94f2977` | COLLECT_INVENTORY | DELIVERED | 2026-06-06 21:04:32.091507+00 | 2026-06-06 21:07:11.222487+00 | (null) | (null) | (null) |
| `d0efb00a-681a-4e32-b7de-a27ef94f2977` | UPDATE_AGENT | FAILED | 2026-06-06 21:02:54.734441+00 | 2026-06-06 21:06:39.182588+00 | 2026-06-06 21:07:43.778449+00 | 2026-06-06 21:07:44.65111+00 | 00:04:49.916669 |
| `d0efb00a-681a-4e32-b7de-a27ef94f2977` | UPDATE_AGENT | FAILED | 2026-06-06 21:00:14.431906+00 | 2026-06-06 21:00:42.515775+00 | 2026-06-06 21:01:47.10408+00 | 2026-06-06 21:01:47.969645+00 | 00:01:33.537739 |
| `d0efb00a-681a-4e32-b7de-a27ef94f2977` | UPDATE_AGENT | FAILED | 2026-06-06 20:56:12.742636+00 | 2026-06-06 20:56:16.75844+00 | 2026-06-06 20:57:21.339735+00 | 2026-06-06 20:57:22.128832+00 | 00:01:09.386196 |
| `d0efb00a-681a-4e32-b7de-a27ef94f2977` | UPDATE_AGENT | FAILED | 2026-06-06 20:53:08.953405+00 | 2026-06-06 20:53:16.750633+00 | 2026-06-06 20:54:21.331721+00 | 2026-06-06 20:54:22.139607+00 | 00:01:13.186202 |
| `d0efb00a-681a-4e32-b7de-a27ef94f2977` | COLLECT_INVENTORY | SUCCEEDED | 2026-06-06 14:45:58.132388+00 | 2026-06-06 14:46:02.042928+00 | 2026-06-06 14:47:06.085769+00 | 2026-06-06 14:47:08.093189+00 | 00:01:09.960801 |
| `d0efb00a-681a-4e32-b7de-a27ef94f2977` | COLLECT_INVENTORY | SUCCEEDED | 2026-06-06 14:39:14.903121+00 | 2026-06-06 14:39:34.257062+00 | 2026-06-06 14:40:38.296587+00 | 2026-06-06 14:40:39.680374+00 | 00:01:24.777253 |
| `d0efb00a-681a-4e32-b7de-a27ef94f2977` | COLLECT_INVENTORY | SUCCEEDED | 2026-06-06 14:07:22.73795+00 | 2026-06-06 14:07:23.712823+00 | 2026-06-06 14:08:27.742465+00 | 2026-06-06 14:08:29.234697+00 | 00:01:06.496747 |

## 6. Cross-device anomaly notes

| Device | Anomaly | Root cause (if known) | Action |
|---|---|---|---|
| PENDING | PENDING | PENDING | PENDING |

## 7. Cross-AI peer review

Implementer AI: Codex
Reviewer AI: N/A for generated evidence draft
Codex thread: N/A
Verdict: not requested for this draft

This document is generated from read-only helper output. PR-level review and CI
metadata are tracked in the pull request body; this draft does not claim an
external AGREE verdict.

## 8. Boundary

- Tier A1 scope only; other tier rollup ayrı doc.
- This rollup draft is not prod-ready, password-reset-ready, or domain-wide rollout-ready evidence.
- This script does not run SQL, dispatch commands, mutate devices, or perform runtime actions.
- 24h soak facts must be operator-reviewed before #1044 moves out of Needs Verify.
