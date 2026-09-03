# RB — Faz 24 Görevler dilim-4b: toplantı görev bildirimi OpenFGA receive grant'ı (TEST)

**Tetik:** notification-orchestrator `meeting.action.assigned` / `meeting.action.reassigned` intent'ini kabul ediyor ama teslim `BLOCKED_BY_AUTHZ policy=authz_deny` ile bitiyor (Layer-2: `template:<id>#can_receive@subscriber:<userId>`), ya da yeni bir test kullanıcısının görev bildirimi alması gerekiyor.

**Bağlam:** platform-backend#1128 (sink + katalog + V28 şablonlar), gitops#3539 (`MEETING_NOTIFY_ENABLED`), gitops#3540 (imaj pinleri). Grant'lar bu turda test-only seed; kalıcı otomatik grant kararı gitops#3541.

## Adımlar (aiserver, VPN üzerinde; ~1 dk)

1. Repo güncel: `cd ~/platform-k8s-gitops && git pull --ff-only`
2. Seed + doğrulama (idempotent):
   ```bash
   ./scripts/faz24/openfga-meeting-action-notify-seed.sh
   ```
   Beklenen: 8 tuple `wrote`/`exists`, 4 smoke_check `PASS` (inheritance, Zeynep, unknown deny, topic-scope deny). Herhangi bir `FAIL` → çıkış kodu ≠ 0; devam etme.
3. Kanıt: web'de toplantıya görev ata (`assigneeUserId` = alıcı) → ≤10 sn içinde alıcının bildirim kutusunda "Size yeni bir toplantı görevi atandı" / "Bir toplantı görevi size devredildi"; orkestratörde `notify.notification_inbox` satırı, `notification_intent.status=DELIVERED`.
4. Yeni kullanıcı eklemek: `bootstrap/openfga/meeting-action-notify-tuples.json` `tuples[]`'a iki `can_receive` satırı (subscriber = users_db numeric id) + smoke_check; PR; script tekrar.

## Rollback
Tuple silme: aynı script'in `write` yerine OpenFGA `deletes` gövdesiyle (pod içinden `curl -X POST …/write -d '{"deletes":{"tuple_keys":[…]}}'`). Bildirim üretimini kapatmak için `MEETING_NOTIFY_ENABLED` patch'ini kaldır (#3539) — poller yalnız Redis yoluna döner; outbox satırları kaybolmaz.

## Sınırlar
Test realm (platform-test) dışı seed yasak; wildcard subject yasak; şablon içeriği sabit metin (aksiyon metni / kimlik taşımaz).
