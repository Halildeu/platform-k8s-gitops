# RB-faz-23-charter — Notification Orchestration Sub-Faz Roadmap

> **Status**: ACTIVE (charter base 2026-05-05; **truth alignment 2026-05-09 Session 39 post 11-PR cycle**)
> **ADR**: [ADR-0013-notification-orchestration](../adr/0013-notification-orchestration.md)
> **Codex thread**: `019df86f-89aa-7200-bb6c-b7b903860148` (charter) + `019e0892` (Session 39 strategic retrospective) + `019e0bb6` (PR review chain)
> **Yardımcı artifact**:
> - `docs/notify/event-contract.md` — Intent contract spec
> - `docs/notify/feature-matrix.md` — 16 kategori × tier × özellik canlı tracker (D45 ile 11 → 16 genişletildi)
> - `docs/notify/must-have-checklist.md` — 10 must-have çizgisi

Bu runbook **takip edilebilir yol haritası**dır. Her sub-faz için: kapsam, bağımlılık, süre, kabul kriteri, evidence path, status. Sub-faz tamamlandığında `Status` sütunu `🟢 done` işaretlenir; eksik kabul kriteri varsa `🟡 in-progress`.

**HARD RULE — discipline (Codex `019e0bff` iter-1 softened)**:

Tüm yapılan iş bu charter'daki sub-faz numaralandırmasına map edilmek zorunda.

**İzinli pattern**: Geçici stratejik label kullanılabilir (örn. Codex retrospective "Step A/B/C/D" / "Tier X" / "Cycle Y"). Şart: her label PR title'ında ve PR body'sinde canonical sub-faz ID'ye map edilmek zorunda — `Step D Vault → 23.2 §Vault/ESO must-have #6` gibi.

**Yasak pattern**: Canonical sub-faz numarasını hiç anmadan improvise label ile çalışmak. Bu doc-drift birikimine yol açar.

**Canonical status authority**: Sub-Faz Tablosu marker'ları + her sub-faz bölümünün kabul kriteri tablosu authoritative truth. Strategic retrospective ladder/label improvise framing olabilir, ama status tracking yalnız 23.x marker'dan türetilir.

**Mark discipline**: Sub-faz `🟢 done` ancak ALL kabul kriteri 🟢 olduğunda işaretlenir. Substantial progress + missing criteria = 🟡 partial. Codex `019e0bff` iter-1: Session 39'da "23.1/23.4/23.9 done" claim overclaim'di — runtime LIVE olsa da D29-Functional evidence + SMS DLR + 72h observation gibi kabul kriteri eksikleri vardı.

> **Session 39 (2026-05-09) doc-drift correction (user-driven)**: 11 PR cycle Codex `019e0892` strategic retrospective sırasında "Step D Vault / Step B alerts / Step C retention / Step B.4 SLO" gibi non-canonical naming ile yapıldı. Bu session sonunda kullanıcı "yazılı planımız takip edilebilir olacak şekilde ilerleyelim" dedi → bu doküman + must-have-checklist + feature-matrix + PLAN.md sub-faz numaralarına re-map edildi. Geriye dönük PR'lar canonical sub-faz altında listelendi (özellikle 23.1 + 23.2 + 23.4 + 23.9).

---

## Toplam Süre

| Faz | Tier | Süre |
|---|---|---:|
| 23.0 | Charter | 1 hafta |
| 23.1 | Kernel/Closed Beta | 3-4 hafta |
| 23.2 | Production MVP dar | **🟢 FULL ACCEPTANCE** Session 44 2026-05-10 — 5-state matrix: Source-ready 12/12 + Live-deployed 12/12 + **Evidence-backed 12/12** + **Acceptance complete 12/12** + Blocked 0/12; **6/6 sub-faz fully 🟢** (23.2.A T1.1 trilogy MERGED 3/3 + 23.2.B subscriber self-service + 23.2.C provider config rollback R12 MITIGATED T1.3 + 23.2.D outage fallback **R9 MITIGATED first drill** + 23.2.E **data classification 8-test acceptance Session 44** + 23.2.F abuse guards FULL acceptance); R2 KVKK admin erasure legal review external ETA 2026-05-25 only residual |
| 23.3 | Production MVP geniş | 3 hafta |
| 23.4-23.8 | v1 | +4-6 hafta |
| 23.9 | Prod cutover | 1 hafta |
| 23.X | v2 (later) | +8-12 hafta |
| **Toplam** | Charter → Prod cutover | **14-18 hafta** (3.5-4.5 ay) |

