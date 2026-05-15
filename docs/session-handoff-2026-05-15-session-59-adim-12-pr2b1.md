# Session 59 Handoff — Adım 12 PR-2b1 (etl-worker runner retry foundation) MERGED

> Format: D28 5-alan + sıradaki agent action list
> **Önceki**: [session-handoff-2026-05-15-session-58-adim-12-pr2a.md](session-handoff-2026-05-15-session-58-adim-12-pr2a.md)
> **Plan dokümanı**: [plan-reporting-refactor-2026-05-14.md](plan-reporting-refactor-2026-05-14.md) — Adım 12 PR-2b1 slice closed
> **Codex thread**: `019e2a5c` (B1 slicing + PR-2b1 plan-time AGREE + REVISE absorb + AGREE post-impl)

---

## 1. Bağlam (bu oturumda ne yapıldı)

Session 58 (Adım 12 PR-2a MERGED) sonrası kullanıcı mandate "tama otonom ilelryelim" → Adım 12 PR-2b1 runner **retry foundation** impl + cross-AI peer review + merge.

Sıralı çıktı:

1. Codex thread `019e2a5c` plan-time consultation — PR-2b'yi b1/b2/b3 olarak slice et. İlk slice: retry/run subcommand (audit + resume + DB writes out of scope).
2. Impl: `etl_worker/retry.py` (134 SLOC) + `etl_worker/runner.py` (89 SLOC) + CLI `run` subcommand + 36 yeni unit test.
3. Post-impl Codex REVISE: 1 blocker — `value < 0` / `value <= 0` / `value < 1.0` comparisons NaN için false → bad input bypass.
4. REVISE absorb: 5 numeric parse path'inde `math.isfinite` guard + 20 yeni NaN/Inf test (+ 4 existing test wording fix).
5. Codex post-REVISE **AGREE `ready_to_merge=true`**.

**Naming discipline (Codex 019e2a5c)**: bu slice "runner retry foundation", "orchestration complete" değil. Audit + resume + DB writes PR-2b2/PR-2b3'te.

## 2. İddia (bu oturumda PR'lar)

### Backend MERGED

