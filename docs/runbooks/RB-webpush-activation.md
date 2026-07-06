# RB-webpush-activation — Web Push Protocol Browser Activation

> **Status**: LIVE + browser-verified (2026-05-22) — M7 T4.2 WebPush activation; subscribe flow end-to-end proven (§3.10)
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
   - Public Key: 65-byte uncompressed P-256, base64url (87 char unpadded; 88 with padding)
   - Private Key: 32-byte scalar, base64url (43 char unpadded)
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

Beklenen (2 log satırı):
- `VapidKeyService activated: subject=mailto:admin@testai.acik.com`
- `DefaultWebPushSender activated: subject=mailto:admin@testai.acik.com ttl=3600s`

> **NOT** (2026-05-22 smoke düzeltmesi): `WebPushAdapter` sınıfı constructor'da
> bilinçli olarak activation log yazmaz (yalnız runtime delivery olaylarını
> loglar). "WebPushAdapter activated" satırı **beklenmez** — bean'in oluştuğunun
> kanıtı VapidKeyService + DefaultWebPushSender log'u + `@ConditionalOnProperty`
> gate'inin açık olması (aynı `notify.adapters.webpush.enabled` koşulu) +
> pod'un sağlıklı ayağa kalkmasıdır.

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
- Network: POST /push/subscribe → 200 OK + endpointId UUID (backend `PushSubscriptionController` returns `ResponseEntity.ok`)
- Application → Service Workers → `/notification-sw.js` Active
- Application → Local Storage → `notify.push.browserEndpointId` = UUID

