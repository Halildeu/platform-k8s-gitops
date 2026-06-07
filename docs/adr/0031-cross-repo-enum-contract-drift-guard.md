# ADR-0031 — Cross-Repo Enum / Contract Drift Guard

> **Status**: Draft iter-4 — Codex thread `019e8832-9c9c-7cc3-89b0-62be4bef43cb` returned REVISE on iter-1 (8 axes), iter-2 (4 narrow blockers), and iter-3 (4 cleanup must-fixes including a mathematical mirror-union bug); this iter-4 absorbs the iter-3 must-fixes: per-mirror equality invariant (was union-of-mirrors, which could hide a stale mirror); §1.2 + §1.3 stale "out-of-scope" language for `ServicesPayloadPolicy` dedup removed (DD-5-4 is closure-blocking — already reflected in §3.3/§5/§6 but the introduction had drifted); DD-5-2 token-input name corrected to `cross_repo_contract_read_token` + secret `CROSS_REPO_CONTRACT_READ_TOKEN` (was the stale iter-2 `cross_repo_contents_token`); I9 paired-PR test case updated to blocking exit 1 (was "advisory" — contradicted I6); various cosmetic factual fixes (Five parser strategies not Four; ServiceState at endpoint-services/types.ts:37 not :40; iter labels in §5/§7); cross-AI consensus pending iter-4 verdict
> **Owner**: Platform-Eng
> **Date**: 2026-06-02
> **Sprint**: WEB-015 v2-a hardening follow-up (board #1163-class drift guard)
> **Predecessors**: ADR-0011 §2.1 (plan-time drift detection axis A) — parent governance frame; ADR-0014 (MFE auth transport contract) — cross-repo contract precedent
> **Related**: ADR-0020 (schema truth-tier — Tier ≠ enum drift, same "two repos, one truth" shape); `platform-backend/.github/workflows/reporting-allowlist-drift.yml` (path-filter trap precedent — must-NOT path-filter a required check)
> **Codex thread**: `019e8832-9c9c-7cc3-89b0-62be4bef43cb` (iter-1 + iter-2 + iter-3 REVISE absorbed in this iter-4 draft)

---

## 1. Context

`platform-backend` defines domain enums (Java `enum`, `Set<String>` constants, or — in one shipping case — `CASE WHEN ... THEN '<literal>'` SQL projections embedded in Java string constants) that constrain which values may appear on a wire payload, persist in a column, or project in a SQL grid expression. `platform-web` mirrors these enums in TypeScript — as `as const` tuples (for AG Grid Set Filter `values`), as union types (`type Foo = 'A' | 'B'`), or both in the same file.

The mirrors are **hand-curated**. `apps/mfe-endpoint-admin/src/entities/endpoint-device/types.ts:7` and `apps/mfe-endpoint-admin/src/entities/endpoint-app-control/types.ts:6-11` document the source path in a header comment:

```ts
// endpoint-device/types.ts:1-11
/**
 * Backend DTO mirror — `EndpointDeviceDto` (record).
 *
 * Source-of-truth (e9cb8dd0):
 *   platform-backend / endpoint-admin-service /
 *     src/main/java/com/example/endpointadmin/dto/v1/admin/EndpointDeviceDto.java
 *     src/main/java/com/example/endpointadmin/model/{DeviceStatus,OsType}.java
 */
```

This convention is a **statement of intent**, not enforcement. When the backend enum changes, nothing fails until LIVE smoke flips a row through the offending value.

### 1.1 Live drift incident (2026-06-02)

WEB-015 v2-a chain LIVE smoke (testai cluster) returned `prohibited_decision=UNKNOWN`. The frontend `PROHIBITED_DECISION_VALUES` tuple at `apps/mfe-endpoint-admin/src/pages/devices/EndpointDevicesPage.tsx:96-101` contained only `['COMPLIANT', 'NON_COMPLIANT', 'UNAUTHORIZED']`. The Set Filter hid the row entirely; the user could not filter on the new ladder tier. PR #736 fast-followed with `'UNKNOWN'` added, but the gap that allowed the drift remains open.

Backend canonical (`endpoint-admin-service/src/main/java/com/example/endpointadmin/model/ComplianceDecision.java`) was extended for the UNAUTHORIZED > UNKNOWN > NON_COMPLIANT > COMPLIANT precedence ladder under Codex `019e6bbf` iter-3 — a fully reviewed backend change. The frontend tuple drift was invisible to every gate that approved it.

### 1.2 Inventory — cross-repo enum mirrors known today (10 mappings, all v1)

iter-1 listed 4 mappings; Codex iter-1 review surfaced the actual inventory is materially larger. The full grid + app-control + services consumer surface today:

| # | Backend canonical (`platform-backend/endpoint-admin-service`) | Type | Path | Frontend mirror(s) (`platform-web/apps/mfe-endpoint-admin`) | Path(s) |
|---|---|---|---|---|---|
| 1 | `ComplianceDecision` | `enum` | `src/main/java/com/example/endpointadmin/model/ComplianceDecision.java` | `PROHIBITED_DECISION_VALUES` (tuple) | `src/pages/devices/EndpointDevicesPage.tsx:96-101` |
| 2 | `DeviceStatus` | `enum` | `src/main/java/com/example/endpointadmin/model/DeviceStatus.java` | `DeviceStatus` (union) + `DEVICE_STATUS_VALUES` (tuple) | `src/entities/endpoint-device/types.ts:13,47-53` |
| 3 | `OsType` | `enum` | `src/main/java/com/example/endpointadmin/model/OsType.java` | `OsType` (union) + `OS_TYPE_VALUES` (tuple) | `src/entities/endpoint-device/types.ts:15,55` |
| 4 | `WDAC_MODE_ENUM` | `Set<String>` | `src/main/java/com/example/endpointadmin/security/AppControlPayloadPolicy.java:93-95` | `WDAC_MODE_VALUES` (tuple) + `WdacMode` (union) | `src/pages/devices/EndpointDevicesPage.tsx:102` + `src/entities/endpoint-app-control/types.ts:33` |
| 5 | `APPLOCKER_MODE_ENUM` | `Set<String>` | `src/main/java/com/example/endpointadmin/security/AppControlPayloadPolicy.java:98-100` | `AppLockerEnforcementMode` (union) | `src/entities/endpoint-app-control/types.ts:36` |
| 6 | `SERVICE_STATE_ENUM` | `Set<String>` | `src/main/java/com/example/endpointadmin/security/EndpointServiceWireEnums.java:27-29` | `APP_ID_SVC_STATE_VALUES` (tuple) + `ServiceState` (union, appears in TWO entity files) | `src/pages/devices/EndpointDevicesPage.tsx:103` + `src/entities/endpoint-app-control/types.ts:42` + `src/entities/endpoint-services/types.ts:37` |
| 7 | `STARTUP_MODE_ENUM` | `Set<String>` | `src/main/java/com/example/endpointadmin/security/EndpointServiceWireEnums.java:32-34` (5-value, includes `AUTO_DELAYED`) | `ServiceStartupMode` (union, app-control file) + `StartupMode` (union, services file — note: **distinct symbol name** from the app-control mirror; the two unions hold the same value-set but the TS identifiers differ) | `src/entities/endpoint-app-control/types.ts:49` + `src/entities/endpoint-services/types.ts:47` |
| 8 | `PROBE_ERROR_CODE_ENUM` | `Set<String>` | `src/main/java/com/example/endpointadmin/security/AppControlPayloadPolicy.java:103-112` | `AppControlProbeErrorCode` (union) | `src/entities/endpoint-app-control/types.ts:62-70` |
| 9 | `PROBE_ERROR_SOURCE_ENUM` | `Set<String>` | `src/main/java/com/example/endpointadmin/security/AppControlPayloadPolicy.java:115-117` | `AppControlProbeErrorSource` (union) | `src/entities/endpoint-app-control/types.ts:76` |
| 10 | `prohibited_status` SQL CASE literals | string literal inside Java | `src/main/java/com/example/endpointadmin/grid/DeviceGridColumns.java:137` (`CASE WHEN pe.id IS NULL THEN 'NO_EVALUATION' ELSE 'OK' END`) | `PROHIBITED_STATUS_VALUES` (tuple) | `src/pages/devices/EndpointDevicesPage.tsx:84` |

**Closure-blocking cleanup discovered by this ADR (intra-backend dedup — NOT a guard-mechanism responsibility, but a co-required fix):**
- `ServicesPayloadPolicy.java:91-95` declares a *private* `SERVICE_STATE_ENUM` + `STARTUP_MODE_ENUM` that duplicates `EndpointServiceWireEnums`. The `EndpointServiceWireEnums` JavaDoc (`endpoint-admin-service/.../security/EndpointServiceWireEnums.java:6-9`) explicitly says it was extracted to keep the two policies consistent without inter-policy coupling — the duplication is an incomplete migration, not the intended terminal state. Tracked as DD-5-4; **CLOSURE-BLOCKING** for ADR-0031 (see § 3.3 rationale, § 5 PR sequence, § 6 closure criteria). The cross-repo guard itself does NOT enforce intra-backend duplication; DD-5-4 removes the duplicate so the guard's `EndpointServiceWireEnums` canonical choice has no ambiguous shadow.

### 1.3 Scope of decision

This ADR governs **value-set drift across the `platform-backend` ↔ `platform-web` boundary**: "Does `set(backend canonical)` equal `set(frontend mirror)` for every mirror listed in the spec?" It does NOT govern:
- DTO field-shape drift (covered separately; OpenAPI / DTO-mirror discipline is documented in `types.ts` headers but not enforced).
- Migration-vs-Java-entity column drift (covered by Flyway / JPA `ddl-auto=validate` at boot).
- Behavior drift (a value present on both sides but treated differently).
- Intra-backend duplication enforcement at the **guard mechanism** level (e.g. `ServicesPayloadPolicy` private duplicate of `EndpointServiceWireEnums` is fixed by DD-5-4 closure-blocking dedup, not by extending the cross-repo guard to backend↔backend mirrors — see § 1.2).
- Agent → backend wire contract (covered by per-feature payload-contract gates such as `gate-outdated-software-contract.yml`).

## 2. Decision — Decision Invariants

The ten invariants below define the contract. Every line is **MUST**: a violation is a CI-red gate.

### I1 — Declarative spec is the single registry, with per-mapping multi-mirror support

A YAML file `config/cross_repo_enum_drift_spec.yaml` in `platform-k8s-gitops` enumerates every guarded mapping. Each mapping has one canonical and **one or more** mirrors (DeviceStatus, OsType, WdacMode, ServiceState all have a `union` AND a `tuple` mirror in the same file; `ServiceState` even appears in TWO entity files):

```yaml
schema_version: 1
mappings:
  - id: compliance-decision
    canonical:
      repo: Halildeu/platform-backend
      path: endpoint-admin-service/src/main/java/com/example/endpointadmin/model/ComplianceDecision.java
      kind: java_enum
      symbol: ComplianceDecision
    mirrors:
      - repo: Halildeu/platform-web
        path: apps/mfe-endpoint-admin/src/pages/devices/EndpointDevicesPage.tsx
        kind: ts_const_tuple
        symbol: PROHIBITED_DECISION_VALUES
    notes: |
      WEB-015 v2-a; ladder UNAUTHORIZED > UNKNOWN > NON_COMPLIANT > COMPLIANT.
      2026-06-02 live drift PR #736 — Codex 019e8820.

  - id: device-status
    canonical:
      repo: Halildeu/platform-backend
      path: endpoint-admin-service/src/main/java/com/example/endpointadmin/model/DeviceStatus.java
      kind: java_enum
      symbol: DeviceStatus
    mirrors:
      - repo: Halildeu/platform-web
        path: apps/mfe-endpoint-admin/src/entities/endpoint-device/types.ts
        kind: ts_union_type
        symbol: DeviceStatus
      - repo: Halildeu/platform-web
        path: apps/mfe-endpoint-admin/src/entities/endpoint-device/types.ts
        kind: ts_const_tuple
        symbol: DEVICE_STATUS_VALUES

  - id: service-state
    canonical:
      repo: Halildeu/platform-backend
      path: endpoint-admin-service/src/main/java/com/example/endpointadmin/security/EndpointServiceWireEnums.java
      kind: java_set_of
      symbol: SERVICE_STATE_ENUM
    mirrors:
      - repo: Halildeu/platform-web
        path: apps/mfe-endpoint-admin/src/pages/devices/EndpointDevicesPage.tsx
        kind: ts_const_tuple
        symbol: APP_ID_SVC_STATE_VALUES
      - repo: Halildeu/platform-web
        path: apps/mfe-endpoint-admin/src/entities/endpoint-app-control/types.ts
        kind: ts_union_type
        symbol: ServiceState
      - repo: Halildeu/platform-web
        path: apps/mfe-endpoint-admin/src/entities/endpoint-services/types.ts
        kind: ts_union_type
        symbol: ServiceState

  - id: prohibited-status-sql-case
    canonical:
      repo: Halildeu/platform-backend
      path: endpoint-admin-service/src/main/java/com/example/endpointadmin/grid/DeviceGridColumns.java
      kind: java_grid_column_case_literals
      symbol: prohibited_status           # the GridColumn colId, not a Java identifier
      anchor: "new GridColumn(\"prohibited_status\","   # extraction anchor in the source
    mirrors:
      - repo: Halildeu/platform-web
        path: apps/mfe-endpoint-admin/src/pages/devices/EndpointDevicesPage.tsx
        kind: ts_const_tuple
        symbol: PROHIBITED_STATUS_VALUES
```

Five parser strategies are supported in v1 (all adopted at once — no "ts_union_type added in a separate PR" deferral; the iter-1 contradiction between I1 and I5 is resolved):
- `java_enum` — `public enum <Symbol> { A, B, C }` (with or without trailing `;`/methods).
- `java_set_of` — `public static final Set<String> <Symbol> = Set.of("A", "B", "C");` (single- or multi-line; `Set.<String>of(...)` cast form accepted).
- `ts_const_tuple` — `const <Symbol> = [...] as const`, `export const <Symbol>: readonly Foo[] = [...] as const`, `as const satisfies readonly Foo[]`.
- `ts_union_type` — `type <Symbol> = 'A' | 'B' | 'C';` (single-line preferred; multi-line tolerated).
- `java_grid_column_case_literals` — narrow strategy that locates the `new GridColumn("<symbol>", "<sql-expression>"` constructor call inside `DeviceGridColumns.java` and extracts the quoted literals from `CASE WHEN ... THEN '<X>' ELSE '<Y>' END`. Does NOT claim to parse arbitrary SQL; rejects any CASE not matching this narrow shape (exit 2).

Adding a new mapping = one YAML block. Adding a new parser strategy = a separate PR with its own unit tests (I7) added to `KNOWN_STRATEGIES`.

### I2 — Per-mirror set equality (NOT mirror-union equality); no value normalization

**Per-mirror equality invariant** (iter-3 axis 8 must-fix — corrects a mathematical bug in iter-2/iter-3):

A mapping passes IFF **every** mirror in `mappings[i].mirrors[]` individually has `set(canonical) == set(mirror_j)`. The overall mapping verdict is the **logical AND** across mirrors, not the union.

Why this matters: comparing against `⋃ set(mirror_j)` can hide a stale mirror. Example failure mode:
- canonical = `{A, B, C, D}`
- mirror_1 (union type) = `{A, B, C, D}` ← updated
- mirror_2 (tuple) = `{A, B, C}` ← stale, missing D
- `⋃(mirror_1, mirror_2)` = `{A, B, C, D}` = canonical → would FALSELY pass under the union rule.
- Under the per-mirror rule: `mirror_2 ≠ canonical` → mapping FAILS, exactly the drift this ADR exists to catch.

**Reporting**: each mirror's diff (`missing_in_mirror`, `missing_in_canonical`, `duplicates`) is reported independently. The report may include a synthetic `mirror_union` diagnostic field for human reading, but it MUST NOT determine pass/fail (iter-3 axis 8 nice-to-have).

**Duplicates**: a value extracted twice from a canonical or a mirror is a value/extraction-level error (NOT a spec-level error; spec-level duplicates are handled by I5). Treated as exit 1 with `duplicates: ['X']` in the diff.

**Empty extracted set** is an error (exit 2 — diagnostic distinct from a legitimately-zero-value enum, which is itself prima facie wrong).

**Order tolerance**: order differences between canonical and mirror are tolerated.

**No value normalization**: `wdac` and `WDAC` are different. Case-sensitive comparison.

### I3 — Read paths via `gh api`, explicit `contents+pull-requests` token from day 1, 403/404 disambiguated per endpoint

The drift script fetches:
- Source files via `gh api repos/<owner>/<repo>/contents/<path>?ref=<sha>` (Base64 decode).
- Paired-PR metadata via `gh api repos/<owner>/<repo>/pulls/<num>` (PR body, head SHA, merge state — required by I6 paired-PR protocol).

No clone. Side-effect-free, network-bounded.

**Token policy (v1, no fallback cascade)**: caller workflows pass an explicit input `cross_repo_contract_read_token` (env var `GH_TOKEN`). For private cross-repo reads this is a fine-grained PAT or GitHub App token with these scopes on `platform-backend`, `platform-web`, and `platform-k8s-gitops`:
- **Contents: Read** — for the `contents/<path>` source fetches.
- **Pull requests: Read** — for the `pulls/<num>` paired-PR metadata fetches (REQUIRED by I6; without it the paired-PR protocol cannot disambiguate `merged_at` for the mirror-side canonical-first block).
- **Metadata: Read** — implicit for any fine-grained token.

Public-repo case may pass `github.token` but the caller declares the choice explicitly. There is no "GITHUB_TOKEN first, PAT fallback" cascade — that conditional path was rejected by Codex iter-1 axis 4 must-fix; auth-missing must fail loudly. The token name `CROSS_REPO_CONTRACT_READ_TOKEN` is intentionally broader than the iter-2 `CROSS_REPO_CONTENTS_TOKEN` to reflect the extended scope.

**Error disambiguation (per-endpoint)**:
- `contents/<path>` 403 → exit 2 with `auth insufficient for contents at <owner>/<repo>/<path>: required Contents:Read`.
- `contents/<path>` 404 → exit 2 with `canonical file not found at <owner>/<repo>/<path>@<ref> — verify spec or token scope`.
- `pulls/<num>` 403 → exit 2 with `auth insufficient for pull request metadata at <owner>/<repo>#<num>: required Pull requests:Read`.
- `pulls/<num>` 404 → exit 2 with `paired PR not found at <owner>/<repo>#<num> — verify paired_pr_url in PR description`.
- `200` with empty body → exit 2 with `empty file at <path>`.
- `200` with parseable body but extracted set is empty → exit 2 with `empty extracted set from <path>:<symbol>`.

The token name is logged as a redacted boolean (`set/unset`), not its value. No token classes mixed in logs.

**Refs**: PR-time runs use `github.event.pull_request.head.sha` for the running-PR side. Paired-PR runs resolve the other side's ref via I6 protocol (paired PR's `head.sha` for canonical-side; canonical `main` for mirror-side after the paired canonical PR's `merged_at` is non-null). `github.head_ref` is NOT used — it is empty on push/schedule events.

**Fetch cache** (nice-to-have, iter-2 axis 1): the script dedupes `gh api` calls keyed on `(repo, path, ref)` so 10 mappings with multi-mirror entries do not re-fetch identical files. Cache TTL is process-scoped (single run).

### I4 — Composite action SHA-pinned in caller workflows; explicit bump PR per interface change

The drift script lives in `platform-k8s-gitops/scripts/drift_detection/check_drift_cross_repo_enums.py`. The reusable composite action lives at `platform-k8s-gitops/.github/actions/check-cross-repo-enum-drift/action.yml` and resolves script + spec via `$GITHUB_ACTION_PATH` (NOT caller-workspace-relative — caller workspaces are `platform-backend` and `platform-web`, where the script and spec do not exist).

**Caller pinning**: caller workflows reference the action at a specific commit SHA — `uses: Halildeu/platform-k8s-gitops/.github/actions/check-cross-repo-enum-drift@<sha>` — not `@main`. The initial pin is the DD-5-1 merge SHA.

**Bump policy**: any action interface or behavior change opens an explicit bump PR per caller (platform-backend, platform-web) with a one-line `## Action bump` block in the PR body citing:
- Script SHA before/after.
- Spec `schema_version` (I1) before/after.
- Caller workflow input diff (added/removed/renamed arg).
- Forced-drift smoke confirmation (workflow_dispatch run on a fixture before bump).

The action emits a `$GITHUB_STEP_SUMMARY` header line on every run with `action_commit_sha: <sha>` and `spec_schema_version: <n>` so a reviewer can confirm the pinned version matches the caller's expectation without opening the action source (iter-2 axis 2 nice-to-have).

Hygiene check: a quarterly review issue scans for action behavior delta since the last caller pin even if no caller is bumping — silent drift between gate behavior and caller expectation is itself a class of bug.

### I5 — Fail-closed unknown strategy + spec schema validation

A mapping whose `canonical.kind` or `mirrors[*].kind` is not in `KNOWN_STRATEGIES` fails CI (exit 2). The spec file itself is validated against an inline JSON Schema before any mapping is processed; the following are spec-level errors (exit 2):
- Duplicate `mapping.id`.
- Unknown `repo` shape (not `<owner>/<repo>`).
- Missing `canonical.path` / `canonical.symbol` / any mirror field.
- Unknown `kind`.
- Zero mirrors (a guarded mapping must guard something).
- `mirrors[*].kind` requiring an `anchor` field (e.g. `java_grid_column_case_literals`) but `anchor` missing.

Spec schema lives next to the file: `config/cross_repo_enum_drift_spec.schema.json`. The script uses Python `stdlib`-only JSON Schema validation via a vendored or `jsonschema`-pip-installed validator (matching the existing pattern in `gate-outdated-software-contract.yml:40` which already installs `jsonschema`).

### I6 — Paired-PR protocol with machine-enforced canonical-first merge invariant (mandatory, NOT advisory)

A PR that adds a value to a `canonical` will turn the gate red in its own repo (canonical-side HEAD diverges from mirror main). The reverse — a PR that adds the value only to a `mirror` — turns the gate red in `platform-web` for the same reason. The gate resolves the deadlock through an explicit pairing override and asymmetric merge-order enforcement.

**Per-PR pairing input** (`paired_pr_url`):
- The PR description carries a single-line fenced block:
  ```
  <!-- cross-repo-enum-drift:paired-pr -->
  paired_pr_url: https://github.com/Halildeu/platform-web/pull/<N>
  ```
- Exactly ONE `paired_pr_url:` line is allowed per block. Multiple lines → exit 2 with `multiple paired_pr_url entries — paired-PR protocol expects exactly one per PR`. Zero lines = unpaired mode.
- The action parses this block from the PR description (via `gh api pulls/<num>` body) and validates the URL:
  - Repo MUST be the opposite side (canonical-side PR's paired URL → mirror repo; mirror-side PR's paired URL → canonical repo). Otherwise exit 2 with `paired PR repo mismatch`.
  - Base MUST be `main`. Otherwise exit 2 with `paired PR base must be main`.
  - The paired PR MUST also reference at least one of the same guarded mappings as the current PR (verified by re-running the gate against the paired PR's head and checking that the same `mapping.id` flips drift state). Otherwise exit 2 with `paired PR does not touch the same guarded mapping`.
- The summary labels the mode: `pairing: paired` or `pairing: unpaired-main`. Report fields: `compared_refs`, `compared_shas`, `paired_pr_url`, `residual_main_drift_risk`, `own_repo_role: canonical|mirror|spec-host`, `reciprocal_pairing: true|false` (true when paired PR's body also references this PR's URL).

**Canonical-first merge invariant — asymmetric machine-enforced block**:

The invariant is asymmetric because canonical merges first by design — the mirror cannot be ahead of the canonical on `main`. The gate enforces this with two distinct rules:

1. **Canonical-side PR** (running in `platform-backend`, canonical-side change):
   - With `paired_pr_url`: fetch paired mirror PR JSON via `gh api pulls/<num>`.
   - If paired mirror PR `state: open`: compare `set(canonical@PR-head) == set(mirror@paired-PR-head)`. Pass on set equality. (The mirror PR does NOT need to be merged first — that is the asymmetric core.)
   - If paired mirror PR `state: closed` AND `merged_at: null`: exit 1 with `paired mirror PR closed without merge; reopen or remove paired_pr_url`.
   - If paired mirror PR `state: closed` AND `merged_at: <ts>`: exit 1 with `paired mirror PR already merged but canonical still open — canonical-first invariant violated; the mirror PR landed before this canonical change`. (Catches reverse-order mistakes after the fact.)

2. **Mirror-side PR** (running in `platform-web`, mirror-side change):
   - With `paired_pr_url`: fetch paired canonical PR JSON.
   - If paired canonical PR `state: open` (any value of `merged_at`): exit 1 (BLOCKING, NOT advisory) with `merge_order_violation: canonical PR <owner>/<repo>#<num> must merge first; current canonical main lacks the new value-set`.
   - If paired canonical PR `state: closed` AND `merged_at: null`: exit 1 with `merge_order_violation: canonical PR closed without merge; remove paired_pr_url or reopen`.
   - If paired canonical PR `state: closed` AND `merged_at: <ts>`: fetch canonical `main` (post-merge), compare `set(canonical@main) == set(mirror@PR-head)`. Pass on set equality.

This asymmetry is the machine-enforced canonical-first guarantee:
- Canonical PR can merge anytime its head set-equals the paired mirror PR head.
- Mirror PR cannot merge until the paired canonical PR has merged AND its merge result is on canonical main.
- The reverse order (mirror-first merge) is BLOCKED at the mirror-side gate, not just warned about. Even if a reviewer attempts to force-merge the mirror PR, GitHub's required-check protection (I7) prevents it because the gate is exit 1 until the canonical PR is merged.

**Unpaired cross-repo enum mutation**: when an unpaired PR touches a canonical without a paired mirror PR (or vice versa), the gate stays red and the summary writes `pairing: unpaired - this PR mutates a guarded enum without a paired mirror PR; open the paired PR or add paired_pr_url`. The reviewer sees an actionable instruction, not a cryptic set diff.

### I7 — Required-check, NOT path-filtered; runs on every PR

Per the `platform-backend/.github/workflows/reporting-allowlist-drift.yml` precedent (Codex `019e2d64` S3 + REVISE rationale, verbatim quoted in the existing workflow):

> Deliberately NOT path-filtered: the script is milliseconds of work, and a path-filtered required check risks the GitHub "missing/pending" merge-block trap on unrelated PRs. Run it on every PR + main push.

The new gate workflow `gate-drift-cross-repo-enums.yml` (in `platform-k8s-gitops`) follows the same pattern:

```yaml
on:
  pull_request:      # every PR, no paths filter
  push:
    branches: [main]
  workflow_dispatch:  # ad-hoc + forced-drift smoke

concurrency:
  group: cross-repo-enum-drift-${{ github.ref }}
  cancel-in-progress: true
```

Each caller (`platform-backend/.github/workflows/contract-gate.yml`, `platform-web/.github/workflows/ci-web-check.yml`) adds the composite action step with `pull_request:` trigger and **no** paths filter. The 14-files-per-run cost (≤10 mappings × ~1.4 files/mapping) is well under any GitHub Actions cost or rate threshold.

### I8 — JSON artifact + Markdown step summary

Each run emits:
- `cross-repo-enum-drift-report.json` — machine-readable, uploaded as a CI artifact (`actions/upload-artifact@v7`, 7-day retention; matches `gate-drift-detection.yml:87-96` pattern). Fields (iter-3 absorbed iter-2 nice-to-have additions):
  ```json
  {
    "spec_path": "config/cross_repo_enum_drift_spec.yaml",
    "spec_schema_version": 1,
    "action_commit_sha": "<sha>",
    "own_repo_role": "canonical" | "mirror" | "spec-host",
    "pairing": "paired" | "unpaired-main",
    "paired_pr_url": "...",
    "reciprocal_pairing": true | false,
    "residual_main_drift_risk": true | false,
    "mappings": [
      {
        "id": "compliance-decision",
        "verdict": "PASS" | "FAIL" | "ERROR",
        "canonical": { "repo": "...", "path": "...", "ref": "...", "sha": "...", "strategy": "java_enum", "symbol": "...", "extracted": ["..."] },
        "mirrors": [
          {
            "repo": "...", "path": "...", "ref": "...", "sha": "...",
            "strategy": "ts_const_tuple", "symbol": "...",
            "extracted": ["..."],
            "missing_in_mirror": [],
            "missing_in_canonical": [],
            "duplicates": []
          }
        ]
      }
    ]
  }
  ```
- A Markdown table appended to `$GITHUB_STEP_SUMMARY` listing per-mapping verdict + per-mirror drift diff. The summary is what the PR reviewer reads in 5 seconds.

### I9 — Unit tests pin every parser strategy + spec-validation + paired-PR + error modes; fixtures derived from real shapes

`tests/drift_detection/test_check_drift_cross_repo_enums.py` exercises (each is a numbered case in the test):

**Parser positive cases** — fixture derived from real source shapes, not synthetic:
- `java_enum`: `ComplianceDecision` (4 values, simple); `DeviceStatus` (5 values); plus a hand-built fixture with trailing `;` followed by enum method bodies + `@Deprecated` on a value + inline `// comment`.
- `java_set_of`: `WDAC_MODE_ENUM` (single-line); `PROBE_ERROR_CODE_ENUM` (multi-line, one value per line); plus a hand-built fixture using `Set.<String>of(...)` cast form + trailing comma + multi-line broken across method-chain.
- `ts_const_tuple`: `PROHIBITED_DECISION_VALUES` (`as const`); `DEVICE_STATUS_VALUES` (`readonly` typed); plus a hand-built fixture with `as const satisfies readonly Foo[]` + single-quote + double-quote + trailing comma.
- `ts_union_type`: `DeviceStatus` (single-line); plus a hand-built fixture with the union broken across multiple lines.
- `java_grid_column_case_literals`: the actual `DeviceGridColumns.java:137` CASE; plus a hand-built fixture with a nested CASE → exit 2 (unparseable, NOT silent extraction).

**Parser negative cases** (must exit 1 with drift detected, NOT silently pass):
- Each strategy with one drifted value (added/removed in the mirror).
- Each strategy with one duplicate (value/extraction-level error per I2 — distinct from spec-level duplicates, which are tested in spec-validation cases below).

**Parser error cases** (must exit 2):
- `java_set_of` with unmatched quote in `Set.of("A, "B")` → parser refuses, exit 2.
- `java_grid_column_case_literals` with a nested CASE → exit 2.
- Empty extracted set from a syntactically-valid but semantically-empty enum → exit 2.

**Spec-validation cases** (must exit 2 before any fetch):
- Duplicate `mapping.id`.
- Unknown `kind`.
- Missing `symbol` or `path`.
- Zero mirrors.
- `java_grid_column_case_literals` without `anchor`.

**Network error cases** (must exit 2, NOT silently pass as drift-free):
- `gh api` 403 → exit 2 with auth-insufficient message.
- `gh api` 404 → exit 2 with file-not-found message (distinct from 403).
- `gh api` 200 with empty body → exit 2 with empty-file message.

**Paired-PR cases**:
- PR body contains `paired_pr_url:` → mirror ref resolves to paired PR's head SHA.
- PR body does NOT contain `paired_pr_url:` AND canonical extracted set ≠ mirror main extracted set → exit 1 with `pairing: unpaired - open paired PR` message.
- PR body contains `paired_pr_url:` pointing to a paired canonical PR with `state: open` AND running PR is the mirror side → blocking exit 1 with `merge_order_violation: canonical PR must merge first` (iter-3 axis 3 must-fix: NOT advisory).
- PR body contains `paired_pr_url:` pointing to a closed-unmerged PR → blocking exit 1 with `merge_order_violation: paired PR closed without merge`.
- PR body contains `paired_pr_url:` pointing to a paired canonical PR with `merged_at: <ts>` AND `set(canonical@main) == set(mirror@PR-head)` → mirror-side PR passes (canonical-first invariant satisfied).

Fixtures live under `tests/drift_detection/fixtures/cross_repo_enums/` mirroring the existing `fixtures/` directory structure.

### I10 — Phase 2 promotion is an active (not deferred) parallel track

Codex iter-1 axis 7 must-fix: the iter-1 "~15 mappings" threshold for Phase 2 was set too high; the corrected v1 inventory is already at 10 mappings (and includes the SQL-CASE strategy). The Phase 2 spike track opens **at DD-5-1 closure**, not 60 days later. Triggers (any one is sufficient):

- ≥8 guarded mappings AND ≥3 parser strategies (we cross both at v1 closure).
- A mapping bound to a third repo (e.g., `platform-agent` as a consumer of the same enum — already referenced in the iter-1 review and visible in `endpoint-app-control/types.ts:8-10` header comment which names `platform-agent internal/inventory/app_control.go` as the upstream source of `WdacMode`).
- The same `canonical` mutated twice within 90 days.
- Paired-PR friction (count of `merge_order_violation` warnings) exceeds 3 per quarter.

The Phase 2 ADR (separate from this one) decides between:
- **Option α**: JSON Schema in `schema/cross-repo-enums.v1.schema.json`, generated `*.java` and `*.ts` outputs.
- **Option β**: OpenAPI fragment of just the enums section, codegen via `openapi-generator-maven-plugin` (Java) + `openapi-typescript` (TS).
- **Option γ**: Continue with the regex-based v1 guard indefinitely if the inventory plateaus.

The decision criterion is documented in this ADR's § 5 closure follow-up; the Phase 2 ADR is opened by the same DD-5-1 PR (as a placeholder issue/draft ADR) so the track stays visible.

## 3. Consequences

### 3.1 Positive

- The 2026-06-02 live drift class (a canonical-side enum addition silently missing in any mirror) cannot recur. A PR that adds a value to a guarded canonical without a paired mirror PR is red in its own CI.
- The YAML spec is the **audit register** of every cross-repo enum bond — 10 entries at v1, expandable to 15-20 without changing the script.
- Extends ADR-0011 §2.1 (drift detection axis A) without inventing a new governance frame.
- No build-pipeline coupling: no npm publish, no Maven plugin, no submodule, no codegen. Fail mode is "CI red," not "Maven build broken" or "pnpm install fails."
- Composite action SHA-pinning keeps the canonical script in one place AND prevents silent action behavior drift in caller repos.
- Required-check-without-path-filter avoids the GitHub "missing/pending" merge-block trap (per existing `reporting-allowlist-drift.yml` precedent).
- Paired-PR protocol lets cross-repo enum mutations land without deadlock and with explicit canonical-first merge ordering — the workflow becomes "one PR each side, paired by URL, canonical-first merge."

### 3.2 Negative / Trade-offs

- **Regex/lexical-scanner parsing is brittle to source shape evolution**. The iter-2 I9 fixture matrix pins the known shapes; any new shape requires a new strategy (I5) with its own tests. Honest naming: the parsers are "small lexical scanners with targeted extractors" — not arbitrary Java/TS parsers. Phase 2 promotion (JSON Schema codegen, I10) is the deferred escape valve when shape evolution outpaces the strategy registry.
- **Composite action SHA pinning requires explicit bump PRs**. The cost is ~5 minutes per interface change × 2 callers (platform-backend, platform-web). Mitigation: rare changes; hygiene check is quarterly.
- **Paired-PR protocol requires reviewer discipline** (the PR description must include the fenced `paired_pr_url:` block). When a reviewer misses this, the unpaired-mutation message is the reviewer cue; the gate is itself self-explaining.
- **`prohibited_status` SQL-CASE strategy is narrowest of the five** and could fail unpredictably if `DeviceGridColumns.java:137` is refactored to a Java enum (which would be the right long-term move). In that case the mapping flips strategy from `java_grid_column_case_literals` to `java_enum` — a YAML edit, not a script change.
- **Phase 2 promotion (I10) opens at DD-5-1 closure**, not after a 60-day observation window. This is faster but the v1 surface is large enough that the trigger is already active; deferring the spike risks the registry growing into 15 entries before the codegen path is even drafted.

### 3.3 Explicit out-of-scope (v1) and closure-blocker exception

- **Intra-backend duplication of `SERVICE_STATE_ENUM` / `STARTUP_MODE_ENUM` between `EndpointServiceWireEnums` (canonical) and `ServicesPayloadPolicy` (private duplicate)** — iter-2 Codex axis 6 must-fix: this is NOT out of closure scope. The duplication leaves canonical-of-canonical ambiguity: the cross-repo guard would pass `set(EndpointServiceWireEnums.SERVICE_STATE_ENUM) == set(StartupMode)` while `ServicesPayloadPolicy.SERVICE_STATE_ENUM` silently drifts to a different set, and the wire-policy validator using `ServicesPayloadPolicy` would then enforce a different surface than the guarded one. DD-5-4 is therefore the **ADR-0031 closure blocker** for intra-backend dedup (see § 5 PR sequence and § 6 closure criteria; renamed from the iter-2-era working name `DD-5-followup-A`). The fix is: `ServicesPayloadPolicy` deletes its private `SERVICE_STATE_ENUM` / `STARTUP_MODE_ENUM` and references `EndpointServiceWireEnums.SERVICE_STATE_ENUM` / `EndpointServiceWireEnums.STARTUP_MODE_ENUM` directly — completing the migration that `EndpointServiceWireEnums.java:6-9` JavaDoc declared as intent.
- **`mirror_extra_allowed` (frontend-only sentinel values)** — Codex iter-1 axis 8 nice-to-have. Rejected for v1: a frontend-only sentinel mixed into a backend-enum mirror IS the failure mode this ADR catches; the right separation is a distinct UI-local type (`type FrontendOnlyExtras = 'LOADING' | 'ERROR'`) that does NOT mirror a backend enum. A v2 amendment may introduce `mirror_extra_allowed` with per-mapping rationale + UI-only-value-never-on-wire test fixture; v1 holds the hard line.
- **DTO field-shape drift** (renaming a backend field, changing nullability). Out of scope for an enum/value-set guard; an OpenAPI-driven DTO mirror is a separate Phase 2-ish initiative.
- **Behavior drift** — same value on both sides, different semantics. Architectural review territory, not regex parsers.

## 4. Rejected alternatives

| Alternative | Reason rejected |
|---|---|
| **A. Generated TS enum (Maven build → npm publish → `@platform/backend-enums` dependency in platform-web)** | Build-pipeline coupling: cross-repo PR ordering becomes "backend release → npm publish → web update," a 3-step manual handoff per change. Maven plugin authorship + GHCR npm registry setup + version-bump discipline is medium-high upfront cost. v1 hold-line; this is Phase 2 Option α/β if inventory growth justifies it. |
| **B. Backend contract test fetching frontend** | Backend integration tests would depend on `platform-web` repo state. PR ordering becomes the problem ("backend test red because web hasn't merged the mirror update yet"). The fail surface is wrong: the contract violation is symmetric, but the test fires asymmetrically. |
| **C. Shared OpenAPI / JSON Schema with codegen** | This IS Phase 2 above, not an alternative — same goal at a different point on the cost curve. v1 is minimum-viable enforcement; Phase 2 promotes the canonical when the inventory justifies it. Per I10 the spike track is open from DD-5-1 closure. |
| **D. Pure cross-repo CI matrix (no shared script — each repo writes its own diff)** | Each repo would duplicate parser logic; drift between the parsers becomes its own bug class. The composite action in I4 is "D done right" — central script, SHA-pinned consumption from each caller. |
| **E. No automation, document the mirror in code comments and rely on PR review** | This is the status quo. The header comment in `endpoint-device/types.ts:1-11` and `endpoint-app-control/types.ts:6-11` already names the backend source path. Review discipline failed to catch the 2026-06-02 drift. Documentation without enforcement is the failure mode this ADR is replacing. |
| **F. Bundle DD-5-4 (introducing a new `APP_ID_SVC_STATE_ENUM` backend constant) into the v1 PR sequence** | iter-1 proposed this; iter-1 Codex review rejected it as wrong on three counts: (a) the canonical already exists (`EndpointServiceWireEnums.SERVICE_STATE_ENUM`), (b) introducing a new constant would create a second canonical and inverts the guard's purpose, (c) backend behavior change should not be bundled into a governance ADR closure. iter-2 binds mapping #6 to the existing `SERVICE_STATE_ENUM` and removes DD-5-4. |

## 5. PR sequence (drives this ADR forward)

| # | Class | Scope | Authority |
|---|---|---|---|
| **DD-5-0** (this PR) | governance docs | ADR-0031 iter-4 + Codex cross-AI consensus iter | Codex consensus only |
| DD-5-1 | A (governance) | `scripts/drift_detection/check_drift_cross_repo_enums.py` + `lib/{java_enum_parser,java_set_of_parser,ts_tuple_parser,ts_union_parser,grid_column_case_parser}.py` + `config/cross_repo_enum_drift_spec.yaml` (10 v1 mappings) + `config/cross_repo_enum_drift_spec.schema.json` + `tests/drift_detection/test_check_drift_cross_repo_enums.py` + fixtures (real-shape derived per I9) + `gate-drift-cross-repo-enums.yml` workflow (NOT path-filtered) + `.github/actions/check-cross-repo-enum-drift/action.yml` composite action (resolves via `$GITHUB_ACTION_PATH`); ALSO opens Phase 2 placeholder issue (I10 spike track) | Codex consensus |
| DD-5-2 | A (governance) | `platform-backend/.github/workflows/contract-gate.yml` adds the composite-action step, pinned to DD-5-1 merge SHA, with `cross_repo_contract_read_token: ${{ secrets.CROSS_REPO_CONTRACT_READ_TOKEN }}` input (no `github.token` fallback; token scope `Contents:Read` + `Pull requests:Read` + `Metadata:Read` per I3) | Codex consensus |
| DD-5-3 | A (governance) | `platform-web/.github/workflows/ci-web-check.yml` adds the composite-action step, symmetric to DD-5-2 | Codex consensus |
| **DD-5-4** (ADR-0031 closure blocker, was DD-5-followup-A) | source/governance cleanup | `ServicesPayloadPolicy.java:91-95` removes the private `SERVICE_STATE_ENUM` / `STARTUP_MODE_ENUM` constants and binds them to `EndpointServiceWireEnums.SERVICE_STATE_ENUM` / `EndpointServiceWireEnums.STARTUP_MODE_ENUM` directly — completing the migration declared as intent by `EndpointServiceWireEnums.java:6-9` JavaDoc. Removes the canonical-of-canonical ambiguity flagged in § 3.3. Backend unit test verifies the wire policy still accepts the same value set | Codex consensus |

All four DD-5-1..DD-5-4 implementation PRs are within the "none of the above (Codex consensus only)" class of ADR-0011 §2.3.2 (governance + CI script + caller wiring + source-code dedup of an intra-backend duplicate constant whose value set is unchanged — no credential-read, no credential-write, no prod state-mutation, no user-communication). The composite action publishing under `Halildeu/platform-k8s-gitops/.github/actions/...` is a public-action-surface change; documented in the PR body but does not require operator approval per ADR-0011 §2.3.1.

DD-5-4 is a closure blocker (iter-2 axis 6 must-fix): leaving `ServicesPayloadPolicy` with a private duplicate would leave the canonical-of-canonical ambiguity outlasting the guard's lifetime, defeating the long-term-durable-solution rule (HARD RULE "Uzun Vadeli Kalıcı Çözüm").

## 6. Closure criteria (when ADR-0031 governance complete)

- DD-5-1..DD-5-4 all merged with cross-AI AGREE (DD-5-4 is the iter-2 closure-blocker promotion — see § 5).
- **Forced-drift smoke** (workflow_dispatch on local fixture): a deliberately drifted `compliance-decision` fixture (adds `'NEW_VALUE'` to canonical, mirror unchanged) turns the gate red with the correct per-mirror diff. Mirror-side block path is exercised via a fixture pair simulating paired-PR state (canonical PR not-yet-merged) — the gate must exit 1 with `merge_order_violation`.
- **No-drift real-source smoke** (iter-2 nice-to-have): a workflow_dispatch run against the actual 10 v1 mappings on `main` passes green and the report JSON records `verdict: PASS` for every mapping — proves the parsers handle the production source shapes.
- 60 days of no recurring `set(canonical) ≠ set(mirror)` live incident in the ten guarded mappings.
- Phase 2 spike issue (I10) opened at DD-5-1 merge; Phase 2 ADR drafted within 90 days of DD-5-1 merge OR explicit deferral decision recorded (Option γ).
- DD-5-4 (intra-backend `ServicesPayloadPolicy` dedup) merged before ADR-0031 closure — NOT a 30-day-after follow-up; the canonical-of-canonical ambiguity does not outlast the guard's introduction.

## 7. Cross-AI Trace

```yaml
implementer_ai: Claude
reviewer_ai: Codex
codex_thread: 019e8832-9c9c-7cc3-89b0-62be4bef43cb
iter_1:
  verdict: REVISE
  key_findings:
    - "factual inventory mismatch (iter-1 listed 4 mappings; real surface is 10)"
    - "EndpointServiceWireEnums.SERVICE_STATE_ENUM exists; iter-1 proposed creating a duplicate"
    - "ci-web-check.yml, not ci.yml"
    - "@main composite action pinning is wrong; SHA-pin + explicit bump PR required"
    - "PR-ordering deadlock unsolved; paired-PR protocol must be in v1"
    - "GITHUB_TOKEN-first / PAT-fallback cascade rejected; require explicit token from day 1"
    - "prohibited_status SQL CASE must be in v1, narrow strategy ok"
    - "path-filtered required check is a trap; precedent reporting-allowlist-drift.yml is canonical"
    - "spec-schema validation required (duplicate id, unknown kind, etc.)"
    - "I1/I5 contradiction on ts_union_type — resolve in iter-2"
    - "Phase 2 trigger ~15 too high; v1 already at 10"
iter_2:
  verdict: REVISE
  narrow_blockers:
    - "axis 3: merge_order_violation must be machine-enforced hard block (not advisory) on mirror-side PR; asymmetric semantic — canonical-side passes on set-equal heads, mirror-side requires paired canonical merged_at != null"
    - "axis 4: token scope expanded to contents:read + pull-requests:read (iter-2 paired-PR protocol reads pulls/<num>); renamed CROSS_REPO_CONTRACT_READ_TOKEN; 403 disambiguated per endpoint (contents vs pulls)"
    - "axis 6: DD-5-followup-A cannot be entirely out of closure scope; promoted to ADR-0031 closure blocker (DD-5-4) OR alternative path absorbing ServicesPayloadPolicy private constants into DD-5-1 guard. iter-3 takes path A (closure blocker) per HARD RULE Uzun Vadeli Kalıcı Çözüm"
    - "global factual: endpoint-services/types.ts exports StartupMode (not ServiceStartupMode); endpoint-app-control/types.ts exports ServiceStartupMode — distinct symbols, same value-set"
    - "iter-2 status line said 6 axes but iter-1 covered 8 axes — cross-AI trace factual cleanup"
  nice_to_have_accepted:
    - "fetch cache layer dedupes (repo, path, ref) lookups in I3"
    - "I9 duplicate case wording: not spec-level, value-level"
    - "Per-mapping own_repo_role: canonical|mirror|spec-host + reciprocal_pairing in report"
    - "Paired_pr_url grammar: exactly one line per block; multiple → exit 2"
    - "Action summary writes action_commit_sha + spec_schema_version"
    - "No-drift real-source fixture run as additional closure evidence"

iter_3:
  verdict: REVISE
  narrow_blockers:
    - "axis 8: mathematical bug — I2 + final decision rule used set(canonical) ≠ ⋃ set(mirror_i); union can hide a stale mirror (e.g., canonical {A,B,C,D}, mirror_1 {A,B,C,D}, mirror_2 stale {A,B,C} — union equals canonical, falsely passes). Replace with per-mirror equality: ∀ mirror_j: set(canonical) == set(mirror_j)."
    - "axis 4: DD-5-2 still showed old `cross_repo_contents_token: ${{ secrets.CROSS_REPO_CONTENTS_TOKEN }}` in §5 PR sequence table even though I3 was updated. Rename to cross_repo_contract_read_token + CROSS_REPO_CONTRACT_READ_TOKEN."
    - "axis 6: §1.2 and §1.3 still had stale 'out-of-scope' language for ServicesPayloadPolicy dedup, contradicting §3.3/§5/§6 which were updated to closure-blocking."
    - "I9 paired-PR test case still said 'merge_order_violation advisory' even though I6 was updated to blocking. Make blocking exit 1."
    - "cosmetic: 'Four parser strategies' but listed five; iter labels in §5/§7 stale (iter-2 → should be iter-4); ServiceState in endpoint-services/types.ts at line 37 not 40."
  nice_to_have_accepted:
    - "I9 duplicate semantic clarified: value/extraction-level (per I2), NOT spec-level (per I5)"
    - "Fork PR limitation note (fine-grained PAT secrets unavailable on fork PRs) — TODO add in I3"

iter_4:
  verdict: pending
  changes_from_iter_3:
    - "I2 rewritten: per-mirror equality (logical AND across mirrors), NOT mirror-union; example failure mode documented; duplicates clarified as value/extraction-level (NOT spec-level)"
    - "Final decision rule rewritten: ∀ mirror_j: set(canonical) == set(mirror_j); mirror_union explicitly NOT determining pass/fail"
    - "DD-5-2 token input + secret name corrected to cross_repo_contract_read_token + CROSS_REPO_CONTRACT_READ_TOKEN (was stale cross_repo_contents_token)"
    - "§1.2 + §1.3 stale 'out-of-scope' language for ServicesPayloadPolicy removed; §1.2 reframed as 'Closure-blocking cleanup discovered by this ADR'; §1.3 reframed as 'guard mechanism does not enforce intra-backend duplication; DD-5-4 removes the duplicate'"
    - "I9 paired-PR test case updated to blocking exit 1 (was 'advisory'); added closed-unmerged and merged_at cases"
    - "I1: 'Five parser strategies' (was Four)"
    - "I9: duplicate test case wording updated to 'value/extraction-level'"
    - "Status line + §5 DD-5-0 + §7 plan-consensus block: iter labels updated to iter-4"
    - "Frontend references: ServiceState at endpoint-services/types.ts:37 (was :40)"
    - "DD-5-4 class: 'source/governance cleanup' (was 'A (governance) + state-mutation (test)')"
    - "§5 phrase: 'DD-5-1..DD-5-4 implementation PRs' (was 'All four DD-5-N PRs')"
    - "changes_from_iter_1 trace: iter-3 supersession note added (DD-5-followup-A → DD-5-4 closure-blocking)"

changes_from_iter_1:
    - "(iter-3 supersession note: 'DD-5-followup-A OUT of closure scope' was reversed in iter-3; the iter-2 axis 6 must-fix promoted it to ADR-0031 closure-blocking as DD-5-4.)"
    - "inventory expanded to 10 mappings with multi-mirror per mapping support"
    - "DD-5-4 (new APP_ID_SVC_STATE_ENUM constant) REMOVED; mapping #6 binds to existing EndpointServiceWireEnums.SERVICE_STATE_ENUM"
    - "DD-5-followup-A added for intra-backend dedup, OUT of ADR-0031 closure scope"
    - "I3 token policy: explicit token from day 1, no fallback cascade, 403/404 disambiguated"
    - "I4 composite action SHA-pinned in callers; bump PR required per interface change"
    - "I5 + new I9 spec schema validation + extensive fixture matrix"
    - "I6 paired-PR protocol with canonical-first merge invariant"
    - "I7 NOT path-filtered (per reporting-allowlist-drift.yml precedent, verbatim quoted)"
    - "I10 Phase 2 active-not-deferred parallel track"
    - "ts_union_type adopted in v1 (resolves iter-1 I1/I5 contradiction)"
    - "java_grid_column_case_literals strategy adopted in v1 (resolves iter-1 §3.3 deferral)"
    - "workflow filename corrected to ci-web-check.yml"
plan_consensus_autonomy: |
  Per HARD RULE Plan Consensus Autonomy: a Codex iter-4 AGREE triggers DD-5-1..DD-5-4
  implementation directly (no separate user-approval step). REVISE → absorb + iter-5.
  RED → user.
```

## 8. References

- ADR-0011 — Plan-Time Drift Detection + Audit Cadence + Boundary Governance (parent §2.1 frame, §2.3 boundary taxonomy)
- ADR-0014 — MFE Auth Transport Contract (cross-repo contract ADR precedent — Decision Invariants + Implementation Map)
- ADR-0020 — Schema Capability Truth-Tier Model (§2.4 defer-rename pattern for v1/v2 split)
- `~/.claude/CLAUDE.md` HARD RULE "Uzun Vadeli Kalıcı Çözüm" — drift guards must be machine-enforced + adversarial-review-pass at 6 months
- `~/.claude/CLAUDE.md` HARD RULE "Cross-AI Peer Review" — implementer Claude → reviewer Codex (provider-level)
- 2026-06-02 live drift incident — `ComplianceDecision.UNKNOWN` missing from `PROHIBITED_DECISION_VALUES`; fast-follow PR #736 (platform-web); Codex review thread `019e8820`
- Existing drift-detection infrastructure: `platform-k8s-gitops/scripts/drift_detection/check_drift_anchor_table.py`, `tests/drift_detection/test_check_drift_anchor_table.py`, `.github/workflows/gate-drift-detection.yml`
- Required-check-NOT-path-filtered precedent: `platform-backend/.github/workflows/reporting-allowlist-drift.yml` (Codex `019e2d64` S3 + REVISE rationale)
- Cross-repo PAT scope precedent: memory `project_pr1085_pat_missing_fallback` (Codex threads `019e8079` + `019e809d` — PR #1163 + PR #1166)
- Source-of-truth header comment convention: `platform-web/apps/mfe-endpoint-admin/src/entities/endpoint-device/types.ts:1-11`, `endpoint-app-control/types.ts:6-30`
- Backend canonical files (paths exhaustive for v1):
  - `endpoint-admin-service/src/main/java/com/example/endpointadmin/model/ComplianceDecision.java`
  - `endpoint-admin-service/src/main/java/com/example/endpointadmin/model/DeviceStatus.java`
  - `endpoint-admin-service/src/main/java/com/example/endpointadmin/model/OsType.java`
  - `endpoint-admin-service/src/main/java/com/example/endpointadmin/security/AppControlPayloadPolicy.java` (lines 93, 98, 103, 115)
  - `endpoint-admin-service/src/main/java/com/example/endpointadmin/security/EndpointServiceWireEnums.java` (lines 27, 32)
  - `endpoint-admin-service/src/main/java/com/example/endpointadmin/grid/DeviceGridColumns.java:137` (SQL CASE)
- Frontend mirror files (paths exhaustive for v1):
  - `apps/mfe-endpoint-admin/src/pages/devices/EndpointDevicesPage.tsx` (lines 60-103)
  - `apps/mfe-endpoint-admin/src/entities/endpoint-device/types.ts` (DeviceStatus, OsType — both union + tuple at 13/47, 15/55)
  - `apps/mfe-endpoint-admin/src/entities/endpoint-app-control/types.ts` (WdacMode at 33, AppLockerEnforcementMode at 36, ServiceState at 42, ServiceStartupMode at 49, AppControlProbeErrorCode at 62-70, AppControlProbeErrorSource at 76)
  - `apps/mfe-endpoint-admin/src/entities/endpoint-services/types.ts` (ServiceState at 37 — distinct file from app-control but same symbol; StartupMode at 47 — note: **different identifier** from app-control's `ServiceStartupMode`, same value-set)

---

**Decision rule (one sentence)**: For every mapping in `config/cross_repo_enum_drift_spec.yaml`, `set(backend canonical enum) ≠ set(frontend mirror_j)` for **any** mirror_j in `mirrors[]` (per-mirror equality, NOT mirror-union equality — iter-3 axis 8 fix) is a CI-red gate on every PR in `platform-backend`, `platform-web`, and `platform-k8s-gitops`; enforcement is a single Python script + declarative YAML spec + JSON-Schema spec validator hosted in `platform-k8s-gitops` and invoked via a SHA-pinned reusable composite action; cross-repo PR coordination is via an explicit paired-PR URL block in the PR description with machine-enforced asymmetric canonical-first merge ordering (mirror-side PR blocks until paired canonical PR merged); the gate is required-check-not-path-filtered to avoid the GitHub merge-block trap; intra-backend `ServicesPayloadPolicy` dedup (DD-5-4) is a closure blocker so the canonical-of-canonical ambiguity does not outlast the guard's introduction.
