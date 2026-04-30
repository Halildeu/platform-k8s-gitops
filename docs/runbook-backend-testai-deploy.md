# Runbook — backend testai auto-deploy

> iter-49 cycle close — `repository_dispatch` ile platform-backend image
> push'undan testai k3d-test cluster'a otomatik 8-service rollout.
>
> **Live verified**: gitops PR #296 + #297 + #294 + #295 + #298 + #299 +
> #301 + backend PR #54 chain (Codex 019ddf43 + 019de00f cycle close).

## Bağlam

`platform-backend` 9 microservice GHCR push (`ci-image-push.yml` matrix).
Bu workflow + dispatch step tek event halinde gitops repo'ya gönderir,
gitops deploy workflow digest-pin mode'da sequential rollout yapar.

**Codex sertleştirmeleri**:
- Sequential rollout (paralel ResourceQuota riski)
- `api-gateway` entry-point EN SON deploy
- Per-service digest payload (B.3 hardening) → `image@sha256:` direct pin
- Tag-based fallback backward-compat (legacy dispatcher için)
- `maxSurge=0/maxUnavailable=1` test overlay'de 8 backend deployment'a
  uygulanmış (Codex 019dd818 PARTIAL → genelleme PR #294)
- 4 verify gate (1a digest match + 1b edge chain + 1c readiness + 2 JWT)
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

- `repository_dispatch` event_type=`backend-testai-deploy` (platform-backend
  ci-image-push.yml dispatch job'undan otomatik)
- `workflow_dispatch` (manuel acil-fix re-trigger)

### Payload (B.3 sonrası)

```json
{
  "sha": "<full-40-char>",
  "short_sha": "<7-char>",
  "ref": "<branch>",
  "digests": {
    "auth-service": "sha256:<64-hex>",
    "permission-service": "sha256:<64-hex>",
    "user-service": "sha256:<64-hex>",
    "variant-service": "sha256:<64-hex>",
    "core-data-service": "sha256:<64-hex>",
    "report-service": "sha256:<64-hex>",
    "schema-service": "sha256:<64-hex>",
    "api-gateway": "sha256:<64-hex>",
    "discovery-server": "sha256:<64-hex>"
  }
}
```

> Backend `ci-image-push.yml` her servis için `docker/build-push-action@v6`
> `outputs.digest` → artifact upload → dispatch job download-artifact ile
> JSON map aggregation → `gh api -F client_payload[digests]=...` syntax.
>
> **Backward-compat**: `digests` field eksikse (legacy dispatcher) deploy
> workflow tag-based fallback'e düşer; field VARSA strict mode (parse fail
> + empty object + invalid digest format = hard fail).

## Verify chain

| Gate | İçerik | Fail davranışı |
|---|---|---|
| 1a | Per-service pod imageID = digest assertion | fail-fast |
| 1a | Digest mode'da: payload digest === pod imageID === GHCR digest D30 üçlü | fail-fast |
| 1b | `https://testai.acik.com/api/users/all` HTTP 200/401/403 (edge chain alive) | fail-fast |
| 1c | 8 servis in-cluster `/actuator/health/readiness` 200 (port 8081) | warn per-service, blocking eğer FAILED > 0 |
| 2 | JWT auth flow smoke (token al + /api/users/all 200) | opt-in (skip if SMOKE_AUTH_* secret yok) |

> **Gate 1b semantik**: `/actuator/health` JWT-protected (401), security
> best-practice. Gate 1b edge chain alive sinyali olarak `/api/users/all`
> kontrol eder; 200 (JWT geçerli + permitted), 401 (JWT eksik = filter
> alive), 403 (JWT geçerli + denied = audz alive) hepsi healthy. 5xx/0xx
> = chain BROKEN.

## Önkoşullar (precondition)

**Aktif test çalışma modu** — deploy workflow her servis için Running pod
varsayar (rollout status + pod imageID extract). Test overlay default'u
D17 scale-to-zero (`replicas: 0`); önce hedef deployment'lar scale-up
edilmeli. Şu an 8 backend deployment hepsi `replicas=1` (test-toggle.sh
veya manuel scale).

**Hızlı kontrol**:
```bash
ssh halil@staging-sw "kubectl --context=k3d-test get deployment -n platform-test \
  -o jsonpath='{range .items[*]}{.metadata.name}{\":\"}{.spec.replicas}{\"\n\"}{end}'"
```

Hepsi `:1` görünmeli. `:0` ise scale-up:
```bash
ssh halil@staging-sw "kubectl --context=k3d-test scale deployment <svc> --replicas=1 -n platform-test"
```

## Manuel deploy

```bash
gh workflow run deploy-backend-testai.yml -R Halildeu/platform-k8s-gitops \
  -f sha=<full-40-char> \
  -f short_sha=<7-char>
```

> `workflow_dispatch` payload digest taşımaz → tag-based fallback aktif.
> Otomatik dispatch (`repository_dispatch`) digest-pin mode tetikler.

## Failure recovery

### Gate 1a fail (digest mismatch)

**Sebep**: pod imageID dispatch payload digest ile uyuşmadı (image pull
race veya yanlış pod yakalama).

iter-49 PR #299 + #301 race fix sonrası: deploy workflow non-terminating
Running pod'lardan en yenisini seçer (deletionTimestamp null +
creationTimestamp asc + last). Bu fail görülürse:

