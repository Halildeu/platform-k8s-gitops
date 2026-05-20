# RB — Faz 23.3 JetSMS SMS Provider Cutover

> SMS provider'ı NetGSM'den JetSMS'e geçirme runbook'u — JetSMS primary +
> NetGSM secondary failover. PR-4 (ESO + ConfigMap config prep) bu runbook'un
> ön-koşuludur; runbook PR-5 cutover adımlarını tanımlar.

## Bağlam

Faz 23.3 SMS multi-provider 5-PR dizisi:

| PR | Kapsam | Durum |
|----|--------|-------|
| PR-0 | Docs alignment (JetSMS primary + NetGSM secondary) | MERGED platform-k8s-gitops #831 |
| PR-1 | `SmsProvider` abstraction + `SmsAdapter` facade | MERGED platform-backend #249 |
| PR-2 | `JetSmsProvider` send + failover matrix | MERGED platform-backend #250 |
| PR-3 | JetSMS DLR polling + generic ingest core | MERGED platform-backend #252 |
| PR-4 | GitOps ESO + ConfigMap config prep (additive) | bu PR |
| PR-5 | Cutover — image bump + provider flip + smoke | bu runbook |

JetSMS DLR **POLL-mode**: NetGSM webhook PUSH ile DLR bildirir; JetSMS webhook
göndermez — backend `HttpSmsReport` endpoint'ini periyodik poll eder
(`JetSmsDlrPollingWorker`, fixedDelay 60s, `@ConditionalOnProperty
notify.dispatch.enabled=true`).

## Pre-PR-4 Gate — Vault blank-seed (TAMAMLANDI 2026-05-19)

> **Neden zorunlu gate**: PR-4 ESO manifest'i (`externalsecret-notify.yaml`)
> 3 yeni `remoteRef.property` (`sms_jetsms_username/password/originator`)
> ekler. ESO Vault provider, var olan bir path'te EKSİK bir property için o
> key'i boş bırakmaz — tüm `ExternalSecret` reconcile'ını fail eder
> (`SecretSyncedError`). Property'nin **boş string değerle VAR olması** gerekir
> (Codex `019e4022` S1). Bu yüzden PR-4 ESO değişikliğinin merge'inden ÖNCE
> Vault'a boş seed yapılır — aksi halde umbrella `platform-test` ArgoCD
> auto-sync ESO'yu degraded duruma sokar.

Yapıldı (Pre-Production Full Authority, 2026-05-19) — `kv patch`, diğer
key'lere dokunmaz:

```bash
docker exec -e VAULT_TOKEN="$ROOT_TOKEN" platform-vault-test \
  vault kv patch kv/platform/notification-orchestrator \
    sms_jetsms_username= sms_jetsms_password= sms_jetsms_originator=
docker exec -e VAULT_TOKEN="$ROOT_TOKEN" platform-vault-prod \
  vault kv patch kv/platform/notification-orchestrator \
    sms_jetsms_username= sms_jetsms_password= sms_jetsms_originator=
```

Doğrulandı: test (secret version 12) + prod (version 5) — 3 `sms_jetsms_*`
property boş string değerle mevcut. PR-4 ESO değişikliği artık apply-safe.

## Tetik

PR-4 merged (ESO 3 JetSMS key + ConfigMap 2 URL) **ve** JetSMS API credential'ları
(username / password / originator) operator elinde → PR-5 cutover başlatılır.

## Ön-koşullar

- [ ] PR-4 merged — `externalsecret-notify.yaml` (test + prod) JetSMS key ref'leri içeriyor
- [ ] JetSMS API credential'ları operator elinde (JetSMS sözleşmesi aktif)
- [ ] platform-backend `main`'de PR #249/#250/#252 → yeni image digest build edilmiş (GHCR)
- [ ] NetGSM secondary kararı netleşmiş: credential gerçek + smoke'lu mu? (R1 #762 blocker durumu)

## Adımlar

### 1. Vault JetSMS gerçek credential seed (test) — ~2 dk

Pre-PR-4 Gate'te boş seed'lenen 3 key'i gerçek JetSMS credential'larıyla
UPDATE eder (yine `kv patch`):

```bash
docker exec -e VAULT_TOKEN="$TEST_ROOT_TOKEN" platform-vault-test \
  vault kv patch kv/platform/notification-orchestrator \
    sms_jetsms_username='<JetSMS API user>' \
    sms_jetsms_password='<JetSMS API pass>' \
    sms_jetsms_originator='<onaylı gönderici başlığı>'
```

