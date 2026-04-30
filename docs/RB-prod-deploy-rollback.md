# Runbook — Prod Deploy Rollback (post-T+72h)

> Sprint "Prod post-cutover compliance" PR-5.
>
> **Scope**: D30 atomic cutover sonrası (T+72h doldu, post-2026-04-27)
> bir prod deploy'un regresyon yarattığı durumda "önceki iyi digest"e
> geri dönüş prosedürü.
>
> **Bu dokuman ≠ cutover-level rollback** (compose'a dönüş, weighted DNS,
> 72h warm window). O scope için: `docs/prod-cutover-runbook-v2.md` §11-12
> + `docs/S4-rollback-runbook.md` (historical companion).

## Bağlam

T0 = 2026-04-24 01:25 UTC+3 cutover. T+72h = 2026-04-27. **Bugün > T+72h**: prod cluster-authoritative kabul ediliyor, compose workload fallback artık geçerli değil. Stateful tier (PG/KC/Vault) compose'da KALICI (D6 contract).

Post-T+72h rollback senaryosu:
- Yeni prod deploy regresyon yarattı (Gate 1b/1c fail veya canlı bug raporu)
- "Rollback" = "önceki iyi digest'e tekrar deploy", NOT "compose'a dön"
- Workflow `deploy-backend-prod.yml` veya `deploy-frontend-prod.yml` aynı
  pattern'le tekrar çalıştırılır (digest input önceki iyi digest)

## Prerequisite — "Önceki iyi digest" nasıl bulunur?

### Backend (8 service digest map)

`current-state.md` Live Delta block veya gitops main commit history'de
post-T+72h en son **stable** Live Delta block'undan digest'leri al.

```bash
# Son merged backend prod deploy run'ından:
gh run list -R Halildeu/platform-k8s-gitops --workflow=deploy-backend-prod.yml \
  --status success --limit 1 --json databaseId,createdAt
```

Stable run log'undan `client_payload[digests]` JSON map çıkar:
```bash
gh run view <RUN_ID> -R Halildeu/platform-k8s-gitops --log \
  | grep -A 1 "## Backend prod deploy — preflight" \
  | grep "services:"
```

Veya canlı deployment'tan (cutover sonrası tüm prod pod'lar `@sha256:`
pinned olduğu için live image budur — REGRESSİON ÖNCESİ snapshot):

```bash
ssh halil@staging-sw "kubectl --context=k3d-prod get deployment -n platform-prod \
  -o jsonpath='{range .items[*]}{.metadata.name}{\":\"}{.spec.template.spec.containers[0].image}{\"\n\"}{end}'" \
  | grep -v frontend \
  | python3 -c "
import sys, json
m = {}
for line in sys.stdin:
    name, img = line.strip().split(':', 1)
    if '@sha256:' in img:
        digest = img.split('@')[-1]
        m[name] = digest
print(json.dumps(m))
"
```

### Frontend (single image_digest)

```bash
ssh halil@staging-sw "kubectl --context=k3d-prod get deployment frontend -n platform-prod \
  -o jsonpath='{.spec.template.spec.containers[0].image}'"
```

## Rollback prosedürü

### A — Backend rollback

1. **Önceki iyi digests_json** topla (yukarıda).
2. Workflow trigger:

```bash
gh workflow run deploy-backend-prod.yml -R Halildeu/platform-k8s-gitops \
  -f sha=<previous-stable-sha-40-char> \
  -f short_sha=<previous-stable-sha-7-char> \
  -f digests_json='<previous-digests-json-map>'
```

3. **GitHub Environment "production"** approval gate çalışacak — reviewer
   onaylar (rollback durumunda, oncall kişi).
4. Sequential rollout 8 service tek tek geri alır; multi-replica strict
   verify her servis sonrası.
5. Gate 1b ai.acik.com edge chain alive + 1c readiness probe + 2 JWT
   smoke — hepsi pass etmeli.

### B — Frontend rollback

```bash
gh workflow run deploy-frontend-prod.yml -R Halildeu/platform-k8s-gitops \
  -f sha=<previous-stable-sha-40-char> \
  -f short_sha=<previous-stable-sha-7-char> \
  -f image=ghcr.io/halildeu/platform-web-frontend \
  -f image_tag=sha-<previous-7-char> \
  -f image_digest=sha256:<previous-64-hex>
```

### C — Kombine rollback (backend + frontend birlikte)

