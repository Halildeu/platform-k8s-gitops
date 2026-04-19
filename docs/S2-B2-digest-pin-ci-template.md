# S2-B2 Digest Pin CI Template — platform-ssot deploy-backend.yml Revize

> **Source:** Codex Tur A3 + S2-B artifact hardening (2026-04-19)
> **Target:** platform-ssot `.github/workflows/deploy-backend.yml` revize + K8s-gitops kustomize edit
> **Goal:** D30 Immutable Artifact HARD RULE uyumu — her build sonrası K8s-gitops overlay'e immutable tag (`sha-<short>`) push

---

## 1. Mevcut Durum

**platform-ssot deploy-backend.yml (K8s-6 önceki ping-pong tespiti):**
- Satır 117: `main-stable` tag push ✅
- Satır 135: `sha-<short>` tag push ✅
- Satır 212: deploy job'da `sha-<short>` kullanımı ✅

**K8s-gitops overlay durumu:**
- `test + prod` overlay 7 servis `newTag: main-stable` (moving tag — **D30 ihlal**)
- Pilot: `permission-service` `newTag: sha-3923901` (S1-C14/C15)

**Hedef:** Platform-ssot build sonunda **K8s-gitops overlay'deki tag'i otomatik güncelle** → `main-stable` → `sha-<new_short>`.

## 2. CI Workflow Eklenti Şablonu

### 2.1 Yeni Job: `bump-gitops-overlay`

`platform-ssot/.github/workflows/deploy-backend.yml` sonuna (deploy job'dan sonra):

```yaml
bump-gitops-overlay:
  name: Bump K8s-gitops overlay tag
  runs-on: ubuntu-latest
  needs: [build, push]  # deploy-backend mevcut job'lar
  if: github.ref == 'refs/heads/main'  # sadece main push
  permissions:
    contents: write   # K8s-gitops repo'ya commit için
  steps:
    - name: Checkout platform-k8s-gitops
      uses: actions/checkout@v4
      with:
        repository: Halildeu/platform-k8s-gitops
        ref: main
        token: ${{ secrets.GITOPS_DEPLOY_PAT }}  # Cross-repo PAT
        path: gitops

    - name: Setup kustomize
      run: |
        curl -sL "https://raw.githubusercontent.com/kubernetes-sigs/kustomize/master/hack/install_kustomize.sh" | bash
        sudo mv kustomize /usr/local/bin/

    - name: Update overlay image tags
      working-directory: gitops/kustomize/overlays/test
      run: |
        SHORT_SHA=$(echo ${{ github.sha }} | cut -c1-7)
        SERVICES=(auth-service api-gateway user-service variant-service core-data-service report-service schema-service permission-service)
        for svc in "${SERVICES[@]}"; do
          kustomize edit set image ${svc}=ghcr.io/halildeu/platform-ssot-${svc}:sha-${SHORT_SHA}
        done

    - name: Update prod overlay (aynı commit)
      working-directory: gitops/kustomize/overlays/prod
      run: |
        SHORT_SHA=$(echo ${{ github.sha }} | cut -c1-7)
        SERVICES=(auth-service api-gateway user-service variant-service core-data-service report-service schema-service permission-service)
        for svc in "${SERVICES[@]}"; do
          kustomize edit set image ${svc}=ghcr.io/halildeu/platform-ssot-${svc}:sha-${SHORT_SHA}
        done

    - name: Commit + push
      working-directory: gitops
      run: |
        git config user.name "platform-ssot-bot"
        git config user.email "noreply@acik.com"
        SHORT_SHA=$(echo ${{ github.sha }} | cut -c1-7)
        git add kustomize/overlays/test/kustomization.yaml kustomize/overlays/prod/kustomization.yaml
        if git diff --cached --quiet; then
          echo "No overlay changes — skip commit"
        else
          git commit -m "feat(auto): bump image tags to sha-${SHORT_SHA} [skip ci]"
          git push origin main
        fi
```

### 2.2 Alternatif: Digest Pin (`@sha256:...`)

`sha-<short>` yerine tam digest pin kullanılmak istenirse (D30 strict):

```bash
DIGEST=$(docker manifest inspect ghcr.io/halildeu/platform-ssot-${svc}:sha-${SHORT_SHA} \
  --platform linux/amd64 | jq -r '.config.digest')
kustomize edit set image ${svc}=ghcr.io/halildeu/platform-ssot-${svc}@${DIGEST}
```

**Tradeoff:**
- `sha-<short>` — human-readable, git commit traceable, tag değişmezlik CI'ın elinde
- `@sha256:...` — content-addressable, tam immutable, ama unreadable

**Codex önerisi:** `sha-<short>` bugün yeterli (D30 pilot pattern), full digest ileri iyileştirme.

## 3. K8s-gitops Tarafı

### 3.1 Overlay Auto-bump Sonrası

ArgoCD varsa (S2-C1 install sonrası): auto-sync ile yeni image tag cluster'a propagate olur (test için).

ArgoCD yoksa (mevcut durum): K8s-6 session'da manuel sync — `kubectl apply -k overlays/test`.

### 3.2 Rollback

Image tag yeni commit'e bump edildi ama canlı regression varsa:
```bash
git revert <bump-commit>  # K8s-gitops'ta
git push origin main
# ArgoCD otomatik geri alır veya manuel kubectl apply
```

## 4. Secret Requirements

### 4.1 `GITOPS_DEPLOY_PAT`

platform-ssot repo secret:
- `GITOPS_DEPLOY_PAT` — GitHub PAT, scope: `repo` (K8s-gitops private), fine-grained token recommended
- Vault path (opsiyonel): `kv/platform/ci/gitops-pat` (CI runner vault-login ile çekebilir)

### 4.2 Alternatif: GitHub App

- GitHub App (organization-wide): installationAccessToken → ephemeral, daha güvenli
- Setup: K8s-gitops repo'ya App install + permission `contents:write`

## 5. Kabul Kriteri

- [ ] platform-ssot deploy-backend.yml `bump-gitops-overlay` job eklenmiş
- [ ] Her main push sonrası K8s-gitops'a commit atılıyor (`sha-<short>` bump)
- [ ] K8s-gitops overlay test+prod 7 servis `newTag: sha-<short>`, 0 `main-stable`
- [ ] Infinite loop yok (`[skip ci]` flag — K8s-gitops commit'i platform-ssot workflow'u tetiklemez)

## 6. Codex İstişare (apply öncesi)

Küçük CI değişikliği ama cross-repo + PAT secret + commit loop risk. Codex pre-apply ping-pong:
- PAT scope minimum
- Cross-repo commit atomic (auth + api-gateway ayrı commit DEĞİL)
- `[skip ci]` flag çalışıyor mu (K8s-gitops'un CI'ı yoksa gereksiz)

## 7. Prompt (platform-ssot CI engineer'a)

```
TASK: S2-B2 Digest Pin CI — auto-bump K8s-gitops overlay
From: K8s-6 S2 scope

Detay: platform-k8s-gitops/docs/S2-B2-digest-pin-ci-template.md

Özet: .github/workflows/deploy-backend.yml sonuna bump-gitops-overlay job
ekle. Her main push sonrası K8s-gitops overlay test+prod kustomize edit set
image sha-<short>. GITOPS_DEPLOY_PAT secret + [skip ci] loop flag.

Kabul: K8s-gitops overlay main-stable yok, sha-<short> tag 8 servis için.
Codex ping-pong apply öncesi (PAT scope + atomic commit).
```
