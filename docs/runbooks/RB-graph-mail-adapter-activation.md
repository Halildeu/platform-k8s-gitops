# RB-graph-mail-adapter-activation — Graph Mail Adapter Activation Runbook (DEFERRED)

> **Status**: **DEFERRED ACTIVATION RUNBOOK**
> **Current runtime**: SMTP Office 365 path canonical (`ai@acik.com`); Graph adapter flag disabled, effectively `false` (backend `@ConditionalOnProperty(notify.adapters.graph.enabled)` default false).
> **Do not execute** until **ADR-0024 trigger conditions** are met (D3) **AND** board issue [#892](https://github.com/Halildeu/platform-k8s-gitops/issues/892) is moved out of Backlog (claim'lenir, scope confirm edilir).
> **Tracker**: [#892](https://github.com/Halildeu/platform-k8s-gitops/issues/892) — P3 Backlog, claim yok, future-only
> **Tarih**: 2026-05-20 (Session 42 defer chain final asset)
> **Codex thread**: `019e44b1` (defer contract alignment review); antecedents `019e42d1` (PR #872 staged-only ESO + DNS runbook) + `019e4445` (#862 deprecation + bridge truth-cleanup)
> **ADR ref**: [ADR-0024 — Notification Mail Delivery: Defer Microsoft Graph Adapter](../adr/0024-graph-mail-adapter-defer.md)

---

## 1. Bağlam — Defer + Reactivation Trigger Conditions

`notification-orchestrator` mail delivery'si bugün SMTP Office 365 path'i üzerinden çalışır. Graph adapter binary (PR #153 backend, sha-585b64f) ve gitops staged ESO 3-key (PR #872) hazır, **ama aktive edilmemiş**. Activation yalnız aşağıdaki trigger'lardan **en az biri** geldiğinde çalıştırılır (ADR-0024 D3):

| # | Trigger | Detect Signal |
|---|---|---|
| 1 | Microsoft App Password deprecation tenant'ı etkiler | `ai@acik.com` App Password ile SMTP AUTH legacy authentication policy break sonucu mail gönderemez; backend pod loglarında `javax.mail.AuthenticationFailedException` veya benzer SMTP AUTH reject |
| 2 | SMTP AUTH tenant policy break | Microsoft 365 admin tenant veya org-level SMTP AUTH disable etti (`Set-TransportConfig -SmtpClientAuthenticationDisabled $true`); proactive admin notification |
| 3 | Outbound port 587 ISP/firewall block recurrence | staging-sw veya cluster outbound 587 timeout/connection-refused; mail send sürekli fail; ISP/firewall log evidence |
| 4 | Ops/security tactical decision | Risk register / audit / compliance gereksinimi OAuth2 modern auth'a geçişi zorunlu kılar |
| 5 | Provider migration tactical decision | Office 365 → başka tenant veya başka mail provider geçişi sırasında Graph path daha kolay |

**Trigger doğrulanmadan bu runbook ÇALIŞTIRILMAZ**. Yapılırsa boşa kaynak harcaması + potansiyel runtime instability (SmtpAdapter aktif kalır ama Graph activation chain'in yan etkileri pod restart gibi).

---

## 2. Pre-Activation Owner Artifact Prereq

Activation öncesi **3 owner artifact** hazır olmalı:

### 2.1 — Entra Client Secret (Microsoft 365 admin owner action)

Entra Admin Center: https://entra.microsoft.com → Identity → Applications → App registrations → **`acik-mail-graph-api`** (`client_id: 6e3e5b4b-b819-41b0-a237-8774c6418e32`) → Certificates & secrets → Client secrets → **+ New client secret**:

- **Description**: `notify-orchestrator-vault-seed-<YYYY-MM-DD>`
- **Expires**: `730 days (24 months)` — Microsoft default 180 gün'ü override et
- **Add** butonu
- **⚠️ KRITIK**: Yeni satırda **`Value`** sütunundaki secret string **sadece 1 kez gösterilir**. Hemen **📋 Copy** ikonuna tıkla; sayfayı yenilersen veya başka sekmeye gidersen secret value bir daha açıkça gösterilmez.
- Password manager'a / parola güvenli notebook'a geçici kayıt

### 2.2 — Mail-enabled Security Group (Exchange Online admin owner action)

ApplicationAccessPolicy `PolicyScopeGroupId` ile çalışır; **mail-enabled security group** zorunlu (regular security group veya distribution group kabul edilmez):

> Exchange Online PowerShell module yüklü olmalı.

```powershell
Install-Module -Name ExchangeOnlineManagement -Scope CurrentUser -Force
Import-Module ExchangeOnlineManagement
Connect-ExchangeOnline -UserPrincipalName <global-admin-upn>   # e.g. ai.enes@acik.com

# Mail-enabled security group oluştur (default Distribution Group → -Type Security ile mail-enabled SG)
New-DistributionGroup -Name "Mail-Graph-Allowed-Mailboxes" `
  -Type "Security" `
  -PrimarySmtpAddress "mail-graph-allowed@acik.com"

# ai@acik.com'u gruba ekle (sadece bu mailbox üzerinden mail gönderilebilir)
Add-DistributionGroupMember -Identity "Mail-Graph-Allowed-Mailboxes" `
  -Member "ai@acik.com"

# Doğrulama
Get-DistributionGroupMember -Identity "Mail-Graph-Allowed-Mailboxes"
```

### 2.3 — Network egress validation (cluster ops)

- Cluster outbound HTTPS port 443 → `graph.microsoft.com` reachable (genelde açık; outbound 443 standart cluster default)
- Test cluster (`k3d-test`) ve prod cluster (`k3d-prod`) outbound test:

```bash
ssh halil@staging-sw 'kubectl --context k3d-test -n platform-test run egress-test --image=busybox:1.36 --rm -it --restart=Never --timeout=20s --command -- wget -q -O- https://graph.microsoft.com/v1.0/$metadata --tries=1 --timeout=10 2>&1 | head -5'
```

Expected: 401 Unauthorized (auth gerek; ama HTTPS reachable) veya 302 redirect. Connection-refused / timeout → egress reachability sorunu, ayrı troubleshooting gerek.

---

## 3. Entra Client Secret Yaratma (UI üzerinden — operator action)

> §2.1 ile aynı; tekrar burada UI step-by-step.

1. **Entra Admin Center** aç → https://entra.microsoft.com
2. Identity → Applications → **App registrations** → **`acik-mail-graph-api`** seç
3. Sol menüden **Sertifikalar ve gizli diziler** (Certificates & secrets)
4. **İstemci gizli dizileri** sekmesi → **+ Yeni istemci gizli dizisi**
5. Form:
   - **Açıklama** (Description): `notify-orchestrator-vault-seed-<date>`
   - **Süre Sonu** (Expires): `730 gün` (24 ay) — dropdown'dan değiştir; varsayılan 180 gün
6. **Ekle** butonu
7. Yeni satırda **Değer** (Value) sütunundaki secret string'i **HEMEN** kopyala (📋 ikon)
8. Password manager'a / güvenli geçici store'a yapıştır

**HARD RULE**: Secret value chat transcript'e veya PR/issue body'sine plaintext yazılmaz. Sadece operator tarafında clipboard + Vault seed komutunda hidden prompt + stdin pipe (§5).

---

## 4. ApplicationAccessPolicy — `ai@acik.com` Mailbox'a Daraltma (operator action — PowerShell)

> §2.2 mail-enabled security group oluştuktan sonra. Microsoft Graph PowerShell SDK veya Exchange Online PowerShell module kullanılır.

```powershell
# 1. Exchange Online'a global admin ile bağlan (eğer §2.2'den disconnect olduysan)
Connect-ExchangeOnline -UserPrincipalName <global-admin-upn>

# 2. ApplicationAccessPolicy yarat — app'i mail-enabled security group'a daralt
New-ApplicationAccessPolicy `
  -AppId "6e3e5b4b-b819-41b0-a237-8774c6418e32" `
  -PolicyScopeGroupId "Mail-Graph-Allowed-Mailboxes" `
  -AccessRight "RestrictAccess" `
  -Description "Restrict acik-mail-graph-api to ai@acik.com mailbox only (per ADR-0024 D6)"

# 3. Verify — policy listede mi
Get-ApplicationAccessPolicy | Where-Object { $_.AppId -eq "6e3e5b4b-b819-41b0-a237-8774c6418e32" }

# 4. Test — ai@acik.com için GRANTED (allow proof)
Test-ApplicationAccessPolicy `
  -Identity "ai@acik.com" `
  -AppId "6e3e5b4b-b819-41b0-a237-8774c6418e32"
# Expected output:
#   AppId            : 6e3e5b4b-b819-41b0-a237-8774c6418e32
#   MailboxId        : <ai@acik.com guid>
#   AccessCheckResult: Granted

# 5. Test — başka mailbox için DENIED (deny proof; tenant-wide leak prevention)
Test-ApplicationAccessPolicy `
  -Identity "halil.kocoglu@serban.com.tr" `
  -AppId "6e3e5b4b-b819-41b0-a237-8774c6418e32"
# Expected output:
#   AccessCheckResult: Denied (RestrictAccessToScope)

# 6. Test — global admin mailbox için DENIED (operator account leak prevention)
Test-ApplicationAccessPolicy `
  -Identity "ai.enes@acik.com" `
  -AppId "6e3e5b4b-b819-41b0-a237-8774c6418e32"
# Expected: Denied

Disconnect-ExchangeOnline -Confirm:$false
```

**Acceptance**: Allow proof + en az 2 deny proof (farklı mailbox'lardan). Eğer herhangi başka mailbox `Granted` çıkarsa policy yanlış (scope group yanlış mailbox'ları içeriyor veya AccessRight yanlış); revoke + yeniden setup.

**Policy değiştir / revoke** (rollback senaryosu):

```powershell
Remove-ApplicationAccessPolicy `
  -Identity "<policy-identity-from-Get-ApplicationAccessPolicy>"
```

---

## 5. Vault Seed (operator action — SSH + stdin pipe pattern)

**HARD RULE**: client_secret bash history'ye yazılmaz; chat transcript'e yazılmaz; argv'ye yazılmaz. **Hidden prompt + stdin pipe + unset** pattern zorunlu.

```bash
ssh halil@staging-sw '
T="6f49871e-cb5b-4b2f-b986-5b68f16365b9"
C="6e3e5b4b-b819-41b0-a237-8774c6418e32"
read -r -s -p "client_secret (clipboarddan paste et): " S && echo

ROOT_T=$(jq -r .root_token /home/halil/bootstrap-drill/vault-init-test.json)
ROOT_P=$(jq -r .root_token /home/halil/bootstrap-drill/vault-init-prod.json)

# Test cluster
docker exec -e VAULT_TOKEN="$ROOT_T" platform-vault-test \
  vault kv patch kv/platform/notification-orchestrator \
    graph_tenant_id="$T" graph_client_id="$C"
printf "%s" "$S" | docker exec -i -e VAULT_TOKEN="$ROOT_T" platform-vault-test \
  vault kv patch kv/platform/notification-orchestrator graph_client_secret=-

# Prod cluster
docker exec -e VAULT_TOKEN="$ROOT_P" platform-vault-prod \
  vault kv patch kv/platform/notification-orchestrator \
    graph_tenant_id="$T" graph_client_id="$C"
printf "%s" "$S" | docker exec -i -e VAULT_TOKEN="$ROOT_P" platform-vault-prod \
  vault kv patch kv/platform/notification-orchestrator graph_client_secret=-

unset S T C ROOT_T ROOT_P
echo "=== DONE — verify (length-only): ==="
docker exec -e VAULT_TOKEN=$(jq -r .root_token /home/halil/bootstrap-drill/vault-init-test.json) platform-vault-test \
  vault kv get -mount=kv -format=json platform/notification-orchestrator \
  | jq ".data.data | to_entries | map(select(.key | startswith(\"graph_\"))) | map({key, value_len: (.value | length)})"
echo "PROD:"
docker exec -e VAULT_TOKEN=$(jq -r .root_token /home/halil/bootstrap-drill/vault-init-prod.json) platform-vault-prod \
  vault kv get -mount=kv -format=json platform/notification-orchestrator \
  | jq ".data.data | to_entries | map(select(.key | startswith(\"graph_\"))) | map({key, value_len: (.value | length)})"
'
```

**Beklenen output**:

```
graph_client_id     value_len: 36
graph_client_secret value_len: 40+ (Entra secret string)
graph_tenant_id     value_len: 36
```

Hem test hem prod 3'er key.

### ESO yaml — Graph remoteRef entries re-enable (defer-aware refactor 2026-05-20 sonrası)

**Önemli — Codex `019e45f8` defer-aware refactor (PR #906 sonrası)**: ESO yaml'lerinde Graph 3 `remoteRef` entry **commented out** durumdadır (ESO aggregate `Ready=False` blocker'ı çözmek için). Vault seed sonrası bu entries **re-enable** edilmeden ESO Graph 3 key'i sync etmez.

Aşağıdaki commit zinciri uncomment + Argo sync + verify yapar:

```bash
# Both test + prod overlay'lerinde Graph 3 remoteRef block'undaki `#` prefix kaldırılır
# (yaml line: `# - secretKey: NOTIFY_ADAPTERS_GRAPH_TENANT_ID` etc.)

# Editor (örnek prod):
$EDITOR kustomize/overlays/prod/eso/notify/externalsecret-notify.yaml
# Remove `# ` prefix from 3 secretKey blocks (12 lines total)

$EDITOR kustomize/overlays/test/eso/notify/externalsecret-notify.yaml
# Same for test overlay

# Verify yaml syntax + diff
git diff kustomize/overlays/{test,prod}/eso/notify/externalsecret-notify.yaml

# Commit + push
git checkout -b roadmap-NNN-graph-activation-step4-re-enable
git add kustomize/overlays/{test,prod}/eso/notify/externalsecret-notify.yaml
git commit -m "feat(notify-23.1): re-enable Graph remoteRef entries — D5 reactivation chain step 4"
git push origin HEAD

# PR open (Cross-AI peer review HARD RULE — Codex review)
gh pr create --title "feat(notify-23.1): Graph remoteRef re-enable — D5 reactivation step 4" \
  --body "Codex thread: <new>; ADR-0024 D5 atomic reactivation chain step 4 of 6"

# CI yeşil + Codex AGREE → normal squash merge
```

### ESO refresh (Vault → K8s Secret propagation)

```bash
ssh halil@staging-sw '
# Test cluster
kubectl --context k3d-test -n platform-test annotate externalsecret notification-orchestrator-secrets \
  force-sync="$(date +%s)" --overwrite
# Prod cluster
kubectl --context k3d-prod -n platform-prod annotate externalsecret notification-orchestrator-secrets \
  force-sync="$(date +%s)" --overwrite
sleep 30
# Verify
for ENV in test prod; do
  CTX="k3d-$ENV"
  NS="platform-$ENV"
  echo "=== $ENV ==="
  kubectl --context "$CTX" -n "$NS" get externalsecret notification-orchestrator-secrets \
    -o jsonpath="ready={.status.conditions[0].status} reason={.status.conditions[0].reason}{\"\\n\"}"
  kubectl --context "$CTX" -n "$NS" get secret notification-orchestrator-secrets \
    -o json | jq ".data | to_entries | map(select(.key | startswith(\"NOTIFY_ADAPTERS_GRAPH\"))) | map({key, value_len: (.value | @base64d | length)})"
done
'
```

Beklenen: ExternalSecret `Ready=True reason=SecretSynced` + Secret'te `NOTIFY_ADAPTERS_GRAPH_TENANT_ID/CLIENT_ID/CLIENT_SECRET` 3 key non-empty.

**Codex `019e45f8` aggregate Ready clarification**: ESO single aggregate Ready condition; defer-aware refactor öncesinde Graph 3 property eksikliği aggregate fail veriyordu (`Ready=False reason=SecretSyncedError`) → JetSMS/SMTP/DKIM/Slack/Teams/Push live key sync target Secret'a propagate edilemiyordu. Re-enable + Vault seed sonrası aggregate Ready=True, tüm key'ler sync.

---

## 6. Activation PR (Codex review + cross-AI HARD RULE)

### 6.1 — Test cluster activation PR

```yaml
# kustomize/overlays/test/kustomization.yaml — ConfigMap notification-orchestrator-config
# data block içine ekle (veya patch):
NOTIFY_ADAPTERS_GRAPH_ENABLED: "true"
NOTIFY_ADAPTERS_GRAPH_SENDER_MAILBOX: "ai@acik.com"           # sender mailbox (ApplicationAccessPolicy scope ile uyumlu)
NOTIFY_ADAPTERS_GRAPH_SAVE_TO_SENT_ITEMS: "true"              # §7.4 Sent Items proof için zorunlu (default false — Codex 019e44b1 finding 2 absorb)
```

Plus (eğer test cluster digest henüz Graph-binary-inclusive sha içermiyorsa):

```yaml
# kustomize/overlays/test/kustomization.yaml — images section
- name: ghcr.io/halildeu/platform-backend-notification-orchestrator
  newTag: sha-<graph-binary-inclusive>   # sha-585b64f veya sonrası
```

PR:
- Title: `feat(notify-23-A8): Graph mail adapter activation — test cluster (Codex 019e44b1 reactivation trigger)`
- Body: ADR-0024 trigger documented + Vault seed verified + ApplicationAccessPolicy granted + smoke acceptance plan
- Boundary declaration: `state-mutation (test cluster)` + (eğer prod parça da var ise) `state-mutation (production)` + `user-approval-required` label
- Cross-AI peer review: Codex thread continuation

### 6.2 — Prod activation PR (sonra)

Test cluster smoke acceptance (§7) sonrası prod aynı pattern. **A5 PR-B + RAID I6 sequencing** ile prod backend digest promotion paralel (eğer prod digest henüz Graph-binary-inclusive sha değilse — promotion zinciri açıkça blocker).

### 6.3 — ArgoCD sync

PR merge sonrası ArgoCD `platform-test` (auto-sync) ve `platform-prod` (manual-sync — D30 HARD RULE) reconcile:

```bash
ssh halil@staging-sw '
# Test cluster auto-sync; sadece verify
kubectl --context k3d-test -n argocd get app platform-test -o jsonpath="sync={.status.sync.status} health={.status.health.status}{\"\\n\"}"

# Prod cluster manual sync (eğer prod activation PR da merged ise)
kubectl --context k3d-prod -n argocd patch application platform-prod --type=merge -p \
  "{\"operation\":{\"sync\":{\"prune\":false,\"syncStrategy\":{\"apply\":{}}}}}"
sleep 30
kubectl --context k3d-prod -n argocd get app platform-prod -o jsonpath="phase={.status.operationState.phase} msg={.status.operationState.message}{\"\\n\"}"
'
```

### 6.4 — Pod rollout

ConfigMap değişimi `envFrom` ile pickup edilmez otomatik; rolling restart gerek:

```bash
ssh halil@staging-sw '
# Test cluster
kubectl --context k3d-test -n platform-test rollout restart deploy/notification-orchestrator
kubectl --context k3d-test -n platform-test rollout status deploy/notification-orchestrator --timeout=180s
# Prod cluster
kubectl --context k3d-prod -n platform-prod rollout restart deploy/notification-orchestrator
kubectl --context k3d-prod -n platform-prod rollout status deploy/notification-orchestrator --timeout=180s
'
```

Pod restart sonrası backend `GraphMailAdapter` `@ConditionalOnProperty` true → aktif; `SmtpAdapter` `@ConditionalOnProperty` `havingValue=false` mutual exclusion → inactive.

---

## 7. Smoke Send Acceptance — Multi-layered Proof

> **HARD RULE**: HTTP 202 Accepted yetmez. Aşağıdaki tüm proof'lar zorunlu (Codex `019e44b1` adversarial note).

### 7.1 — Token acquisition success

```bash
ssh halil@staging-sw '
kubectl --context k3d-test -n platform-test logs deploy/notification-orchestrator --since=5m | grep -iE "GraphTokenService|Graph access_token|AADSTS" | head -10
'
```

Backend gerçek log davranışı (Codex `019e44b1` iter-3 finding 2 absorb):
- **INFO level (boot)**: `GraphTokenService initialized: tenantId=<first8> clientId-prefix=<first8>***` — tenant_id ve client_id PII safety için first-8 + masked
- **DEBUG level only** (logging.level.notify.adapters.graph=DEBUG ile): `Graph access_token refreshed: expires_in=<ts>` — default INFO log'da görünmez
- **Error (acceptance blocker)**: `AADSTS70011` (invalid scope) / `AADSTS90002` (tenant not found) / `AADSTS7000222` (invalid client secret) — credential mismatch veya scope problem; troubleshoot before continuing

**Acceptance gate**: `GraphTokenService initialized` log presence + AADSTS error absence yeterli. `access_token refreshed` INFO log'da görünmez; kanıt §7.2'deki başarılı `status=202` ile gelir (token implicit olarak alındı demektir).

### 7.2 — Canonical intent API smoke (`POST /api/v1/notify/intents`)

Backend canonical intent endpoint kullanılır (özel `/admin/smoke-send` endpoint backend yüzeyinde **yok** — Codex `019e44b1` finding 1 absorb). JWT-authenticated intent + `SubmitIntentRequest` full contract + external recipient + Graph adapter path tetiklenir.

**Backend contract** (Codex iter-3 absorb — D29 evidence pattern):
- **Zorunlu field'lar**: `intentId`, `idempotencyKey`, `orgId`, `topicKey`, `severity`, `dataClassification`, `template`, `payload`, `channels`, `recipients`
- **External recipient** (mail smoke için): `{"type": "external", "email": "<addr>", "locale": "tr-TR"}` (subscriberId tek başına geçersiz)
- **Subject/body**: template render'dan gelir (`payload.subject/body` tek başına garanti etmez); activation öncesi `t1` smoke template'inin var olması prereq

```bash
ssh halil@staging-sw '
# Port-forward + JWT mint
kubectl --context k3d-test -n platform-test port-forward svc/notification-orchestrator 8089:8089 &
PF=$!
trap "kill $PF 2>/dev/null || true" EXIT
sleep 3

# JWT token (admin user veya service principal smoke account; d29-smoke pattern)
TOKEN="$(get-admin-jwt-test)"   # operator script veya manual mint
TS=$(date +%s)

# Canonical intent POST (SubmitIntentRequest full contract)
curl --fail-with-body -sX POST http://127.0.0.1:8089/api/v1/notify/intents \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "X-Org-Id: default" \
  -d "$(cat <<JSON
{
  "intentId": "graph-smoke-$TS",
  "idempotencyKey": "graph-smoke-$TS-key",
  "correlationId": "graph-activation-$TS",
  "orgId": "default",
  "topicKey": "test.d29.email",
  "severity": "info",
  "dataClassification": "system",
  "recipients": [
    {"type": "external", "email": "halil.kocoglu@serban.com.tr", "locale": "tr-TR"}
  ],
  "template": {"templateId": "t1", "version": 1, "locale": "en"},
  "channels": ["email"],
  "payload": {"name": "Graph Smoke"}
}
JSON
)"
'
```

**Expected**: HTTP 202 from notification-orchestrator (intent accepted) + pod log `graph mail accepted: to=<hash:...> subject=<...> message_id=... status=202` + Microsoft Graph API response 202.

**Note on subject/body** (Codex iter-3): Mail subject/body, `template.templateId=t1` render output'undan gelir — `payload.subject/body` tek başına garanti etmez. Activation öncesi `t1` smoke template'inin tenant template store'da kayıtlı olduğundan emin olunmalı. §7.3 recipient inbox proof'unu beklenen template output ile karşılaştırın (sabit subject literal değil).

Alternatif (canonical intent API access yoksa): `/api/v1/admin/notify/deliveries` audit + replay path veya backend admin actuator endpoint.

### 7.3 — Recipient inbox proof

Recipient (`halil.kocoglu@serban.com.tr`) inbox'ı kontrol et — mail geldi mi?

- Subject: **`t1` template render output'una göre değişir** — sabit literal değil (Codex `019e44b1` iter-3 absorb). Activation öncesi `t1` smoke template subject expected output'unu kayıt altına al, recipient inbox'ta o output'u eşle.
- From: `ai@acik.com` (App Registration owns this mailbox via ApplicationAccessPolicy)
- Body: `t1` template render output (gene template'e bağlı; literal `Microsoft Graph adapter activation test...` değil)
- Receive timestamp: smoke send'den sonra dakikalar içinde
- **Header/correlation** (Codex `019e44b1` iter-4 absorb): `POST /api/v1/notify/intents` response'u sadece `intentId`, `status`, `trackingUrl` döner (`message_id` YOK; acceptance intentId ile başlatılır). Provider correlator (Graph adapter'ın aldığı value) pod log `graph mail accepted ... message_id=...` veya admin delivery row `provider_msg_id` alanından alınır. Email headers içinde standart `Message-ID` değil, custom `X-Notify-Message-ID` internet header'ı aranır (backend Graph adapter payload'a set eder)

### 7.4 — Sender Sent Items proof (zorunlu — `saveToSentItems=true` ConfigMap'ten)

Sender (`ai@acik.com`) mailbox'ın **Sent Items** klasörü:

- Microsoft 365 Outlook web (https://outlook.office.com) → ai@acik.com login → Sent Items
- Mail görünüyor mu? — **§6.1 ConfigMap'te `NOTIFY_ADAPTERS_GRAPH_SAVE_TO_SENT_ITEMS=true` ZORUNLU** çünkü backend `GraphMailAdapter` default value `false` (Codex `019e44b1` finding 2 absorb: payload explicit `saveToSentItems=false` gönderiyor; tenant default override etmez). Eğer §6.1 ConfigMap'te bu flag missing/false → Sent Items proof fail eder ve activation acceptance blocker olur.

### 7.5 — Pod logs `GraphMailAdapter active`, `SmtpAdapter inactive`

Codex `019e44b1` finding 3 absorb: backend gerçek log string'leri kullanılır (ConditionalOnProperty `matched/skipped` lines debug açılmadan üretilmez):

```bash
ssh halil@staging-sw '
# Fresh boot logs (Graph activation rollout sonrası, son 10 dk)
kubectl --context k3d-test -n platform-test logs deploy/notification-orchestrator --since=10m \
  | grep -iE "GraphMailAdapter|GraphTokenService|SmtpAdapter" | head -10
'
```

Backend gerçek log strings (Codex iter-3 finding 2 absorb — PII safety masking):

**Required presence**:
- `GraphMailAdapter initialized: senderMailbox=ai@acik.com fromName=<...> saveToSentItems=true`
- `GraphTokenService initialized: tenantId=<first8> clientId-prefix=<first8>***` (PII safety: first-8 + masked; scope alanı INFO log'da yok)
- `graph mail accepted: to=<hash:...> subject=<...> message_id=... status=202` (post-smoke send)

**Required absence (fresh boot logs)**:
- `SmtpAdapter activated: dkimEnabled=...` ← **ABSENT** (mutual exclusion; conditional bean registration — bean instantiate edilmez)

Eğer `SmtpAdapter activated` log'u fresh boot'ta görünürse → ConfigMap flag `NOTIFY_ADAPTERS_GRAPH_ENABLED` reload edilmemiş veya backend ConditionalOnProperty config mismatch; troubleshoot.

Alternatif kanıt — Spring Boot Actuator beans endpoint:

```bash
ssh halil@staging-sw '
kubectl --context k3d-test -n platform-test exec deploy/notification-orchestrator -- \
  curl -s http://localhost:8089/actuator/beans 2>/dev/null \
  | jq ".contexts.application.beans | to_entries | map(select(.key | test(\"(?i)(graph|smtp).*Adapter\"))) | map({key, value: .value.type})"
'
```

Beklenen: `graphMailAdapter` bean present, `smtpAdapter` bean ABSENT (Spring conditional bean registration).

### 7.6 — Acceptance gate

7.1–7.5 **hepsi pass**: ✅ acceptance. Eğer biri fail:
- 7.1 token fail → credential mismatch; Vault seed verify + ApplicationAccessPolicy verify
- 7.2 202 fail → Graph endpoint or permission issue
- 7.3 recipient fail → Microsoft mail routing veya spam folder (kontrol et)
- 7.4 Sent Items fail → `saveToSentItems` config; ya da ApplicationAccessPolicy unexpected denial
- 7.5 SmtpAdapter still active → ConditionalOnProperty config mismatch; ConfigMap flag verify

### 7.7 — D43 outage fallback compatibility

D43 outage fallback chain (`alertmanager-fallback` direct-fallback receiver) `notification-orchestrator` outage'ında devreye girer — bağımsız path. Graph activation **D43 chain'i etkilemez**; ama Graph activation sonrası D43 smoke (synthetic NotifyServiceDown) tekrar test edilebilir reaktivasyon kontrolü için.

---

## 8. Rollback Procedure

Smoke acceptance fail veya runtime instability durumunda:

### 8.1 — Hızlı rollback (ConfigMap flip)

```bash
# kustomize/overlays/{test,prod}/kustomization.yaml — ConfigMap data block
NOTIFY_ADAPTERS_GRAPH_ENABLED: "false"   # veya satırı tamamen kaldır
```

PR (revert): `revert(notify-23-A8): Graph adapter activation rollback — <reason>`. Aynı sequencing (test cluster önce, prod sonra).

Pod restart → SmtpAdapter `@ConditionalOnProperty havingValue=false matchIfMissing=true` ile yeniden aktif.

### 8.2 — Vault graph_* keys revoke (defensive, opsiyonel)

```bash
ssh halil@staging-sw '
ROOT_T=$(jq -r .root_token /home/halil/bootstrap-drill/vault-init-test.json)
ROOT_P=$(jq -r .root_token /home/halil/bootstrap-drill/vault-init-prod.json)
# Test cluster
docker exec -e VAULT_TOKEN="$ROOT_T" platform-vault-test \
  vault kv patch kv/platform/notification-orchestrator \
    graph_tenant_id="" graph_client_id="" graph_client_secret=""
# Prod cluster
docker exec -e VAULT_TOKEN="$ROOT_P" platform-vault-prod \
  vault kv patch kv/platform/notification-orchestrator \
    graph_tenant_id="" graph_client_id="" graph_client_secret=""
unset ROOT_T ROOT_P
'
```

Plus ESO force-sync; Secret 3 key'i empty olur.

### 8.3 — Entra client secret revoke (defensive, full rollback)

Entra Admin Center → `acik-mail-graph-api` → Certificates & secrets → ilgili secret row → **🗑️ Delete** → confirm.

Plus Vault graph_client_secret empty (§8.2 ile aynı anda yapılır).

**NOT**: ApplicationAccessPolicy + admin consent + app reg **silinmez** (ADR-0024 D4 — Entra asset preserved). Sadece secret revoke, future reactivation chain'i tekrarlanabilir bırakır.

### 8.4 — Audit doc + #892 update

Rollback sonrası:
- Audit doc: `docs/faz-23-evidence/<YYYY-MM-DD>-graph-activation-rollback.md` (smoke acceptance hangi adımda fail + rollback timeline + root cause)
- Board #892 yorumu: rollback timeline + reactivation retry conditions

---

## 9. Cross-References

- [ADR-0024 — Notification Mail Delivery: Defer Microsoft Graph Adapter](../adr/0024-graph-mail-adapter-defer.md)
- [docs/notify/risk-register.md R23](../notify/risk-register.md) — Graph deferral risk
- [docs/notify/milestones.md](../notify/milestones.md) — M3/M7 status mapping
- [docs/notify/feature-matrix.md](../notify/feature-matrix.md) — A1 Email parenthetical + H14 Provider Management Graph row
- [docs/state/current-state.md](../state/current-state.md) — Runtime snapshot (Entra + Vault + ConfigMap state)
- [docs/runbooks/RB-faz-23-dns-records-acik-com.md](RB-faz-23-dns-records-acik-com.md) — SPF/DMARC/DKIM (mail authentication baseline; Graph activation sonrası re-validate)
- [docs/runbooks/RB-notification-outage-fallback.md](RB-notification-outage-fallback.md) — D43 outage fallback (bağımsız path; Graph activation ile compatibility)
- Board: [#892](https://github.com/Halildeu/platform-k8s-gitops/issues/892) — P3 Backlog reactivation tracker

## 10. Last Update

**2026-05-20 (Session 42 — Codex `019e44b1` defer contract alignment)** — Runbook yaratıldı. Activation deferred; reactivation trigger conditions + 5-step atomic chain documented. Owner-action required: client secret + ApplicationAccessPolicy + Vault seed + ConfigMap flag + pod rollout + smoke acceptance + rollback procedure all in-scope.
