# RB-bl011-prod-sms-canary-execute — Prod SMS Canary Smoke (BL-011)

> **Status**: ✅ **LIVE DELIVERED 2026-05-25 16:58:45 UTC** — gerçek SMS gönderildi `+905551815564` numarasına. JetSMS provider_msg_id `jetsms-2605251959362908914`. DELIVERED 71s DLR cycle. 7/7 acceptance gate PASS. Evidence: `docs/faz-23-evidence/2026-05-25-bl011-prod-sms-canary-live.md`.
> **Discovery 2026-05-25**: Preflight sonucu prod notify_db boş data state (0 templates, 0 subscribers, 0 intents) + prod OpenFGA model `01KS15PF...` notification types DESTEKLEMİYOR (sadece D35 ERP types: action/branch/company/module/organization/project/report/report_group/user/warehouse). M4 cutover sadece infrastructure layer LIVE; functional+authz katmanları ayrı milestone'larda.
> **Codex strategic verdict chain**: 
> - iter-1 thread `019e5e76`: R28 keşif (DB seed eksik)
> - iter-2/3 thread `019e5ebe-2ec3-70e3-b408-37792c04f208`: B-with-lanes (BL-028a + BL-028b ayrı), Layer-2 fail-closed kanıt
> **Risk**: HARD CAP 3 SMS (önceki verdict 019e5b8a); recommended **max_count=1** — BL-028a VE BL-028b SONRASI
> **Recipient**: `+905551815564` (kullanıcı 2026-05-25 explicit onay — iki gate sonrası execute için saklanır)
> **Cost**: ~5-15 kuruş JetSMS (1-3 SMS aralığı) — iki gate tamam olduğunda

---

## 1. Bağlam (BL-011 prereq)

