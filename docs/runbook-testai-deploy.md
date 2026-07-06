# Runbook — testai.acik.com Auto-Deploy

> iter-50 Step 3.3 — `repository_dispatch` ile platform-web image push'undan testai.acik.com'a otomatik deploy.
>
> **iter-50 Step 5 B (Tier 2) update**: Host nginx static mount artık yok. Edge proxy SNI routing (`host-compose/proxy/conf/nginx.conf`) testai → k3d-test ingress yapıyor; pod doğrudan serve ediyor.

## Bağlam (Tier 2 — current state)

`testai.acik.com` artık tek yerden servis edilir:

```
DNS testai.acik.com → 10.9.10.53 (staging-sw)
  → host edge proxy nginx :443 (host-compose/proxy)
    → SNI routing: testai → http://test_k3d_ingress (127.0.0.1:31080)
      → k3d-test ingress-nginx-controller
        → platform-test/platform Ingress
          → /     → frontend:80 (pod nginx static serve)
          → /api  → api-gateway:8080
          → /auth → api-gateway:8080
          → /actuator, /users, /variants, /core, /reports, /schemas → api-gateway:8080
```

Host static mount path (`/home/halil/platform/web-stage/releases/ac35567`) ve `platform-web-nginx-stage` container artık **trafik almıyor** (Step 5 B keşif kanıtı: container down + testai yine 200 döner). Cleanup runbook aşağıda.

## Legacy (pre-Step 5 B, sadece referans)

Eski yapı host nginx Docker container `platform-web-nginx-stage` üzerinden static serve yapıyordu — bu artık geçerli değil; commit history'de yer alıyor (PR #283 baseline).

## Workflow trigger

Platform-web `ci-web-image-push.yml` testai variant SUCCESS sonra `gh api repos/.../dispatches` ile event_type=`testai-deploy` fırlatır. Payload:

```json
{
  "sha": "<full 40-char>",
  "short_sha": "<7-char>",
  "ref": "main",
  "image": "ghcr.io/halildeu/platform-web-frontend-testai",
  "image_tag": "sha-XXXXXXX",
  "image_digest": "sha256:..."
}
```

Bu repo'da `.github/workflows/deploy-testai.yml` dinler ve self-hosted runner'da koşar.

## Verify chain (4 gate)

Workflow her deploy'da 4 gate koşar (**Step 5 B sonrası: 5. step "Sync host nginx static" kaldırıldı**):

| Gate | İçerik | Fail davranışı |
|---|---|---|
| 1a | Pod imageID digest == GHCR manifest digest (containerd `docker-pullable://...@sha256:...` normalize) | fail-fast (rollout başarısız sayılır) |
| 1b | `/index.html` 200 + `/assets/<rootEntry>` 200 (edge proxy → k3d ingress → frontend pod) | fail-fast |
| 1c | `/build-info.json` JSON parse + `.sha == expected` (pod doğrudan serve) | fail-fast (eğer JSON yoksa warn-only — pre-Step-2 image fallback) |
| 2 | Playwright login → `/admin/users` → row dblclick → `[role="dialog"]` | warn-only eğer secret yoksa; secret varsa fail |

## İlk kurulum (one-time setup)

### 1. Self-hosted runner staging-sw'de

Custom runner image (Step 3.4 ayrı PR ile gelecek) preinstall:
- `actions/runner` (GitHub Actions)
- `kubectl` (k3d-test context erişimi)
- `rsync`, `curl`, `jq`, `skopeo`, `gh`
- Playwright + Chromium (Gate 2 için)

Mount'lar:
- `~/.kube/config` → `/home/runner/.kube/config` (read-only)
- `/home/halil/platform/web-stage/releases` → `/home/halil/platform/web-stage/releases` (read-write)
- **NOT mount**: `/var/run/docker.sock` — Codex 019dded6 S1 sertleştirme: deploy işi container build/job-container çalıştırmamalı.

Labels: `self-hosted`, `staging-sw`, `testai-deploy`.

Runner lifecycle:
```bash
# 1. staging-sw'de:
ssh halil@staging-sw

# 2. Runner image build + run
cd /home/halil/platform/platform-k8s-gitops/gha-runner

# 3. Önce GitHub API egress preflight. Bu fail ise runner'ı başlatma;
#    container registration-token fetch loop'una girmemeli.
curl -fsS --connect-timeout 5 --max-time 8 -I https://api.github.com | head -1

# 4. RUNNER_PAT .env'de least-privilege PAT olarak bulunur; registration token
#    entrypoint tarafından API'den fresh alınır.
docker compose up -d
```