Beklenen: `Success! Data written to: kv/platform/notification-orchestrator`.
Fail sinyali: token expired / path yok → `vault kv get kv/platform/notification-orchestrator` ile doğrula.

### 2. ESO sync + Secret doğrulama — ~1 dk

`refreshInterval` 1h; force-sync için annotate:

```bash
kubectl --context k3d-test -n platform-test annotate externalsecret \
  notification-orchestrator-secrets force-sync="$(date +%s)" --overwrite
kubectl --context k3d-test -n platform-test get externalsecret \
  notification-orchestrator-secrets -o jsonpath='{.status.conditions[0]}'
kubectl --context k3d-test -n platform-test get secret \
  notification-orchestrator-secrets \
  -o jsonpath='{.data.NOTIFY_ADAPTERS_SMS_JETSMS_USERNAME}' | base64 -d
```

Beklenen: ESO `Ready=True`; 3 JetSMS key de Secret'ta non-empty.

> **Acceptance kuralı**: username **+ password + originator** ÜÇÜ de non-empty.
> `JetSmsProvider` password-blank için erken gate yoktur — ESO `Ready` tek
> başına yetmez (Codex 019e4022 adversarial not).

### 3. Backend image digest bump — PR (kustomize/overlays/test)

`overlays/test/kustomization.yaml` notification-orchestrator image digest'ini
PR #249/#250/#252 içeren build'e pin'le (immutable `sha256:...` — D30 kuralı,
`main-stable` YASAK).

### 4. Provider flip — ConfigMap (image bump ile AYNI PR/apply, atomik)

```yaml
NOTIFY_ADAPTERS_SMS_PRIMARY_PROVIDER: "jetsms"
# NetGSM secondary YALNIZCA credential gerçek + smoke'lu ise:
NOTIFY_ADAPTERS_SMS_SECONDARY_PROVIDER: "netgsm"
```

