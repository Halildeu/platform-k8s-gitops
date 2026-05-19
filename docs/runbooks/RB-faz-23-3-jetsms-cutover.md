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
