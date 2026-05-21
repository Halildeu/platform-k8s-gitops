# RB-webpush-activation — Web Push Protocol Browser Activation

> **Status**: source-ready (2026-05-21) — operator action chain for M7 T4.2 WebPush LIVE
>
> **Owner**: ops + dev (joint)
> **Scope**: browser-only Web Push (RFC 8030 + RFC 8292 VAPID); mobile FCM/APNS Faz 22.2 dep DIŞI
> **Backend chain**: 12 sub-PR MERGED (PR-W1..W7 + #649 UI integration); cluster deploy LIVE sha-aaf5f09 (defer-aware ENABLED=false)
> **Dependencies**: M3 23.2 source-side LIVE; M4 prod cutover LIVE; M5 Preference UI source-ready

## 1. Bağlam

Faz 23.7 M7 T4.2 Web Push Protocol browser-only foundation source-side tam tamamlandı:
- Backend: `WebPushAdapter` + `DefaultWebPushSender` (nl.martijndwars:web-push 5.1.1) + `PushSubscriptionController` + V19/V20 migration LIVE
- Frontend: `PushSubscriptionCard` UI component + `usePushSubscription` hook + service worker `/notification-sw.js`
- GitOps: ConfigMap WebPush 5 entries + ExternalSecret 3 entries (defer-aware comment-out)
- Cross-AI chain: Codex 019e49e7 (master plan) + 7 thread iter chain AGREE

Activation pre-cutover: Vault VAPID 3-key seed + ESO uncomment + ConfigMap `ENABLED=true` + GitHub `vars.NOTIFY_VAPID_PUBLIC_KEY` set + image bump + browser smoke.

## 2. Önkoşullar (Preflight)

### 2.1 Backend image LIVE doğrula

```bash
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  get pod -l app.kubernetes.io/name=notification-orchestrator \
  -o jsonpath='{.items[0].status.containerStatuses[0].imageID}{\"\\n\"}'"
```

Beklenen: `sha256:f3f8c497df87fd3ee394c224d7209b67714b026152c92ae119b0d8c4c16fbaf6` (sha-aaf5f09) veya sonraki digest.

### 2.2 V19 + V20 migration applied doğrula

```bash
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  exec deploy/notification-orchestrator -- \
  bash -c \"echo \\\"SELECT version FROM notify.flyway_schema_history WHERE version IN ('19','20')\\\" | PGPASSWORD=\\\$SPRING_DATASOURCE_PASSWORD psql -h postgres -U \\\$SPRING_DATASOURCE_USERNAME -d notify_db\""
```

Beklenen: 19 + 20 satırı listede; subscriber_push_endpoint table + BLOCKED_NO_PUSH_ENDPOINT enum LIVE.

### 2.3 ExternalSecret ESO state (defer-aware OK olmalı)

```bash
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  get externalsecret notification-orchestrator-secrets \
  -o jsonpath='{.status.conditions[?(@.type==\"Ready\")].status}{\"\\n\"}'"
```

Beklenen: `True`. Eğer `False`, mevcut ExternalSecret zaten broken; bu runbook'un dışında bir problem var.

## 3. Adımlar

### 3.1 VAPID anahtar çifti üret (BouncyCastle ECDSA P-256)

Backend repo'da dedicated `VapidKeygenCli` sınıfı **YOK** (bu runbook iter-1 öneri; CLI ekleme follow-up scope). Operator için **doğrulanmış 2 alternatif**:

**Seçenek A — Online web-push-codelab (önerilen, hızlı)**:
1. Tarayıcıda https://web-push-codelab.glitch.me/ aç
2. "Application Server Keys" bölümünde otomatik üretilen pair:
   - Public Key: 65-byte uncompressed P-256, base64url (88 char ~ no padding)
   - Private Key: 32-byte scalar, base64url (43 char ~ no padding)
3. ⚠️ Private key tarayıcıdan kopyalandığı an Vault'a seedlenip clipboard temizle

**Seçenek B — Offline OpenSSL (air-gapped operator)**:
```bash
# Generate EC P-256 key pair PEM format
openssl ecparam -genkey -name prime256v1 -out vapid-key.pem
# Public key extract + uncompressed 65-byte form
openssl ec -in vapid-key.pem -pubout -outform DER 2>/dev/null \
  | tail -c 65 | base64 -w 0 | tr '/+' '_-' | tr -d '='
# Private key extract + 32-byte scalar form
openssl ec -in vapid-key.pem -outform DER 2>/dev/null \
  | head -c 38 | tail -c 32 | base64 -w 0 | tr '/+' '_-' | tr -d '='
# vapid-key.pem dosyasını seed sonrası SİL (shred)
shred -u vapid-key.pem
```

⚠️ Private key gizli — sadece Vault'a seed et, log/dosyaya yazma. Clipboard'u temizle. Backend dedicated `VapidKeygenCli` follow-up issue (M8 multi-tenant pre-req'i içinde).

### 3.2 Vault'a VAPID 3-key seed (test cluster)

```bash
docker exec -e VAULT_TOKEN="$TEST_ROOT_TOKEN" platform-vault-test \
  vault kv patch kv/platform/notification-orchestrator \
    vapid_public_key='<step 3.1 public output>' \
    vapid_private_key='<step 3.1 private output>' \
    vapid_subject='mailto:admin@testai.acik.com'
```

Doğrulama (PII-safe — secret value'ları terminale basmaz):

```bash
docker exec -e VAULT_TOKEN="$TEST_ROOT_TOKEN" platform-vault-test \
  sh -c 'vault kv get -mount=kv -format=json platform/notification-orchestrator \
    | jq -e ".data.data | has(\"vapid_public_key\") and has(\"vapid_private_key\") and has(\"vapid_subject\")"'
```

Beklenen output: `true` (3 key mevcut). Key uzunluk doğrulaması (private key value'ı basmadan):

```bash
docker exec -e VAULT_TOKEN="$TEST_ROOT_TOKEN" platform-vault-test \
  sh -c 'vault kv get -mount=kv -format=json platform/notification-orchestrator \
    | jq -r ".data.data | {pub_len: (.vapid_public_key|length), priv_len: (.vapid_private_key|length), subj_present: (.vapid_subject != null)}"'
```

Beklenen: `pub_len ~88, priv_len ~43, subj_present true` (base64url-encoded P-256 length).

### 3.3 ExternalSecret 3 entry uncomment (SADECE test overlay)

`kustomize/overlays/test/eso/notify/externalsecret-notify.yaml` içinde:

```yaml
# --- WebPush VAPID 3 remoteRef entries — DEFER-AWARE COMMENTED OUT ---
# - secretKey: NOTIFY_ADAPTERS_WEBPUSH_PUBLIC_KEY
#   remoteRef:
#     key: kv/platform/notification-orchestrator
#     property: vapid_public_key
# - secretKey: NOTIFY_ADAPTERS_WEBPUSH_PRIVATE_KEY
#   ...
```

3 entry'nin `#` prefix'ini kaldır → uncomment.

⚠️ **Prod overlay (`kustomize/overlays/prod/eso/notify/externalsecret-notify.yaml`) bu PR'da uncomment EDİLMEZ**. Prod Vault VAPID seed yapılmadan prod ExternalSecret aggregate `Ready=False` riski doğar (mevcut SMS/SMTP/DKIM live key sync bozulur). Prod ESO uncomment + prod ConfigMap enable + prod VAPID seed test 72h soak sonrası §6 Prod cutover slot'unda ayrı PR.

### 3.4 Test overlay ConfigMap patch (ENABLED=true + Deployment annotation bump)

`kustomize/overlays/test/kustomization.yaml` içinde `patches` bölümüne (ADR-0023 overlay-managed discipline — `kubectl rollout restart` YASAK):

```yaml
patches:
  # WebPush activation — ConfigMap flag flip
  - target:
      kind: ConfigMap
      name: notification-orchestrator-config
    patch: |-
      - op: replace
        path: /data/NOTIFY_ADAPTERS_WEBPUSH_ENABLED
        value: "true"
  # Pod template annotation bump → kustomize apply otomatik rollout tetikler
  # (envFrom ConfigMap pickup için manual rollout restart pattern'i ADR-0023
  # ile uyumsuz; annotation bump declarative + audit trail içinde)
  - target:
      kind: Deployment
      name: notification-orchestrator
    patch: |-
      - op: add
        path: /spec/template/metadata/annotations/notify-webpush-activated-at
        value: "2026-05-21T20:00Z"
```

Mevcut overlay'de zaten benzer annotation bump pattern'leri var (örn. `notify-tempo-otel-restart-at` PR #931 — line 3473+).

### 3.5 PR aç + Codex review + merge

```bash
git checkout -b feat-webpush-activation-test-overlay
git add kustomize/overlays/test/eso/notify/externalsecret-notify.yaml \
        kustomize/overlays/prod/eso/notify/externalsecret-notify.yaml \
        kustomize/overlays/test/kustomization.yaml
git commit -m "feat(notify-23.7): M7 T4.2 WebPush activation — test overlay (Codex 019e49e7 P11)"
git push -u origin feat-webpush-activation-test-overlay
gh pr create --base main --head feat-webpush-activation-test-overlay --title "feat(notify-23.7): WebPush activation test overlay"
```

CI yeşil + Codex AGREE sonrası squash merge.

### 3.6 Frontend rebuild + image push (VITE_NOTIFY_VAPID_PUBLIC_KEY)

GitHub Actions Settings → Variables → New repository variable:
- Name: `NOTIFY_VAPID_PUBLIC_KEY`
- Value: `<step 3.1 public output>`

`platform-web` repo'da `main` branch'e dummy commit veya `ci-web-image-push.yml` workflow_dispatch trigger → frontend image rebuild (VAPID public key bundle'a inject edilir).

### 3.7 Frontend overlay digest bump (platform-k8s-gitops)

Yeni frontend image build sonrası:
```bash
gh run view <run-id> -R Halildeu/platform-web --log 2>&1 | grep "manifest sha256:" | head -3
```

Yeni digest'i kustomization.yaml'da pin (canonical frontend image isim):
```yaml
- name: ghcr.io/halildeu/platform-web-frontend-testai
  digest: sha256:<new-digest>
```

PR aç + Codex review + merge.

### 3.8 Cluster apply (ADR-0023 overlay-managed; rollout restart YASAK)

```bash
ssh halil@staging-sw "cd /home/halil/platform-k8s-gitops && git pull origin main --quiet && \
  kubectl --context k3d-test -n platform-test apply -k kustomize/overlays/test 2>&1 | tail -5 && \
  kubectl --context k3d-test -n platform-test rollout status deploy/notification-orchestrator --timeout=180s"
```

Step 3.4'teki Deployment annotation bump (`notify-webpush-activated-at`) kustomize apply ile Pod template hash değiştirir → Kubernetes otomatik rolling restart. `kubectl rollout restart` ad-hoc imperative patch YASAK (test overlay discipline — AGENTS.md L37-38).

### 3.9 Acceptance — Pod startup log doğrula

```bash
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  logs deploy/notification-orchestrator --tail=100 | grep -iE 'WebPush|VapidKey|DefaultWebPushSender'"
```

Beklenen:
- `VapidKeyService activated: subject=mailto:admin@testai.acik.com`
- `DefaultWebPushSender activated: subject=mailto:admin@testai.acik.com ttl=3600s`
- `WebPushAdapter activated`

Eğer `VapidKeyService` fail-closed exception varsa → step 3.2 Vault seed'i doğrula.

### 3.10 Browser end-to-end smoke (HARD RULE — Tarayıcı Verifikasyon Zorunlu)

Chrome MCP veya computer-use:

1. `https://testai.acik.com/settings/notifications` aç (M365 SSO sonrası)
2. `<PushSubscriptionCard>` render olmalı; "Aboneliği aç" button görünür
3. Button tıkla → browser notification permission dialog → "Allow"
4. Backend POST `/api/v1/notify/push/subscribe` 200 (DevTools Network tab)
5. Card "Aboneliği kapat" button + "bu tarayıcıda bildirimler etkin" mesajı
6. Test SMS/email intent submit → push notification OS toast'u beklenen
7. Click toast → tab focus + navigation to `/notifications` inbox

DevTools kanıt:
- Network: POST /push/subscribe → 200 Created + endpointId UUID
- Application → Service Workers → `/notification-sw.js` Active
- Application → Local Storage → `notify.push.browserEndpointId` = UUID

### 3.11 Acceptance — Backend metric verify

```bash
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  exec deploy/notification-orchestrator -- wget -qO- localhost:8081/actuator/prometheus \
  | grep -E 'notify_(intent|dispatch|webpush)' | head -10"
```

Beklenen: `notify_intent_terminated_total{terminal=...}` + `notify_dispatch_outcome_total{channel=\"push\", status=...}` rate > 0 (push channel aktif).

## 4. Rollback

ENABLED=false rollback (ADR-0023 overlay-managed):

```bash
# 1. ConfigMap + annotation patch revert (PR'da yapılan değişikliğin tümü)
git revert <feat-webpush-activation-test-overlay-merge-commit>
git push
# 2. Cluster apply — annotation bump revert Pod template hash değiştirir,
# otomatik rolling restart (imperative rollout restart YASAK)
ssh halil@staging-sw "cd /home/halil/platform-k8s-gitops && git pull && \
  kubectl --context k3d-test -n platform-test apply -k kustomize/overlays/test && \
  kubectl --context k3d-test -n platform-test rollout status deploy/notification-orchestrator --timeout=180s"
```

WebPushAdapter `@ConditionalOnProperty` ile bean creation block → adapter pasif. Mevcut subscriber endpoint kayıtları silinmez (soft-delete sadece manuel `DELETE /api/v1/notify/push/subscribe/{id}`).

Vault VAPID keys silmek YASAK (audit trail). Sadece ConfigMap flag flip yeterli.

## 5. Acceptance Gates Tablosu

| Gate | Kanıt | Status |
|---|---|---|
| Vault seed | `vault kv get` 3 key görünür | □ |
| ESO Ready=True | `kubectl get externalsecret` | □ |
| ConfigMap ENABLED=true | `kubectl get configmap -o yaml` | □ |
| Pod startup log VapidKeyService activated | `kubectl logs ...` | □ |
| Frontend VAPID env injection | DevTools Network POST payload contains valid p256dh | □ |
| Browser end-to-end smoke | Notification toast + inbox navigation | □ |
| Backend metric notify_dispatch_outcome push channel rate > 0 | Prometheus query | □ |

## 6. Prod cutover (ayrı slot)

Test cluster 72h soak başarılı sonrası prod overlay aynı 3.3-3.10 adımları ile uygula. **Prod-specific dikkat**:

- Vault prod seed Pre-Production Full Authority sırasında yapılır (kullanıcı 2026-04-29 mandate)
- Prod overlay `NOTIFY_ADAPTERS_WEBPUSH_ENABLED=true` patch ayrı PR (D29 evidence gate)
- Real user M365 SSO + browser end-to-end smoke functional canary (Codex `019e4965` Layer-1 strict-mode evidence pattern)

## 7. Referanslar

- ADR-0013 notification orchestration
- Faz 23 Charter (RB-faz-23-charter.md)
- M7 T4.2 milestones.md
- Codex thread 019e49e7 master plan + 7 iter chain (019e4a2e, 019e4a3d, 019e4a57, 019e4a70, 019e4a87, 019e4bf5, 019e4c0e)
- Backend PRs: #277/#278/#279/#280/#281/#282/#283/#284/#285
- GitOps PRs: #939 (ConfigMap + ExternalSecret defer-aware + overlay digest bump)
- Frontend PRs: #648 (SW + hook), #649 (UI integration + VAPID env build chain)

## 8. Risk

- **R11** Push delivery — ~mitigated (browser-only foundation MERGED + LIVE)
- **R23** Graph mail adapter defer monitoring — unrelated
- **R10** Multi-tenant trigger gate — M8 pre-req (M7 stable + 30day sonrası); backend org_id Counter Tag retrofit ayrı issue
