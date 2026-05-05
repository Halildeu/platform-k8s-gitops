# RB-faz-23-charter — Notification Orchestration Sub-Faz Roadmap

> **Status**: DRAFT (Faz 23.0 charter — 2026-05-05)
> **ADR**: [ADR-0013-notification-orchestration](../adr/0013-notification-orchestration.md)
> **Codex thread**: `019df86f-89aa-7200-bb6c-b7b903860148`
> **Yardımcı artifact**:
> - `docs/notify/event-contract.md` — Intent contract spec
> - `docs/notify/feature-matrix.md` — 11 kategori × tier × özellik canlı tracker
> - `docs/notify/must-have-checklist.md` — 10 must-have çizgisi

Bu runbook **takip edilebilir yol haritası**dır. Her sub-faz için: kapsam, bağımlılık, süre, kabul kriteri, evidence path, status. Sub-faz tamamlandığında `Status` sütunu `🟢 done` işaretlenir; eksik kabul kriteri varsa `🟡 in-progress`.

---

## Toplam Süre

| Faz | Tier | Süre |
|---|---|---:|
| 23.0 | Charter | 1 hafta |
| 23.1 | Kernel/Closed Beta | 3-4 hafta |
| 23.2 | Production MVP dar | 2-3 hafta |
| 23.3 | Production MVP geniş | 3 hafta |
| 23.4-23.8 | v1 | +4-6 hafta |
| 23.9 | Prod cutover | 1 hafta |
| 23.X | v2 (later) | +8-12 hafta |
| **Toplam** | Charter → Prod cutover | **14-18 hafta** (3.5-4.5 ay) |

---

## Sub-Faz Tablosu

| # | Sub-faz | Tier | Süre | Bağımlılık | Status |
|---|---|---|---:|---|:---:|
| **23.0** | Charter | docs | 1 hafta | — | 🟡 in-progress |
| 23.1 | Kernel/Closed Beta | code | 3-4 hafta | 23.0 + Faz 22.1.1b III review verdict | ⏳ blocked |
| 23.2 | Production MVP dar | code | 2-3 hafta | 23.1 | ⏳ |
| 23.3 | Production MVP geniş | code | 3 hafta | 23.2 | ⏳ |
| 23.4 | v1 — DLR + in-app UI | code | 2 hafta | 23.3 | ⏳ |
| 23.5 | v1 — preference UI | code | 1 hafta | 23.4 | ⏳ |
| 23.6 | v1 — Teams + Slack zenginleştirme | code | 1 hafta | 23.4 | ⏳ |
| 23.7 | v1 — push (FCM/APNS) | code | 2 hafta | 23.4 + Faz 22.2 | ⏳ |
| 23.8 | v1 — analytics + bounce loop | code | 2 hafta | 23.4 | ⏳ |
| 23.9 | Prod cutover | atomic | 1 hafta | 23.4-23.8 stable | ⏳ |
| 23.X | v2 (later) | code | 8-12 hafta | v1 stable | ⏳ |

Status legend: 🟢 done · 🟡 in-progress · ⏳ pending · 🔴 blocked

---

## Faz 23.0 — Charter (current)

**Kapsam**:
- ADR-0013 DRAFT → ACTIVE
- 8 OQ resolve (kullanıcı clarify)
- 5 artifact merged: ADR-0013, event-contract, feature-matrix, must-have-checklist, RB-faz-23-charter
- PLAN.md Faz 23 entry + D38-D47 D-kararlar
- Commit + PR + Codex review

**Bağımlılık**: Yok (Faz 22 ile paralel ilerleyebilir).

**Kabul kriteri**:
- ✅ ADR-0013 dosyası mevcut
- ✅ event-contract.md dosyası mevcut
- ✅ feature-matrix.md dosyası mevcut
- ✅ must-have-checklist.md dosyası mevcut
- ✅ RB-faz-23-charter.md (bu dosya) mevcut
- ⏳ PLAN.md Faz 23 entry eklendi
- ⏳ Commit + PR + CI yeşili
- ⏳ Codex review (yeni thread veya 019df86f reply) AGREE
- ⏳ 8 OQ kullanıcıdan cevap geldi
- ⏳ ADR-0013 DRAFT → ACTIVE

**Evidence**:
- `git log --oneline | grep "Faz 23.0"` — 1+ commit
- PR URL — Codex review verdict

---

## Faz 23.1 — Kernel / Closed Beta

