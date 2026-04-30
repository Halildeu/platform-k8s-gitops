# Runbook — backend testai auto-deploy

> iter-49 follow-up — `repository_dispatch` ile platform-backend image
> push'undan testai k3d-test cluster'a otomatik 8-service rollout.

## Bağlam

`platform-backend` 9 microservice GHCR push (`ci-image-push.yml` matrix).
Bu workflow + dispatch step (ayrı PR) sonrası testai cluster'a sequential
deploy.

**Codex 019ddf43 sertleştirmeleri**:
- Sequential rollout (paralel ResourceQuota riski — iter-50 frontend deploy'da quota aşımı yaşandı)
- api-gateway entry-point EN SON deploy
- skopeo runtime digest resolve → `image@sha256:` pin (D30 immutable artifact)
- 4 verify gate (1a per-service digest + 1b public health + 1c readiness + 2 opt-in JWT)
- `endpoint-admin-service` + `discovery-server` ilk cut'tan SKIP

## Servis sırası

1. `auth-service`
2. `permission-service` (Zanzibar hub)
3. `user-service`
4. `variant-service`
5. `core-data-service`
6. `report-service`
7. `schema-service`
8. `api-gateway` (entry-point, en son)

## Trigger

- `repository_dispatch` event_type=`backend-testai-deploy` (platform-backend ci'den)
- `workflow_dispatch` (manuel acil-fix re-trigger)

Payload:
```json
{
  "sha": "<full-40-char>",
  "short_sha": "<7-char>"
}
```

Image digest workflow runtime'da `skopeo inspect` ile çözülür (her servis için ayrı).

## Verify chain

| Gate | İçerik | Fail davranışı |
|---|---|---|
| 1a | Pod imageID == GHCR manifest digest (her 8 servis için, rollout sonrası) | fail-fast |
| 1b | testai.acik.com/actuator/health 200 (api-gateway public) | fail-fast |
| 1c | 8 servis in-cluster `/actuator/health/readiness` 200 (port 8081) | warn-only her tek servis, blocking eğer FAILED > 0 |
| 2 | JWT auth flow smoke (token al + /api/users/all 200) | opt-in (skip if SMOKE_AUTH_* secret yok) |

## Manuel deploy

```bash
gh workflow run deploy-backend-testai.yml -R Halildeu/platform-k8s-gitops \
  -f sha=<full-40-char> \
  -f short_sha=<7-char>
```

## Failure recovery

### Gate 1a fail (digest mismatch)

**Sebep**: Pod yeni image pull etmedi (containerd cache veya rollout timeout).

```bash
ssh halil@staging-sw
kubectl --context=k3d-test rollout restart deployment/<svc> -n platform-test
kubectl --context=k3d-test rollout status deployment/<svc> -n platform-test
```

### Sequential rollout stuck (ResourceQuota)

iter-50 frontend deploy yaşandı: quota aşımı (8000m limit, 1000m fazla).

```bash
# Quota durumu
kubectl --context=k3d-test describe quota -n platform-test

# Manuel pod cleanup (eski replicaset)
kubectl --context=k3d-test delete pod -l app.kubernetes.io/name=<svc> -n platform-test --grace-period=10
```

iter-49 follow-up B.4: `maxSurge=0` + `maxUnavailable=1` test overlay'de
backend deployment template'lerine eklenmeli (ayrı PR).

### Gate 1c fail (readiness probe)

Spring Boot Actuator `/actuator/health/readiness` management port 8081'de.
Servis henüz hazır değilse rollout-status PASS olabilir ama readiness
probe FAIL. Bekle veya manifest health probe interval kontrol.

### Gate 2 fail (JWT auth)

Test persona credentials secret'ları:
- `SMOKE_AUTH_USERNAME` 
- `SMOKE_AUTH_PASSWORD`

CLAUDE.md HARD RULE: kullanıcı login user'ına dokunma; ayrı persona
zorunlu. Keycloak'ta read-only viewer role oluştur, secret olarak
gitops repo'ya ekle.

## Drift guard

Dispatch step etkin mi?
```bash
# platform-backend repo'da workflow son run'daki dispatch step
gh run list --workflow=ci-image-push.yml -R Halildeu/platform-backend --limit=1 --json conclusion,status

# gitops deploy-backend-testai workflow son run
gh run list --workflow=deploy-backend-testai.yml -R Halildeu/platform-k8s-gitops --limit=3 --json status,conclusion,event
```

## Out-of-scope (follow-up)

- **B.4** — backend deployment manifest `maxSurge=0/maxUnavailable=1`
  (ResourceQuota aware rollout)
- **B.5** — Slack/PagerDuty paging receiver (iter-49 B.2 PR #291 warning
  rule'lar pre-prod; receiver netleşince severity=critical paging ekle)
- **endpoint-admin-service** + **discovery-server** dahil etme — manifest
  contract netleşince ayrı PR
- **Production deploy** — `deploy-backend-prod.yml` workflow_dispatch
  + GitHub environment approval (D30 atomic cutover öncesi)

## Codex thread

`019ddf43-e6eb-7dd0-9c30-d6c9b867e5dd`

## Bağımlılık (merge sırası)

1. **Bu PR (workflow + runbook)** — gitops side ready
2. **Ayrı PR**: backend deployment manifest `maxSurge=0` (test overlay)
3. **Ayrı PR**: platform-backend ci-image-push.yml dispatch step
   (ÖNCE: workflow ready olmalı; yoksa dispatch boş kalır)
