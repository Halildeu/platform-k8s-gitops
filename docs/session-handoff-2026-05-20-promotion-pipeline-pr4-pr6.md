# Session Handoff — 2026-05-20 (Late Afternoon) — Promotion Pipeline PR-4 + PR-6 Landed; PR-7 Plan Ready

> **Format**: D28 5-alan + sıradaki agent P0 aksiyon listesi.
> **Önceki handoff**: `docs/session-handoff-2026-05-20-promotion-pipeline-progress.md` (PR-2 + PR-5 + P0-c/d/e + PR-8 omission correction Update).
> **Tetikleyici**: HARD RULE — Session Otomatik Açma #4 (pre-completion natural break — 3 PR merged + PR-7 scope handoff'a alındı).

## 1. Bağlam (bu oturumda ne yapıldı)

Kullanıcı "hand off" + "tam otonom devam edelim" + "kalan işleri önerdiğin sıra ile tamamla" yönergesi verdi. Promotion-pipeline guardrail train'inde 3 PR landed; PR-7 plan-time Codex iter-1 + iter-2 chain'ini tamamladı ama scope büyüdü → handoff'a alındı.

### Initiative dağılımı

1. **Handoff doc PR-8 omission correction** (#893) — Önceki handoff doc'un §2/§5 PR-8'i içermiyordu (PR-8 merge zamanı doc'tan önceydi ama doc autorize ederken PR-8 listelenmemişti). Codex iter-1 REVISE (temporal/honesty/provenance) → iter-2 AGREE. MERGED.
2. **Guardrail PR-4** (#895) — `check_env_drift.sh` test+prod overlay/live drift gate. Codex 3 iter chain (12+ must_fix absorbed: ArgoCD context split, 5-state machine, exit precedence, NotFound regex narrowing, runtime selector, evidence strictness). MERGED.
3. **Guardrail PR-6** (#896) — Runtime artifact ledger schema + validator + CI gate + 8 fixtures. Codex 3 iter chain (12 must_fix absorbed: canonical digest algorithm, env-scoped store_ref, pending nullability, evidence required conditionals, runtime_selector oneOf, approval pathway guards). MERGED.
4. **Guardrail PR-7 plan** — Codex 019e44eb iter-1 REVISE (7 P0/P1) → iter-2 REVISE (7 yeni must_fix). Plan çok büyüdü (image predicate fix + active pointer schema + backfill chain + manifest detection + target revision render). Codex ready_for_handoff_to_next_session: **true**. Impl sonraki session'da daha temiz akar.

## 2. İddia (bu session'da MERGED PR'lar — hepsi `platform-k8s-gitops`)

| PR | Başlık | Merge commit | Codex thread |
|---|---|---|---|
| #893 | docs(handoff): PR-8 omission correction on 2026-05-20 promotion-pipeline progress doc | `b46cfad` | `019e44ad` |
| #895 | feat(drift-detection): Guardrail PR-4 — check_env_drift.sh + live-runtime CI gate (ADR-0023) | `d250914` | `019e44b9` + `019e44c8` |
| #896 | feat(promotion): Guardrail PR-6 — runtime-artifact ledger schema + validator (ADR-0023) | `<pr-6-merge-sha>` | `019e44d9` |

Detay:

- **#893** — Handoff doc'un §2 (İddia) PR-8'i içermiyordu + §5 PR-8'i "yapılmadı/öneri #1" listelemişti. Update bölümü eklendi: `git merge-base --is-ancestor ac5a3b2 da9128a` ile PR-8'in handoff'tan **önce** merge olduğu kanıtlandı. Codex thread `019e44ad` iter-1 REVISE (3 blocking: temporal wrong, thread id wrong, line count) → iter-2 AGREE.

- **#895** — `git mv check_prod_drift.sh check_env_drift.sh`; +422-line script (5-state ArgoCD machine, env-bazlı severity, hub context split, exit precedence fix); +72-line CI workflow (self-hosted staging-sw runtime gate, schedule + dispatch); 11 operator-facing caller renames; 17-line deprecation stub. Codex thread `019e44b9` plan-time iter-1 REVISE (6 must_fix) → iter-2 REVISE (2 must_fix) → iter-3 AGREE; post-impl `019e44c8` iter-1 REVISE (2 must_fix) → iter-2 must_fix (NotFound regex narrowing) → iter-3 AGREE ready_to_merge:true. CI 11/11 PASS.

- **#896** — 240-line schema (Draft 2020-12 + conditional allOf for pending/verified/promoted + emergency-bypass/historical-backfill guards); 164-line README (RFC 8785 canonical digest algorithm normative); 256-line validator (jsonschema + path↔content + per-kind format hooks + fixture-mode bypass); 106-line CI workflow (3 jobs: PR diff + main full + 8-fixture matrix). Codex thread `019e44d9` iter-1 REVISE (6 must_fix: OpenFGA identity, Vault semantics, backfill honesty, evidence loose, schema mismatch, promotion timestamps, CI parity) → iter-2 REVISE (6 must_fix: canonical digest algo, env store_ref, pending nullability, evidence required, runtime_selector oneOf, approval guards) → iter-3 AGREE ready_for_impl:true → post-impl AGREE ready_to_merge:true. CI 17/17 PASS.

## 3. İspatlar

### CI evidence (each PR)
- #893: 11/11 pass + CLEAN MERGEABLE → squashed
- #895: 11/11 pass (after update-branch + re-CI) + CLEAN MERGEABLE → squashed
- #896: 17/17 pass (extra: 8-fixture matrix + Validate runtime-artifact ledger PR diff + Validate runtime-artifact ledger main full scan skipping intentional)

### Local validator smoke (PR-6)
8/8 fixture classify correctly:
```
OK  invalid-bad-digest.json           (rc=1 expected=1)
OK  invalid-bad-ulid.json              (rc=1 expected=1)
OK  invalid-emergency-bypass-no-justification.json (rc=1 expected=1)
OK  invalid-historical-backfill-no-imported-at.json (rc=1 expected=1)
OK  invalid-loose-evidence.json        (rc=1 expected=1)
OK  invalid-missing-required.json     (rc=1 expected=1)
OK  invalid-pending-with-evidence.json (rc=1 expected=1)
OK  valid-openfga-model.json           (rc=0 expected=0)
```

### Cross-AI peer review chains (HARD RULE)
- #893: implementer=claude, reviewer=codex(019e44ad), AGREE
- #895: implementer=claude, reviewer=codex(019e44b9 plan + 019e44c8 post-impl), both AGREE
- #896: implementer=claude, reviewer=codex(019e44d9 plan + post-impl), AGREE

### Forensic archive tags
- archive/2026/05/docs-promotion-pipeline-pr8-followup-pr893
- archive/2026/05/feat-guardrail-pr4-env-drift-gate-pr895
- archive/2026/05/feat-guardrail-pr6-runtime-artifact-ledger-pr896

## 4. İspatlamaz (bu session'da kanıtlanamayan)

- **PR-7 impl** — plan-time Codex chain devam ediyor, scope büyüdü. ready_for_handoff_to_next_session:true. Detaylı plan §5 altında.
- **Operator action — cluster-add** — `argocd cluster add k3d-test --name test-cluster --upsert --yes` (RB-argocd-register-test-cluster.md Step 2) henüz koşulmadı. PR-3 bu adıma bağlı.
- **Frontend reports MFE auth race** — önceki spawn_task chip (`PermissionProvider AuthNotReadyError`). Platform-web sprint'i ayrı.
- **P0-c OpenFGA model historical backfill** — PR-6 schema'sını kullanan ilk ledger entry. PR-7-pre-A scope'unda; PR-7 ön-koşulu.

## 5. Bilinen Boşluk + Sıradaki Agent P0 Aksiyon Listesi

### Geçerli sıralama (sonraki session için)

| # | İş | Engelleyen | Effort | Notlar |
|---|---|---|---|---|
| 1 | **PR-7-pre-A** runtime active pointer + OpenFGA historical-backfill ledger | bağımsız | M | Detaylı plan aşağıda |
| 2 | **PR-7-pre-B** image ledger D29 evidence backfill (mevcut prod-render image'lar için) | bağımsız | S-M | release-candidates altındaki entries D29 GREEN check |
| 3 | **PR-7 strict gate** `check_artifact_dependencies.py` + `deploy-prod-gitops.yml` preflight wire-up | PR-7-pre-A + PR-7-pre-B | L | Detaylı plan aşağıda |
| 4 | **Operator cluster-add** (concurrent with PR-7 work) | — | XS | `argocd cluster add k3d-test --name test-cluster --upsert --yes` |
| 5 | **PR-3** test deploy workflow'ları → GitOps PR (no kubectl set image) | Operator cluster-add (#4) | L | deploy-backend-testai.yml + deploy-testai.yml ad-hoc paths kaldırılır |

### PR-7 Plan Detayı (Codex 019e44eb iter-2 absorbed must_fix MF-1 → MF-14)

#### Files to create

| Path | Purpose |
|---|---|
| `schema/runtime-active-pointer-v1.schema.json` | Active pointer schema (`environment + runtime_artifacts[]` array, content_digest + selector + ledger_path required, runtime_selector oneOf vault/openfga-store-direct, NO null selector) |
| `runtime-artifacts/_active/test.json` + `_active/prod.json` | Active pointer files; OpenFGA `kv/platform/openfga#model_id` selector required if prod render uses that ExternalSecret remoteRef |
| `scripts/promotion/validate-runtime-active-pointer.py` | Pointer schema validator + cross-checks: filename ↔ environment match, ledger_path file exists, ledger entry's artifact_content_digest matches pointer's |
| `scripts/promotion/check_artifact_dependencies.py` | The actual PR-7 preflight script (image resolver + runtime resolver classes, target-revision render handling, fail-closed) |
| `.github/workflows/gate-artifact-dependencies.yml` | PR-time validate (pointer schema + ledger consistency) + fixture matrix |
| `tests/promotion/fixtures/check-artifact-deps/*.{yaml,json}` | 11+ fixtures covering image-pre-deploy semantics, runtime test-bypass detection, target-revision mismatch, jwt-validates AMBER policy edge, third-party ignore |
| `deploy-prod-gitops.yml` preflight job EDIT | Add artifact preflight step BEFORE production environment approval gate |

#### Image pre-deploy predicate (MF-8 absorbed — Codex finding)

Mevcut `promotion-ledger-v1.schema.json` semantics reuse:
- Image ledger entry exists at `release-candidates/<repo>/<git_sha>.json` (filename = git_sha, NOT digest — Codex MF-9)
- Lookup by digest via `gate-evidence-check.py::find_ledger_entries_by_digest()` (existing function)
- `image.path` matches render's `ghcr.io/<path>`
- `image.digest` matches render's `image@sha256:<digest>`
- `promotion.test.promoted_at` non-null AND `promotion.test.verified_at` non-null (test was deployed somewhere and verified)
- `promotion.test.smoke_evidence`:
  - `d29_up.status == GREEN`
  - `d29_functional.status == GREEN`
  - `d29_zanzibar.status`: per `services.yaml` policy — if `jwt_validates: true` GREEN required; if `jwt_validates: false` (e.g. frontend per ADR-0022) GREEN **or** AMBER acceptable
- **NO** check for `promotion.prod.*` fields (those are post-deploy closure, not pre-deploy gate)
- `d29_secured` does NOT exist in schema — `d29_up.details` collapses Secured tier per `d29-smoke-runner.sh`

#### Runtime artifact pre-deploy predicate (MF-10 absorbed)

For each detected runtime dependency:
- `promotion.test.status in [verified, promoted]` AND `promotion.test.evidence_completeness == "complete"`
- `promotion.prod.status == "promoted"` AND `promotion.prod.evidence_completeness == "complete"`
- Both test and prod `evidence` non-null
- Ledger's `artifact_content_digest` matches pointer's entry digest

(Test verification check is critical: PR-7's actual failure mode is test-bypass, not just prod-missing.)

#### Manifest dependency detection (MF-3 absorbed)

Parse prod render YAML for ExternalSecret references:
```python
for resource in render.iter_yaml():
    if resource.kind == "ExternalSecret":
        for data_entry in resource.spec.data:
            remote = data_entry.remoteRef
            if remote.key == "kv/platform/openfga" and remote.property == "model_id":
                runtime_deps.append(("openfga-model", "kv/platform/openfga#model_id"))
```

If `runtime_deps` non-empty:
- `runtime-artifacts/_active/prod.json` MUST exist
- Pointer MUST have entry covering each detected selector
- Ledger lookup via pointer's `ledger_path`

#### Target revision render (MF-5 + MF-11 absorbed)

Workflow:
```bash
git fetch --depth=1 origin "${{ inputs.revision }}"
mkdir -p /tmp/target-revision-render
git archive "${{ inputs.revision }}" | tar -x -C /tmp/target-revision-render
cd /tmp/target-revision-render
kubectl kustomize kustomize/overlays/prod > /tmp/prod-render.yaml
cd "$GITHUB_WORKSPACE"  # back to current main checkout for ledger reads
python3 scripts/promotion/check_artifact_dependencies.py \
  --overlay-render /tmp/prod-render.yaml \
  --revision "${{ inputs.revision }}" \
  --ledger-image-dir release-candidates \
  --ledger-runtime-dir runtime-artifacts \
  --active-pointer runtime-artifacts/_active/prod.json
```

Critical: **target revision** is used for manifest render only; **current main checkout** is used for ledger/schema/script reads.

#### Fixtures matrix (MF-7 + MF-14 absorbed)

`tests/promotion/fixtures/check-artifact-deps/`:
1. `valid-all-promoted.yaml` + ledgers + pointer (image jwt_validates:true GREEN, runtime promoted complete)
2. `valid-frontend-zanzibar-amber.yaml` (jwt_validates:false service, d29_zanzibar AMBER acceptable per ADR-0022)
3. `invalid-image-ledger-missing.yaml` (digest not in release-candidates/)
4. `invalid-image-d29-not-green.yaml` (jwt_validates:true service with d29_functional=RED)
5. `invalid-image-no-promoted-at.yaml` (test pre-deploy promoted_at null)
6. `invalid-runtime-pointer-missing.yaml` (render has ExternalSecret kv/platform/openfga#model_id but no _active/prod.json)
7. `invalid-runtime-pointer-no-coverage.yaml` (pointer exists but no matching kind+selector entry)
8. `invalid-runtime-ledger-pending.yaml` (pointer + ledger but ledger.promotion.prod.status=pending)
9. `invalid-runtime-ledger-partial-import.yaml` (evidence_completeness=partial-import)
10. `invalid-runtime-test-unverified.yaml` (prod promoted but test pending — test-bypass detection)
11. `invalid-pointer-selector-mismatch.yaml` (pointer entry for different selector than render dep)
12. `invalid-pointer-digest-mismatch-ledger.yaml` (pointer says digest A, ledger entry has digest B)
13. `invalid-target-revision-render-current-ledger.yaml` (target render uses image not in current main ledger — verifies target-revision/ledger separation)
14. `ignore-third-party.yaml` (image with `services.yaml.third_party: true` — gate ignores)

#### Backfill (MF-4 + MF-13 absorbed)

**PR-7-pre-A** (runtime backfill):
- Fetch canonical OpenFGA authorization model JSON from **test** AND **prod** stores (both required — MF-13)
- Verify both stores return same RFC 8785 canonicalized digest (or document divergence + cross-AI review)
- Create `runtime-artifacts/openfga-model/<digest>.json` with:
  - `promotion.test`: status=verified or promoted, evidence with test ULID + types, evidence_completeness=partial-import (some evidence may be incomplete from session-handoff retroactive)
  - `promotion.prod`: status=promoted, evidence with prod ULID + types, evidence_completeness=partial-import
  - `audit.backfill: true`, `audit.imported_at`, `audit.approval_pathway: "historical-backfill"`
  - `source_docs`: ["docs/session-handoff-2026-05-20-promotion-pipeline-progress.md", "docs/session-handoff-2026-05-20-multi-initiative-closure.md"]
- Create `runtime-artifacts/_active/prod.json` (and `test.json`) pointing to the new ledger entry

**PR-7-pre-B** (image baseline check):
- Audit current `kustomize/overlays/prod` rendered image digests
- Verify each has a `release-candidates/<repo>/<git_sha>.json` entry
- Verify each has `promotion.test.smoke_evidence` D29 GREEN per the predicate
- If any missing/AMBER-where-not-allowed: backfill PR

Both backfill PRs land before PR-7 strict.

### Codex thread referansları

- `019e44ad` — #893 handoff doc correction
- `019e44b9` (plan) + `019e44c8` (post-impl) — #895 PR-4
- `019e44d9` (plan + post-impl) — #896 PR-6
- `019e44eb` — PR-7 plan iter-1 + iter-2 (will continue in next session)

### Yeni session için ilk komut

```bash
cd /Users/halilkocoglu/Documents/platform-k8s-gitops
git pull --rebase origin main
cat docs/session-handoff-2026-05-20-promotion-pipeline-pr4-pr6.md   # bu doc
cat docs/session-handoff-2026-05-20-promotion-pipeline-progress.md  # önceki (PR-2 + PR-5 + P0-c/d/e)
bash scripts/board-sync.sh list                                       # board claim durumu

# İlk iş: PR-7-pre-A (runtime active pointer + OpenFGA historical-backfill ledger).
#   - Fetch test + prod OpenFGA model JSON
#   - RFC 8785 canonicalize + sha256
#   - Create runtime-artifacts/openfga-model/<digest>.json (historical-backfill)
#   - Create runtime-artifacts/_active/{test,prod}.json pointers
#   - Codex plan-time consult before impl
```

### Parallel session ısrarı (PR-8 LIVE-mutation guard'ı doğrulayan kanıt)

Bu session içinde paralel session **4 kez** worktree branch'imi switch'ledi (`roadmap-892-graph-mail-adapter-defer-contract` ve diğer). PR-8 (`require-claim.sh`) tam bu pattern'i adresliyor ama heartbeat/claim sürecinde **board issue** açılmamışsa guard tetiklenmiyor. Sonraki session için öneri: önemli iş öncesi `bash scripts/board-sync.sh claim <issue>` ile claim al, sonra `BOARD_SESSION_ID=$SESSION` ile çalış. PR-7 işi için board issue açmak gerek (bu sessiónda denedik #894 oluşturulamadı — Status label yoktu).

## Referanslar

- ADR-0023 `docs/adr/0023-promotion-pipeline-test-overlay-authoritative.md`
- Önceki handoff: `docs/session-handoff-2026-05-20-promotion-pipeline-progress.md`
- Multi-initiative paralel doc: `docs/session-handoff-2026-05-20-multi-initiative-closure.md`
- PR-6 schema: `schema/runtime-artifact-ledger-v1.schema.json`
- PR-6 README: `runtime-artifacts/README.md` (RFC 8785 algorithm + extension how-to)
- PR-4 script: `scripts/drift-detection/check_env_drift.sh` (5-state ArgoCD machine)
- Codex threads: 019e44ad, 019e44b9, 019e44c8, 019e44d9, 019e44eb
