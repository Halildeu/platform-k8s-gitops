# gha-runner — Self-hosted GitHub Actions runner (staging-sw)

> iter-50 Step 3.4a — testai-deploy event'leri için tek amaçlı self-hosted runner.

## Bağlam

`platform-k8s-gitops/.github/workflows/deploy-testai.yml` workflow'u `runs-on: [self-hosted, staging-sw, testai-deploy]` etiketli runner bekler. GitHub-hosted runner'lar staging-sw'nin private intranet'ine ulaşamadığı için (`10.9.10.53`, `kubectl k3d-test`, `host nginx mount`) self-hosted runner zorunlu.

Codex `019dded6` S1 sertleştirmesi:
- **Tek amaçlı runner**: sadece testai-deploy event'leri için, label-fenced
- **`docker.sock` NO mount**: deploy işi container build / job-container çalıştırmamalı
- **Mount'lar**: kubeconfig RO + `/home/halil/platform/web-stage/releases` RW
- **Ephemeral mode**: her job sonrası container restart, yeni registration token

## Kurulum (one-time setup)

### 1. PAT (platform-web → gitops dispatch için)

> Bu PAT runner'a değil, platform-web'in dispatch step'ine gerekli. Runner'a registration token gerek (aşağıda).

1. GitHub UI: Settings → Developer settings → Personal access tokens → Fine-grained tokens
2. **Generate new token**:
   - Token name: `platform-web → gitops dispatch`
   - Expiration: 1 yıl (veya policy'ye göre)
   - Repository access: **Only select repositories** → `Halildeu/platform-k8s-gitops`
   - Repository permissions: **Contents: Write** (Codex S2 — repository_dispatch endpoint için yeter)
3. Token'ı kopyala
4. **platform-web** repo'sunda: Settings → Secrets and variables → Actions → New repository secret
   - Name: `GITOPS_DISPATCH_PAT`
   - Value: yapıştır

### 2. Runner image build + start

staging-sw'de:

```bash
# 1. Repo clone
ssh halil@staging-sw
cd /home/halil/platform
git clone git@github.com:Halildeu/platform-k8s-gitops.git
cd platform-k8s-gitops/gha-runner

# 2. .env doldur
cp .env.example .env

# 3. Registration token al:
#    GitHub UI: platform-k8s-gitops repo → Settings → Actions → Runners
#                → New self-hosted runner → Linux x64
#    Çıkan registration token'ı kopyala (1h geçerli)
#    .env içine RUNNER_REGISTRATION_TOKEN=... yapıştır
vim .env

# 4. Image build + container up
docker compose build
docker compose up -d

# 5. GitHub UI: Settings → Actions → Runners
#    `staging-sw-testai-deploy` runner online görünmeli (yeşil nokta)
```

### 3. Verify (manual workflow_dispatch test)

```bash
# Local makinede:
gh workflow run deploy-testai.yml -R Halildeu/platform-k8s-gitops \
  -f sha=<full-40-char> \
  -f short_sha=<7-char> \
  -f image_digest=sha256:<64-char>

# Workflow run'ı izle:
gh run watch -R Halildeu/platform-k8s-gitops
```

Beklenen: 4 verify gate koşar (1a, 1b, 1c pass; Gate 2 secret yoksa skip).

## Ops

### Runner restart

```bash
ssh halil@staging-sw
cd /home/halil/platform/platform-k8s-gitops/gha-runner
docker compose restart runner
```

### Yeni registration token (token expired)

Registration token 1h geçerli. Container restart'ta runner yeniden register olur (ephemeral). Token expire olduysa:

1. GitHub UI'da yeni token al (yukarıdaki adım 3)
2. `.env` dosyasında `RUNNER_REGISTRATION_TOKEN` güncelle
3. `docker compose up -d` (otomatik restart)

### Runner image upgrade

```bash
ssh halil@staging-sw
cd /home/halil/platform/platform-k8s-gitops
git pull
cd gha-runner
docker compose build --no-cache
docker compose up -d
```

### Logs

```bash
docker compose logs -f runner --tail=100
```

### Runner unregister (cleanup)

```bash
docker compose down  # entrypoint.sh trap unregister yapar
```

## Önemli notlar

- **`docker.sock` NO mount**: docker-compose.yml içinde özellikle silinmiş. Codex S1: deploy işi container build/job çalıştırmamalı; runner sadece kubectl + rsync + curl + jq ile çalışır.
- **Network mode: host**: kubeconfig'in API URL'i `https://localhost:RANDOM` ise host network gerek (k3d-test default). Bridge yetersiz olabilir.
- **Ephemeral mode**: `--ephemeral` flag ile her job sonrası container restart. Bu hem güvenlik (state pollution riski azalır) hem upgrade için kolaylık.
- **`/home/halil/platform/web-stage/releases` RW**: runner host'taki releases dir'e yazıyor (rsync target). Permission'lar host'ta runner UID (1000) için writable olmalı. Default `halil:halil` ile `halil` UID 1000 ise sorun yok.
- **Test persona**: Gate 2 (Playwright dblclick smoke) için `SMOKE_AUTH_USERNAME` + `SMOKE_AUTH_PASSWORD` secret'ları gitops repo'ya ekle. Yoksa Gate 2 skip eder. CLAUDE.md HARD RULE — kullanıcı login user'ının şifresine dokunma; ayrı persona zorunlu.

## İlişkili dosyalar

- `.github/workflows/deploy-testai.yml` — workflow consumer
- `docs/runbook-testai-deploy.md` — full ops runbook
- `platform-web/.github/workflows/ci-web-image-push.yml` — dispatch tetikleyici (PR #133)
- `platform-web/scripts/deploy/build-single-domain.mjs` — build-info.json sentinel writer (PR #132)
