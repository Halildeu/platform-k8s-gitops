# gha-runner — Self-hosted GitHub Actions runner (aiserver)

> iter-50 Step 3.4a — testai-deploy event'leri için tek amaçlı self-hosted runner.

## Bağlam

`platform-k8s-gitops` deployment workflow'ları `runs-on: [self-hosted, aiserver, testai-deploy]` etiketli runner bekler. GitHub-hosted runner'lar aktif platformun private intranet'ine ulaşamadığı için (`10.9.10.15`, `kubectl k3d-test`, `host nginx mount`) self-hosted runner zorunlu.

Codex `019dded6` S1 sertleştirmesi:
- **Tek amaçlı runner**: sadece testai-deploy event'leri için, label-fenced
- **`docker.sock` NO mount**: deploy işi container build / job-container çalıştırmamalı
- **Mount'lar**: kubeconfig RO + `/srv/platform/web-stage/releases` RW
- **Ephemeral mode**: her job sonrası container restart, yeni registration token
- **Secret-safe token fetch**: `RUNNER_PAT` curl process argümanına konmaz;
  GitHub API egress kapalıysa bounded backoff ile bekler.

## Kurulum (one-time setup)

### İki ayrı PAT gerek (least-privilege ayrımı)

#### PAT #1 — `GITOPS_DISPATCH_PAT` (platform-web → gitops dispatch)

> Bu PAT platform-web repo'da secret olarak saklanır. Runner'a değil, platform-web'in dispatch step'ine gerekli.

1. GitHub UI: Settings → Developer settings → Personal access tokens → Fine-grained tokens
2. **Generate new token**:
   - Token name: `platform-web → gitops dispatch`
   - Expiration: 1 yıl
   - Repository access: **Only select repositories** → `Halildeu/platform-k8s-gitops`
   - Repository permissions: **Contents: Write** (Codex S2 — repository_dispatch endpoint için)
3. Token'ı kopyala
4. **platform-web** repo'sunda: Settings → Secrets and variables → Actions → New repository secret
   - Name: `GITOPS_DISPATCH_PAT`
   - Value: yapıştır

#### PAT #2 — `RUNNER_PAT` (runner entrypoint → registration-token endpoint)

> Bu PAT aiserver host'ta `.env` dosyasında saklanır. Codex 019dded6 ek sertleştirme: `--ephemeral` runner her start'ta TAZE registration token alır; PAT bunu API'den fetch etmeyi sağlar.

1. GitHub UI: Settings → Developer settings → Personal access tokens → Fine-grained tokens
2. **Generate new token**:
   - Token name: `aiserver runner → registration-token`
   - Expiration: 1 yıl
   - Repository access: **Only select repositories** → `Halildeu/platform-k8s-gitops`
   - Repository permissions: **Administration: Write** (`POST /repos/.../actions/runners/registration-token` endpoint için)
   - Repository permissions: **Metadata: Read** (default, gerekli)
3. Token'ı kopyala (sonraki adımda `.env`'e yapıştır)

### Runner image build + start

aiserver üzerinde:

```bash
# 1. Repo clone
ssh aiadmin@aiserver
cd /srv/platform/gitops
git clone git@github.com:Halildeu/platform-k8s-gitops.git
cd platform-k8s-gitops/gha-runner

# 2. .env doldur
cp .env.example .env
# RUNNER_PAT=<PAT #2 from yukarıda>
# (RUNNER_REPO, RUNNER_NAME, RUNNER_LABELS default OK)
vim .env

# 3. GitHub API egress preflight
curl -fsS --connect-timeout 5 --max-time 8 -I https://api.github.com | head -1
# Beklenen: HTTP/2 200 veya HTTP/1.1 200

# 4. Image build + container up
docker compose build
docker compose up -d

# 5. Logs ile runner registration kontrol
docker compose logs -f runner --tail=50
# Beklenen: "[entrypoint] Registered: aiserver-testai-deploy (labels: ...)"

# 6. GitHub UI: Settings → Actions → Runners
#    `aiserver-testai-deploy` runner online görünmeli (yeşil nokta)
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
ssh aiadmin@aiserver
cd /srv/platform/gitops/platform-k8s-gitops/gha-runner

# Önce egress preflight; bu fail ise runner'ı restart etme.
curl -fsS --connect-timeout 5 --max-time 8 -I https://api.github.com | head -1

docker compose restart runner
```

### PAT rotation (yıllık)

`RUNNER_PAT` 1 yıl geçerli (PAT generation sırasında set edilen expiration). Yenileme:

1. GitHub UI: yeni fine-grained PAT oluştur (Administration: Write scope)
2. `.env` dosyasında `RUNNER_PAT` güncelle
3. `docker compose restart runner`

> NOT: registration token (1h) entrypoint tarafından otomatik fetch edilir. Kullanıcı bu token'ı manuel doldurmak zorunda değil; PAT geçerli olduğu sürece runner kendi yenilemesini yapar.
> `RUNNER_PAT` process argümanlarına yazılmaz; entrypoint transient curl config
> dosyasını varsayılan olarak `/dev/shm` altında oluşturur ve scoped cleanup trap
> ile siler.

### Runner image upgrade

```bash
ssh halil@staging-sw
cd /srv/platform/gitops/platform-k8s-gitops
git pull
cd gha-runner

# Önce egress preflight; bu fail ise container'ı ayağa kaldırma.
curl -fsS --connect-timeout 5 --max-time 8 -I https://api.github.com | head -1

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
- **`/srv/platform/web-stage/releases` RW**: runner host'taki releases dir'e yazıyor (rsync target). Permission'lar runner servis kimliği için writable olmalı.
- **Test persona**: Gate 2 (Playwright dblclick smoke) için `SMOKE_AUTH_USERNAME` + `SMOKE_AUTH_PASSWORD` secret'ları gitops repo'ya ekle. Yoksa Gate 2 skip eder. CLAUDE.md HARD RULE — kullanıcı login user'ının şifresine dokunma; ayrı persona zorunlu.

## İlişkili dosyalar

- `.github/workflows/deploy-testai.yml` — workflow consumer
- `docs/runbook-testai-deploy.md` — full ops runbook
- `platform-web/.github/workflows/ci-web-image-push.yml` — dispatch tetikleyici (PR #133)
- `platform-web/scripts/deploy/build-single-domain.mjs` — build-info.json sentinel writer (PR #132)