```bash
ssh halil@staging-sw
kubectl --context=k3d-test rollout restart deployment/<svc> -n platform-test
kubectl --context=k3d-test rollout status deployment/<svc> -n platform-test --timeout=180s
kubectl --context=k3d-test get pod -l app.kubernetes.io/name=<svc> -n platform-test \
  -o jsonpath='{.items[0].status.containerStatuses[0].imageID}'
```

### Sequential rollout stuck (ResourceQuota)

PR #294 maxSurge=0/maxUnavailable=1 8 backend deployment'a uygulandı.
ResourceQuota baskısı yok artık. Gene fail görülürse quota durumu:

```bash
kubectl --context=k3d-test describe quota platform-quota -n platform-test
```

### Gate 1b fail (edge chain BROKEN)

5xx veya 0xx → ingress, host nginx, veya gateway pod down.
- `kubectl get pod -l app.kubernetes.io/name=api-gateway -n platform-test`
- `kubectl logs deployment/api-gateway -n platform-test --tail=50`
- `ssh halil@staging-sw "docker exec platform-web-nginx nginx -t"`

### Gate 1c fail (readiness probe)

Spring Boot Actuator `/actuator/health/readiness` management port 8081'de.
Servis startup yavaşsa rollout-status PASS olabilir ama readiness probe
FAIL. JVM heap genişletme veya readiness probe `initialDelaySeconds`
artırma gerek olabilir.

### Gate 2 fail (JWT auth)

Test persona credentials secret'ları:
- `SMOKE_AUTH_USERNAME`
- `SMOKE_AUTH_PASSWORD`

CLAUDE.md HARD RULE: kullanıcı login user'ına dokunma; ayrı test persona
zorunlu. Keycloak'ta read-only viewer role oluştur, GitHub repo secret
olarak ekle.

## Drift guard

Dispatch chain etkin mi?
```bash
# platform-backend ci-image-push son run + dispatch step
gh run list --workflow=ci-image-push.yml -R Halildeu/platform-backend --limit=1 \
  --json conclusion,status,event

# gitops deploy-backend-testai son run
gh run list --workflow=deploy-backend-testai.yml -R Halildeu/platform-k8s-gitops --limit=3 \
  --json status,conclusion,event
```

Digest-pin mode aktif mi (log inspeksiyonu)?
```bash
JOB_ID=$(gh run view <run-id> -R Halildeu/platform-k8s-gitops --json jobs --jq '.jobs[0].databaseId')
gh api "repos/Halildeu/platform-k8s-gitops/actions/jobs/${JOB_ID}/logs" \
  | grep -E "Digest-pin mode active|Tag-based fallback"
```

## Out-of-scope (follow-up)

- **B.5** — Slack/PagerDuty paging receiver (iter-49 B.2 PR #291 warning
  rule'lar pre-prod; receiver netleşince severity=critical paging ekle)
- **endpoint-admin-service** + **discovery-server** dahil etme — manifest
  contract netleşince ayrı PR (Faz 22)
- **Production deploy** — `deploy-backend-prod.yml` workflow_dispatch
  + GitHub environment approval (D30 atomic cutover öncesi)
- **Multi-replica pod doğrulama** — şu an replicas=1; prod scale 2+
  olduğunda Gate 1a "all non-terminating Running pods digest match" gate'e
  dönüştürülmeli (Codex 019de00f öneri)

## Codex thread'leri

- `019ddf43-e6eb-7dd0-9c30-d6c9b867e5dd` — initial cycle (B.3 chain)
- `019de00f-4b40-75c1-8ead-01b79c5819c1` — post-iter-49 PARTIAL review
  (#1 backend race fix + #2 strict digest mode)

## Cycle close PR'ları

| PR | Konu |
|---|---|
| #292 | Initial workflow + runbook |
| #293 | Skopeo bypass tag-based |
| #294 | maxSurge=0 generalize 8 backend |
| #295 | Gate 1b 200/401/403 healthy |
| #296 | Digest-pin mode initial |
| #297 | String-form digest normalize |
| backend #54 | Per-service digest aggregation |
| #301 | Backend pod capture race + strict digest mode |