Detaylı kurulum ve PAT ayrımı: `gha-runner/README.md`.

### 2. PAT (platform-web → gitops dispatch için)

Platform-web tarafından gitops repo'suna `repository_dispatch` event göndermek için **fine-grained PAT** lazım.

Kullanıcı GitHub UI'da:

1. Settings → Developer settings → Personal access tokens → Fine-grained tokens
2. **Generate new token**:
   - Token name: `platform-web → gitops dispatch`
   - Expiration: 1 yıl (veya policy'ye göre)
   - Repository access: **Only select repositories** → `Halildeu/platform-k8s-gitops`
   - Repository permissions: **Contents: Write** (Codex 019dded6 S2 — repository_dispatch endpoint için bu scope yeter; Actions: write değil)
3. Token'ı kopyala
4. **platform-web** repo'sunda: Settings → Secrets and variables → Actions → New repository secret
   - Name: `GITOPS_DISPATCH_PAT`
   - Value: yapıştır

PAT yoksa: ci-web-image-push.yml dispatch step warning verip skip eder, fail değil. Manuel rsync (acil-fix) yine çalışır.

### 3. (Opsiyonel) Behavior smoke için test persona

Gate 2 için Keycloak'ta read-only test persona (CLAUDE.md HARD RULE: kullanıcı login user'ına dokunmama):

```bash
# Keycloak admin REST ile (örnek; adjust as needed)
ssh halil@staging-sw
KC_ADMIN_TOKEN=$(curl -sk -X POST \
  "https://testai.acik.com/realms/master/protocol/openid-connect/token" \
  -d "grant_type=password" \
  -d "client_id=admin-cli" \
  -d "username=admin" \
  -d "password=$KC_ADMIN_PWD" | jq -r .access_token)

# Persona oluştur
curl -sk -X POST \
  "https://testai.acik.com/admin/realms/platform-test/users" \
  -H "Authorization: Bearer $KC_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "testai-smoke",
    "enabled": true,
    "credentials": [{
      "type": "password",
      "value": "<random secret>",
      "temporary": false
    }]
  }'

# Read-only role grant (örn. "viewer")
# ...
```

Gitops repo secret'ları:
- `SMOKE_AUTH_USERNAME=testai-smoke`
- `SMOKE_AUTH_PASSWORD=<random secret>`

Secret yoksa Gate 2 skip eder (warn-only).

## Manuel deploy (acil-fix / re-trigger)

### Manual `workflow_dispatch`

```bash
gh workflow run deploy-testai.yml \
  -f sha=<full-40-char> \
  -f short_sha=<7-char> \
  -f image_digest=sha256:<64-char>
```

### Manuel kubectl set image (runner down ise)

Step 5 B (Tier 2) sonrası rsync gereksiz; pod imageID set edilir, edge proxy otomatik yansıtır:

```bash
ssh halil@staging-sw '
EXPECTED_DIGEST=sha256:<64-char>
kubectl --context=k3d-test set image deployment/frontend \
  frontend=ghcr.io/halildeu/platform-web-frontend-testai@${EXPECTED_DIGEST} \
  -n platform-test
kubectl --context=k3d-test rollout status deployment/frontend -n platform-test --timeout=300s

# Verify (pod doğrudan serve eder, edge proxy → k3d ingress)
curl -sk https://testai.acik.com/build-info.json | jq -r .sha
'
```

### Step 5 B legacy cleanup (one-time, manuel)

`platform-web-nginx-stage` container ve `/home/halil/platform/web-stage/` dizini artık trafik almıyor (edge proxy SNI routing testai → k3d ingress). One-time cleanup:

```bash
ssh halil@staging-sw '
# 1. Legacy stage container'ı durdur + sil (manuel run, compose-managed değil)
docker stop platform-web-nginx-stage 2>/dev/null || true
docker rm platform-web-nginx-stage 2>/dev/null || true

# 2. Legacy releases dizini (artık kullanılmıyor)
# DİKKAT: tek-yönlü silme. Önce backup almak isterseniz tar -czf
sudo rm -rf /home/halil/platform/web-stage/releases/
sudo rm -rf /home/halil/platform/web-stage/current
# nginx config'i isteğe bağlı:
# sudo rm -rf /home/halil/platform/web-stage/nginx/

# 3. Verify testai still serves correctly
curl -sk https://testai.acik.com/build-info.json | jq -r .sha
'
```

Cleanup sonrası tek path: edge proxy → k3d ingress → frontend pod. Drift guard: docker inspect platform-web-nginx-stage → "No such object" (silinmiş kanıtı).

## Failure recovery

### Gate 1a fail (digest mismatch)

