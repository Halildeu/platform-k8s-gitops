# Runbook — Critical-Fix Prod-Deploy SLA Monitor

> **Belge kodu**: `RB-critical-fix-sla-monitor`
> **Tarih**: 2026-05-21
> **Sahip**: Halil
> **Sprint**: DiD-1 (PR #926) defense-in-depth follow-up — 2026-05-21 PermissionProvider stale-token incident
> **Tetik**: `[critical-fix-SLA] PR #N — ...` başlıklı issue açıldığında veya PR'da `critical-fix-sla-warning` body marker'ı bulunan comment göründüğünde

---

## 1. Bağlam

DiD-1 (PR #926) MERGED 2026-05-21 — `scripts/promotion/critical_fix_sla_monitor.py` + `.github/workflows/critical-fix-sla-monitor.yml`. Workflow `*/15 dk` cron'da koşar:

1. `Halildeu/platform-k8s-gitops` repo'sunda **son 48 saatte** `critical-fix` label'lı **merged** PR'ları tarar
2. Her PR için: `deploy-prod-gitops.yml` workflow'un başarılı bir run'ı PR merge commit'ini ancestor olarak içeriyor mu?
3. SLA threshold'ları:
   - `>= 1 saat` merge → no deploy: PR'a **warning comment** post eder (stable marker, son 1 saat içinde tekrar değil)
   - `>= 4 saat` merge → no deploy: **tracking issue** açar (label: `critical-fix-sla-active`, body marker: `<!-- critical-fix-sla pr=N merge_sha=... -->`)

**Correlation 3-layer** (FU-Artifact PR #929 sonrası):
1. **Primary** — `prod-sync-result.json` artifact (`gh run download --name prod-sync-result`)
2. **Fallback** — log-grep (`argocd app sync --revision <sha>` / `Revision: <sha>` lines)
3. **Last resort** — `headSha` exact / ancestor

**Neden bu monitör var**: 2026-05-21'de PR #640 (PermissionProvider stale-token fix) prod'a ~22 saat sonra ulaştı. Lag yalnız son kullanıcı sayfayı broken görünce farkedildi. Bu monitor aynı sınıf lag'i **otomatik sinyal** olarak yakalar.

**Bağlantılı PR'lar**:
- PR #640 (platform-web): incident kaynağı fix
- PR #917 (gitops): incident prod deploy
- PR #926 (gitops, BU monitor): DiD-1 SLA monitor
- PR #929 (gitops): FU-Artifact (`prod-sync-result.json` artifact emit)

---

## 2. SLA Tracking Issue (CRITICAL, ≥4 saat)

### 2.1 Anlamı

Issue body marker `<!-- critical-fix-sla pr=N merge_sha=... -->` taşır. Label: `critical-fix-sla-active`. Title format: `[critical-fix-SLA] PR #N — <truncated title> exceeded 4h prod-deploy SLA`.

**Hemen anlamı**: Bir critical-fix PR merge edildi (label uygulandı), ama bu merge commit'i içeren bir başarılı `deploy-prod-gitops` run'ı yok ve aradan 4 saatten fazla geçti. Bu SLA breach — operasyonel insan eylemi bekliyor.

### 2.2 Anlık triage (2 dakika)

```bash
# 1. PR numarasını ve merge SHA'sını issue body marker'dan al
ISSUE_BODY=$(gh issue view <ISSUE_NUM> --repo Halildeu/platform-k8s-gitops --json body --jq '.body')
PR_NUM=$(echo "$ISSUE_BODY" | grep -oE 'pr=([0-9]+)' | head -1 | cut -d= -f2)
MERGE_SHA=$(echo "$ISSUE_BODY" | grep -oE 'merge_sha=([a-f0-9]+)' | head -1 | cut -d= -f2)

# 2. PR durumu + label'lar
gh pr view $PR_NUM --repo Halildeu/platform-k8s-gitops --json state,mergedAt,labels,title

# 3. PR diff scope (prod kustomization değişti mi yoksa kod-only mu)
gh pr view $PR_NUM --repo Halildeu/platform-k8s-gitops --json files --jq '.files[].path'

# 4. Bu merge SHA'sından sonra her deploy-prod-gitops run
gh run list --repo Halildeu/platform-k8s-gitops --workflow deploy-prod-gitops.yml --limit 10 \
  --json databaseId,createdAt,headSha,status,conclusion \
  | jq --arg sha "$MERGE_SHA" '.[] | select(.createdAt > (now - 48*3600 | strftime("%Y-%m-%dT%H:%M:%SZ"))) | {databaseId, createdAt, conclusion, status}'
```

### 2.3 Karar matrisi

| Durum | Aksiyon |
|---|---|
| PR prod-overlay değiştirmiyor (kod-only, frontend image bump yok) | Bu issue **false-positive** — `critical-fix-sla-active` label'ı kaldır + issue'yi `not-applicable` ile kapat. Operator manuel — script otomatik tahmin yapamıyor. |
| PR prod-overlay değiştiriyor + deploy henüz başlamadı | **Deploy başlat** (aşağıda §2.4) |
| Deploy başladı ama henüz `production` environment gate approval bekliyor | Operator GitHub Actions UI'da `production` gate'i **approve et** |
| Deploy success run var ama monitor görmedi | `prod-sync-result.json` artifact'ı eksik olabilir → run log'una manuel bak (`gh run view <id> --log | grep -i revision`). Eğer artifact eksikse: layer-2/3 fallback testi yap; eğer hâlâ false-negative, monitor bug (issue aç ayrı). |
| Deploy fail | Sebebi düzelt + yeniden başlat (workflow_dispatch) |

### 2.4 Deploy başlatma (issue'yi çözmek için)

```bash
# Önce: prod overlay'in main HEAD'i taşıdığını doğrula (resources mode için zorunlu)
git fetch origin main
ORIGIN_MAIN=$(git rev-parse origin/main)
echo "main HEAD: $ORIGIN_MAIN"
echo "merge SHA:  $MERGE_SHA"
git merge-base --is-ancestor $MERGE_SHA $ORIGIN_MAIN && echo "✓ merge ancestor of main" || echo "✗ merge NOT ancestor (revert?)"

# resources mode (frontend digest bump için tipik)
gh workflow run deploy-prod-gitops.yml --repo Halildeu/platform-k8s-gitops --ref main \
  --field revision=$ORIGIN_MAIN \
  --field sync_mode=resources \
  --field resources='apps:Deployment:frontend' \
  --field allow_prune=false \
  --field confirm=SYNC-PROD

# Owner production environment gate'i approve etmeli (GitHub Actions UI).
```

### 2.5 Issue lifecycle — net davranış

Önemli: **Monitor deploy bulduğunda mevcut SLA issue'sine DOKUNMAZ.** Refresh comment yalnız hâlâ deploy bulamadığı durumda (`create_or_update_issue()` `find_existing_sla_issue()` match'lerse comment ekler) çalışır.

Deploy başarılı olduktan ve `prod-sync-result.json` artifact'ında `revision == $ORIGIN_MAIN` (veya ancestor) doğrulandıktan sonra **operator manuel kapatır**:

```bash
# Önce artifact'tan deploy revision'ı doğrula
TMP=$(mktemp -d)
gh run download <DEPLOY_RUN_ID> --repo Halildeu/platform-k8s-gitops --name prod-sync-result --dir $TMP
jq '.revision, .conclusion' $TMP/prod-sync-result.json

# revision merge_sha'yı içeriyorsa kapat (merge_sha ancestor-of revision direction)
gh issue close <ISSUE_NUM> --repo Halildeu/platform-k8s-gitops --comment "Resolved: deploy-prod-gitops run <RUN_ID> success at <UTC>. merge_sha=$MERGE_SHA is ancestor of revision=<rev> in prod overlay."
```

### 2.6 Idempotency davranışı (script ile uyumlu)

| Senaryo | Davranış |
|---|---|
| Aynı PR için 2 kez 4h breach (örn. monitor 15dk cron) | Var olan **açık** issue'ye refresh comment eklenir (`SLA still active — age now Xh.`), yeni issue YOK |
| Operator issue'yi manuel kapattı + PR hâlâ deploy edilmedi | Sonraki monitor iter (≤15dk) **yeni** issue açar — script `--state open` filter ile arıyor, kapalı issue'ler match dışı |
| Operator issue'yi manuel kapattı + PR deploy edildi | Yeni issue yok (artifact/log/headSha layer-1/2/3 deploy'u bulur, `[OK]` log + `continue`) |
| Body marker `pr=640` ile başka PR'ın `pr=6400` body'sini karıştırma | Boundary regex (`<!--\s*critical-fix-sla\s+pr=640(?:\s\|-->\|$)`) ile false-positive yok (PR #926 iter-4 P2 fix) |
| `--dry-run` mode | Hiç gh side-effect yok; log'da `[DRY-RUN] would create/update...` |

---

## 3. SLA Warning Comment (≥1 saat)

### 3.1 Anlamı

PR'da body marker `<!-- critical-fix-sla-warning pr=N -->` taşıyan comment. `checked_at=<iso>` ayrı satırda. Anlamı: critical-fix label'lı PR 1 saat öncesinde merge edildi, henüz deploy success yok. SLA henüz breach değil (4h değil) — ama **trajectory uyarısı**.

### 3.2 Eylem

Eğer deploy yakında başlayacaksa (örn. dependent PR mergesi bekleniyor): **eylem gerekmez**, monitor 1 saatte tekrar uyarmayacak (timestamp-stable marker, son 1 saat içinde ise skip).

Eğer deploy yapılmayacaksa (PR yanlışlıkla critical-fix label aldı): label'ı **kaldır**:

```bash
gh pr edit <PR_NUM> --repo Halildeu/platform-k8s-gitops --remove-label critical-fix
```

Label kaldırıldığında bir sonraki monitor iter (≤15 dk) PR'ı kapsamına almayacak — yeni warning veya issue üretilmeyecek.

---

## 4. Monitor health check

Workflow çalışıyor mu?

```bash
# Son 5 monitor run
gh run list --repo Halildeu/platform-k8s-gitops --workflow critical-fix-sla-monitor.yml --limit 5 \
  --json conclusion,createdAt,status

# Beklenen: success bucket'ında — cron her 15dk
```

Workflow fail ediyorsa (exit 1):
- `correlation_errors > 0` sebep — bir veya birden fazla `gh run list` / `gh issue list` / `gh pr view` çağrısı fail oldu
- Log'a bak: `gh run view <id> --log`
- Tipik sebep: GitHub API rate limit (60/hour unauthenticated, 5000/hour for GITHUB_TOKEN — bu workflow GITHUB_TOKEN kullanıyor, rate limit aşımı az olası)
- Diğer tipik: `--status success` filtresi bir field shape değişikliği (gh CLI version drift) — rare

Workflow uzun süredir koşmuyorsa (>30dk):
- `gh workflow view critical-fix-sla-monitor.yml --repo Halildeu/platform-k8s-gitops` — enabled mi?
- GitHub Actions overall status check (status.github.com)
- `concurrency: critical-fix-sla-monitor` group — başka bir workflow lock tutuyor olabilir mi

---

## 5. Manuel dry-run

Monitor'ün ne yapacağını gerçekten yapmadan görmek için:

```bash
gh workflow run critical-fix-sla-monitor.yml --repo Halildeu/platform-k8s-gitops --ref main \
  --field dry_run=true \
  --field critical_hours=4 \
  --field warning_hours=1

# Run log'unda:
# [DRY-RUN] would create/update SLA issue: ...
# [DRY-RUN] would post warning comment on PR #...
```

Threshold'ları manuel çağrıda override edilebilir (örn. `critical_hours=1` ile daha agresif).

---

## 6. Bilinen sınırlar

- **Correlation accuracy**: Layer 1 (artifact) yalnız FU-Artifact (PR #929) sonrası deploy run'larında yazıldı. PR #929 öncesi run'lar için layer 2 (log-grep) + layer 3 (headSha) fallback. Log retention 90 gün — eski run'larda log boş dönerse headSha ancestor check yapılır (rollback false-pass guard'ı layer-1 olmadığı için zayıf).
- **PR scope**: Yalnızca `Halildeu/platform-k8s-gitops` repo'sundaki PR'ları izler. Source repo'lardaki (`platform-web`, `platform-backend`) critical-fix label'ları kapsama girmez (cross-repo correlation kompleks; ayrı follow-up).
- **Label discipline**: `critical-fix` label'ı **manuel** uygulanmalı. PR template trailer otomasyonu (`Critical-Fix: yes` → auto-label) follow-up scope (PR #-tba-).
- **Closed issue re-open**: Monitor yalnız HÂLÂ DEPLOY BULAMADIĞINDA açık issue'ye refresh comment ekler (deploy bulunca issue'ye dokunmaz). **Kapatılan** issue'yi yeniden açmaz; ama eğer kullanıcı kapatır ve PR hâlâ deploy edilmemişse, sonraki iter'de **yeni** issue açar (idempotency yalnız `--state open` issue match'inde, kapalı issue'ler scope dışı).

---

## 7. Bağlantılı runbook'lar

> Repo iki runbook dizini taşıyor — operasyonel/cluster operations runbook'ları
> `docs/operations/RUNBOOKS/` altında, monitoring/alerting + faz-bazlı
> runbook'lar `docs/runbooks/` altında. Cross-reference'larda **tam path** ver.

- [docs/operations/RUNBOOKS/RB-prod-gitops-sync.md](../operations/RUNBOOKS/RB-prod-gitops-sync.md) — deploy-prod-gitops.yml manual dispatch
- [docs/runbooks/RB-synthetic-frontend-probes.md](RB-synthetic-frontend-probes.md) — HTTP-level edge regression detection (DiD-2, complementary monitor)
- [docs/runbooks/RB-alertmanager-bridge-gh-token-seed.md](RB-alertmanager-bridge-gh-token-seed.md) — alert delivery → GitHub issue mechanism

---

## 8. Değişiklik geçmişi

| Tarih | Değişiklik | Bağlantı |
|---|---|---|
| 2026-05-21 | İlk yazım — DiD-1 (PR #926) + FU-Artifact (PR #929) follow-up | PR #-tba- (this PR) |