**Tier**: Kernel (3-4 hafta)

**Kapsam (özet)**:
- Spring Boot module skeleton (`platform-backend/notification-orchestrator/`)
- DB migration V1 (notification_intent + notification_delivery + notification_template + audit_event + outbox + provider_config)
- 3 kanal: **Email** (SMTP — Mailpit lab) + **Slack** (incoming webhook) + **Webhook egress** (HMAC signed)
- OutboxPoller (PG advisory lock, 5s poll cycle)
- Retry exponential backoff + DLQ + manual replay endpoint
- Template versioning + safe interpolation (Thymeleaf)
- OpenFGA `subscriber#can_receive` check
- PII redaction (log + audit)
- Idempotency + dedupe (24h window)
- Prometheus metrics (delivery_attempts_total, failures_total, retry_total, dlq_size)
- Mock provider strategy (Mailpit + WireMock CI test)
- Vault/ESO provider credentials (kv/platform/notify/{smtp,slack})
- 1 workflow: drift-alarm-receiver → notification-orchestrator (PR #347 alarm-receiver entegrasyon)

**Out of scope (sonra)**:
- SMS, in-app inbox UI, mobile push, MS Teams
- Preference UI (API var, UI yok)
- Subscriber history UI (API var, UI yok)
- Per-tenant brand
- Bounce loop / spam complaint feedback

**Bağımlılık**:
- 🔴 **Faz 22.1.1b III review verdict** (lokal 22 untracked dosya + commit/no-commit kararı)
- 23.0 charter merged

**Kabul kriteri (D29-NOTIFY-Up + Functional + Authorized 3 kanal için)**:

| Madde | Kanıt |
|---|---|
| Pod Ready, /actuator/health 200 | `kubectl get pod` Running 1/1 |
| DB migration V1 applied | `psql -c "\dt notify.*"` 8 tablo |
| Vault/ESO secret sync | `kubectl get externalsecret -n platform-test` Ready |
| Outbox poller alive | log "outbox poll cycle" < 60s gap |
| **Email D29-Functional**: Mailpit'te test mesajı görünür | Mailpit UI screenshot + delivery row INSERT |
| **Slack D29-Functional**: test channel'a mesaj geldi | Slack channel screenshot + delivery row INSERT |
| **Webhook D29-Functional**: HMAC-signed POST → 2xx | wireshark/curl trace + delivery row INSERT |
| **OpenFGA allow case**: subscriber#can_receive PASS | `/check` request log + audit row |
| **OpenFGA deny case**: no tuple → no delivery + audit BLOCKED_BY_AUTHZ | audit row INSERT |
| **Idempotency**: 24h içinde duplicate → no extra delivery | 2nd POST same key returns original intent_id |
| **DLQ**: max retry → DLQ row + alert | dead_letter row + Alertmanager fired |
| **PII redaction**: log entry'de body yok | grep -i "password" stdout = 0 match |
| **Drift alarm integration**: drift-alarm-receiver intent submit → orchestrator processes | end-to-end trace + delivery success |

**Evidence**:
- `docs/faz-23-evidence/2026-XX-XX-23-1-kernel-canli.md` (D29-NOTIFY 3-katman per-channel)

---

## Faz 23.2 — Production MVP Dar

**Tier**: Production MVP dar (2-3 hafta)

**Kapsam**:
- Preference API (`PUT /preferences/me`, `GET /preferences/me`)
- KVKK Art.11 erasure path (`DELETE /audit/me` → payload purge)
- KVKK Art.13 right-to-information API (`GET /audit/me`)
- Provider config versioning + rollback (`provider_config_history` table)
- Grafana dashboard (delivery rate + channel breakdown + DLQ trend)
- Alertmanager rule (DLQ > N → ops alert)
- **Outage fallback bypass** (D43): Alertmanager direct → SMTP/Slack ayrı kredensiyel; runbook `RB-notification-outage-fallback.md`
- Data classification policy enforcement (`transactional/security/commercial/system` → quiet bypass + retention)
- Abuse prevention guards (D45): rate limit per source, duplicate flood detection, webhook fan-out cap

**Out of scope**:
- SMS (23.3'e)
- In-app inbox (23.3'e)

**Bağımlılık**: 23.1 done

**Kabul kriteri**:

| Madde | Kanıt |
|---|---|
| Preference API canlı | `curl /preferences/me` returns subscriber row |
| Erasure path test | DELETE → audit `details.payload = null`, recipient_hash kalır |
| Provider config rollback | history table + atomic switch (test override) |
| Grafana dashboard | dashboard URL + 3+ panel (delivery, DLQ, latency) |
| Alertmanager DLQ rule | rule fired test (manual DLQ row INSERT) |
| Outage fallback bypass | orchestrator down → Slack #alerts'e direct mesaj geldi |
| Data classification | `severity=critical` quiet bypass'ı geçer kanıt |
| Abuse guard | rate limit 429 + audit `RATE_LIMITED` |

**Evidence**:
- `docs/faz-23-evidence/2026-XX-XX-23-2-mvp-dar-canli.md`

---

## Faz 23.3 — Production MVP Geniş

**Tier**: Production MVP geniş (3 hafta)

**Kapsam**:
- **SMS adapter** (NetGSM primary, İletimerkezi secondary)
  - SmsProvider interface
  - NetGsmClient (REST/SOAP — provider docs)
  - GSM-7/UCS-2 segment hesabı
  - Sender ID config
  - Failover (pre-accept fail auto)
- DLR (Delivery Receipt) callback endpoint (provider POSTs delivery status)
- **In-app inbox backend API**:
  - `GET /inbox/me` (paged)
  - `POST /inbox/{id}/read`
  - `POST /inbox/{id}/archive`
  - WS endpoint (SockJS/STOMP) — real-time badge
- 4 workflow tamamlandı: admin invite, password reset, drift alarm, break-glass audit

**Out of scope**:
- SMS DLR runbook (23.4'e)
- In-app full UI (23.4'e)
- IYS lookup (D40-IYS sub-faz)

**Bağımlılık**: 23.2 done

**Kabul kriteri**:

| Madde | Kanıt |
|---|---|
| SMS NetGSM canlı | sandbox/canary number → DELIVERED |
| In-app API canlı | `GET /inbox/me` returns rows |
| WS endpoint | unread count badge update |
| 4 workflow live test | her biri D29-NOTIFY 3 katman PASS |

**Evidence**:
- `docs/faz-23-evidence/2026-XX-XX-23-3-mvp-genis-canli.md`

---

## Faz 23.4 — v1 DLR + In-app UI

**Tier**: v1 (2 hafta)

**Kapsam**:
- SMS DLR callback ingestion (provider → orchestrator)
- mfe-host **in-app inbox React component** (custom, Novu yok)
  - List view (paged)
  - Read/unread toggle
  - Archive
  - Real-time WS badge
  - Notification history (son 30 gün)

**Bağımlılık**: 23.3 done

**Kabul kriteri**:

| Madde | Kanıt |
|---|---|
| DLR callback round-trip | NetGSM DLR → delivery row UPDATE status=DELIVERED |
| In-app inbox UI canlı | mfe-host'ta inbox component render + real-time badge |
| Notification history | son 30 gün rows görünür |

---

## Faz 23.5 — v1 Preference UI

**Tier**: v1 (1 hafta)

**Kapsam**:
- mfe-host **preference settings page**
- Per-channel toggle
- Per-topic toggle
- Quiet hours editor
- Frequency limit slider
- Unsubscribe link landing page (RFC 8058 one-click)

**Bağımlılık**: 23.4 done

**Kabul kriteri**:

| Madde | Kanıt |
|---|---|
| Preference UI canlı | mfe-host'ta sayfa render + save → API çağrısı |
| One-click unsubscribe | email footer link → landing page → preference UPDATE |

---

## Faz 23.6 — v1 Teams + Slack Zenginleştirme

**Tier**: v1 (1 hafta)

**Kapsam**:
- Microsoft Teams adapter (Power Automate webhook + Adaptive Cards)
- Slack zenginleştirme (Block Kit + threading)

**Bağımlılık**: 23.4 done

---

## Faz 23.7 — v1 Push (FCM + APNS)

**Tier**: v1 (2 hafta)

**Kapsam**:
- FCM adapter (Android — Faz 22 endpoint-admin agent için)
- APNS adapter (iOS — Faz 22.2 iOS gerekirse)
- Cihaz token registry (`subscriber_device` table)
- Token rotation handling

**Bağımlılık**: 23.4 done + Faz 22.2 endpoint-admin Lab tier ready

---

## Faz 23.8 — v1 Analytics + Bounce Loop

**Tier**: v1 (2 hafta)

**Kapsam**:
- Per-tenant Grafana dashboard (delivery rate, channel breakdown)
- Email bounce loop (provider feedback → suppression list)
- Spam complaint feedback (FBL endpoint)
- Per-template analytics (open/click rate — privacy concern: opt-in tracking)

**Bağımlılık**: 23.4 done

---

## Faz 23.9 — Prod Cutover

**Tier**: Atomic (1 hafta)

**Kapsam**:
- k3d-prod manifest deploy (image digest pin)
- Provider config prod environment activation
- 72h observation window
- Rollback runbook test (manuel revert provası)

**Bağımlılık**: 23.4-23.8 stable, D30-NOTIFY discipline

**Kabul kriteri**:

| Madde | Kanıt |
|---|---|
| k3d-prod pod Ready | `kubectl --context k3d-prod get pod` |
| Image digest pin | pod imageID == GHCR digest |
| Atomic provider switch | DB row update + cache invalidate test |
| Rollback prova | revert PR → previous version restore |
| 72h observation | DLQ count = 0, error rate < 0.1% |

**Evidence**:
- `docs/faz-23-evidence/2026-XX-XX-23-9-prod-cutover.md`

---

## Faz 23.X — v2 (later, gerekçe çıkarsa)

**Tier**: v2 (8-12 hafta)

**Kapsam**:
- A/B testing variant
- Conditional steps (rule engine — "if user.role == admin")
- Workflow editor UI (no-code, admin self-service)
- WhatsApp Business adapter
- Voice/IVR adapter (Twilio)
- Per-tenant provider config (org X kendi SMTP'sini kullansın)
- Per-tenant brand
- Vault dynamic secret TTL token
- IYS commercial SMS lookup (D40-IYS sub-faz)

**Tetikleyici**: v1 stable + müşteri/ops gerekçesi açık

---

## Status Tracking Convention

Her sub-faz tamamlandığında:

1. Yukarıdaki **Sub-Faz Tablosu**'nda `Status` sütunu `🟢 done` işaretlenir
2. İlgili sub-faz bölümünün **Kabul kriteri** tablosunda her satır işaretlenir
3. **Evidence** path doldurulur (canlı kanıt dosyası)
4. PR/commit ID + Codex review thread referansı eklenir
5. Bağlı olan sonraki sub-faz `Status` ⏳ → 🟡 in-progress'e geçer

---

## Cross-Faz Bağımlılık Diyagramı

```
[Faz 22.1.1b III review verdict]
       │
       ▼
   23.0 ───▶ 23.1 ───▶ 23.2 ───▶ 23.3 ───▶ 23.4 ───┬──▶ 23.5
                                                    │
                                                    ├──▶ 23.6
                                                    │
                                  [Faz 22.2] ──────▶ 23.7
                                                    │
                                                    └──▶ 23.8 ───▶ 23.9
                                                                    │
                                                                    ▼
                                                                  23.X (later)
```

23.0 paralel başlanabilir (22.1.1b ile çakışma yok). 23.1 başlangıcı için 22.1.1b III review verdict zorunlu.

---

## 8 Open Question (kullanıcı clarify)

| OQ | Soru | Kim cevaplar | Status |
|---|---|---|---|
| OQ-1 | Corporate SMTP relay var mı, yoksa Postal self-host? | ops + kullanıcı | ⏳ |
| OQ-2 | SMS primary NetGSM mi İletimerkezi mi? | kullanıcı | ⏳ |
| OQ-3 | IYS kaydı mevcut mu? | ops | ⏳ |
| OQ-4 | Audit retention süre tercihi (30/90/180/365)? | kullanıcı + legal | ⏳ |
| OQ-5 | Slack workspace kanal isimleri? | kullanıcı | ⏳ |
| OQ-6 | FCM project + APNS bundle id mevcut mu? | mobile/ops | ⏳ |
| OQ-7 | In-app inbox custom React vs Novu component onay? | kullanıcı | 🟡 (Codex önerdi: custom) |
| OQ-8 | 3rd party SMTP (SendGrid/Mailgun) izinli mi? | kullanıcı + legal | ⏳ |

OQ-1, OQ-2, OQ-4, OQ-5, OQ-7, OQ-8 = **23.0 charter close için zorunlu** (ADR DRAFT → ACTIVE)
OQ-3 = 23.3'te SMS sub-faz öncesi cevap gerek
OQ-6 = 23.7'de push sub-faz öncesi cevap gerek
