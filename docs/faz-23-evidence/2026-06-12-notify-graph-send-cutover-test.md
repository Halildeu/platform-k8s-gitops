# Faz 23.8 — Backend Mail Send SMTP → Graph Cutover (TEST) Evidence (2026-06-12)

> **Scope**: notification-orchestrator backend mail send path SMTP → Microsoft Graph app-only cutover, **TEST cluster** (prod ayrı owner-gated slot)
> **PR**: #1477 MERGED (`00466d2a`) — ESO uncomment + ConfigMap flag
> **ADR**: ADR-0024 D1-D6 reactivation; Codex thread `019ebc0e` REVISE→absorb (plan) + post-impl AGREE
> **Trigger**: App Password / legacy SMTP basic-auth deprecation riski (bu tenant'ta Conditional Access agresif — device-code 4× timeout 2026-06-12) + D7b Graph app-only external delivery PROOF (ai@acik.com → serban recipient-confirmed)
> **Backend GraphMailAdapter DEĞİŞMEDİ source-side** — sadece `notify.adapters.graph.enabled` flag flip (mutual exclusion)

## 1. İddia (ne yapıldı)

Test cluster notification-orchestrator mail GÖNDERME path'i SMTP (Office 365 relay, App Password basic-auth) → **Microsoft Graph app-only** (`POST /users/ai@acik.com/sendMail`, client_credentials token) cutover edildi. GraphMailAdapter `@ConditionalOnProperty(notify.adapters.graph.enabled=true)` ile aktif; SmtpAdapter mutual exclusion ile pasif.

## 2. İspatlar (LIVE doğrulanan — adapter/infra seviyesi)

| Gate | Komut | Sonuç |
|---|---|---|
| **G1 ESO Ready** | `kubectl get externalsecret notification-orchestrator-secrets -o jsonpath status` | `True SecretSynced` ✅ |
| **G2 Secret 3 Graph key** | `kubectl get secret ... -o json \| jq base64d len` | NOTIFY_ADAPTERS_GRAPH_CLIENT_ID len=36, CLIENT_SECRET len=40, TENANT_ID len=36 ✅ |
| **G3 GraphMailAdapter active** | boot log | `GraphMailAdapter initialized: senderMailbox=ai@acik.com fromName="Ai - Açık Holding (test)" saveToSentItems=true` ✅ + `GraphTokenService initialized` (tenantId + clientId-prefix masked logged) ✅ |
| **G3-neg SmtpAdapter absent** | boot log grep `SmtpAdapter` count | **0** (mutual exclusion proven; Slack/Teams/SMS adapter'lar normal aktif) ✅ |
| **G4 Pod env** | `kubectl exec ... env \| grep GRAPH_ENABLED` | `NOTIFY_ADAPTERS_GRAPH_ENABLED=true` ✅ |
| **Binary provenance** | `gh search GraphMailAdapter platform-backend` | `com/serban/notify/adapter/GraphMailAdapter.java` main'de + GraphMailAdapterTest + GraphTokenServiceTest → live image (sha-175b3da) Graph-inclusive → digest bump GEREKMEZ ✅ |

## 3. ✅ Functional smoke PROVEN (2026-06-12 15:26-15:28 UTC) — §8

**No Fake Work HARD RULE**: §2'deki "adapter/infra LIVE ama end-to-end intent smoke pending" durumu **2026-06-12'de KAPANDI**. Gerçek bir intent (`POST /api/v1/notify/intents` email channel) → GraphMailAdapter.send() → Graph POST /sendMail → **DELIVERED + Sent Items + Inbox receipt** uçtan-uca koşuldu ve doğrulandı. Tam kanıt **§8**'de.

Kısa özet:
- Intent `graph-smoke-1781278009` → **HTTP 202 ACCEPTED** → intent `COMPLETED`
- `notification_delivery`: status=**DELIVERED**, provider_msg_id=`<af51812a-…@notification-orchestrator-graph>`
- Pod log: `GraphMailAdapter : graph mail accepted: subject=<D29 Test> message_id=<af51812a-…@notification-orchestrator-graph> status=202` + `GraphTokenService : Graph access_token refreshed`
- ai@acik.com **Sent Items** (saveToSentItems=true) + **Inbox** (gerçek teslim) + delivered e-postanın `x-notify-message-id` header'ı = DB provider_msg_id (**birebir** uçtan-uca izlenebilirlik)

GraphMailAdapter'ın **kendi code path'i** (in-cluster GraphTokenService app-only auth + payload builder + Graph POST) artık bir gerçek intent ile **kanıtlandı** (D7b raw-API proof'undan ayrı kapı kapandı).

## 4. Kalan acceptance (next step)

D7b'nin `saveToSentItems=true` avantajı: GraphMailAdapter bir email gönderdiğinde ai@acik.com Sent Items'a kopya yazar → **D7 read helper** (`graph-mail-list.sh --search`) ile teslim doğrulanabilir.

Tam acceptance smoke (Codex `019ebc0e` gate listesi) — **2026-06-12 KOŞULDU (§8)**:
- [x] Intent: `POST /api/v1/notify/intents` email channel (JWT + template + recipient) → **202 ACCEPTED**
- [x] Delivery: delivery row `DELIVERED` + provider_msg_id `<af51812a-…@notification-orchestrator-graph>`
- [x] Mailbox: ai@acik.com **Sent Items** (saveToSentItems) + **Inbox receipt** (self-send, gerçek teslim)
- [x] Headers: `Authentication-Results` yakalandı (`dkim=none; dmarc=none` — intra-tenant Internal; **DKIM/DMARC prod gate**, header kaydı ✓) + `x-notify-message-id` = DB provider_msg_id
- [x] Negative: AADSTS / Graph 403/429/5xx / duplicate YOK (status=202, all_delivered=true)
- [ ] Soak → **prod ayrı owner-gated slot** (D30 disiplini) — TEST functional PROVEN, prod ayrı

## 5. Rollback (doğrulanmış güvenli)

```
NOTIFY_ADAPTERS_GRAPH_ENABLED=false (ConfigMap revert) + rollout restart
→ SmtpAdapter @ConditionalOnProperty(matchIfMissing=true) tekrar aktif
→ SMTP credentials + config KORUNUYOR (üstte); AAP/consent/app-reg dokunulmaz
```

## 6. Credential (Codex `019ebc0e` #4 absorb)

Backend için **dedicated client secret** üretildi (display name `notify-orchestrator-test-graph-20260612`, 12 ay; KeyId local credential dosyasında kayıtlı, doc'a yazılmaz) — D7/D7b agent helper secret'inden **AYRI** → bağımsız rotation. Test Vault `kv/platform/notification-orchestrator.graph_*` (platform-vault-test) seed; prod cutover'da ayrı prod backend secret üretilecek.

## 7. Cross-AI Peer Review

- **Implementer**: Claude (Anthropic) — Session Faz 23.8 backend Graph cutover
- **Reviewer (plan + post-impl)**: Codex (OpenAI GPT-5.2) thread `019ebc0e` — plan REVISE-with-conditions → absorb (test-first, prod separate); post-impl REVISE (apply-sequencing P1 + comment P3) → absorb → AGREE
- **Reviewer (functional smoke)**: Codex thread `019ebc5b` (handoff review) MED items — Sent-Items folder-specific + KC persona auth preflight → §8 reçetesine absorbed
- **Verdict**: AGREE — adapter/infra LIVE + **functional end-to-end smoke PROVEN (§8)**

**TEST closure**: Bu cutover TEST için **DONE** — §8 end-to-end intent smoke + DELIVERED + Sent Items + Inbox receipt + Authentication-Results yakalandı. **Prod ayrı owner-gated slot** (ayrı prod secret + DKIM/DMARC re-validate + 72h soak; D30 disiplini).

## 8. Functional Smoke Evidence (2026-06-12 15:26–15:28 UTC) — LIVE

**Senaryo**: gerçek intent → GraphMailAdapter code path → Graph 202 → DELIVERED + ai@acik.com self-send (Sent Items + Inbox makine-okunur doğrulama). Tüm eligibility guard'lar AÇIK (NOTIFY_AUTHZ + PREFERENCES + SUBSCRIBER_IDENTITY_STRICT).

### 8.1 Setup (proven t318 ALLOW-path reuse)
- **Persona** `d29-evidence-tester` (realm `platform-test`, KC test container `:8082`) → JWT mint (frontend public client, password grant); claims: `iss=https://testai.acik.com/realms/platform-test`, `org_id=default`, `subscriberId=t318-smoke-1779625913`, `aud=[notification-orchestrator,…]`. Test persona pw reset (operator login DEĞİL — HARD RULE uyumlu).
- **Subscriber** `t318-smoke-1779625913`: email → `ai@acik.com` (`email_verified=true`); smoke sonrası **orijinal değere geri alındı** (test data temiz).
- **OpenFGA authz** (store `01KPP0CFP4G82K42Y6NYSPT4JF`, model `01KS8QE8T1EJ2DF5CRS4VV9YX1`): `Check(subscriber:t318-smoke-1779625913, can_receive, template:t1)` → **allowed:true** (t318 ALLOW tuple'ları mevcut).
- **Template** `t1` (en, `external_allowed=true`, body_html+body_text).

### 8.2 Intent + Delivery (LIVE)
```
POST /api/v1/notify/intents (Bearer persona-JWT, via api-gateway)
  intentId=graph-smoke-1781278009 topicKey=auth.password-reset channels=[email]
  recipients=[{type:subscriber, subscriberId:t318-smoke-1779625913}] template={t1,v1,en}
→ HTTP 202 {"status":"ACCEPTED"}

notify.notification_delivery:
  channel=email status=DELIVERED delivered_at=2026-06-12 15:27:01
  provider_msg_id=<af51812a-941e-4edc-a092-9bd0f0b12e39@notification-orchestrator-graph>
notify.notification_intent: status=COMPLETED
```

### 8.3 Pod log (GraphMailAdapter code path — KESİN KANIT)
```
c.s.notify.provider.GraphTokenService : Graph access_token refreshed: expires_in=3599
c.s.notify.adapter.GraphMailAdapter   : graph mail accepted: to=<hash:07c51b85…> subject=<D29 Test>
                                        message_id=<af51812a-…@notification-orchestrator-graph> status=202
c.s.n.delivery.DeliveryDispatchService: dispatch end: intentId=graph-smoke-1781278009 attempted=1 all_delivered=true
```
> `provider=smtp-default` DB kolonu statik config label'ı; gerçek adapter = GraphMailAdapter (message_id format + GraphTokenService log + saveToSentItems kesin kanıt).

### 8.4 Mailbox (ai@acik.com self-send, Graph API ile doğrulandı)
- **Sent Items**: `2026-06-12T15:28:13Z | D29 Test | to:[ai@acik.com]` (saveToSentItems=true)
- **Inbox**: `2026-06-12T15:28:15Z | D29 Test` (gerçek Graph teslim, alındı)
- **Delivered e-posta internet header'ları** (49 header):
  - `x-notify-message-id: <af51812a-941e-4edc-a092-9bd0f0b12e39@notification-orchestrator-graph>` → **DB provider_msg_id ile BİREBİR** (uçtan-uca izlenebilirlik)
  - `Authentication-Results: dkim=none (message not signed); dmarc=none action=none; header.from=acik.com`
  - `X-MS-Exchange-Organization-AuthAs: Internal` (intra-tenant self-send)

> **Dürüstlük notu (Codex `019ebc5b` absorb)**: Intra-tenant self-send **external SPF/DKIM/DMARC pass kanıtı ÜRETMEZ**; external `Authentication-Results` hâlâ **prod/external deliverability gate altında pending**. Bu D7c TEST functional smoke'u bloklamaz (adapter code path + Graph 202 + delivery + mailbox kanıtlandı). D7b external delivery (serban/hotmail recipient-confirmed, no-NDR) iyi yan kanıt ama external auth-header kanıtı **değil** (o mailbox'lar okunamadı). `dkim=none` = DKIM imzalama **prod-cutover gate**.

### 8.5 Negatif kontrol
AADSTS yok · Graph 403/429/5xx yok · status=202 · `all_delivered=true` · duplicate delivery yok.
