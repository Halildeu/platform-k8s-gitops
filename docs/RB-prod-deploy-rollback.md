# Runbook — Prod Deploy Rollback (post-T+72h)

> **Scope**: D30 atomic cutover sonrası (T+72h doldu, post-2026-04-27) bir
> prod deploy'un regresyon yarattığı durumda `platform-prod`'u önceki iyi
> git revision'ına geri alma prosedürü.
>
> **Mekanizma (2026-05-18, PR-2)**: Rollback artık `deploy-prod-gitops.yml`
> `sync_mode=full` + `confirm=SYNC-PROD-ROLLBACK` ile yapılır. Eski
> image-only `deploy-backend-prod.yml` / `deploy-frontend-prod.yml`
> workflow'ları emekli edildi (Codex `019e35d1` 4-PR planı, PR-2) — prod'un
> tek mutasyon mekanizması ArgoCD GitOps sync.
>
> **Bu doküman ≠ cutover-level rollback** (compose'a dönüş, weighted DNS,
> 72h warm window). O scope için: `docs/prod-cutover-runbook-v2.md` §11-12
> + `docs/S4-rollback-runbook.md` (historical companion).
>
> **Dispatch mekaniği**: `docs/operations/RUNBOOKS/RB-prod-gitops-sync.md`
> canonical (sync workflow girdileri, gate'ler, operator setup). Bu runbook
> rollback **kararını** tanımlar — ne zaman, hangi revision'a, sonra ne.

## Bağlam

T0 = 2026-04-24 01:25 UTC+3 cutover. T+72h = 2026-04-27. **Bugün > T+72h**:
prod cluster-authoritative kabul ediliyor, compose workload fallback artık
geçerli değil. Stateful tier (PG/KC/Vault) compose'da KALICI (D6 contract).

Post-T+72h rollback senaryosu:
- Yeni prod sync regresyon yarattı (acceptance smoke fail veya canlı bug raporu).
- "Rollback" = `platform-prod` ArgoCD app'ini **önceki iyi git revision'a**
  geri sync, NOT "compose'a dön".
- Prod'un tüm desired-state'i (Deployment image digest'leri + ConfigMap +
  manifest) gitops repo'da versiyonlu — bir önceki iyi commit'e sync etmek
  tüm katmanları birden geri alır.

## İki rollback yolu

| Yol | Ne zaman | Hız | Git tutarlılığı |
|---|---|---|---|
| **A — Doğrudan revision sync** (`sync_mode=full` + eski revision) | Acil incident; regresyon **mevcut** kaynakların image/config/manifest'inde | Hızlı (~tek run) | Cluster eski revision'da, `main` HEAD ileride → **revert PR şart** (follow-up) |
| **B — Revert-forward** (`git revert` PR → merge → HEAD'e sync) | Acil olmayan regresyon **veya** kaynak ekleme/silme içeren regresyon | Yavaş (PR + CI + review) | `main` ve cluster tutarlı kalır |

D30 prensibi "Önce trafik, sonra teşhis": immediate trigger'larda **Yol A**
(hız), sonra zorunlu revert PR. Acil olmayan durumda **Yol B**.

⚠️ **Yol A sınırı** (aşağıda "Yol A sınırı" bölümünde detay): `full` rollback
`--prune` taşımaz ve workflow prune gate'i revision-aware değildir — regresyon
yeni bir kaynak **eklediyse** Yol A onu canlıdan kaldırmaz. Kaynak ekleme/silme
içeren regresyon → **Yol B**.

## Prerequisite — "Önceki iyi revision" nasıl bulunur?

GitOps rollback **revision-temelli**: bir commit SHA'ya sync edersin, o
commit'teki tüm `platform-prod` manifest'leri (Deployment image digest +
ConfigMap + manifest) canlıya gelir. "Önceki iyi revision" = regresyonu
getiren değişiklikten **önceki** son stabil commit.

Üç kaynak:

1. **current-state.md Live Delta** — her prod rollout revision + digest
   kaydeder; son stabil rollout bloğunun revision'ını al:
   ```bash
   grep -nE 'Live Delta|revision|sha256:' docs/state/current-state.md | head -30
   ```
2. **Overlay commit geçmişi** — prod overlay'i değiştiren commit'ler:
   ```bash
   git log --oneline -15 -- kustomize/overlays/prod
   ```
   Regresyonu getiren commit `X` ise önceki iyi revision genelde `X^`.
3. **ArgoCD app history** (canlı) — `argocd` login sonrası (RB-prod-gitops-sync.md §1.2):
   ```bash
   argocd --plaintext --server 127.0.0.1:18083 app history platform-prod
   ```

Seçilen SHA `origin/main` ancestor + 40-hane lowercase hex olmalı (workflow
preflight şartı).

## Rollback prosedürü — Yol A (doğrudan revision sync)

1. **Önceki iyi revision SHA'sını** belirle (yukarıda) — 40-hane hex.
2. Stateful tier sağlık check (rollback öncesi):
   ```bash
   ssh halil@staging-sw "docker ps --format '{{.Names}}\t{{.Status}}' \
     | grep -E 'platform-(pg|kc|vault)-prod'"
   ```
3. `deploy-prod-gitops.yml` dispatch — `sync_mode=full`, rollback token:
   ```bash
   gh workflow run deploy-prod-gitops.yml \
     --repo Halildeu/platform-k8s-gitops --ref main \
     -f revision=<önceki-iyi-40-hane-sha> \
     -f sync_mode=full \
     -f allow_prune=false \
     -f confirm=SYNC-PROD-ROLLBACK
   ```
   - `revision` != main HEAD → workflow `is_rollback=true` algılar; token
     `SYNC-PROD-ROLLBACK` olmalı.
   - `full` mode tüm app'i o revision'a sync eder (selective değil).
   - Gate'ler + dispatch detayı: `RB-prod-gitops-sync.md` §2-3.
4. **`production` environment approval gate** — oncall reviewer onaylar.
5. Workflow içinde `argocd app wait --operation --sync --health` — sync +
   health beklenir.
6. Acceptance smoke (aşağıda) — rollback'in regresyonu kaldırdığını doğrula.
7. **Zorunlu follow-up**: `main` HEAD hâlâ regresyon commit'ini içeriyor —
   cluster ileride tekrar HEAD'e sync edilirse regresyon geri gelir. 30 dk
   içinde regresyon commit'i için `git revert` PR aç + merge et.

## Rollback prosedürü — Yol B (revert-forward, acil olmayan)

1. Regresyonu getiren commit için `git revert <sha>` PR aç.
2. Cross-AI review + CI yeşil + squash merge (normal akış).
3. `deploy-prod-gitops.yml` dispatch — merge sonrası yeni main HEAD'e:
   ```bash
   REV=$(git rev-parse origin/main)
   gh workflow run deploy-prod-gitops.yml \
     --repo Halildeu/platform-k8s-gitops --ref main \
     -f revision="${REV}" \
     -f sync_mode=resources \
     -f resources='<etkilenen GROUP:KIND:NAME listesi>' \
     -f allow_prune=false \
     -f confirm=SYNC-PROD
   ```
   - revision == HEAD → `resources` mode kullanılabilir (selective, dar yüzey).
   - Geniş revert ise `sync_mode=full` + `confirm=SYNC-PROD`.

## Yol A sınırı — prune gate revision-aware değil

`deploy-prod-gitops.yml` prune gate'i (`argocd app get` →
`.status.resources[].requiresPruning`) prune adayını **mevcut** desired-state'e
göre değerlendirir — dispatch edilen eski revision'a göre revision-aware bir
diff yapmaz. Ayrıca rollback run'ı `--prune` taşıyamaz (`allow_prune=true` +
eski-revision rollback aynı run'da yasak; workflow preflight reddeder).

Sonuç: Yol A `full` sync, eski revision'da **bulunan** kaynakların
image/config/manifest'ini geri alır; eski revision'da **bulunmayan** (HEAD'de
sonradan eklenmiş) bir kaynağı **silmez** — orphan canlıda kalır. "App tümüyle
eski revision'a döndü" diye okuma.

Regresyon kaynak ekleme/silme içeriyorsa → **Yol B**: revert PR ekleme/silmeyi
desired-state'ten düzgün çıkarır, sonra normal HEAD sync.

## Rollback Trigger Set (D30 invariant)

`docs/S4-rollback-runbook.md` §1'deki tetikleyici matrisi geçerli:

| Tetikleyici | Eşik | Aksiyon |
|---|---|---|
| Edge 5xx ratio | `> 1%` 15dk sustained | Immediate rollback (Yol A) |
| Authz synthetic fail | 3× peş peşe | Immediate rollback (Yol A) |
| Hub DOWN (permission-service up=0) | 2dk+ | Immediate rollback (Yol A) |
| Critical bug raporu (kullanıcı) | bildirim | Immediate rollback (Yol A) |
| p95 latency | `> 2s` 10dk sustained | Investigate → rollback candidate |
| OpenFGA DOWN | 2dk+ | Authz plane kayıp → rollback (Yol A) |
| Pod restart spike | 3+ restart 15dk | Investigate → rollback candidate |

**Prensip (D30)**: "Önce trafik, sonra teşhis." Immediate tetikleyicilerde
teşhis BEKLEMEZ; Yol A sync tetiklenir, post-mortem ayrı.

## Smoke after rollback

```bash
# Public flow 3-katman (D29)
curl -sk -o /dev/null -w 'frontend=%{http_code}\n' https://ai.acik.com/
curl -sk -o /dev/null -w 'gateway=%{http_code}\n' https://ai.acik.com/api/users/all
curl -sk -o /dev/null -w 'oidc=%{http_code}\n' https://ai.acik.com/realms/master/.well-known/openid-configuration

# Pod imageID == hedef revision digest doğrulama
ssh halil@staging-sw "kubectl --context=k3d-prod get pod -n platform-prod \
  -l app.kubernetes.io/part-of=platform \
  -o jsonpath='{range .items[*]}{.metadata.name}{\"\t\"}{.status.containerStatuses[0].imageID}{\"\n\"}{end}'"

# ArgoCD app durumu (argocd login: RB-prod-gitops-sync.md §1.2)
#  Yol A sonrası: operation success + Healthy + hedef revision kaynakları
#  canlı. App `main` HEAD'e karşı OutOfSync GÖRÜNÜR (HEAD hâlâ regresyon
#  commit'ini içerir) — beklenen; oos=0 parity revert-forward PR merge sonrası.
#  Yol B sonrası: Synced + Healthy + oos=0.
```

## NE YAPMA (post-T+72h)

- ❌ **Compose workload'a dönme** (warm fallback window doldu; eski compose
  api-gateway/auth/etc artık çalışmıyor olabilir, deploy ad-hoc kalır)