> **VERIFIED — browser end-to-end smoke PASS (2026-05-22)**
>
> Steps 1–5 proven on testai.acik.com against the #652 frontend
> (`platform-web` sha-07805aa; gitops overlay digest `sha256:aef8169e…`,
> PR #986). Tooling: Playwright **persistent context** (`launchPersistentContext`).
>
> Root-cause note for future operators — `browser.newContext()` is
> incognito-equivalent and Chrome deliberately blocks the Push API in
> incognito (crbug.com/41124656); `pushManager.subscribe()` there fails
> with `Registration failed - permission denied`. Use
> `launchPersistentContext` (a real non-incognito profile) for any
> automated WebPush smoke.
>
> Evidence (`webpush-smoke` persona, Keycloak SSO login):
> - Cold-load `/settings/notifications` → `GET /preferences/me` +
>   `/push/subscribe/me` + `/inbox/me` all **200**. The prior cold-load
>   401 was an RTK Query `Request`-object header-drop bug (frontend nginx
>   ↔ orchestrator dropped `Authorization` + identity headers on the
>   `fetch(new Request(...))` form), fixed by #652 `unwrapRequestFetchFn`
>   wired as the `fetchFn` for all 4 authenticated notify RTK clients.
> - `PushSubscriptionCard` renders; `Notification.permission=granted`;
>   service worker `/notification-sw.js` **active**.
> - "Aboneliği aç" click → `pushManager.subscribe` returns a real FCM
>   endpoint (`https://jmt17.google.com/fcm/send/…`).
> - `POST /api/v1/notify/push/subscribe` → **200**; card flips to
>   "Aboneliği kapat / bu tarayıcıda bildirimler etkin / 1 aktif cihaz".
> - 0 console errors.
>
> Steps 6–7 (real push delivery → OS toast → click-to-navigate) are
> covered by the §3.11 backend dispatch-metric gate.

### 3.11 Acceptance — Backend metric verify

```bash
ssh halil@staging-sw "kubectl --context k3d-test -n platform-test \
  exec deploy/notification-orchestrator -- wget -qO- localhost:8081/actuator/prometheus \
  | grep -E 'notify_(intent|dispatch|webpush)' | head -10"
```

Beklenen: `notify_intent_terminated_total{terminal=...}` + `notify_dispatch_outcome_total{channel=\"push\", status=...}` rate > 0 (push channel aktif).

> **VERIFIED — push dispatch pipeline wired, metric > 0 (2026-05-22)**
>
> Synthetic push intent submitted for the `webpush-smoke` subscriber
> (`123be09e-…`, live FCM endpoint). The intent API is NOT exposed at the
> public edge — `POST /api/v1/notify/intents` reached the orchestrator via
> `kubectl port-forward svc/notification-orchestrator 18089:8089`
> (orchestrator HTTP port is **8089**, management/actuator **8081**).
>
> - `POST /api/v1/notify/intents` (template `t1` v1, `channels:["push"]`,
>   recipient `subscriber:123be09e-…`) → **202 ACCEPTED**.
> - Pod logs prove the full push pipeline is wired:
>   `IntentSubmissionService: intent accepted … channels=[push]
>   dispatch.enabled=true` → `DeliveryPlanService: push plan …
>   target_count=1` (the subscriber's registered push endpoint resolved)
>   → `DeliveryDispatchService: dispatch start`.
> - Metric **`notify_dispatch_outcome_total{channel="push"} > 0`** — the
>   push channel is live and producing dispatch outcomes.
>
> Outcome is `status=BLOCKED_BY_AUTHZ` (`policy=authz_deny`). Root cause
> traced: the orchestrator `AuthzClient` calls permission-service
> `POST /api/v1/internal/authz/check` with `{principal_type:subscriber,
> relation:can_receive, object_type:template}`, resolved against OpenFGA.
> The live OpenFGA authz model (`01KRTJVEMAW80B2D35GN8HJDPG` — the only
> model permission-service is configured with, `ERP_OPENFGA_MODEL_ID`)
> defines **only ERP types** (organization / company / project /
> warehouse / branch / module / action / report / report_group) — it has
> **no `template`, `can_receive` or `subscriber` type**. So the
> subscriber-recipient notification authz path cannot resolve to allow in
> the current deployment: every `subscriber`-type push delivery is
> `BLOCKED_BY_AUTHZ` by construction. (`external`-recipient deliveries —
> the email/SMS path proven in M2/M4 — do not hit this `can_receive`
> check, which is why they work.)
>
> A `SUCCESS`-status subscriber push delivery (real FCM push → OS toast)
> therefore requires **provisioning the OpenFGA model with the
> notification authz types** (`template` type + `can_receive` relation +
> `subscriber` user type) plus the
> `template:t1#can_receive@subscriber:123be09e-…` tuple — a Zanzibar
> authz-plane task (model migration), NOT a one-line tuple seed and NOT a
> WebPush-channel defect. The WebPush adapter + dispatch wiring is itself
> fully proven (intent → plan → dispatch → metric > 0).

> **TRUTH CORRECTION 2026-05-23 — post OpenFGA cutover (PR #995)**:
> The "model gap" framing above is the **secondary / latent** blocker.
> Primary blocker, surfaced after the cutover apply, is a **401
> Unauthorized at the `InternalApiKeyAuthFilter`**: orchestrator's
> `NOTIFY_AUTHZ_INTERNAL_API_KEY` (Vault `kv/platform/notification-
> orchestrator.authz_internal_api_key`) and permission-service's
> `PERMISSION_SERVICE_INTERNAL_API_KEY` (Vault `kv/platform/permission-
> service.internal_api_key`) were never aligned (len 31 vs 44, different
> sha256 hashes). All pre-cutover `BLOCKED_BY_AUTHZ` outcomes were 401s
> from the auth filter — the OpenFGA Check call never reached the
> resolution stage where the model-gap would have mattered. Once the
> 401 is resolved (this PR re-aligns the orchestrator ExternalSecret to
> share the permission-service Vault path via ESO; canonical follow-up
> = operator Vault patch), the Check WILL reach OpenFGA and the model
> extension (PR #990 — `01KS8QE8…`, model_id cutover PR #995) becomes
> the active prerequisite that lets the resolution succeed. Both fixes
> are required — the 401 is just the gate ordering: trigger fires first.

> **POST-CUTOVER LIVE SUCCESS 2026-05-23 — §3.11 ✅**
>
> All three preparation+fix steps merged and applied; live re-smoke
> proves end-to-end SUCCESS push delivery:
>
> - **PR #990** (OpenFGA model extension safe-phase): new model
>   `01KS8QE8T1EJ2DF5CRS4VV9YX1` written additive to store
>   `01KPP0CFP4G82K42Y6NYSPT4JF`; ERP types byte-identical; isolated
>   Check TRUE for `subscriber:123be09e-… can_receive template:t1`.
> - **PR #995** (model_id cutover): permission-service Deployment env
>   override `ERP_OPENFGA_MODEL_ID=01KS8QE8…` via test-overlay patch
>   (operator follow-up = Vault `kv/platform/openfga#model_id` patch +
>   override revert).
> - **PR #996** (401 root-cause fix): orchestrator ExternalSecret
>   `NOTIFY_AUTHZ_INTERNAL_API_KEY` remoteRef re-aligned to
>   `kv/platform/permission-service#internal_api_key` (operator
>   follow-up = Vault patch + remoteRef revert).
>
> Live evidence (intent `webpush-authz-push-1779519748`):
> - Intent status: **COMPLETED**.
> - Metric: **`notify_dispatch_outcome_total{channel="push",status="DELIVERED"} 1.0`**.
> - Pod logs: `webpush send: status=201 reason=Created` →
>   `webpush delivered: endpointId=c8753c6c-… code=201 msg_id=webpush-7c3e91fe-…` →
>   `dispatch end: all_delivered=true`.
> - ERP regression smoke: permission-service `/actuator/health` UP;
>   `/api/v1/authz/me`+`/authz/version` 200 success traffic; no errors.
> - `/api/v1/internal/authz/check` metric: 200 = 1 (new SUCCESS
>   post-fix) + 401 = 1 (historical pre-cutover).
>
> §5 metric gate row: 🟡 → ✅. Browser-only WebPush LIVE end-to-end
> (subscribe flow + push delivery). Mobile FCM/APNS Faz 22.2 dep stays
> out-of-scope.

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

| Gate | Kanıt | Status (2026-05-22) |
|---|---|---|
| Vault seed | `vault kv get` 3 key: pub 87ch + priv 43ch + subject | ✅ |
| ESO Ready=True | `notification-orchestrator-secrets` Ready=True/SecretSynced; Secret'ta 3 `NOTIFY_ADAPTERS_WEBPUSH_*` key | ✅ |
| ConfigMap ENABLED=true | pod env `NOTIFY_ADAPTERS_WEBPUSH_ENABLED=true` (gitops PR #976) | ✅ |
| Pod startup log VapidKeyService activated | pod log: `VapidKeyService activated` + `DefaultWebPushSender activated` | ✅ |
| Frontend VAPID env injection | testai.acik.com `window.__env__.VITE_NOTIFY_VAPID_PUBLIC_KEY` 87ch (HTTP + Playwright runtime); `PushSubscriptionCard` config-missing branch tetiklenmedi (gitops PR #977) | ✅ |
| Browser end-to-end smoke (subscribe flow) | Persistent-context Playwright, #652 frontend live (overlay digest `aef8169e`, PR #986): `webpush-smoke` KC SSO → `/settings/notifications` cold-load → `GET /preferences/me`+`/push/subscribe/me`+`/inbox/me` **200** (önceki 401 RTK `Request`-object fetchFn bug'ı #652 ile çözüldü) → "Aboneliği aç" → `pushManager.subscribe` gerçek FCM endpoint → `POST /push/subscribe` **200** → kart "Aboneliği kapat / 1 aktif cihaz". 0 console error. §3.10 step 1–5 (root-cause: `browser.newContext()` incognito → Push API blocked; `launchPersistentContext` ile çözüldü) | ✅ |
| Backend metric notify_dispatch_outcome push channel rate > 0 | Sentetik push intent (template `t1` v1, `channels:["push"]`, recipient `subscriber:123be09e-…`) → `POST /api/v1/notify/intents` **202 ACCEPTED** → intent status **COMPLETED** → metric **`notify_dispatch_outcome_total{channel="push",status="DELIVERED"} 1.0`** + pod logs `webpush send: status=201 reason=Created` → `webpush delivered: endpointId=c8753c6c-… code=201 msg_id=webpush-7c3e91fe-…` → `dispatch end: all_delivered=true`. 2026-05-23 cutover zinciri: PR #990 (OpenFGA model extension safe-phase, model `01KS8QE8…` additive) + PR #995 (`ERP_OPENFGA_MODEL_ID` test overlay env override cutover) + PR #996 (orchestrator ExternalSecret `NOTIFY_AUTHZ_INTERNAL_API_KEY` re-aligned to `kv/platform/permission-service#internal_api_key` — 401 root cause düzeldi; truth correction: 401 primary trigger, model gap secondary prerequisite). ERP regression smoke clean (permission-service health UP, `/api/v1/authz/me`+`/authz/version` 200 trafik, no errors). | ✅ SUCCESS — orchestrator+permission-service auth aligned, OpenFGA model extended + cutover, gerçek FCM 201 delivery + msg_id |

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
- GitOps PRs: #939 (ConfigMap + ExternalSecret defer-aware + overlay digest bump), #976/#977 (activation + VAPID frontend digest), #986 (#652 fetchfn frontend digest bump)
- Frontend PRs: #648 (SW + hook), #649 (UI integration + VAPID env build chain), #650/#651 (notify RTK auth-ready hardening), #652 (`unwrapRequestFetchFn` shared module — cold-load 401 root fix; Codex 019e512f AGREE)

## 8. Risk

- **R11** Push delivery — ~mitigated (browser-only foundation MERGED + LIVE)
- **R23** Graph mail adapter defer monitoring — unrelated
- **R10** Multi-tenant trigger gate — M8 pre-req (M7 stable + 30day sonrası); backend org_id Counter Tag retrofit ayrı issue
