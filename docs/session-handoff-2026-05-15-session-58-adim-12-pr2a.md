# Session 58 Handoff — Adım 12 PR-2a (etl-worker config / CLI / client wiring) MERGED

> Format: D28 5-alan + sıradaki agent action list
> **Önceki**: [session-handoff-2026-05-15-session-57-pr-cleanup-plus-adim-12-pr1.md](session-handoff-2026-05-15-session-57-pr-cleanup-plus-adim-12-pr1.md)
> **Plan dokümanı**: [plan-reporting-refactor-2026-05-14.md](plan-reporting-refactor-2026-05-14.md) — Adım 12 PR-2a slice closed
> **Codex thread**: `019e2a5c` (Opt-B AGREE → REVISE absorb → AGREE post-impl + post-REVISE-2 AGREE)

---

## 1. Bağlam (bu oturumda ne yapıldı)

Session 57'nin Adım 12 PR-1 (`SchemaServiceClient` scaffold + 31 unit test) merged sonrası kullanıcı mandate "tama otonom ilelryelim" → Adım 12 PR-2a (config + CLI + entry point + typed exit codes) impl + cross-AI peer review + merge.

Sıralı çıktı:

1. Codex thread `019e2a5c` plan-time consultation — scope shape A (config + CLI + entry point + exit-code matrix) picked over B (`--output-format`) and C (env-only). 10 decision locks pinned.
2. Impl: `etl_worker/config.py` (153 SLOC) + `etl_worker/cli.py` (236 SLOC) + `etl_worker/__main__.py` (wrapper) + 39 yeni unit test (23 config + 16 cli).
3. Post-impl Codex REVISE: 1 blocker — malformed URL'ler (`http://[::1`, `http://host:badport`, `http://host:99999`) raw `urlparse` / `.port` `ValueError` sızıyor → CLI `EX_USAGE=64` kontratı bozuluyor.
4. REVISE absorb: `_validate_url` çift `try/except ValueError` → `ConfigError`. +4 test (3 parameterised config-level + 1 CLI-level stack-trace-safe).
5. Codex post-REVISE **AGREE `ready_to_merge=true`**.

## 2. İddia (bu oturumda PR'lar)

### Backend MERGED

