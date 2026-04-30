# Runbook — testai.acik.com Auto-Deploy

> iter-50 Step 3.3 — `repository_dispatch` ile platform-web image push'undan testai.acik.com'a otomatik deploy.

## Bağlam

`testai.acik.com` üç ayrı yerden servis edilir:

1. **k3d-test pod** (`platform-test/frontend` Deployment) — kubectl set image hedefi.
2. **Host nginx Docker container** (`platform-web-nginx-stage`) — `/usr/share/nginx/html` bind mount: `/home/halil/platform/web-stage/releases/ac35567`. Kullanıcının browser'ı buradan servis alır.
3. **`current` symlink** — `/home/halil/platform/web-stage/current` → `releases/<sha>`. Mount path henüz takip etmiyor (Step 5 long-term refactor).

**Kritik**: Mount path **hardcoded** `releases/ac35567`. Yeni release dir oluşturmak yetmez; hardcoded path'e mirror etmek zorunlu. Atomic mv -T riskli (Docker bind mount inode'a bağlanabilir; container restart isterdi).

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

Workflow her deploy'da 4 gate koşar:

| Gate | İçerik | Fail davranışı |
|---|---|---|
| 1a | Pod imageID digest == GHCR manifest digest (containerd `docker-pullable://...@sha256:...` normalize) | fail-fast (rollout başarısız sayılır) |
| 1b | `/index.html` 200 + `/assets/<rootEntry>` 200 | fail-fast |
| 1c | `/build-info.json` JSON parse + `.sha == expected` | fail-fast (eğer JSON yoksa warn-only — pre-Step-2 image fallback) |
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

Runner registration:
```bash
# 1. GitHub UI'da:
#    Settings → Actions → Runners → New self-hosted runner
#    Architecture: linux x64
#    Bir registration token üretilir (~1h geçerli)

# 2. staging-sw'de:
ssh halil@staging-sw

# 3. Runner image build + run (Step 3.4 PR ile gelecek docker-compose)
cd /home/halil/platform/gha-runner
docker compose up -d

# 4. İlk start'ta runner registration token'ı sor — env file'a koyula bilir
```

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

### Tam manual rsync (runner down ise)

```bash
ssh halil@staging-sw 'set -euo pipefail
POD=$(kubectl --context=k3d-test get pod -n platform-test -l app.kubernetes.io/name=frontend -o jsonpath="{.items[0].metadata.name}")
SHA_SHORT=<7-char>
TMP=/tmp/web-deploy-$SHA_SHORT-$$
RELEASE_DIR=/home/halil/platform/web-stage/releases/$SHA_SHORT
HARDCODED=/home/halil/platform/web-stage/releases/ac35567

kubectl --context=k3d-test cp platform-test/$POD:/usr/share/nginx/html $TMP
mkdir -p $RELEASE_DIR
rsync -a --delete $TMP/ $RELEASE_DIR/
ln -snf $RELEASE_DIR /home/halil/platform/web-stage/current
rsync -a --delete --delay-updates --delete-delay $RELEASE_DIR/ $HARDCODED/
rm -rf $TMP

# Verify
HOST_ENTRY=$(grep -oE "index-[A-Za-z0-9_-]+\.js" $HARDCODED/index.html | head -1)
echo "HOST entry: $HOST_ENTRY"
curl -sk https://testai.acik.com/build-info.json | jq -r .sha
'
```

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

**Sebep**: Docker container down, network issue, runner token expired.

**Recovery**:
```bash
ssh halil@staging-sw
cd /home/halil/platform/gha-runner
docker compose ps
docker compose logs --tail=100 runner
# Restart eğer gerek
docker compose restart runner

# Token expired ise:
# GitHub UI'da yeni registration token al
# .env dosyasına yapıştır
docker compose down && docker compose up -d
```

## Step 5 long-term refactor (defer)

Mount path hardcode'unu kaldırma seçenekleri:

**A) Mount → "current" symlink** (kısa-orta vade):
```yaml
# docker-compose.yml host nginx
volumes:
  - /home/halil/platform/web-stage/current:/usr/share/nginx/html:ro
```
Riski: container bind mount inode resolution; symlink follow her container'da farklı olabilir. Test gerek.

**B) testai → k3d ingress + LB** (uzun vade):
- Host nginx tamamen kaldır
- k3d-test ingress controller + ExternalDNS
- Çift-surface deploy ortadan kalkar

**C) Status quo + auto-rsync** (Codex 019dded6 değerlendirmesi: "sadece geçici"):
- Mevcut Step 3 yeterli
- Mount refactor opt out

Karar ADR-level (Codex tercihi: A → B → C az tercihli).

## Drift guard

Bu runbook'un hardcoded path'ı (`releases/ac35567`) gerçeği yansıtıyor mu, periyodik kontrol:

```bash
ssh halil@staging-sw 'docker inspect platform-web-nginx-stage --format "{{range .Mounts}}{{.Type}} {{.Source}} -> {{.Destination}}{{println}}{{end}}"'
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