BL-010 prod scope COMPLETED 2026-05-25 (PR #1062 MERGED):
- `serban` realm `notify-canary` client scope LIVE
- `org_id` User Attribute mapper attach (oidc-usermodel-attribute-mapper)
- Persona `notify-canary-org-prod-default` Vault seed (41 char password)
- JWT 3-way claim verified (access_token + id_token + userinfo `org_id="default"`)
- Resource-server auth verified (HTTP 400 = `@Valid` pre-guard; controller reached)
- **Guard-pass behavioral proof** BL-011 acceptance scope

## 2. Codex iter-1 verdict — daraltma + revize

| Q | Codex önerisi (revize) |
|---|---|
| Q1 | **(b) Conservative 1-SMS Senaryo B** — `topic_key=marketing.campaign`, kısa body. A+C VFO senaryoları prod env'de gerçek davranış üretmez (`CHANNEL_OTP_TOPIC_KEYS=""` blank → tüm OTP'ler de VF'den çıkar) |
| Q2 | **(a) notify-canary-org-prod-default password grant** (frontend client; smoke-client backup) |
| Q3 | Canonical schema: `SubmitIntentRequest` DTO + `/v3/api-docs` authenticated probe |
| Q4 | Acceptance: metric `notify_org_access_match_total{source="org_id"}` increase + `notify.notification_delivery` row + `notify.audit_event_v2` `actual_channel=VF` + provider log (guard log line ŞARTI kaldırıldı — backend kod o satırı emit etmiyor) |
| Q5 | No-SMS preflight → JWT mint → tek POST → 90-120s observe → strict abort |
| Q6 | Cost cap 3'ü karşılıyor; recommended execute count **1** |

## 3. No-SMS Preflight (6 madde — execute öncesi tamam olmalı)

> **PREREQ #0 (BL-028/R28 — 2026-05-25 iter-3 absorb)**: **İKİ GATE** PASS olmadan BL-011 SMS canary execute YASAK:
>
> **Lane A — BL-028a (DB functional seed, agent-doable)**:
> - ✅ At least 1 active SMS-capable template (`notify.notification_template` `active=true`, `locale=tr-TR`, body_text doldurulmuş, `external_allowed=false`) — canonical `canary-prod-marketing-v1` v1 tr-TR
> - ✅ Canary subscriber row (`notify.subscriber_contact`: `org_id=default`, `subscriber_id=bl028-prod-canary-001`, `phone=+905551815564`, `phone_verified=true`)
> - ✅ Permission-service `:8090/actuator/health` reachable (port :8090 — :8094 drift fixed)
> - ✅ Backend env state canonical (`NOTIFY_AUTHZ_ENABLED=true`, `NOTIFY_AUTHZ_PERMISSION_SERVICE_URL=http://permission-service:8090`, `NOTIFY_DISPATCH_ENABLED=true`, `NOTIFY_PREFERENCES_ENABLED=true`)
> - ✅ Detay RB: `docs/runbooks/RB-bl028-prod-data-seed-execute.md` Lane A
>
> **Lane B — BL-028b (OpenFGA notification model cutover, operator+architecture gate, DEFERRED M4.6)**:
> - ✅ Prod OpenFGA store'a notification model revision yazıldı (subscriber + notification_topic + template types + relations); yeni prod model_id ULID
> - ✅ Permission-service runtime `ERP_OPENFGA_MODEL_ID` yeni model id'ye geçirildi (ESO sync + rollout restart + pod env verify)
> - ✅ Topic-inheritance tuple seed:
>   - `notification_topic:marketing.campaign#can_receive@subscriber:bl028-prod-canary-001`
>   - `template:canary-prod-marketing-v1#topic@notification_topic:marketing.campaign`
> - ✅ Permission check ALLOW kanıtı: `POST permission-service:8090/api/v1/internal/authz/check` → `{"allowed": true}`
> - ✅ ERP regression smoke (mevcut 10 type aynı kalmalı)
> - ✅ Detay RB: [`docs/runbooks/RB-bl028b-prod-openfga-notification-model-cutover.md`](RB-bl028b-prod-openfga-notification-model-cutover.md) — **READY-FOR-EXECUTION post M4.6 operator window** (Codex 019e5ee5 iter-2 AGREE; 12 section + 10 hard acceptance gate)
>
> **Lane A acceptance** BL-011'i unblock ETMEZ — Layer-2 fail-closed (backend `AuthzClient`: non-200/exception → `deny("authz_<code>")`; prod model notification types desteklemiyorsa permission-service `allowed=false` → `BLOCKED_BY_AUTHZ`). Sadece **Lane A + Lane B birlikte PASS** ile BL-011 execute olabilir.

### 3.1 Backend prod env confirmation

```bash
POD=notification-orchestrator-6f8bd9446f-5zz7p
NS=platform-prod
ssh halil@staging-sw "
kubectl --context k3d-prod -n $NS exec $POD -- env | grep -E '^(NOTIFY_AUTHZ_ENABLED|NOTIFY_DISPATCH_ENABLED|NOTIFY_ADAPTERS_SMS_(PRIMARY_PROVIDER|JETSMS_(CHANNEL|CHANNEL_ALLOWED|CHANNEL_OTP_TOPIC_KEYS)))'
"
```

**Beklenen state** (prod canonical 2026-05-25):
- `NOTIFY_AUTHZ_ENABLED=true` (Layer-1 guard active)
- `NOTIFY_DISPATCH_ENABLED=true` (provider'a gerçekten SMS gönderilir)
- `NOTIFY_ADAPTERS_SMS_PRIMARY_PROVIDER=jetsms`
- `NOTIFY_ADAPTERS_SMS_JETSMS_CHANNEL=VF`
- `NOTIFY_ADAPTERS_SMS_JETSMS_CHANNEL_ALLOWED=VF,VFO`
- `NOTIFY_ADAPTERS_SMS_JETSMS_CHANNEL_OTP_TOPIC_KEYS=` (blank — R24 workaround prod'da aktif)

### 3.2 Active marketing.campaign topic + SMS template

```bash
# Via pod exec (or via backend GET /api/v1/notify/topics)
kubectl --context k3d-prod -n $NS exec $POD -- curl -sS \
  -H "Authorization: Bearer \$ADMIN_TOKEN" \
  http://localhost:8089/api/v1/notify/topics?key=marketing.campaign 2>&1
```

**Beklenen**:
- `topic_key=marketing.campaign` enabled=true
- En az 1 active SMS template (canary için: kısa, single-segment body)
- `external_allowed=true` flag (eğer external recipient kullanılacaksa) VEYA canary subscriber path

### 3.3 Canary subscriber + contact phone match

**Pattern A**: Mevcut subscriber'ı kullan
```sql
SELECT id, subscriber_id, org_id, phone, phone_verified, source
FROM notify.subscriber_contact
WHERE phone = '+905551815564' AND org_id = 'default' AND phone_verified = true
LIMIT 1;
```

> **Schema note (Codex iter-3 P1 fix)**: Canonical table `notify.subscriber_contact` (NOT `notify.subscriber`); columns `phone` (NOT `contact_phone`), `phone_verified` (NOT `deleted_at`). Composite UNIQUE `(org_id, subscriber_id)`.

**Pattern B**: Canary subscriber yarat (PRE-execute, idempotent — BL-028a Lane A scope)
- subscriber_id: `bl028-prod-canary-001` (string identifier; subscriber master tablosu YOK — sadece subscriber_contact)
- org_id=`default`
- phone=`+905551815564`
- phone_verified=`true`
- OpenFGA tuple (topic-inheritance, BL-028b Lane B scope — Codex iter-2 P0 fix):
  - `notification_topic:marketing.campaign#can_receive@subscriber:bl028-prod-canary-001`
  - `template:canary-prod-marketing-v1#topic@notification_topic:marketing.campaign`
- Direct `subscriber#can_receive@template` tuple shape **YANLIŞ** — topic inheritance modeli kullan

**Pattern C** (Codex iter-1 risk warning): External recipient `{"type":"external","phone":"+905551815564"}`
- Template `external_allowed=true` gerek
- OpenFGA/permission path external için ALLOW gerek
- **Daha riskli** — önce A veya B tercih

### 3.4 OpenFGA permission ALLOW (internal contract)

> **Endpoint + contract (Codex iter-3 P2 fix)**: permission-service internal API endpoint `POST /api/v1/internal/authz/check`, auth `X-Internal-Api-Key` (NOT Bearer JWT), snake_case payload.

```bash
# Layer-2 OpenFGA check via permission-service internal API
# NOT: Bu check ancak BL-028b (prod OpenFGA notification model cutover) sonrası ALLOW dönebilir.
# Historical (pre-2026-05-25 12:01 UTC): prod model 01KS15PF... notification types DESTEKLEMİYOR idi → allowed=false beklenirdi.
# Güncel (post BL-028b LIVE 2026-05-25): prod model 01KSFFK9K3V43DD211Z79K3FYA notification types LIVE → allowed=true (tuple_match) döner.
INTERNAL_API_KEY=$(kubectl --context k3d-prod -n $NS exec $POD -- printenv NOTIFY_AUTHZ_INTERNAL_API_KEY 2>/dev/null)

kubectl --context k3d-prod -n $NS exec $POD -- curl -sS \
  -X POST \
  -H "X-Internal-Api-Key: $INTERNAL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "principal_type": "subscriber",
    "principal_id": "bl028-prod-canary-001",
    "relation": "can_receive",
    "object_type": "template",
    "object_id": "canary-prod-marketing-v1"
  }' \
  http://permission-service.platform-prod.svc.cluster.local:8090/api/v1/internal/authz/check
```

**Beklenen** (BL-028b sonrası): `{"allowed": true}` — yoksa BL-028b runbook çalıştır (prod OpenFGA notification model cutover + topic-inheritance tuple seed).

**Şu an** (BL-028b öncesi): `{"allowed": false}` veya `error` — Layer-2 fail-closed davranır, `BLOCKED_BY_AUTHZ` döner, SMS gitmez. Bu BEKLENEN bloked state.

### 3.5 Pre-metric snapshot

```bash
kubectl --context k3d-prod -n $NS exec $POD -- curl -sS http://localhost:8081/actuator/prometheus 2>&1 | \
  grep -E "^notify_org_access_match_total" | head -5
```

**Beklenen**: `notify_org_access_match_total{source="none"} N` (baseline; `source="org_id"` henüz yok veya 0). Bu baseline değer **execute sonrası karşılaştırmada** kullanılır.

## 4. Execute (1-SMS Senaryo B)

### 4.1 JWT mint

```bash
ssh halil@staging-sw 'bash -s' <<'OUTER'
ROOT_TOKEN=$(jq -r .root_token /home/halil/bootstrap-drill/vault-init-prod.json)
PERSONA_PASS=$(docker exec -e VAULT_TOKEN="$ROOT_TOKEN" platform-vault-prod \
  vault kv get -mount=kv -field=password platform/keycloak/persona/notify-canary-org-prod-default)
unset ROOT_TOKEN

ACCESS_TOKEN=$(curl -sS -X POST \
  "https://ai.acik.com/realms/serban/protocol/openid-connect/token" \
  -d "username=notify-canary-org-prod-default" \
  --data-urlencode "password=$PERSONA_PASS" \
  -d "grant_type=password" \
  -d "client_id=frontend" \
  -d "scope=openid notify-canary" | jq -r .access_token)
unset PERSONA_PASS

echo "JWT len=${#ACCESS_TOKEN}"

# Persist for next step (umask 077; never log token)
umask 077
echo "$ACCESS_TOKEN" > /tmp/bl011-jwt
OUTER
```

### 4.2 POST /api/v1/notify/intents (1 SMS Senaryo B)

```bash
INTENT_ID="bl011b-$(date -u +%Y%m%d-%H%M%S)"
PAYLOAD=$(cat <<JSON
{
  "intentId": "$INTENT_ID",
  "idempotencyKey": "$INTENT_ID",
  "orgId": "default",
  "topicKey": "marketing.campaign",
  "severity": "info",
  "dataClassification": "commercial",
  "recipients": [
    {"type": "subscriber", "subscriberId": "<canary-subscriber-id-from-3.3>"}
  ],
  "template": {
    "templateId": "<active-sms-template-id-from-3.2>",
    "version": 1,
    "locale": "tr-TR"
  },
  "channels": ["sms"],
  "payload": {
    "body": "BL-011 prod canary SMS. Test. Ignore."
  },
  "correlationId": "$INTENT_ID"
}
JSON
)

# POST via prod ingress
HTTP=$(curl -sS -o /tmp/bl011-post.out -w "%{http_code}" \
  -X POST \
  -H "Authorization: Bearer $(cat /tmp/bl011-jwt)" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" \
  https://ai.acik.com/api/v1/notify/intents)
echo "HTTP=$HTTP"
cat /tmp/bl011-post.out | jq . 2>&1 | head -10
```

**Beklenen**:
- `HTTP=202 Accepted` (full E2E PASS)
- Response: `{"intentId":"bl011b-...", "status":"ACCEPTED"}`
- VEYA `HTTP=400` (`@Valid` validation hatası — payload schema fix gerek)
- VEYA `HTTP=403` (guard reject — BL-010 mapper veya OpenFGA mismatch)

### 4.3 Observe 90-120s + 4-katman acceptance evidence

```bash
sleep 90  # JetSMS dispatch + DLR poll window

POD=notification-orchestrator-6f8bd9446f-5zz7p
NS=platform-prod

# Acceptance 1: metric increase
ssh halil@staging-sw "kubectl --context k3d-prod -n $NS exec $POD -- curl -sS http://localhost:8081/actuator/prometheus 2>&1 | grep -E '^notify_org_access_match_total'"
# Beklenen: source="org_id" line var (yeni metric label); count >= 1

# Acceptance 2: notification_delivery row
# (DB query via pod psql)

# Acceptance 3: audit_event_v2 DELIVERY_ACCEPTED + actual_channel=VF + actual_provider=jetsms
# (DB query)

# Acceptance 4: pod log JetSms dispatch + provider_msg_id
ssh halil@staging-sw "kubectl --context k3d-prod -n $NS logs --tail=200 $POD 2>&1 | grep -iE '(IntentSubmission|JetSms|provider_msg|actual_channel|bl011b)' | tail -10"
```

**Acceptance criteria (5/5)**:
- ✅ HTTP 202 Accepted from POST
- ✅ `notify_org_access_match_total{source="org_id"}` increment ≥ 1 (guard-pass behavioral proof — **BL-010 acceptance completion**)
- ✅ `notify.notification_delivery` row: `provider=jetsms`, `provider_msg_id` non-null, `status=ACCEPTED`
- ✅ `notify.audit_event_v2` row: type=`DELIVERY_ACCEPTED`, details.actual_channel=`VF`, details.actual_provider=`jetsms`
- ✅ User receives SMS on `+905551815564` (visual confirm)

## 5. Abort Criteria (Codex iter-1 strict)

| Trigger | Aksiyon |
|---|---|
| JWT mint fail (BL-010 regression) | abort + investigate persona/Vault drift |
| HTTP 400 `@Valid` payload validation | payload/schema/template fix; ama aynı run içinde kör retry YOK |
| HTTP 403 (auth/guard contradiction) | abort + investigate BL-010 mapper veya OpenFGA |
| 202 sonrası `BLOCKED_BY_AUTHZ`, `BLOCKED_EXTERNAL_NOT_ALLOWED`, preference/capacity block | abort; provider'a çıkmadıysa SMS sayılmaz |
| JetSMS provider error veya `provider_msg_id` yok | abort; investigate R24 veya JetSMS health |
| Guard metric alınamıyor | SMS evidence ayrı tutulur; guard-pass acceptance kapatılmaz |

## 6. Cleanup + Evidence

### 6.1 Token cleanup

```bash
rm -f /tmp/bl011-jwt /tmp/bl011-post.out
```

### 6.2 Evidence doc

```
docs/faz-23-evidence/2026-05-XX-bl011-prod-sms-canary-execute.md
```

İçerik (BL-008 mock-receipt drill pattern paralel):
- §1 Bağlam (BL-010 prereq + Codex 019e5e76 verdict + recipient onay)
- §2 Preflight 5 madde verify (state snapshot — env + topic + template + subscriber + OpenFGA + metric baseline)
- §3 JWT mint output (token length-only, no plaintext)
- §4 POST intent: HTTP code + body + intentId
- §5 4-katman acceptance evidence (metric pre/post diff + delivery row + audit row + JetSMS provider log + visual SMS confirm)
- §6 R24 etkisi gözlemi (CHANNEL_OTP_TOPIC_KEYS=blank → VF; marketing.campaign zaten VF olmalı)
- §7 HARD RULE compliance (cost cap + recipient explicit onay + no plaintext token log)
- §8 BL-010 guard-pass behavioral proof closure (metric source="org_id" first increment)

### 6.3 Risk register + handoff update

- **R28 row**: 🔴 Pending → 🟢 Mitigated (Prod data seed COMPLETED + BL-011 canary execute PASS)
- **BL-010 evidence follow-up**: Guard-pass behavioral proof BL-011 ile tamamlandı (metric `source="org_id"` increment); BL-010 scope unchanged
- **BL-028 backlog**: `[ ]` → `[x]` (Prod data seed complete + canary smoke)
- **BL-011 handoff line**: `[ ] DEFER` → `[x]` execute success
- **Charter 23.3 marker**: `🟢 infrastructure LIVE; 🟡 functional data seed pending` → `🟢 LIVE (infra + functional canary)`

## 7. References

- Codex thread `019e5e76-de62-7292-88c9-953f8392d9fd` (BL-011 strategic iter-1 — REVISE-minor 1-SMS path)
- Codex thread `019e5b8a` (önceki BL-011 verdict — 1-3 SMS hard cap)
- Codex thread `019e5bfb` (BL-010 prod hibrit C AGREE)
- BL-010 prod evidence: `docs/faz-23-evidence/2026-05-25-bl010-prod-kc-org-id-mapper-serban.md`
- BL-008 mock-receipt drill evidence (pattern paralel): `docs/faz-23-evidence/2026-05-24-bl008-r9-d43-drill.md`
- HARD RULE Pre-Production Full Authority (CLAUDE.md global, 2026-04-29)
- HARD RULE No Fake Work (CLAUDE.md global, 2026-04-25)