- ❌ **Weighted DNS / partial traffic split** (D30 HARD RULE — atomic switch
  yalnız)
- ❌ **`kubectl edit` / `set image` / `patch` ile prod mutasyonu** (manifest
  drift; D30 GitOps disiplini — prod'un tek mutasyon yolu ArgoCD sync)
- ❌ **`main` HEAD'i geri sync etmeden bırakma** — Yol A sonrası revert PR
  açılmazsa, sonraki herhangi bir sync regresyonu geri getirir

## Compose stateful (D6) — DOKUNULMAZ

Bu rollback prosedürü compose stateful tier'ı (PG/KC/Vault) ETKİLEMEZ.
ADR-0002 D6: stateful prod K8s-dışı, kalıcı; GitOps sync yalnız k3d-prod
cluster workload'ı yönetir.

```bash
# Stateful tier sağlık check (rollback öncesi, sonrası, daima)
ssh halil@staging-sw "docker ps --format '{{.Names}}\t{{.Status}}' \
  | grep -E 'platform-(pg|kc|vault)-prod'"
```

## Post-rollback follow-up

1. **`git revert` PR** (Yol A sonrası zorunlu): regresyon commit'i revert
   edilir, cross-AI review + CI yeşil + merge → `main` cluster ile tutarlı.
2. **Post-mortem doc**: `docs/postmortem-<YYYY-MM-DD>-prod-rollback.md`
   (root cause + trigger + timeline + hedef revision + open follow-up).
3. **current-state.md Live Delta block** ekle (rollback evidence).
4. **Codex retrospektif istişare** (yeni thread): rollback senaryosu,
   alınan kararlar, prod deploy discipline'da değişiklik öneri.
5. Eğer regresyon **sync workflow bug**'ından kaynaklandıysa: ayrı PR ile
   `deploy-prod-gitops.yml` fix + bu runbook update.

## Referanslar

- `docs/operations/RUNBOOKS/RB-prod-gitops-sync.md` — sync workflow canonical
  (girdiler, gate'ler, §5 `full`+eski-revision rollback dispatch, operator setup)
- `.github/workflows/deploy-prod-gitops.yml` — prod'un tek deploy/rollback workflow'u
- `docs/prod-cutover-runbook-v2.md` — cutover-level (T-24h → T+0 → T+72h)
- `docs/S4-rollback-runbook.md` — historical companion (cutover-level
  detaylı; post-cutover scope partially superseded)

## Codex thread

- `019de00f-4b40-75c1-8ead-01b79c5819c1` — sprint "Prod post-cutover
  compliance" (orijinal image-only rollback runbook).
- `019e35d1` — prod-deploy mimarisi 4-PR planı; PR-2 bu runbook'u GitOps
  revision rollback'a taşıdı.