İki workflow ayrı concurrency group'larda (`prod-backend-deploy` +
`prod-frontend-deploy`). Aynı anda tetiklenebilir; environment gate her
ikisinde de approval bekler.

```bash
# Paralel
gh workflow run deploy-backend-prod.yml ... &
gh workflow run deploy-frontend-prod.yml ...
wait
```

## Rollback Trigger Set (D30 invariant)

`docs/S4-rollback-runbook.md` §1'deki tetikleyici matrisi geçerli:

| Tetikleyici | Eşik | Aksiyon |
|---|---|---|
| Edge 5xx ratio | `> 1%` 15dk sustained | Immediate rollback |
| Authz synthetic fail | 3× peş peşe | Immediate rollback |
| Hub DOWN (permission-service up=0) | 2dk+ | Immediate rollback |
| Critical bug raporu (kullanıcı) | bildirim | Immediate rollback |
| p95 latency | `> 2s` 10dk sustained | Investigate → rollback candidate |
| OpenFGA DOWN | 2dk+ | Authz plane kayıp → rollback |
| Pod restart spike | 3+ restart 15dk | Investigate → rollback candidate |

**Prensip (D30)**: "Önce trafik, sonra teşhis." Immediate tetikleyicilerde
teşhis BEKLEMEZ; rollback workflow tetiklenir, post-mortem ayrı.

## Smoke after rollback

```bash
# Public flow 3-katman (D29)
curl -sk -o /dev/null -w 'frontend=%{http_code}\n' https://ai.acik.com/
curl -sk -o /dev/null -w 'gateway=%{http_code}\n' https://ai.acik.com/api/users/all
curl -sk -o /dev/null -w 'oidc=%{http_code}\n' https://ai.acik.com/realms/master/.well-known/openid-configuration

# Pod imageID == önceki digest doğrulama
ssh halil@staging-sw "kubectl --context=k3d-prod get pod -n platform-prod \
  -l app.kubernetes.io/part-of=platform \
  -o jsonpath='{range .items[*]}{.metadata.name}{\"\t\"}{.status.containerStatuses[0].imageID}{\"\n\"}{end}'"
```

## NE YAPMA (post-T+72h)

- ❌ **Compose workload'a dönme** (warm fallback window doldu; eski compose
  api-gateway/auth/etc artık çalışmıyor olabilir, deploy ad-hoc kalır)
- ❌ **Weighted DNS / partial traffic split** (D30 HARD RULE — atomic switch
  yalnız)
- ❌ **kubectl edit deployment** (manifest drift; D17 koruma + GitOps disiplin)
- ❌ **kubectl set image @<tag>** (tag fallback prod'da YASAK; PR #305 strict
  digest gate)

## Compose stateful (D6) — DOKUNULMAZ

Bu rollback prosedürü compose stateful tier'ı (PG/KC/Vault) ETKİLEMEZ.
ADR-0002 D6: stateful prod K8s-dışı, kalıcı; deploy workflow'lar yalnız
k3d-prod cluster workload'ı yönetir.

```bash
# Stateful tier sağlık check (rollback öncesi, sonrası, daima)
ssh halil@staging-sw "docker ps --format '{{.Names}}\t{{.Status}}' \
  | grep -E 'platform-(pg|kc|vault)-prod'"
```

## Post-rollback follow-up

1. **Post-mortem doc**: `docs/postmortem-<YYYY-MM-DD>-prod-rollback.md`
   (root cause + trigger + timeline + resolved digest + open follow-up).
2. **current-state.md Live Delta block** ekle (rollback evidence).
3. **Codex retrospektif istişare** (yeni thread): rollback senaryosu,
   alınan kararlar, prod deploy discipline'da değişiklik öneri.
4. Eğer regresyon **deploy workflow bug**'ından kaynaklandıysa: ayrı
   PR ile workflow fix; bu runbook update.

## Referanslar

- `docs/prod-cutover-runbook-v2.md` — cutover-level (T-24h → T+0 → T+72h)
- `docs/S4-rollback-runbook.md` — historical companion (cutover-level
  detaylı; post-cutover scope partially superseded)
- `.github/workflows/deploy-backend-prod.yml` — backend prod deploy workflow
- `.github/workflows/deploy-frontend-prod.yml` — frontend prod deploy workflow
- `scripts/deploy/verify-pod-digest.sh` — multi-replica strict digest helper

## Codex thread

`019de00f-4b40-75c1-8ead-01b79c5819c1` — sprint "Prod post-cutover
compliance" AGREE-with-revisions.