> NetGSM hâlâ R1 (#762) blocker ise `secondary-provider` BOŞ bırak. Aksi halde
> JetSMS transient hatasında boş-credential NetGSM'e failover denenir,
> `PROVIDER_CONFIG` hatası üretir ve gerçek failure semantiğini bulandırır.
> Durum etiketi: "JetSMS-primary degraded mode; NetGSM failover acceptance pending".

> **Sıralama kritik**: image bump + ConfigMap flip atomik olmalı. Flip eski
> image'a (PR #249 öncesi) uygulanırsa `SmsAdapter` 'primary jetsms not
> registered' → SMS FAILED. Test overlay umbrella ArgoCD app `automated +
> selfHeal` ile sync ettiği için flip merge'i tek başına apply tetikler.

### 5. Apply + rollout — ~3 dk

```bash
kubectl --context k3d-test -n platform-test apply -k kustomize/overlays/test
kubectl --context k3d-test -n platform-test rollout status \
  deploy/notification-orchestrator --timeout=300s
```

### 6. Smoke — JetSMS send + DLR poll round-trip

- Pod log: `JetSmsDlrPollingWorker activated: batchSize=100 pollInterval=PT1M
  leaseDuration=PT2M maxAge=PT72H scheduling=true` — effective DLR tuning
  değerlerini log'dan doğrula (PR-4 ConfigMap'e yazmadı, backend default).
- Test SMS intent → delivery `ACCEPTED` + `provider=jetsms` + `provider_msg_id=jetsms-<id>`.
- ~60-120s sonra DLR poll cycle → delivery `DELIVERED` (veya `FAILED`) + intent terminal.
- Browser console + network temiz (HARD RULE — deploy sonrası tarayıcı verify).

## Egress notu

JetSMS `api.jetsms.com.tr` HTTPS **443** — test overlay'deki
`netpol-notification-egress-mail-providers.yaml` port 443 egress kuralı
(`0.0.0.0/0` minus RFC1918) JetSMS'i ZATEN kapsar. Ek NetworkPolicy gerekmez;
bu 443 kuralı JetSMS için load-bearing'dir (daraltılırsa SMS kırılır).

**Prod**: notification-orchestrator-özel egress NetworkPolicy YOK (pre-existing
gap — base default-deny aktif). Prod cutover öncesi ayrı preflight: prod notify
egress aktivasyonu (rollback + smoke + canlı kanıt ile, ayrı controlled iş).

## Rollback

ConfigMap flip + image digest'i revert + apply:

```bash
git revert <PR-5 commit> && kubectl --context k3d-test -n platform-test \
  apply -k kustomize/overlays/test
```

`primary-provider=netgsm` + eski image digest → NetGSM-only restore. D30 72h
warm rollback penceresi geçerli.

## Acceptance

- [ ] Vault 3 JetSMS key non-empty (username + password + originator)
- [ ] ESO `Ready=True`, Secret render OK
- [ ] Pod yeni image digest (`imageID` == GHCR digest)
- [ ] Pod log `JetSmsDlrPollingWorker activated`
- [ ] JetSMS send smoke: delivery `ACCEPTED`, `provider=jetsms`
- [ ] DLR poll smoke: delivery terminal transition (`DELIVERED`/`FAILED`)
- [ ] Browser console / network temiz

## Referans

- platform-backend PR #249/#250/#252 — JetSMS backend kod
- platform-k8s-gitops PR #831 (PR-0 docs) + bu PR (PR-4 config prep)
- Codex thread `019e3f82` (plan), `019e3ff7` (PR-3 review), `019e4022` (PR-4 plan)
- `docs/runbooks/RB-faz-23-4-dlr-smoke-test.md` — NetGSM DLR webhook smoke

---

## Prod Cutover Addendum — M4 A.2 + A.3 (2026-05-20, PR #911)

> Codex `019e4514` iter-3 P1 absorb (2026-05-20): prod cutover'un test
> overlay'inden farklı operasyonel adımları net olarak ayırın. Test
> runbook'u yukarıda; aşağıdaki bölüm sadece PROD cutover için.

### Pre-conditions (apply blocker — agent + operator paralel)

| # | Kontrol | Komut | Beklenen |
|---|---|---|---|
| 1 | Prod Vault `sms_jetsms_*` 3 key non-empty | `vault kv get -format=json kv/platform/notification-orchestrator \| jq '.data.data \| {u:(.sms_jetsms_username \| length),p:(.sms_jetsms_password \| length),o:(.sms_jetsms_originator \| length)}'` | u/p/o > 0 (length-only, no plaintext) |
| 2 | Prod ESO `Ready=True` | `kubectl --context k3d-prod -n platform-prod get externalsecret notification-orchestrator-secrets -o json \| jq '.status.conditions[] \| select(.type=="Ready") \| .status'` | `"True"` |
| 3 | Backend secret render OK | `kubectl --context k3d-prod -n platform-prod get secret notification-orchestrator-secrets -o json \| jq -r '.data \| keys[]' \| grep sms_jetsms` | 3 anahtar listede |
| 4 | Pod imageID (pre-cutover) | `kubectl --context k3d-prod -n platform-prod get pod -l app.kubernetes.io/name=notification-orchestrator -o jsonpath='{.items[0].status.containerStatuses[0].imageID}'` | sha-70491543 (eski; cutover öncesi) |

### Apply (prod overlay merge sonrası)

```bash
# 1. Git pull (PR #911 merged sonrası)
ssh halil@staging-sw "cd /home/halil/platform-k8s-gitops && git pull --ff-only"

# 2. Apply prod overlay
ssh halil@staging-sw "kubectl --context k3d-prod -n platform-prod apply -k /home/halil/platform-k8s-gitops/kustomize/overlays/prod"

# 3. Rollout restart (annotation bump yeterli ama explicit garantili)
ssh halil@staging-sw "kubectl --context k3d-prod -n platform-prod rollout restart deploy/notification-orchestrator"

# 4. Rollout status
ssh halil@staging-sw "kubectl --context k3d-prod -n platform-prod rollout status deploy/notification-orchestrator --timeout=180s"
```

### Post-apply verify (acceptance gate)

| # | Kontrol | Komut | Beklenen |
|---|---|---|---|
| 1 | Pod imageID match | `kubectl --context k3d-prod -n platform-prod get pod -l app.kubernetes.io/name=notification-orchestrator -o jsonpath='{.items[0].status.containerStatuses[0].imageID}'` | `sha256:30b0bf658dcd879c531451352c4e37680551fe14ab667a255eea36adbb281a5b` |
| 2 | Rendered ConfigMap JetSMS (non-secret) | `kubectl --context k3d-prod -n platform-prod get configmap notification-orchestrator-config -o json \| jq '.data \| {NOTIFY_ADAPTERS_SMS_PRIMARY_PROVIDER, NOTIFY_ADAPTERS_SMS_JETSMS_MULTIPART_ENABLED, NOTIFY_ADAPTERS_SMS_JETSMS_ON_LENGTH_PROBLEM, NOTIFY_ADAPTERS_SMS_JETSMS_SOAP_OPERATION, NOTIFY_ADAPTERS_SMS_JETSMS_CHANNEL, NOTIFY_ADAPTERS_SMS_JETSMS_CHANNEL_ALLOWED, NOTIFY_ADAPTERS_SMS_JETSMS_CHANNEL_OTP_TOPIC_KEYS, NOTIFY_ADAPTERS_SMS_JETSMS_CHANNEL_OTP_MAX_LENGTH}'` | 8 non-secret config key set + PRIMARY=jetsms + OTP_TOPIC_KEYS="" (BLANK R24) — **Codex iter-2 P1 absorb**: Secret değerleri (USERNAME/PASSWORD/ORIGINATOR) DUMP edilmez; envFrom render kanıtı ayrı (gate #2b key-only) |
| 2b | Secret JetSMS keys exist (key-only, no plaintext) | `kubectl --context k3d-prod -n platform-prod get secret notification-orchestrator-secrets -o json \| jq '.data \| keys[] \| select(startswith("NOTIFY_ADAPTERS_SMS_JETSMS_"))'` | 3 key listede: `NOTIFY_ADAPTERS_SMS_JETSMS_USERNAME` + `_PASSWORD` + `_ORIGINATOR` (values base64-encoded; **decode etmeyin**) |
| 3 | NetworkPolicy egress mevcut | `kubectl --context k3d-prod -n platform-prod get networkpolicy allow-notification-orchestrator-egress-mail-providers -o jsonpath='{.spec.podSelector.matchLabels}'` | triple-label selector |
| 4 | Pod log SmsAdapter primary | `kubectl --context k3d-prod -n platform-prod logs deploy/notification-orchestrator --tail=200 \| grep "SmsAdapter activated"` | `primary=jetsms` |
| 5 | Pod log DLR worker | `kubectl --context k3d-prod -n platform-prod logs deploy/notification-orchestrator --tail=200 \| grep "JetSmsDlrPollingWorker activated"` | aktif |

### Smoke (A.4 + A.5 — operator + agent paralel)

**A.4 SMS intent submit (prod canary persona)**:

```bash
# Persona: prod-smoke-tester user JWT (kullanıcı kararı: prod persona varsa kullan; yoksa create)
# Phone: kullanıcı test numarası (+905551815564 önceki test-overlay'de proven)
TOKEN="<prod smoke-tester JWT>"
INTENT_ID="prod-cutover-canary-$(date +%s)"

curl -sS -X POST https://ai.acik.com/api/v1/notify/intents \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"intentId\": \"$INTENT_ID\",
    \"idempotencyKey\": \"$INTENT_ID\",
    \"orgId\": \"default\",
    \"topicKey\": \"system.canary.smoke\",
    \"severity\": \"info\",
    \"dataClassification\": \"system\",
    \"recipients\": [{\"type\":\"external\",\"phone\":\"+905551815564\"}],
    \"template\": {\"templateId\":\"sms-multipart-test\",\"version\":1,\"locale\":\"tr-TR\"},
    \"channels\": [\"sms\"],
    \"payload\": {}
  }" | jq .

