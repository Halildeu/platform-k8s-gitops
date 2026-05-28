# RB-upgrade-pr-playbook — platform-web upgrade PR playbook

> Bu runbook **platform-k8s-gitops** repo'sunda yaşar ama scope'u **platform-web upgrade PR lifecycle**'dır.
>
> Kod / lockfile / CI workflow değişiklikleri **her zaman platform-web issue/PR hattında** kalır. Bu runbook yalnızca upgrade PR'larının lifecycle'ını, evidence shape'ini ve follow-through standardını tanımlar (Codex `019e7098` PARTIAL absorb).

---

## Scope ayrımı

| Taraf | Repo | Sorumluluk |
|---|---|---|
| Source | `platform-web` | `package.json`, lockfile, `vite.config.*`, CI workflows, test, build, ESLint config |
| Operations | `platform-k8s-gitops` (bu repo) | Upgrade PR playbook, audit evidence shape, follow-through (issue/runbook) standardı |

---

## Tetik

Bu playbook şu durumlarda uygulanır:

- Dependabot **major** upgrade PR'ı (örn. `@vitejs/plugin-react` 5→6, `react` 18→19)
- Manuel **batch upgrade** (1+ PR aynı tema altında — örn. vite ailesi 5 paket)
- Periyodik **health check** (sprint sonu, release gate öncesi)
- Lockfile shape değişimi (`pnpm-lock.yaml` regenerate)

---

## 9-Katman Audit Pattern

Major upgrade chain post-merge bir defa koşulur. Background bash task ile dispatch edilir.

> **Not**: Bu playbook içinde `bjiebsl2x` gibi task id'ler **sample evidence shape** olarak kullanılır — canonical dependency değil. Her run kendi task id'sini üretir.

### Layer 1 — Working tree state

```bash
cd /Users/halilkocoglu/Documents/platform-web
git status --short
git branch --show-current
git log --oneline -5
```

**Beklenen**: temiz working tree veya bilinen `.gitignore` artıkları. **Multi-session race detect**: 30+ modified file görülüyorsa (başka session aktif olabilir) **durdur** ve audit iptal — race halinde upgrade verdict güvenilir değil.

### Layer 2 — Lockfile integrity

```bash
pnpm install --frozen-lockfile 2>&1 | tee /tmp/upgrade-layer2.log
```

**Beklenen**: "Done" satırı + 0 ekleme/silme (frozen lock). Lockfile shape değiştiyse Layer 1'e dön — bu upgrade artık major sayılır.

### Layer 3 — Peer dependency warnings

```bash
grep -E 'unmet peer|deprecated subdependency' /tmp/upgrade-layer2.log
```

**Beklenen**: 0 `unmet peer`. Deprecated subdeps bilgi amaçlı (toplu sweep ayrı sprint).

