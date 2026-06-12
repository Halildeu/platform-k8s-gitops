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

## 3. İspatlamaz (pending — end-to-end intent send smoke)

**No Fake Work HARD RULE — overclaim YASAK**: Adapter/infra LIVE doğrulandı, ama **end-to-end intent→delivery→Sent-Items smoke henüz koşulmadı**:

- `POST /api/v1/notify/intents` (email channel) → GraphMailAdapter.send() → Graph POST /sendMail → DELIVERED + Sent Items proof henüz YOK
- Bu smoke JWT mint (Keycloak test realm org/role) + active EMAIL template + verified subscriber + DB erişim gerektiriyor; bu ortamda hızlı kurulamadı (psql notification pod'da yok, postgres pod Error state, JWT mint setup'lı değil)

**Mevcut kanıt sınırı**: GraphMailAdapter'ın **kendi kodu** (token service in-cluster + payload builder) bir gerçek intent ile test edilmedi. D7b raw Graph API'yi (POST /sendMail) kanıtladı (external delivery recipient-confirmed) ama **adapter'ın spesifik code path'i** ayrı kapı.

## 4. Kalan acceptance (next step)

D7b'nin `saveToSentItems=true` avantajı: GraphMailAdapter bir email gönderdiğinde ai@acik.com Sent Items'a kopya yazar → **D7 read helper** (`graph-mail-list.sh --search`) ile teslim doğrulanabilir.

Tam acceptance smoke (Codex `019ebc0e` gate listesi):
- [ ] Intent: `POST /api/v1/notify/intents` email channel (JWT + template + recipient)
- [ ] Delivery: delivery/audit row `DELIVERED` + provider message id
- [ ] Mailbox: ai@acik.com Sent Items'ta mesaj (D7 helper) + recipient inbox receipt
- [ ] Headers: `Authentication-Results` SPF/DKIM/DMARC capture (DKIM/DMARC ayrı remediation; header kaydı şart)
- [ ] Negative: AADSTS / Graph 403/429/5xx / duplicate delivery YOK
- [ ] Soak → **prod ayrı owner-gated slot** (D30 disiplini)

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
- **Verdict**: AGREE source-side + apply sequencing; adapter LIVE doğrulandı; end-to-end intent smoke pending

**Closure ≠ adapter LIVE**: Bu cutover "DONE" sayılması için §4 end-to-end intent smoke + Sent Items + Authentication-Results + soak gerekir. Şu an: **TEST adapter-LIVE + mutual exclusion proven; functional send acceptance pending**.