# Beklenen: HTTP 202, intentId same, status=ACCEPTED
```

**A.5 DLR terminal state evidence**:

```bash
# Cluster log:
kubectl --context k3d-prod -n platform-prod logs deploy/notification-orchestrator --tail=200 \
  | grep -E "jetsms SOAP ACCEPTED|jetsms channel resolved|dlr jetsms UPDATED"

# Beklenen log lines:
#   jetsms channel resolved: default channel (no allowlist match; OTP blank) → VF
#   jetsms SOAP ACCEPTED (awaits DLR poll): msg_id=jetsms-<id> segments=N channel=VF
#   dlr jetsms UPDATED: code=1 delivery_id=<id> prior=ACCEPTED new=DELIVERED

# PG delivery row:
ssh halil@staging-sw "docker exec platform-pg-prod psql -U platform -d notify_db -c \"
  SELECT intent_id, status, channel, provider, provider_msg_id, delivered_at
  FROM notify.notification_delivery
  WHERE intent_id LIKE 'prod-cutover-canary-%'
  ORDER BY created_at DESC LIMIT 5;\""

# audit_event actual_channel:
ssh halil@staging-sw "docker exec platform-pg-prod psql -U platform -d notify_db -c \"
  SELECT event_type, details->>'actual_channel' as actual_channel, details->>'provider_msg_id' as msg_id
  FROM notify.audit_event
  WHERE intent_id LIKE 'prod-cutover-canary-%' AND event_type='DELIVERY_ACCEPTED'
  ORDER BY occurred_at DESC LIMIT 3;\""