> **Pattern**: 4+ `unmet peer` aynı paket ailesinde (örn. `@tiptap/core` 3.21 vs 3.23) → P2 issue (Halildeu/platform-web#697 pattern).

### Layer 4 — TypeScript strict (paket-paket)

```bash
pnpm -r typecheck 2>&1 | tee /tmp/upgrade-layer4.log
```

**Beklenen**: 0 error veya tüm error'lar `pre-existing` umbrella'da kayıtlı (örn. Halildeu/platform-web#691).

> **Pre-existing vs upgrade-induced ayrımı — güvenli baseline (Codex `019e7098` P1 absorb)**:
>
> `git stash` ile pre/post karşılaştırma **çalışmaz**: temiz worktree'de no-op olur; committed upgrade değişikliklerini geri almaz; aynı commit üzerinde iki typecheck koşulur ve hatalar yanlış olarak "pre-existing" sınıflandırılır. Güvenli pattern ayrı worktree ile detached baseline:
>
> ```bash
> # Upgrade chain başlamadan önce SHA kaydedilmiş olmalı (örn. PR open SHA veya merge-base)
> BASE_SHA=<first-upgrade-before-sha>
> TMP_PRE=$(mktemp -d /tmp/platform-web-pre.XXXXXX)
> git worktree add --detach "$TMP_PRE" "$BASE_SHA"
> (cd "$TMP_PRE" && pnpm install --frozen-lockfile && pnpm -r typecheck 2>&1 | tee /tmp/upgrade-pre.log)
> pnpm -r typecheck 2>&1 | tee /tmp/upgrade-layer4.log
> diff -u /tmp/upgrade-pre.log /tmp/upgrade-layer4.log || true
> git worktree remove "$TMP_PRE"
> ```
>
> Aynı error'lar pre-existing; yeni error'lar upgrade-induced (PR scope'u içinde fix gerek).
>
> **`BASE_SHA` yoksa**: pre-existing kanıtlanamaz; umbrella'ya otomatik fold **YASAK**; manuel review gerek.

### Layer 5 — ESLint + Stylelint

```bash
pnpm run lint:semantic 2>&1 | tee /tmp/upgrade-layer5-semantic.log
pnpm run lint:style 2>&1 | tee /tmp/upgrade-layer5-style.log
```

**Risk**: `lint:semantic` workspace büyüdükçe OOM olabilir (Node V8 heap exhaustion, exit 134). Mitigation:

```bash
NODE_OPTIONS=--max-old-space-size=8192 pnpm run lint:semantic
```

> **Required check kontrolü (Codex `019e7098` P2 absorb — combined gate)**:
>
> Required check iki yerden gelebilir: classic branch protection **VEYA** repo/org ruleset. İkisini birlikte kontrol et:
>
> ```bash
> PROTECTION=$(gh api repos/<owner>/platform-web/branches/main/protection 2>&1 | jq -r '.required_status_checks.checks[]?.context' 2>/dev/null)
> RULESETS=$(gh api repos/<owner>/platform-web/rules/branches/main 2>&1 | jq -r '.[] | select(.type=="required_status_checks") | .parameters.required_status_checks[]?.context' 2>/dev/null)
>
> # Karar:
> # - lint:semantic her iki listede de YOK → P2 audit visibility blocker (Halildeu/platform-web#698 pattern)
> # - lint:semantic listede VAR → P1 (merge blocker; required check)
> # - İkisi de okunamıyor (auth/404 kombinasyonu kafa karıştırıcı) → unknown → P-downgrade YASAK, manuel verify
> ```
>
> Sadece `branches/main/protection` 404'üne bakmak yeterli değil — ruleset'ten gelen required check'i kaçırır.

### Layer 6 — Test suite (Vitest workspace)

```bash
pnpm test 2>&1 | tee /tmp/upgrade-layer6.log
```

**Beklenen**: tüm workspace 100% PASS (skipped acceptable). 1+ fail → upgrade chain durdurulur, PR'a fix commit eklenir.

> Vitest workspace command: `pnpm test --run` `npm-run-all` ile çakışıyor; parametre-siz `pnpm test` doğru çağrı.

### Layer 7 — Build sanity (tüm apps)

```bash
pnpm -r build 2>&1 | tee /tmp/upgrade-layer7.log
```

**Beklenen**: tüm app `Done`. Module Federation `bypass sharing mechanism` warning'leri **advisory** (federation host eager-load pattern).

### Layer 8 — Security audit (osv)

```bash
pnpm dlx osv-scanner@latest --recursive --lockfile=pnpm-lock.yaml 2>&1 | tee /tmp/upgrade-layer8.log
```

**Beklenen**: 0 high, low/moderate tolerable.

> **Severity sweep matrisi**:
> - 1+ high → P1 sweep issue (Halildeu/platform-web#695 pattern), audit gate kırmızı sayılır
> - 5+ moderate → P2 sweep (ayrı sprint)
> - low → bilgi amaçlı, action gerekmez

### Layer 9 — Bundle artifacts verify

```bash
# Federation host + 5 federated MFE
for app in mfe-shell mfe-endpoint-admin mfe-access mfe-audit mfe-reporting mfe-users; do
  test -f apps/$app/dist/remoteEntry.js && echo "$app: ✓RE"
  test -f apps/$app/dist/index.html && echo "$app: ✓idx"
done
```

**Beklenen**: her federation app için iki dosya da var. Eksik artifact → Vite build pipeline regression.

---

## Background script template

Long-running audit `Bash(run_in_background=true)` ile dispatch edilir; sonuç notification ile karşılanır.

**Template** (özet — gerçek script audit task'ı dispatch eden agent tarafından dinamik üretilir):

```bash
#!/usr/bin/env bash
set -euo pipefail

cd /Users/halilkocoglu/Documents/platform-web
LOG_DIR=/tmp/upgrade-audit-$(date +%Y%m%d-%H%M%S)
mkdir -p "$LOG_DIR"

echo "═══ Layer 1 — Working tree ═══" | tee "$LOG_DIR/all.log"
git status --short | tee -a "$LOG_DIR/all.log"

echo "═══ Layer 2 — Lockfile ═══" | tee -a "$LOG_DIR/all.log"
pnpm install --frozen-lockfile 2>&1 | tee -a "$LOG_DIR/all.log"

# ... Layer 3-9
```

**Çıktı evidence id**: `Bash` tool'un dönen `task_id`'si (örn. `bjiebsl2x`) — issue body'lerinde `Audit task id: <id>` ile referanslanır. ID **canonical dependency değil**; ileride aynı audit re-run'larında yeni id üretilir.

---

## Cross-AI Peer Review absorb pattern

CLAUDE.md HARD RULE **Cross-AI Peer Review** gereği her upgrade PR'ı cross-provider review'dan geçer.

### Plan-time

```
Codex MCP yeni thread (sandbox=read-only, approval=never)
  ↓
Plan + bağlam + risk + sorular
  ↓
Verdict:
  AGREE / ready_for_impl=true → direkt impl
  PARTIAL → küçük scope düzeltmesi + impl (HARD RULE Plan Consensus Autonomy: kullanıcıya plan onayı sorulmaz)
  REVISE → plan iterasyonu + yeni Codex submit
  RED → kullanıcıya rapor + yön sor
```

### Post-impl

```
Aynı thread codex-reply ile review iste
  ↓
AGREE → normal squash merge (HARD RULE Admin Merge YASAK + CI Kırmızıyken Merge YASAK)
PARTIAL → küçük commit + tekrar review
REVISE → iter
```

### Authority hiyerarşisi (Codex provenance: thread `019e7098`)

> **AI çıktısı = evidence; local gate / CI / command output = authority.**

Yani:
- Codex AGREE alındı ama `pnpm test` fail ediyorsa → merge YASAK (CI doğrudur, AI bias)
- Codex REVISE dedi ama lokal audit pass ediyorsa → **fix gerek demek değil**; REVISE gerekçesi evidence-backed absorb edilir, gerekirse "no-change rationale" (neden REVISE'ın geçersiz olduğu kanıtla) bırakılır ve PR body'de açıklanır

---

## Forensic cleanup integration

Her PR post-merge `~/.claude/scripts/ai-post-merge-cleanup.sh` çağrılır (HARD RULE Git Workflow):

```bash
gh pr merge $PR --repo $REPO --squash --delete-branch && \
  bash ~/.claude/scripts/ai-post-merge-cleanup.sh "$PR" "$BRANCH"
```

> Script'e branch adı 2. argüman olarak geçirmek tag namespace + branch delete adımlarının dış kaynaktan ayrıştırılmasını sağlar (Codex `019e7098` P3 absorb).

### 5-layer hardening (script içinde — şu an mevcut davranış)

1. **Per-worktree lock** (atomic `mkdir`) — aynı worktree race engelle
2. **Working tree safety** — uncommitted check → abort (önemli: **unrelated user changes untouched**, başka session aktif olabilir)
3. **Remote tag push HARD GATE** — push fail = no delete
4. **Existing tag SHA collision check** — aynı SHA idempotent OK; farklı SHA abort (forensic corruption alarm)
5. **Local-only branch delete only with merged PR proof** — `gh pr view --json mergedAt` doğrulaması
6. **Dry-run env** — `AI_CLEANUP_DRY_RUN=1` ile tüm script preview moda geçer (mevcut)
7. **Default protected branch list** — script `main`, `master`, `develop`, `trunk` adlarını delete etmez

### Script-side follow-up (önerilen, runbook scope dışı)

> Bu davranışlar runbook'ta beklenti olarak yazılır; gerçek implementasyon `~/.claude/scripts/ai-post-merge-cleanup.sh` tarafında ayrı issue ile takip edilir:

- **CLI `--dry-run` flag**: env var (`AI_CLEANUP_DRY_RUN=1`) mevcut; ek olarak `--dry-run` CLI flag introspection için daha keşfedilebilir (script-side issue)
- **Explicit `release/*` protected guard**: şu an `release/*` pattern script default'unda yok — `main/master/develop/trunk` literal listesi açık; pattern bazlı guard eklemek script-side iş

### Audit log

`~/.claude/logs/git-cleanup.log` — host-level, repo-bağımsız, multi-user safe (POSIX O_APPEND atomic < PIPE_BUF).

Disaster recovery (laptop ölümü):

```bash
git clone <repo>
git fetch --tags origin
git tag --list 'archive/*'   # tüm geçmiş PR'lar erişilebilir
```

---

## Pre-existing tech debt folding

Audit bulguları **upgrade sebep değilse** (pre-existing state'te aynı error mevcut), şu pattern uygulanır:

### Karar adımları

1. **Umbrella issue** mevcut mu (`gh issue list --search "in:title ..."`)
2. **Yoksa**: umbrella aç (örn. Halildeu/platform-web#691 "Pre-existing TS strict errors umbrella")
3. **Varsa**: yeni leaf issue + umbrella body/comment scope update
4. **Leaf issue body**'sinde `Tracked by #<umbrella>` veya `Parent: #<umbrella>`
5. **Acceptance kriteri**: umbrella ancak **tüm leaf'ler** kapanınca kapanır
6. **P-label**: leaf'lerde **zorunlu** (P1/P2); umbrella P-label opsiyonel

### Örnek: Codex `019e7098` PARTIAL absorb (2026-05-29)

| Bulgu | P | Parent | Leaf issue |
|---|---|---|---|
| @types/react drift (mixed 18/19) | P1 | Halildeu/platform-web#687 epic (React 19 migration) | Halildeu/platform-web#694 |
| osv high vuln (5x — @lhci/cli zinciri) | P1 | — (stand-alone sweep) | Halildeu/platform-web#695 |
| x-charts removed API (anomalySummary, BarChart, inert) | P2 | Halildeu/platform-web#691 umbrella (TS strict) | Halildeu/platform-web#696 |
| tiptap peer drift (@tiptap/core 3.21 vs 3.23) | P2 | — | Halildeu/platform-web#697 |
| ESLint OOM (required değil) | P2 | — | Halildeu/platform-web#698 |

> Codex absorb: "A3 için yeni bağımsız umbrella açma. Halildeu/platform-web#691 zaten umbrella; doğru hareket Halildeu/platform-web#691 body/comment güncellemesi + gerekiyorsa `x-charts removed API cleanup` leaf issue açmak."

---

## Rollback

Upgrade chain'i geri çevirme:

### Pre-merge rollback

```bash
gh pr close <PR> --delete-branch --comment "Rollback: <neden>"
```

Branch silindiğinde Dependabot pazartesi schedule'ında yeni PR açar (veya `@dependabot recreate` ile elle tetikle).

### Post-merge rollback

```bash
git revert <merge-commit-sha>
gh pr create --title "Revert: <original-title>" --body "Rolls back #<PR>"
```

### Forensic archive recovery (1+ yıl sonra)

```bash
git tag --list 'archive/*pr<N>*'
git checkout -b recovery/x archive/2026/05/<branch>-pr<N>
```

> Audit trail: `grep "pr=<N>" ~/.claude/logs/git-cleanup.log`

---

## Bağlantı (HARD RULE)

| Kural | Bu runbook ile ilişkisi |
|---|---|
| No Fake Work | Her layer için real koşum + paste'lenebilir output zorunlu |
| Cross-AI Peer Review | Sağlayıcı-seviyesinde cross-provider; aynı session/subagent yetmez |
| Plan Consensus Autonomy | Codex AGREE/PARTIAL → impl direkt, plan onayı sorulmaz |
| Admin Merge YASAK | CI yeşil → normal squash; kırmızı → fix |
| CI Kırmızıyken Merge YASAK | False-red → workflow `skipped`'a çevrilir, görmezden gelinmez |
| Git Workflow Forensic Cleanup | `ai-post-merge-cleanup.sh` 5-layer hardened |
| Uzun Vadeli Kalıcı Çözüm | Pre-existing debt folding (workaround değil, umbrella + leaf) |
| Tarayıcıdan Sonuç Doğrulanmadan İş Bitmedi | UI etkileyen upgrade'lerde browser MCP / computer-use verify |

---

## Kaynak / referans

- Cross-AI workflow definition: `Halildeu/platform-k8s-gitops/.github/workflows/gate-cross-ai-audit.yml` (V2.1-GOV-1)
- Forensic cleanup script: `~/.claude/scripts/ai-post-merge-cleanup.sh`
- Audit log: `~/.claude/logs/git-cleanup.log`
- Sample plan-time istişare thread: Codex `019e7098` (PARTIAL absorb)
- Sample audit task id: `bjiebsl2x` (örnek evidence shape)
- Umbrella örnekleri: platform-web Halildeu/platform-web#687 (React 19 epic), Halildeu/platform-web#691 (TS strict umbrella)
- Leaf örnekleri: platform-web Halildeu/platform-web#694, Halildeu/platform-web#695, Halildeu/platform-web#696, Halildeu/platform-web#697, Halildeu/platform-web#698 (Codex `019e7098` absorb sonucu)