| Konu | PR | Status |
|---|---:|---|
| **Adım 12 PR-2a** — etl-worker config / CLI / client wiring + 39 + 4 tests | [#206](https://github.com/Halildeu/platform-backend/pull/206) | ✅ MERGED |

### Gitops MERGED (handoff)

| Konu | PR | Status |
|---|---:|---|
| **Session 58 handoff + plan-doc Adım 12 PR-2a status** (bu doc) | bu PR | yeni |

## 3. İspatlar

### Local gates (PR-2a final)

```bash
cd platform-backend/etl-worker
.venv/bin/python -m ruff check etl_worker tests
# All checks passed!

.venv/bin/python -m mypy etl_worker
# Success: no issues found in 6 source files

.venv/bin/python -m pytest
# 74 passed in 0.05s  (31 PR-1 + 23 config + 16 cli + 3+1 REVISE absorb)

.venv/bin/etl-worker --help                         # console script works
.venv/bin/etl-worker fetch-snapshot                 # exit 64 + stderr (no env)
```

### CI checks PR #206 (snapshot at merge)

- ✅ `etl-worker Python gates` SUCCESS (new ruff + mypy + pytest workflow, path-filtered `etl-worker/**`)
- ✅ `Maven full reactor build (all 9 modules)` SUCCESS
- ✅ All 4 Testcontainers IT (auth-service WireMock / permission-service / report-service MSSQL / notification-orchestrator PG) SUCCESS
- ✅ `gitleaks`, `osv-scan`, `contract-gate`, `schema-service standalone build`, `OpenFGA DSL`: all SUCCESS

### Cross-AI peer review chain

| PR | Implementer | Reviewer | Verdict |
|---|---|---|---|
| #206 (Adım 12 PR-2a) | Claude | Codex `019e2a5c` | plan-time AGREE scope A + 10 decision locks → post-impl REVISE (1 blocker: urlparse/.port ValueError leak) → post-REVISE **AGREE `ready_to_merge=true`** |

### PR-2a CLI usage (delivered)

```
$ etl-worker --help
usage: etl-worker [-h] {fetch-snapshot} ...

$ etl-worker fetch-snapshot --help
usage: etl-worker fetch-snapshot [-h] [--schema SCHEMA] [--timeout TIMEOUT]
```

Environment matrix:

| Variable | Required | Default | Notes |
|---|---|---|---|
| `SCHEMA_SERVICE_URL` | ✅ | — | http/https only; no embedded credentials; trailing slash trimmed; **malformed URL → ConfigError → EX_USAGE** |
| `SCHEMA_SERVICE_INTERNAL_API_KEY` | — | unset | Sent as `X-Internal-Api-Key` header |
| `SCHEMA_SERVICE_TIMEOUT_SECONDS` | — | `10` | Positive float |
| `SCHEMA_SERVICE_SCHEMA` | — | unset | Default for `?schema=` selector |
| `SCHEMA_SERVICE_CONTRACT_VERSIONS` | — | `1` | CSV |

Exit-code contract:

| Exit | Constant | Trigger |
|---:|---|---|
| `0` | `EX_OK` | Success — single-line JSON summary on stdout |
| `64` | `EX_USAGE` | Bad CLI args / missing config / invalid URL / bad timeout / empty CSV |
| `70` | `EX_SOFTWARE` | 4xx / parse / malformed (terminal) |
| `75` | `EX_TEMPFAIL` | 5xx / transport outage (retryable) |
| `76` | `EX_PROTOCOL` | Contract version mismatch (terminal) |

## 4. İspatlamaz (kalan iş)

### Adım 12 — kalan slice'lar (agent-actionable)

- **PR-2b — Runner orchestration**: retry / audit / resume / DB lifecycle. Effort: 1-2 gün. Codex `019e2a5c` thread devam edilebilir.
- **PR-3 — Dockerfile + K8s Job manifest + test cluster wiring**. Effort: ~1 gün. Operator-readiness için Vault path + ESO ExternalSecret + ConfigMap envFrom.
- **PR-4 — Live smoke against testai schema-service + reports DB writes**. Effort: ~0.5 gün. Operator gate (testai schema-service ready + reports_db writable).

### Schema-service emission değişikliği (Adım 12 PR-2b prerequisite)

PR-1 ve PR-2a target contract'a (`contract_version`, `allowlist_name`, `allowlist_version`, `tables` list, column `type`) karşı çalışıyor. Schema-service bugün farklı emit ediyor (`version`, `metadata`, `tables` Map, column `dataType`). PR-2b runner live test cluster'da çalışabilmesi için schema-service tarafında emission değişikliği gerek. Effort: 2-3 saat.

### Operator action (agent yetkisi DIŞI)

- **Adım 13** Faz 16.1 annex 2A SEAL (DBA + owner, 5-8 saat) — runbook PR #643 mevcut
- **Adım 11.5** prod cutover (Adım 13 sonrası)
- **Adım 1.5** prod 3-persona browser smoke (Adım 11.5 sonrası)
- **D30 atomic cutover** ai.acik.com (owner go)
- **D dalga 1.2-1.7 Vault rotation** (user/permission/core-data/report/schema/endpoint-admin)

## 5. Bilinen Boşluk + Sıradaki Agent için P0 Aksiyon Listesi

### P0 — Yeni session ilk turu (agent-actionable)

1. **Adım 12 PR-2b — Runner orchestration**:
   - `etl_worker/runner.py` (retry + backoff için `tenacity` veya stdlib loop; audit log şeması; resume checkpoint dosyası)
   - `etl_worker/db.py` (reports_db connection — Postgres veya MSSQL stub; PR-2b'de mock, PR-3'te live)
   - Yeni CLI subcommand `run` orchestration için
   - Effort: 1-2 gün, parça parça yapılabilir (PR-2b1 retry + PR-2b2 audit + PR-2b3 resume gibi)
   - Codex `019e2a5c` thread devam

2. **Schema-service emission değişikliği** (PR-2b live wire prerequisite):
   - `SchemaSnapshot.java` + `ColumnInfo.java`'da hedef shape emit
   - Backward-compat: yeni alanlar additive (current shape preserve edilebilir)
   - Effort: 2-3 saat

### P1 — Adım 12 sonrası

3. **PR-3 — Dockerfile + K8s Job manifest + test cluster wiring** (Vault path + ESO + ConfigMap)
4. **PR-4 — Live smoke** (operator gate)

### P2 — Paralel agent-actionable

5. **Adım 14 FE kozmetik** (Session 56 spawn task — hook'lar 1-2 saat + adoption 1 gün)
6. **platform-web #507** FineKinney domain refactor (CI check + merge)
7. **platform-web #503** blocks convention doc (review + merge)

### Operator/owner-blocked

- Adım 13 SEAL (5-8 saat DBA + owner)
- Adım 11.5 prod cutover (Adım 13 sonrası, kubectl + 72h warm rollback)
- Adım 1.5 prod 3-persona smoke
- D30 atomic cutover ai.acik.com (owner go)

### Yeni Session İçin İlk Komut

```bash
cd /Users/halilkocoglu/Documents/platform-k8s-gitops
cat docs/session-handoff-2026-05-15-session-58-adim-12-pr2a.md  # this file

# Highest-value next step: Adım 12 PR-2b runner orchestration
cd /Users/halilkocoglu/Documents/platform-backend
git fetch && git checkout main && git pull
git checkout -b feat/adim-12-pr2b-etl-worker-runner-orchestration
# scope: runner.py + retry + audit + resume + db lifecycle stub (live in PR-3/PR-4)
```

### Codex thread devamı

`019e2a5c` — Adım 12 ana thread. PR-1 + PR-2a kapandı; PR-2b plan-time için aynı thread devam edilebilir veya yeni thread açılabilir (Codex thread limit yaklaşırsa).

---

## 6. Kapanış Notu — Session 58 İstatistikleri

| Metrik | Değer |
|---|---:|
| MERGED PR (bu session) | 1 backend (#206) + 1 gitops pending (bu doc) |
| Yeni unit test | +43 (23 config + 16 cli + 3 malformed URL parameterised + 1 stack-trace-safe CLI) |
| Toplam test (etl-worker) | 74 (31 PR-1 + 43 PR-2a) |
| Cross-AI Codex iter | ~3 turn (plan-time + post-impl REVISE + post-REVISE AGREE) |
| Cross-AI Peer Review HARD RULE ihlal | 0 |
| Admin bypass kullanımı | 0 |
| Production outage | 0 |
| Plan ilerleme (Adım 12 effort bazında) | PR-1 ~20% + PR-2a ~30% = **~50% of overall Adım 12** |

**Adım 12 yolunda kalan**:
- PR-2b runner orchestration (~30%)
- PR-3 Dockerfile + K8s Job (~15%)
- PR-4 live smoke (~5%)