| Konu | PR | Status |
|---|---:|---|
| **Adım 12 PR-2b1** — runner retry foundation + run subcommand + 56 yeni test | [#208](https://github.com/Halildeu/platform-backend/pull/208) | ✅ MERGED |

### Gitops MERGED (handoff)

| Konu | PR | Status |
|---|---:|---|
| **Session 59 handoff + plan-doc Adım 12 PR-2b1 status** (bu doc) | bu PR | yeni |

## 3. İspatlar

### Local gates (PR-2b1 final)

```bash
cd platform-backend/etl-worker
.venv/bin/python -m ruff check etl_worker tests
# All checks passed!

.venv/bin/python -m mypy etl_worker
# Success: no issues found in 8 source files

.venv/bin/python -m pytest
# 130 passed in 0.07s

.venv/bin/etl-worker run --help                     # works
.venv/bin/etl-worker run --retry-attempts 0         # exit 64
.venv/bin/etl-worker run --retry-initial-seconds nan  # exit 64 (NaN bypass guard)
```

Test breakdown:
- 31 (PR-1 schema_service_client) + 43 (PR-2a config/cli) + 36 (PR-2b1 retry/runner/cli-run) + 20 (PR-2b1 NaN/Inf hardening) = **130 total**

### CI checks PR #208 (snapshot at merge)

11/11 SUCCESS (Maven full reactor + 4 Testcontainers IT + etl-worker Python gates + 5 governance/security gates).

### PR-2b1 delivered modules

- `etl_worker/retry.py`:
  - `Sleeper` Protocol + `SystemSleeper` default
  - `RetryPolicy` frozen+slots dataclass with 4-field `__post_init__` validation + `math.isfinite` guards
  - `delay_for_attempt(n)` exponential backoff with cap
  - `call_with_retry[T](operation, *, retryable, policy, sleeper)` PEP 695 generic
- `etl_worker/runner.py`:
  - `RunResult` (summary + attempts)
  - `run_fetch(*, client, schema, policy, sleeper)` — terminal exceptions propagate, transient exhausted surfaces last error
- `etl_worker/cli.py`:
  - New `run` subcommand with `--schema` / `--timeout` / `--retry-attempts` / `--retry-initial-seconds` / `--retry-multiplier` / `--retry-cap-seconds`
  - `main(..., sleeper=None)` injection
  - `_handle_fetch_snapshot` + `_handle_run` private helpers
  - argparse type converters with `math.isfinite` guards

### Cross-AI peer review chain

| PR | Implementer | Reviewer | Verdict |
|---|---|---|---|
| #208 (Adım 12 PR-2b1) | Claude | Codex `019e2a5c` | plan-time AGREE B1 + PR-2b1 retry foundation → post-impl REVISE (1 blocker: NaN/Inf bypass `value < 0` comparisons) → post-REVISE **AGREE `ready_to_merge=true`** |

### Exit-code contract extended

`run` subcommand reuses PR-2a exit-code matrix:

| Exit | Constant | Trigger (run subcommand) |
|---:|---|---|
| `0` | EX_OK | Success — JSON summary on stdout, includes `attempts` field |
| `64` | EX_USAGE | Bad CLI args / missing config / invalid URL / bad timeout / bad retry config (NaN/Inf/sub-unit/negative) |
| `70` | EX_SOFTWARE | 4xx / parse / malformed (terminal, **not retried**) |
| `75` | EX_TEMPFAIL | 5xx / transport outage — retry budget exhausted, surfaces `"after N attempts"` in stderr |
| `76` | EX_PROTOCOL | Contract version mismatch (terminal, **not retried**) |

## 4. İspatlamaz (kalan iş)

### Adım 12 — kalan slice'lar

- **PR-2b2 — Audit log + checkpoint / resume**: ~0.5 gün scope. Audit JSON line writer + JSON Lines audit file + checkpoint state file for resume mid-cycle.
- **PR-2b3 — reports_db writer stub interface**: ~0.5 gün scope. DB-agnostic writer Protocol + connection lifecycle boundaries (real driver wired in PR-3).
- **PR-3 — Dockerfile + K8s Job manifest + test cluster wiring**: ~1 gün. ESO ExternalSecret + ConfigMap envFrom + CronJob schedule.
- **PR-4 — Live smoke against testai schema-service + reports DB writes**: ~0.5 gün. Operator gate (testai schema-service ready + reports_db writable).

### Schema-service emission değişikliği

Adım 12 PR-2b live wire öncesi schema-service'in target contract emit etmesi gerek (current: `version`, `metadata`, `tables` Map, column `dataType` → target: `contract_version`, `allowlist_name`, `allowlist_version`, `tables` list, column `type`). Effort: 2-3 saat. Codex önerisi (PR-2b plan-time): mevcut endpoint'i mutate etme; yeni `?scope=etl-worker` veya `/snapshot/etl-worker` ekle, backwards-compat preserve.

### Operator action (agent yetkisi DIŞI)

- **Adım 13** Faz 16.1 annex 2A SEAL (DBA + owner, 5-8 saat) — runbook PR #643 mevcut
- **Adım 11.5** prod cutover (Adım 13 sonrası)
- **Adım 1.5** prod 3-persona browser smoke (Adım 11.5 sonrası)
- **D30 atomic cutover** ai.acik.com (owner go)

## 5. Bilinen Boşluk + Sıradaki Agent için P0 Aksiyon Listesi

### P0 — Yeni session ilk turu (agent-actionable)

1. **Adım 12 PR-2b2 — Audit log + checkpoint / resume**:
   - `etl_worker/audit.py` (JSON Lines writer + record schema: timestamp, run_id, attempt, outcome, summary)
   - `etl_worker/checkpoint.py` (state file format + resume logic for mid-cycle interruption)
   - `run` subcommand `--audit-path` / `--checkpoint-path` flags
   - Effort: ~0.5 gün
   - Codex `019e2a5c` thread devam

2. **Schema-service emission değişikliği** (PR-2b live wire prerequisite):
   - `schema-service/SchemaController` yeni endpoint `?scope=etl-worker` veya `/snapshot/etl-worker`
   - `SchemaSnapshot` target shape mapper
   - Backwards-compat preserve (existing consumers etkilenmesin)
   - Effort: 2-3 saat
   - Codex peer review separate thread

### P1 — Adım 12 yolu devam

3. **PR-2b3** — reports_db writer stub interface (~0.5 gün)
4. **PR-3** — Dockerfile + K8s Job (~1 gün)
5. **PR-4** — Live smoke (operator gate, ~0.5 gün)

### P2 — Paralel agent-actionable

6. **Adım 14 FE kozmetik** (Session 56 spawn task)
7. **platform-web #507** FineKinney domain refactor
8. **platform-web #503** blocks convention doc

### Operator/owner-blocked

- Adım 13 SEAL (5-8 saat DBA + owner)
- Adım 11.5 prod cutover (Adım 13 sonrası)
- Adım 1.5 prod 3-persona smoke
- D30 atomic cutover

### Yeni Session İçin İlk Komut

```bash
cd /Users/halilkocoglu/Documents/platform-k8s-gitops
cat docs/session-handoff-2026-05-15-session-59-adim-12-pr2b1.md  # this file

# Highest-value next step: Adım 12 PR-2b2 audit + checkpoint
cd /Users/halilkocoglu/Documents/platform-backend
git fetch && git checkout main && git pull
git checkout -b feat/adim-12-pr2b2-etl-worker-audit-checkpoint
```

### Codex thread devamı

`019e2a5c` — Adım 12 ana thread. PR-1 + PR-2a + PR-2b1 kapandı; PR-2b2 için aynı thread devam edilebilir.

---

## 6. Kapanış Notu — Session 59 İstatistikleri

| Metrik | Değer |
|---|---:|
| MERGED PR (bu session) | 1 backend (#208) + 1 gitops pending (bu doc) |
| Yeni unit test | +56 (16 retry + 7 runner + 13 cli-run + 20 NaN/Inf hardening) |
| Toplam test (etl-worker) | **130** (31 PR-1 + 43 PR-2a + 56 PR-2b1) |
| Yeni source modül | 2 (`retry.py` + `runner.py`) |
| Cross-AI Codex iter | ~3 turn (plan-time + post-impl REVISE + post-REVISE AGREE) |
| Cross-AI Peer Review HARD RULE ihlal | 0 |
| Admin bypass kullanımı | 0 |
| Production outage | 0 |
| Plan ilerleme (Adım 12 effort bazında) | PR-1 ~20% + PR-2a ~30% + PR-2b1 ~15% = **~65% of overall Adım 12** |

**Adım 12 yolunda kalan**:
- PR-2b2 audit + checkpoint (~10%)
- PR-2b3 DB writer stub (~10%)
- PR-3 Docker + K8s (~10%)
- PR-4 live smoke (~5%)