**Sebep**: Pod yeni image'ı pull etmedi ya da kubectl set image yanlış digest.

**Recovery**:
```bash
ssh halil@staging-sw
kubectl --context=k3d-test rollout restart deployment/frontend -n platform-test
kubectl --context=k3d-test rollout status deployment/frontend -n platform-test --timeout=300s
# Workflow'u re-run et
```

### Gate 1c fail (build-info.json sha mismatch)

**Sebep**: Image'da Step 2 sentinel var ama BUILD_SHA build-arg geçilmemiş (Step 3.1 PR pre-merge image).

**Recovery**: PR #133 (Step 3.1+3.2) merge edilince çözülür. Geçici warning OK.

### Gate 2 fail (Playwright dblclick)

**Sebep**: 
- (a) DS regression — drawer açılmıyor;
- (b) Auth flow değişmiş — login fail;
- (c) Selector kaymış — `[role="dialog"]` yerine başka query gerek.

**Recovery**: Test persona kontrol et, Playwright trace artifact'a bak (workflow run artifacts).

### Runner offline

**Sebep**: Docker container down, GitHub API egress kapalı, veya `RUNNER_PAT` scope/expiry sorunu.

**Recovery**:
```bash
ssh halil@staging-sw
cd /home/halil/platform/platform-k8s-gitops/gha-runner
docker compose ps
docker compose logs --tail=100 runner

# Önce egress preflight; bu fail ise runner'ı restart etme.
curl -fsS --connect-timeout 5 --max-time 8 -I https://api.github.com | head -1

# Egress OK ise restart.
docker compose restart runner

# PAT expired/scope invalid ise:
# GitHub UI'da yeni least-privilege RUNNER_PAT üret
# .env dosyasında RUNNER_PAT değerini güncelle
# docker compose restart runner
```

## Step 5 B — Tier 2 (current state)

Step 5 B keşif kanıtı (2026-04-30):

1. Edge proxy nginx (`host-compose/proxy/conf/nginx.conf`) zaten testai → k3d-test ingress (`http://test_k3d_ingress` = 127.0.0.1:31080) SNI routing yapıyor.
2. K3d-test cluster ingress (`platform-test/platform`) zaten 9 gündür kurulu: `/` → frontend:80, `/api/auth/users/...` → api-gateway:8080. TLS: ingress kendi cert (default veya secret).
3. `platform-web-nginx-stage` container DURDURULDU + testai 200 dönmeye devam etti → container legacy artık.
4. Pod imageID Gate 1a guarantee + edge proxy direct ingress = host static rsync gereksiz.

Bu sebeple A/B/C kademe planı **gereksiz**: Tier 2 mimari zaten gerçekleşmiş. Cleanup adımları yukarıdaki "Step 5 B legacy cleanup" bölümünde.

## Drift guard

Step 5 B Tier 2 sonrası periyodik kontroller:

```bash
ssh halil@staging-sw '
# 1. Edge proxy testai → k3d ingress yönlendirmesi aktif mi?
grep -A 5 "testai.acik.com" /home/halil/platform/platform-k8s-gitops/host-compose/proxy/conf/nginx.conf | grep proxy_pass

# 2. K3d ingress çalışıyor mu?
kubectl --context=k3d-test get ingress -n platform-test platform

# 3. Stage container silinmiş mi (drift kanıtı)?
docker inspect platform-web-nginx-stage 2>&1 | grep -q "No such object" && echo "OK: stage removed" || echo "DRIFT: stage container still exists"

# 4. End-to-end (edge proxy → ingress → pod) hala 200 mu?
curl -sk https://testai.acik.com/build-info.json | jq -r .sha
'
```

Çıktıda `/home/halil/platform/web-stage/releases/ac35567` yoksa runbook + `deploy-testai.yml` env güncellemeli.

## Codex referansları

- 019dded6 plan-time iter (REVISE → PARTIAL+ready_for_impl=true)
- Sertleştirmeler: docker.sock NO mount, fine-grained PAT scope (Contents: Write), digest pin format `image@sha256:...`, pod imageID normalize (containerd suffix-match), atomic refresh `--delete-delay --delay-updates`, behavior smoke opt-in if secret hazır.

## İlişkili dosyalar

- `.github/workflows/deploy-testai.yml` (bu workflow)
- `platform-web/.github/workflows/ci-web-image-push.yml` (dispatch tetikleyici)
- `platform-web/Dockerfile` (BUILD_SHA build-arg)
- `platform-web/scripts/deploy/build-single-domain.mjs` (build-info.json sentinel)
- `gha-runner/` (Step 3.4 PR — self-hosted runner image template)
