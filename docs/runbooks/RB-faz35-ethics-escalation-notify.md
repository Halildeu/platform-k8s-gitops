# RB — Faz 35 ES-301b: eskalasyon bildirimi, ikinci kademe yönlendirme (TEST)

**Tetik:** platform-backend#1153 — bir etik vakası SLA eskalasyon seviyesine ulaştığında birinci kademe (yönetici) L1'i, ikinci kademe (uyum/kurul) L2+'yı bildirim kutusunda görmeli; ya da bu zincirde bir halka kopmuş (intent kabul, teslim `BLOCKED_BY_AUTHZ`; bildirim var, zil boş).

**Bağlam:** platform-backend#1161 (outbox olayları `CASE_ESCALATED_L1..L5`, sinyal bütçesi, V27; orkestratör V29 şablonu). Ölçüm 2026-09-11: 174 etkinlik bildirimi inbox'ta yalnız Keycloak subject UUID'si altındaydı; shell zili `/authz/me.subscriberId` (sayısal) ile okur — birinci kademe de bu turda sayısal id'ye (11) geçti. Kalıcı otomatik grant kararı gitops#3541.

## Kimlikler (TEST hücresi)

| Kademe | Persona | users_db id | Nasıl |
|---|---|---|---|
| 1 | `ethics-manager-test` | 11 | mevcut yönetici; `ETHICS_NOTIFICATION_RECIPIENT_SUBSCRIBER_ID` |
| 2 | `ethics-compliance-test` | 33 | `scripts/faz35/provision-test-ethics-escalation-recipient.sh` (KC kullanıcı + org_id, şifre 0600, user-service profil → writer aktivasyonu, `/authz/me` sayısal id; **yönetici rolü yok, permissions []**) |

## Sıra (rollout güvenliği — eski worker yeni olayları birinci kademeye etkinlik gibi yönlendirir)

1. Repo güncel: `cd ~/platform-k8s-gitops && git pull --ff-only`
2. Persona (idempotent, id'leri basar; şifre basmaz):
   ```bash
   ./scripts/faz35/provision-test-ethics-escalation-recipient.sh
   ```
3. Env (bu PR): `ETHICS_NOTIFICATION_RECIPIENT_SUBSCRIBER_ID="11"`, `ETHICS_NOTIFICATION_ESCALATION_RECIPIENT_SUBSCRIBER_ID="33"`, `ETHICS_NOTIFICATION_ESCALATION_SIGNALS_ENABLED="false"` — ArgoCD ile ethics-service yeniden başlar; eski imaj yeni env'i yok sayar.
4. İmaj: ethics-service + notification-orchestrator digest'leri (platform-backend#1161 sha) — pin öncesi grype; `scripts/deploy/verify-pod-digest.sh` ile **bütün** replikalar yeni.
5. OpenFGA (erp-stage store; idempotent):
   ```bash
   ./scripts/faz35/openfga-notify-topic-seed.sh bootstrap/openfga/faz35-ethics-escalation-notify-tuples.json
   ```
   Beklenen: 4 tuple `wrote`/`exists`, 6 smoke_check `PASS` (11 ve 33 escalation şablonunda allow, 11 etkinlikte allow, 33 etkinlikte deny, subscriber:1 ve bilinmeyen deny). `FAIL` → dur.
6. Bayrak: `ETHICS_NOTIFICATION_ESCALATION_SIGNALS_ENABLED="true"` (ayrı PR) → sweeper bir sonraki döngüde (15 dk) kaydettiği her seviye için bir sinyal üretir (kurum+seviye başına kayan 24 saatte bir).

## Kanıt (aynı artifact seti üzerinde, ayrı ayrı)

- ethics-service: `ethics_notification_outbox` satırı `CASE_ESCALATED_L<n>` → `DELIVERED`; intent body (log/`notification_intent`): topic `ethics.case.escalation`, template `ethics.case.escalated` v1, `payload.level = n`, recipient 11 (L1) / 33 (L2+), severity info/warning.
- notification-orchestrator: `notify.notification_delivery.status = DELIVERED`; `notify.notification_inbox` satırı `(org, subscriber_id=33, intent_id)` L2 için, `(…, 11, …)` L1 için; karşı kademede aynı intent **yok**.
- Tarayıcı: `ethics-compliance-test` shell oturumunda zil sayacı ve metin "Etik vakası eskalasyonu — seviye 2"; `ethics-manager-test` için seviye 1. Personanın etkin tercihi (`/api/v1/notify/prefs`) engel değil.
- Kesinti: orkestratör erişilemezken outbox satırı `DEAD_LETTER`'a düşer; `POST /api/v1/ethics/notifications/dead-letters/requeue` → aynı outbox UUID = aynı `intentId` → tek inbox satırı.

## Rollback

Önce `ETHICS_NOTIFICATION_ESCALATION_SIGNALS_ENABLED="false"` (sinyal üretimi durur; kayıtlı seviyeler ve outbox satırları kaybolmaz), sonra gerekirse imaj geri; L1–L5 backlog'unu eski imaja **okutma** (yanlış yönlendirir). Tuple silme: seeder'ın `write` gövdesi yerine OpenFGA `deletes` gövdesi.

## Sınırlar

Test realm (platform-test) dışı seed yasak; wildcard subject yasak; şablon kopyası sabit (vaka kimliği, konu, anlatı taşımaz — `EthicsEscalationTemplateSeedTest` render eder); ikinci kademe personası yönetici değildir (Faz 35 en-az-yetki sözleşmesi değişmez); topic tercih kataloğuna eklenmedi (kapsam tercihi; "susturulamaz" garantisi değildir).