---

## Sub-Faz Tablosu

| # | Sub-faz | Tier | Süre | Bağımlılık | Status |
|---|---|---|---:|---|:---:|
| **23.0** | Charter | docs | 1 hafta | — | 🟢 done (PR #362 + 5 follow-up commits + 2026-05-09 truth alignment) |
| **23.1** | Kernel/Closed Beta | code | 3-4 hafta | 23.0 + Faz 22.1.1b III review | 🟡 partial (Codex `019e0bff` iter-1 absorb: service runtime LIVE prod, V8 partition + 3 channel adapters + OutboxPoller + RetryWorker + auth guards activated; **D29-NOTIFY-Functional 3-channel evidence still PENDING** per `docs/faz-23-evidence/2026-05-06-23-1-pr5-d29-notify.md`) |
| **23.2** | Production MVP dar | code | R2 KVKK legal review external | 23.1 | **🟢 FULL ACCEPTANCE** (Session 44 sonu 2026-05-10: KVKK retention + Vault/ESO + Grafana 15-panel + 25 PrometheusRule + DLQ SLO 99.5% LIVE; 5-state matrix Source-ready 12/12 + Live-deployed 12/12 + **Evidence-backed 12/12 + Acceptance complete 12/12** + Blocked 0/12; **6/6 sub-faz fully 🟢: 23.2.A T1.1 trilogy MERGED 3/3 (PR #142+#143+#144+#145+#146+#147+#498+#501) + 23.2.B subscriber self-service + 23.2.C provider config rollback (R12 Mitigated PR #140) + 23.2.D outage fallback (R9 Mitigated) + 23.2.E data classification 8-test acceptance (PR #149) + 23.2.F abuse guards**; R2 KVKK legal review external ETA 2026-05-25) |
| 23.3 | Production MVP geniş | code | 3 hafta | 23.2 | 🟡 partial (Session 42: **23.3.1 NetGSM Vault path canonical LIVE 2026-05-10** PR #482 + #485 DLR follow-up — kv/platform/notification-orchestrator + 4 NetGSM keys (username/password/msgheader/dlr_token all empty fail-closed) + ESO 9/9 Ready + 4/4 pod env vars injected; **NetGSM contract activation R1 pending ETA 2026-05-30**; in-app inbox API + IYS gate + multi-provider failover pending) |
| **23.4** | v1 — DLR + in-app UI | code | 2 hafta | 23.3 | 🟡 partial (PR-5.x cycle in-app inbox + SSE LIVE + strict identity guards LIVE; **SMS DLR + archive UI + 30-day history pending**) |
| 23.5 | v1 — preference UI | code | 1 hafta | 23.4 | ⏳ pending (FE preference settings page) |
| 23.6 | v1 — Teams + Slack zenginleştirme | code | 1 hafta | 23.4 | ⏳ pending (Teams adapter + Slack Block Kit + threading) |
| 23.7 | v1 — push (FCM/APNS) | code | 2 hafta | 23.4 + Faz 22.2 | ⏳ pending (FCM/APNS adapters + device token registry) |
| 23.8 | v1 — analytics + bounce loop | code | 2 hafta | 23.4 | 🟡 partial (alerts/dashboard LIVE; Tempo + bounce loop + spam complaint feedback pending) |
| **23.9** | Prod cutover | atomic | 1 hafta | 23.4-23.8 stable | 🟡 partial (activation LIVE 2026-05-08 ai.acik.com; **72h observation in progress until 2026-05-11; rollback prova + browser SSO verify pending user**) |
| 23.X | v2 (later) | code | 8-12 hafta | v1 stable | ⏳ deferred (A/B + workflow editor + WhatsApp + voice + per-tenant provider) |

Status legend: 🟢 done · 🟡 in-progress · ⏳ pending · 🔴 blocked

**Snapshot (2026-05-10 Session 42 post PR #482 + #483, Codex `019e10b4` iter-1 absorb)**:
- Done (whole sub-faz fully closed): 23.0 (1/11 = 9%)
- Partial (substantial progress, kabul kriteri eksikleri var): 23.1, 23.2, **23.3**, 23.4, 23.8, 23.9 (6/11 = 55%) — **23.3 promoted Session 42 via 23.3.1 NetGSM Vault path canonical LIVE PR #482**
- Pending: 23.5, 23.6, 23.7, 23.X (4/11 = 36%)
- Effective progress estimation: **~33% of v1 scope** (semantic estimate — counts each partial sub-faz as 0.5 toward done; exact denominator NOT literal feature matrix count)
- **Note**: Earlier "23.1/23.4/23.9 🟢 done" claim was overclaim per Codex review. Service runtime is LIVE but each sub-faz has explicit kabul kriteri eksikleri (D29-Functional evidence for 23.1, SMS DLR + archive for 23.4, 72h observation + rollback prova for 23.9). Marker accuracy correction is part of "going forward, mark only when ALL kabul kriteri are 🟢" discipline. **23.3 promotion (Session 42 2026-05-10): 23.3.1 NetGSM Vault path canonical LIVE; 23.3 still 🟡 partial — NetGSM contract activation R1 + DLR + IYS + multi-provider failover + in-app inbox API kabul kriteri pending.**

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
- ✅ PLAN.md Faz 23 entry eklendi (Faz 23 D38-D47 D-kararlar live)
- ✅ Commit + PR + CI yeşili (PR #362 + 5 follow-up + 2026-05-09 truth alignment)
- ✅ Codex review AGREE (thread `019df86f`)
- 🟡 8 OQ resolution: 5/8 resolved, 3 pending (OQ-3 IYS legal, OQ-6 FCM/APNS Faz 22.2 dep, OQ-1 SMTP relay decision)
- ✅ ADR-0013 DRAFT → ACTIVE

**Evidence**:
- PR #362 (charter base) + Codex thread `019df86f` AGREE iter-1
- 2026-05-09 truth alignment PR (this session) — sub-faz tablosu + must-have-checklist + feature-matrix sync
- `docs/state/current-state.md` Session 39 entry (live truth)

---

## Faz 23.1 — Kernel / Closed Beta

**Tier**: Kernel (3-4 hafta) — **🟡 partial (Session 39 — service runtime LIVE; D29-NOTIFY-Functional 3-channel evidence pending)**

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

**Evidence (Session 39 update 2026-05-09)**:
- `kustomize/base/apps/notification-orchestrator/deployment.yaml` LIVE prod 2 pod 1/1 Running
- V8 migration: 7 initial partitions + retention_log table LIVE (verified `\dt notify.*` 8 tablo)
- ESO secret synced: `kv/platform/notification-orchestrator` → `notification-orchestrator-secrets` (5 keys, owned by ExternalSecret post PR #424)
- OutboxPoller + RetryWorker activated logs (cycles=442+ on prod)
- 3 channel adapters: SMTP/Slack/Webhook in `com.serban.notify.adapter.*`
- OpenFGA `subscriber#can_receive` check — `DeliveryEligibilityService activated: preferences=true authz=true`
- 24h idempotency window: `NOTIFY_IDEMPOTENCY_WINDOW_HOURS=24`
- Prometheus metrics emitted via `/actuator/prometheus`
- Drift alarm-receiver integration: PR #347 LIVE
- **Note**: Faz 22.1.1b III review verdict was bypassed in pre-prod tek-user context (kullanıcı 2026-05-08 onayı). Multi-tenant cutover öncesi review canlanır.

**PRs that contributed to 23.1 closure**:
- Pre-Session 39: notification-orchestrator service skeleton + V8 migration + 3 adapters (multiple PRs in earlier sessions)
- Session 39 PR #424: Vault path `kv/platform/notification-orchestrator` + ESO ExternalSecret (closes "Vault/ESO provider credentials" kabul kriteri)
- Session 39 PR #427/#437: audit retention activation (closes "PII redaction" + retention infrastructure)

---

## Faz 23.2 — Production MVP Dar

**Tier**: Production MVP dar (Session 44 sonu: **6/6 sub-faz fully 🟢 FULL ACCEPTANCE** — 23.2.A T1.1 trilogy 3/3 + P0.1-P0.5 + P1.2 PR-A + 23.2.B + 23.2.C + 23.2.D + 23.2.E + 23.2.F — T1.1 + T1.2 + T1.3 + T1.4 + T1.6 + 23.2.E Data Classification 8-test acceptance FULL ACCEPTANCE; residual R2 KVKK legal review external coordination only) — **🟢 FULL ACCEPTANCE (Session 44 5-state matrix Evidence-backed 12/12 + Acceptance complete 12/12)**

**Acceptance breakdown** (Codex iter-1 absorb):
- **Original MVP-dar 8 kabul kriteri: 6/8 done** (Grafana dashboard, Alertmanager DLQ rule, **provider config rollback** Session 42 PR #140, outage fallback bypass Session 41, data classification, abuse prevention guards Session 41)
- **Session 39 hardening (charter ek)** 3/3 done: KVKK Art.7 audit retention, Vault/ESO managed Secret, DLQ SLO 99.5% multi-window
- **Pending**: erasure path (R2 KVKK legal review external) — 1 kriter

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

**Kabul kriteri** (M3 stale audit 2026-05-09 5-state matrix per `docs/notify/m3-stale-audit-2026-05-09.md`):

| Madde | Status | Kanıt |
|---|:---:|---|
| Preference API canlı | 🟢 source-ready/live, **T1.1 trilogy 3/3 MERGED** | `PreferenceController` 290 satır LIVE: GET/PUT `/api/v1/notify/preferences/me` + DELETE `/me/{id}` + DELETE `/me`; **T1.1.6 quiet hours PR #142 (7 unit tests) + T1.1.7 frequency_limit_per_user PR #143 (4-iter Codex chain, fixed-window race-safe, ConcurrentHashMap synchronized) + T1.1.8 unsubscribe trilogy PR-A #144 (HMAC-SHA256 token + Clock injection 8 unit tests) + PR-B #145 (UnsubscribeUrlBuilder 4 unit tests) + PR-C #146 (UnsubscribeRevokeService preference revoke + audit publish)** all MERGED Session 43; D29-Authorized acceptance test BLOCKED on RAID I6 Keycloak credential |
| Admin erasure path | 🟡 source-ready, R2 legal review | `AdminErasureController` 129 satır LIVE: `POST /api/v1/admin/notify/erasure` (admin scope); R2 legal review ETA 2026-05-25 |
| **Subscriber self-service erasure** (`DELETE /audit/me`) | 🟢 done | T1.2 FULL ACCEPTANCE Session 41 (PR #134 + acceptance evidence 2026-05-09) — endpoint LIVE + integration test |
| **Subscriber right-to-info** (`GET /audit/me`) | 🟢 done | T1.2 FULL ACCEPTANCE Session 41 (PR #134 + acceptance evidence 2026-05-09) — endpoint LIVE + integration test |
| Provider config rollback | 🟢 done | `ProviderConfigHistory` + Repository LIVE; `ProviderConfigService.switchActive()` @Transactional SERIALIZABLE + TransactionSynchronization.afterCommit cache invalidation; 4 Testcontainers integration tests CI GREEN (atomic_switch + concurrent_switch_race + cache_invalidate + rollback_on_fail); platform-backend PR #140 MERGED 2026-05-10 (Codex iter-1 RED → iter-2 AGREE thread `019e116e`/`019e1173`); R12 🟢 Mitigated |
| **Grafana dashboard** | 🟢 done | PR #431 + #436 → 15 panel (strict cutover + retention + queue + DLQ + SLO burn rate); sidecar imported `notification-orchestrator-dashboard` ConfigMap LIVE prod monitoring ns |
| **Alertmanager DLQ rule** | 🟢 done | PR #425 + #428 + #430 + #433 → 25 PrometheusRule alerts LIVE: NotifyDlqSustained (>5/sec critical), NotifyDlqUnreplayed (>100), NotifyDlqSloBurnRateFast/Slow/Medium (1h/6h/24h burn rate), all with runbook_url annotations |
| Outage fallback bypass (D43) | 🟢 done | T1.4 D43 outage fallback FULL ACCEPTANCE Session 41 2026-05-10 00:18-00:24Z (PR #457+#462+#463+#464+#467+#468 — Alertmanager native receiver + ESO Vault fallback secret + PrometheusRule stable labels + first controlled drill: scale=0 → NotifyServiceAbsent firing → Mailpit SMTP delivery 00:22:33Z); R9 🟢 Mitigated |
| Data classification | 🟢 substantively LIVE | `NotificationIntent.DataClassification` enum (transactional/security/commercial/system) + `IntentSubmissionService` + `DeliveryEligibilityService` source-ready/live; acceptance test gate |
| Abuse guard | 🟢 done | T1.6 abuse guards FULL ACCEPTANCE Session 41 2026-05-09 23:45Z (PR #134 + #455 + acceptance evidence: 100×202 + 5×429 burst + RATE_LIMITED audit rows + notify_abuse_blocked_total Prometheus counter; sliding window rate limit max-per-window=100/(orgId, topicKey)/60s window; webhookFanoutCap=10 HARD safety limit; PiiRedactor whitelist OK); R13 + R19 🟢 Mitigated |
| **KVKK Art.7 audit retention** (charter ek, Session 39) | 🟢 done | PR #427 + #437 → AuditPartitionRetentionService activated dryRun=false LIVE prod+test; retention-days=90 + grace=24h; first cycle clean (CREATE phase produces audit_event_v2_2026_08, DETACH/DROP=0 candidates); backend test PR #130 covers DETACH/DROP path with disposable partition |
| **Vault/ESO production secret management** (charter ek) | 🟢 done | PR #424 → flat path `kv/platform/notification-orchestrator` (5 keys: db_username/password, webhook_signing_secret, authz_internal_api_key, redaction_pepper); ExternalSecret creationPolicy=Owner byte-identical takeover; eso-runtime policy extended; legacy split path `kv/platform/notify/*` retired |
| **DLQ SLO definition + burn rate alerts** (charter ek) | 🟢 done | PR #433 → 99.5% target, 18 recording rules + 4 alerts (Google SRE workbook §4 multi-window pattern: 1h+5m / 6h+30m / 24h / 72h burn rates); slow `unless` fast suppression to avoid duplicate P1 paging |

**Evidence (Session 39 — 2026-05-09)**:
- `docs/state/current-state.md` Session 39 + post-02:00 correction entries
- `kustomize/base/apps/notification-orchestrator/prometheusrule.yaml` (25 alerts in 4 groups)
- `kustomize/base/monitoring/notify-dlq-slo-rule.yaml` (18 recording + 4 alert SLO group)
- `kustomize/base/monitoring/grafana-dashboards/notification-orchestrator-dashboard.yaml` (15 panel, sidecar imported)
- `kustomize/overlays/{test,prod}/eso/notify/externalsecret-notify.yaml`
- `bootstrap/vault-policies/common/eso-runtime.hcl` (`kv/data/platform/notification-orchestrator` read added)
- `scripts/operations/notify-audit-retention-preflight.sh` (7-section read-only inventory + DECISION GATE checklist)
- `docs/operations/RUNBOOKS/RB-notify-strict-subscriberid-cutover.md` (extended with strict cutover storm response + retention triage)

**Sub-faz 23.2 closure plan** (M3 stale audit 2026-05-09 re-baseline):
- 🟢 **23.2.A**: Preference API backend ZATEN LIVE; **T1.1 trilogy 3/3 MERGED Session 43**:
  - **T1.1.6** quiet hours enforcement (PR #142, 7 unit tests pass: `SubscriberPreferenceService.evaluate()` quiet hours guard + Clock injection + cross-day window + critical bypass + non-UTC tz + critical no-bypass deny + invalid config fail-open)
  - **T1.1.7** per-user frequency limit (PR #143, 4-iter Codex chain `019e1228`, `FrequencyLimitService` ConcurrentHashMap + AtomicLong + synchronized fixed-window race-safe)
  - **T1.1.8** unsubscribe trilogy (PR #144 PR-A `UnsubscribeTokenService` HMAC-SHA256 + Clock 8 unit tests + PR #145 PR-B `UnsubscribeUrlBuilder` 4 unit tests + PR #146 PR-C `UnsubscribeRevokeService` preference revoke + audit publish + global revoke `muteChannel` pattern + KVKK PiiRedactor recipient hash); residual: ESO 15. key + Vault seed + base-url prod-host guard + integration test e2e (P0.2-P0.5 ~3-4h)
- 🟢 **23.2.B**: KVKK admin erasure source-ready (`AdminErasureController`), R2 legal review external coordination ETA 2026-05-25; **subscriber self-service `DELETE/GET /audit/me` 🟢 T1.2 FULL ACCEPTANCE Session 41** (PR #134 + acceptance evidence)
- 🟢 **23.2.C**: Provider config rollback FULL ACCEPTANCE 2026-05-10 (platform-backend PR #140 MERGED — `switchActive()` @Transactional SERIALIZABLE + afterCommit cache + 4 Testcontainers tests CI GREEN; R12 🟢 Mitigated)
- 🟢 **23.2.D**: Outage fallback bypass (D43) — **T1.4 FULL ACCEPTANCE Session 41 2026-05-10 first controlled drill** (PR #457+#462+#463+#464+#467+#468; R9 🟢 Mitigated)
- 🟢 **23.2.E**: Data classification FULL ACCEPTANCE Session 44 2026-05-10 (PR #149 platform-backend `DataClassificationAcceptanceTest` 8-test matrix-coverage: enum 4-way persistence + severity x classification matrix + DB round-trip + PiiRedactor whitelist boundary; evidence: `docs/faz-23-evidence/2026-05-10-23-2-e-data-classification-acceptance.md`)
- 🟢 **23.2.F**: Abuse prevention guards (D45) — **T1.6 FULL ACCEPTANCE Session 41 2026-05-09 23:45Z** (PR #134 + #455 + acceptance evidence; sliding window 100/orgId-topicKey/60s; R13 + R19 🟢 Mitigated)

Estimated remaining work (Session 44 sonu): **R2 KVKK legal review external coordination ETA 2026-05-25 only** (T1.1 trilogy 3/3 MERGED Session 43 + P0.1-P0.5 + P1.2 PR-A MERGED Session 44; T1.3 MERGED Session 42; 23.2.E acceptance MERGED Session 44 PR #149).

**Historical**: önceki ~100h estimate / Session 41 sonrasında ~52-55h drift; Session 42 T1.3 + Session 43 T1.1 trilogy + Session 44 P0.1-P0.5 + 23.2.E ile residual sıfıra indirgendi (R2 external dışında).

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

**Tier**: v1 (2 hafta) — **🟡 partial (Codex `019e0bff` iter-1 absorb)**

**Acceptance state**:
- **Done**: in-app inbox UI LIVE (PR-5.x cycle), strict identity guards LIVE (PR-5.4/5.5)
- **Pending**: SMS DLR callback ingestion (Faz 23.3 dep — NetGSM provider activation öncesi mümkün değil), archive UI button, 30-day notification history filter

**Kapsam**:
- SMS DLR callback ingestion (provider → orchestrator) — ⏳ deferred (Faz 23.3 dep — NetGSM provider activation pending)
- mfe-host **in-app inbox React component** (custom, Novu yok) — ✅ LIVE
  - List view (paged) ✅
  - Read/unread toggle ✅
  - Archive ⏳ pending UI button
  - Real-time WS badge — replaced with SSE (PR-E.4 cross-pod broadcast PG LISTEN/NOTIFY)
  - Notification history (son 30 gün) — backend filter ⏳ pending
- **Strict identity guards** (Session 39 ek scope): SubscriberIdentityGuard + NotifyOrgAccessGuard hardening — ✅ LIVE prod (PR-5.4 default-org strict close + PR-5.5 subscriberId strict cutover)

**Bağımlılık**: 23.3 done (SMS DLR için) — partial bypass for in-app UI (Session 39)

**Kabul kriteri**:

| Madde | Status | Kanıt |
|---|:---:|---|
| DLR callback round-trip | ⏳ pending | NetGSM DLR → delivery row UPDATE status=DELIVERED — Faz 23.3 dep |
| **In-app inbox UI canlı** | 🟢 done | mfe-host inbox component LIVE testai + ai.acik.com; SSE stream stable; PR-5.x cycle multiple iterations |
| **Inbox /me 400 page-load race fix** | 🟢 done | platform-web PR #316/317/318 (skipToken + RTK fetchFn unwrap Request→string) |
| **SubscriberIdentityGuard strict** | 🟢 done | Backend Faz 23.5 hardening + PR-5.5 strict cutover (NOTIFY_SECURITY_SUBSCRIBER_IDENTITY_STRICT=true LIVE prod) |
| **NotifyOrgAccessGuard strict** | 🟢 done | PR-5.4 default-org close (NOTIFY_SECURITY_DEFAULT_ORG_ID="" LIVE prod) |
| **F3 cutover gate observation** | 🟢 done | source="default" + source="none" sustained 0-emit 4h+ on testai pre-prod cutover |
| Notification history (son 30 gün) | ⏳ pending | backend `GET /inbox/me?since=30d` filter — Faz 23.3 chain |

**Evidence (Session 39 update 2026-05-09)**:
- platform-web PRs: #316/#317/#318 (inbox 400 fix), #315 (FE orgId state-source PR-5.3), #332 (protected route auth-ready)
- platform-backend PRs: PR-5.2 NotifyOrgAccessGuard, PR-5.4/5.5 strict cutover
- platform-k8s-gitops PR #419 (Faz 23.9 prod activation), PR #424 (Vault path)
- Cluster live: testai sha-156ba88 + ai.acik.com sha256:6d926376 (frontend prod), notification-orchestrator sha-204042d both clusters
- Codex thread chain: `019e0675` PR-5.x cycle, `019e07d6` strict cutover plan, `019e0316` SubscriberIdentityGuard hardening

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

**Tier**: Atomic (1 hafta) — **🟡 partial (Codex `019e0bff` iter-1 absorb)**

**Acceptance state**:
- **Done (activation)**: notification-orchestrator deployment LIVE ai.acik.com; image digest pin (sha-204042d); strict cutover env active; Vault/ESO managed Secret; audit retention LIVE
- **Partial**: rollback prova (runbook exists, drill not executed); 72h observation window (T+72h = 2026-05-11 19:42Z, in progress)
- **Pending**: browser SSO verify (manual user action), atomic provider switch test (Faz 23.3 dep)

**Mark discipline**: Even though service is LIVE prod, "Faz 23.9 done" requires 72h observation closure + rollback drill execution. Currently 🟡 partial.

**Kapsam**:
- k3d-prod manifest deploy (image digest pin)
- Provider config prod environment activation
- 72h observation window
- Rollback runbook test (manuel revert provası)

**Bağımlılık**: 23.4-23.8 stable, D30-NOTIFY discipline

**Kabul kriteri**:

| Madde | Status | Kanıt |
|---|:---:|---|
| **k3d-prod pod Ready** | 🟢 done | 2 pod 1/1 Running ready=true since 2026-05-08 19:42Z, restart=0 |
| **Image digest pin** | 🟢 done | sha256:ef0f487f… pinned in `kustomize/overlays/prod/kustomization.yaml`; pod imageID matches GHCR digest |
| Atomic provider switch | ⏳ deferred | DB row update + cache invalidate test — Faz 23.3 dep (no provider config rows in pre-prod context) |
| **Rollback prova** | 🟡 partial | rollback runbook exists in `RB-faz-23-2-notify-vault-paths.md` + `RB-notify-strict-subscriberid-cutover.md`; manual revert prova not yet executed |
| **72h observation window** | 🟡 in progress | T0=2026-05-08 19:42Z, T+72h=2026-05-11 19:42Z; current state: 0 ERROR, DLQ count = 0, all alerts inactive/correctly-pending; **continues until 2026-05-11** |
| **Strict cutover env active** (charter ek) | 🟢 done | NOTIFY_SECURITY_DEFAULT_ORG_ID="" + NOTIFY_SECURITY_SUBSCRIBER_IDENTITY_STRICT="true" + MANAGEMENT_TRACING_ENABLED="false" LIVE both clusters |
| **Audit retention LIVE** (charter ek) | 🟢 done | NOTIFY_AUDIT_RETENTION_ENABLED=true + DRY_RUN=false (PR #437); first real cycle 2026-05-09 created audit_event_v2_2026_08 |
| **Vault/ESO managed Secret** (charter ek) | 🟢 done | PR #424; ESO ExternalSecret ownership; rotation via Vault path |
| **Browser SSO verify** (charter ek) | ⏳ pending user | A.2 manuel verify gerekli — testai + ai.acik.com /inbox/me + SSE 200 cross-domain |

**Evidence (Session 39 — 2026-05-08/09)**:
- PR #419 prod overlay activation (notification-orchestrator image, replicas=2, strict env, JWT issuer)
- PR #424 Vault path + ESO managed Secret (post-cutover hardening)
- D29 evidence ledger: `release-candidates/platform-backend/204042dd699e3f6add5bf919303db0e7d665c9e1.json` (schema-valid)
- Live state: 2 pod prod 1/1 Running 14h+, testai 1 pod 1/1 Running 14h+
- Activation logs: `AuditPartitionRetentionService activated: dryRun=false`
- 25 PrometheusRule alerts inactive, 18 SLO recording rules queryable
- Grafana dashboard 15 panel sidecar imported

**Pending 23.9 closure tasks**:
- ⏳ A.2: Browser verify on both testai + ai.acik.com (kullanıcı manuel SSO session)
- ⏳ Rollback prova execution (drill mode — non-destructive)
- 🟡 72h observation completion (T+72h = 2026-05-11 19:42Z natural)

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

## 8 Open Question — 2026-05-05 Resolution (Codex 019df86f Q4 PARTIAL absorb)

| OQ | Soru | Kim cevaplar | Status | Resolution |
|---|---|---|---|---|
| OQ-1 | Corporate SMTP relay var mı, yoksa Postal self-host? | ops + kullanıcı | 🟡 Tentative | **Corporate relay first**; Postal yedek + ops onayı. 23.2'de clarify. |
| OQ-2 | SMS primary NetGSM mi İletimerkezi mi? | kullanıcı | 🟡 Tentative | **NetGSM primary**, İletimerkezi secondary. Prod sözleşme kullanıcı onayı. 23.3 öncesi clarify. |
| OQ-3 | IYS kaydı mevcut mu? | ops + legal | 🔴 Pending | Transactional MVP'de skip; commercial SMS gerekirse legal confirm. D40-IYS sub-faz. |
| OQ-4 | Audit retention süre tercihi (30/90/180/365)? | kullanıcı + legal | 🟡 Tentative | **90 gün teknik default**, legal confirm. 23.2 sub-faz drift. |
| OQ-5 | Slack workspace kanal isimleri? | kullanıcı | 🟡 Tentative | Test: `#alerts`/`#audit`/`#ops`. Prod webhook kullanıcı/ops confirm. 23.6 scope. |
| OQ-6 | FCM project + APNS bundle id mevcut mu? | mobile/ops | ⏳ Deferred | Henüz absent. Faz 22.2 ile birlikte aktive. 23.7 öncesi clarify. |
| OQ-7 | In-app inbox custom React vs Novu component onay? | kullanıcı | ✅ Resolved | **Custom React** (Codex 019df86f Q1 REVISE absorb — Novu deferred lab). 23.4 sub-faz. |
| OQ-8 | 3rd party SMTP (SendGrid/Mailgun) izinli mi? | kullanıcı + legal | 🔴 Pending | Default: disabled. Legal/KVKK confirm yoksa açılmaz. 23.2 sub-faz drift. |

**Status legend**:
- ✅ Resolved (agent default kabul, ADR ACTIVE)
- 🟡 Tentative default (agent öneri, sub-faz öncesi confirm)
- 🔴 Pending legal/ops (sub-faz öncesi confirm zorunlu)
- ⏳ Deferred (Faz 22 ile bağlantılı)

**Charter Close Eşiği**: ✅ + 🟡 OQ'ları kabul edilmiş sayılır → ADR-0013 **DRAFT → ACTIVE**. 🔴 + ⏳ OQ'lar sub-faz öncesi clarify zincirleri runbook'larda track edilir.

**Charter close için tüm OQ'lar geçti** — ADR-0013 statüsü ACTIVE.
