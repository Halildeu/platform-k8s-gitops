# 2026-09-11 — ES-301b: eskalasyon bildirimi, ikinci kademe yönlendirme (TEST kabul)

**İş:** platform-backend#1153 (ES-301 #882'nin ikinci dilimi). **Kod:** platform-backend#1161 (Codex `01a08f67` plan REVISE→AGREE, post-impl REVISE→AGREE). **GitOps:** #3668 (alıcı kimlikleri, persona, OpenFGA grant'ları, bayrak `false`), #3670 (ethics-service `1c474b0b…` + orchestrator `abc24cce…`, V27/V29), #3672 (bayrak `true`, r2), #3674 (worker'larda sweep kapalı). Runbook: `docs/runbooks/RB-faz35-ethics-escalation-notify.md`.

## Ölçülen ön bulgu — bildirim alıcısı hiç görülmemiş

`notify.notification_inbox`'ta 174 etik etkinlik bildirimi (org …0001: 98, …0003: 76) yalnız Keycloak subject UUID'si (`f8a3b6f6…`) altındaydı; sayısal `11` altında 0. Shell zili `/authz/me.subscriberId` (sayısal) ile okur → birinci kademe bu bildirimlerin hiçbirini zilden görmemişti. Düzeltme: `ETHICS_NOTIFICATION_RECIPIENT_SUBSCRIBER_ID="11"` + `subscriber:11 can_receive notification_topic:ethics.case.activity` (#3668). Hücre düzeyinde tek alıcı / org kapsamlı inbox sınırı: gitops#3669.

## Kimlikler ve grant'lar

| Kademe | Persona | users_db id | org | OpenFGA (erp-stage) |
|---|---|---|---|---|
| 1 | ethics-manager-test | 11 | …0001 | `can_receive` escalation + activity topic |
| 2 | ethics-compliance-test (yönetici rolü yok, `permissions []`) | 33 | …0003 (sentetik kanal) | `can_receive` escalation topic |

Seed (`openfga-notify-topic-seed.sh`): 4 tuple `wrote`, 6 smoke_check PASS — 11/33 `template:ethics.case.escalated` allow, 11 `template:ethics.case.activity` allow, 33 activity **deny**, `subscriber:1` deny, bilinmeyen deny.

## Rollout

| Adım | Kanıt |
|---|---|
| #3668 env + r1 | pod yeniden başladı 08:41Z; `printenv` → `11 / 33 / false` |
| #3670 imaj | ethics-service imageID `1c474b0b…`, Flyway "Migrating schema ethics_service to version 27 - notification case escalated events … now at version v27"; orchestrator `abc24cce…`, "notify … version 29 - seed ethics case escalated template … v29" (08:44Z) |
| #3672 bayrak | r2 rollout; `printenv` → `11 / 33 / true` |
| #3674 worker'lar | `ETHICS_SLA_ESCALATION_ENABLED=false` (evidence + cdr worker, printenv); worker-config-revision r1 |

## Kabul (sentetik org …0003; `accept-test-ethics-escalation-notify.sh`, `BACKDATE_DAYS=94`)

Vaka `fdb334a8-71da-4095-a0a9-ae92920194ea` (speakup intake, receipt `f4bc4cc1…`; created_at 94 gün geriye → FEEDBACK yükümlülüğü 4 gün geçmiş). Sweep 09:15:39Z:

| Katman | Kayıt |
|---|---|
| ethics `ethics_case_escalation` | FEEDBACK L1 (threshold 2026-09-07), FEEDBACK L2 (threshold 2026-09-10), ikisi 09:15:39.748Z |
| ethics `ethics_notification_outbox` | `1b374f2f…` `CASE_ESCALATED_L1` DELIVERED attempt 1; `78ca6f51…` `CASE_ESCALATED_L2` DELIVERED attempt 1 |
| orchestrator `notification_intent` | `ethics-1b374f2f…`: topic `ethics.case.escalation`, template `ethics.case.escalated` v1, severity **info**, payload `{"level": 1}`, recipient **11**, COMPLETED; `ethics-78ca6f51…`: severity **warning**, payload `{"level": 2}`, recipient **33**, COMPLETED |
| orchestrator `notification_inbox` | 11 → "Etik vakası eskalasyonu — seviye 1" UNREAD; 33 → "Etik vakası eskalasyonu — seviye 2" UNREAD |
| Kademe ayrımı | org …0003 escalation satırları: `11 → seviye 1` ×1, `33 → seviye 2` ×1 — karşı kademede diğer seviye yok |
| İkinci kademe tercihleri | `subscriber_preference` satırı 0 (engel yok) |

Sinyal bütçesi (kayan 24 saat, kurum+seviye) V27 `ethics_notification_signal_window` üzerinden; aynı seviyenin ikinci vakası aynı gün sinyal üretmez (Postgres testi `twoCasesOfOneOrganisationSignalEachLevelOnce`).

## Tarayıcı — zil (ikinci kademe, kendi oturumu)

`notify-bell-browser-smoke.sh` (PERSONA=ethics-compliance-test, EXPECTED_SUBJECT="seviye 2", FORBIDDEN_SUBJECT="seviye 1"): **PASS** (09:3xZ) — shell `/login` → kurumsal giriş → Keycloak → `/home`; shell'in kendi `GET /api/v1/notify/inbox/me` çağrısı (`X-Org-Id …0003`, `X-Subscriber-Id 33`) → `unreadCount=1`, 1 öğe: subject "Etik vakası eskalasyonu — seviye 2", topic `ethics.case.escalation`, severity warning, intentId `ethics-78ca6f51…` (yukarıdaki L2 intent'i ile aynı); "seviye 1" öğesi yok; konsol hatası 0; ekran görüntüleri `01-shell-after-login.png`, `02-bell-open.png` (aiserver `/tmp/es301b/bell-evidence`). Ön koşul canlı ders 3: personaların Keycloak `userId` attribute'u (mapper → `userId` claim) yoktu; guard 403 veriyordu — persona betiği iki kademeye de yazıyor.

## Kesinti dayanıklılığı

Outbox mekanizması (claim/lease, üstel geri çekilme, `DEAD_LETTER` → requeue aynı outbox UUID = aynı `intentId`) bu dilimde **değişmedi**; canlı DLQ→requeue kanıtı ES-208 kaydında (`2026-07-27-staff-closed-loop.md`: 20 DEAD_LETTER → requeue → 20 inbox satırı). Bu turda kesinti indüklenmedi.

## Canlı dersler

1. `AckNetWorker` 11 gün geriye alınmış vakayı 50 s içinde otomatik onayladı → onay yolu eskalasyona gitmez; fixture FEEDBACK üzerinden (94 gün).
2. Worker'lar eskalasyon sweep'ini miras alıp seviyeleri bayrak kapalı kaydetti (`evidence-worker: candidates=240 recorded=2`) → sinyal bir daha üretilmez; #3674 ile sweep yalnız ethics-service'te (#3271 emsali).
3. Zil `X-Subscriber-Id`'yi JWT `subscriberId | userId | sub` claim'leriyle eşler; `userId` claim'i Keycloak kullanıcı attribute'u `userId` üzerinden basılır. İki etik personasında attribute yoktu → inbox 403 → birinci kademenin zili hiç çalışmamıştı. Persona betiği attribute'u iki kademeye de yazar ve geri okur.

## Açık kalanlar (backlog)

gitops#3669 (org başına alıcı yönlendirmesi; birinci kademe …0001 sentetik org satırlarını zilden göremez), gitops#3671 (orchestrator jar CVE borcu, önceden var), gitops#3541 (kalıcı grant).