```

### A.6 Rollback (D30 72h warm window)

ConfigMap flip + image digest revert + apply:

```bash
# Option 1: PR revert (PREFERRED — GitOps canonical truth)
git revert <PR #911 commit>
git push
# (CI yeşillenince + Codex AGREE) → merge revert PR → cluster auto-apply
```

> **Codex iter-2 absorb (non-blocking note)**: Option 2 break-glass-only
> + same-incident reconciliation PR şart. Manual `kubectl patch` / `set
> image` GitOps canonical truth'u bypass eder → drift; emergency
> kullanım sonrası **aynı incident içinde** revert/forward PR ile
> GitOps state'i tekrar canonical hale getirin.

```bash
# Option 2: Break-glass manual (EMERGENCY ONLY — IMMEDIATE reconciliation PR şart)
ssh halil@staging-sw "kubectl --context k3d-prod -n platform-prod patch configmap notification-orchestrator-config \
  --type=json -p='[{\"op\":\"replace\",\"path\":\"/data/NOTIFY_ADAPTERS_SMS_PRIMARY_PROVIDER\",\"value\":\"netgsm\"}]'"

ssh halil@staging-sw "kubectl --context k3d-prod -n platform-prod set image deploy/notification-orchestrator \
  notification-orchestrator=ghcr.io/halildeu/platform-backend-notification-orchestrator@sha256:70491543fdc3341fbf7685773efec74a6ca2ca473c90e38f89a5247e3568b1c3"

ssh halil@staging-sw "kubectl --context k3d-prod -n platform-prod rollout status deploy/notification-orchestrator --timeout=180s"

# IMMEDIATELY after break-glass apply: open reconciliation PR
# (revert PR #911 OR forward fix PR) so cluster state == GitOps truth.
# Break-glass without reconciliation = drift = audit gap.
```

`primary-provider=netgsm` + sha-70491543 → NetGSM-only restore. R1 NetGSM
contract henüz aktive değilse SmsAdapter "primary netgsm not registered"
crash; bu durumda rollback geçici NOT mümkün (forward-only).

### R24 mitigation post-merge (provisioning sonrası)

JetSMS Biotekno OTP allowlist provisioning tamamlanınca:

```bash
# Operator config patch (PR'sız hızlı flip):
ssh halil@staging-sw "kubectl --context k3d-prod -n platform-prod patch configmap notification-orchestrator-config \
  --type=json -p='[{\"op\":\"replace\",\"path\":\"/data/NOTIFY_ADAPTERS_SMS_JETSMS_CHANNEL_OTP_TOPIC_KEYS\",\"value\":\"auth.mfa-otp,auth.password-reset-otp\"}]'"

# Annotation bump for rolling restart:
ssh halil@staging-sw "kubectl --context k3d-prod -n platform-prod annotate deploy/notification-orchestrator sms.acik.com/jetsms-otp-allowlist-enable=\"$(date +%s)\""

ssh halil@staging-sw "kubectl --context k3d-prod -n platform-prod rollout restart deploy/notification-orchestrator"

# VFO smoke (kısa OTP topic):
# (test cluster A senaryo pattern paralel)
```

### Acceptance (prod M4 A.2 + A.3 closure)

- [ ] Prod Vault 3 JetSMS key non-empty (length-only proof)
- [ ] Prod ESO `Ready=True`
- [ ] Pod imageID = sha256:30b0bf658dcd...
- [ ] Pod ConfigMap 8 non-secret JETSMS key set (PRIMARY=jetsms, OTP_TOPIC_KEYS="") — gate #2 jq filter (Codex iter-2 P1 absorb)
- [ ] Pod Secret 3 JETSMS key mevcut (USERNAME/PASSWORD/ORIGINATOR — key-only/length-only) — gate #2b
- [ ] NetworkPolicy `allow-notification-orchestrator-egress-mail-providers` exists
- [ ] Pod log SmsAdapter primary=jetsms + DlrPollingWorker activated
- [ ] A.4 prod canary SMS intent: ACCEPTED + provider=jetsms + msg_id
- [ ] A.5 DLR terminal state: DELIVERED
- [ ] A.5 audit_event DELIVERY_ACCEPTED.actual_channel=VF
- [ ] A.6 rollback plan documented (bu addendum)
- [ ] R24 follow-up: Biotekno OTP allowlist provisioning (ops + provider coordination)
