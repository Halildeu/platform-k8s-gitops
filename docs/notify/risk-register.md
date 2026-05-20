# Notification Platform — Risk Register

> **Status**: ACTIVE (Session 42 update 2026-05-10)
> **ADR**: [ADR-0013-notification-orchestration](../adr/0013-notification-orchestration.md)
> **Charter**: [RB-faz-23-charter](../runbooks/RB-faz-23-charter.md)
> **Last review**: 2026-05-10

Bu register **takip edilebilir + güncellenir** risk tablosudur. Her risk için: ID, açıklama, probability, impact, mitigation, owner, status, last review tarihi.

> **Faz 2 — GitHub Project migration (2026-05-17)** — Açık risk takibi [platform Roadmap board](https://github.com/users/Halildeu/projects/2) (`Faz 23` view · `Kind=risk`) üzerinde. Bu doküman probability×impact / mitigation detayı + mitigated/closed/deferred risk arşivinin canonical kaynağı kalır. Açık risk board mapping: R1 #762 · R2 #763 · R6 #765 · R11 #767 · R14 #768 · R15 #769 · R16 #770 · R17 #771 · R21 #772 · R22 #773. (R3 #764 Session 44'te mitigated, R10 #766 Faz 21'e deferred → board item closed; ikisi de bu dokümanda kayıtlı.)

**Review cadence**:
- Per-PR: yeni risk gözlemlenirse R-N satırı eklenir
- Weekly: tüm aktif riskler review edilir, status update
- Per-incident: incident sonrası retrospective ile yeni risk eklenir

---

## Risk Probability × Impact Matrix

| Probability \\ Impact | Low | Medium | High | Critical |
|---|:---:|:---:|:---:|:---:|
| **High (>50%)** | Low | Medium | High | Critical |
| **Medium (10-50%)** | Low | Medium | Medium | High |
| **Low (<10%)** | Low | Low | Low | Medium |

---

## Active Risks (Session 42 update)

| ID | Risk | Probability | Impact | Severity | Mitigation | Owner | Status | Sub-faz | Last Review |
|---|---|:---:|:---:|:---:|---|---|:---:|---|---|
| R1 | NetGSM secondary provider sözleşme gecikmesi → SMS failover acceptance blocker | Medium | Medium | **Medium** | **Semantik (2026-05-19 kullanıcı kararı)**: SMS primary artık **JetSMS** (canlı sözleşme + HTTP API aktif) — R1 SMS *primary activation* blocker DEĞİL. R1 yalnızca **NetGSM secondary failover acceptance** blocker'ıdır: JetSMS-only degraded mode SMS gönderir, ama "JetSMS primary + NetGSM secondary failover live-ready" kabul kriteri NetGSM contract aktivasyonuna bağlı. Backup: JetSMS-only degraded mode; **NetGSM Vault path infrastructure 🟢 LIVE 2026-05-10 (PR #482 + #485) — secondary hazır, contract activation pending ETA 2026-05-30** | ops + legal | 🟡 Active | 23.3.1 | 2026-05-19 |
| R2 | KVKK erasure scope yanlış implement → audit fail / legal exposure | Medium | Critical | **High** | Legal review öncesi merge yasak; runbook + integration test pre-prod | legal/dev | 🟡 Active | 23.2.B | 2026-05-09 |
| R3 | DKIM/SPF/DMARC prod activation breaks email delivery | Medium | High | **Medium** | A4 DKIM RFC 6376 full impl (backend PR #151, 61 test sign+verify); activation flip A5 PR-B deferred. Mailpit dev test + canary domain + 24h pre-cutover validation | ops/dev | 🟢 Mitigated | 23.2 | 2026-05-11 |
| R4 | Audit retention DETACH/DROP destructive bug (data loss) | Low | Critical | **Medium** | Backend test PR #130 + dry-run observation + ownership check | dev | 🟢 Mitigated | 23.2 (retention) | 2026-05-09 |
| R5 | Multi-pod cron lock contention causing missed retention cycles | Low | Medium | **Low** | LockSkippedSustained alert (PR #435 multi-pod aware) | dev | 🟢 Mitigated | — | 2026-05-09 |
| R6 | Codex API limit / cross-AI peer review HARD RULE blocker | Low | Medium | **Low** | Multi-thread strategy + queue-based review + offline absorb pattern | agent | 🟡 Active | — | 2026-05-09 |
| R7 | Browser SSO verify user availability blocking 23.9 closure | Medium | Low | **Low** | Pre-Production Full Authority HARD RULE agent headless tool — Session 49 closure 2026-05-14: testai + ai.acik.com SSO LIVE evidence (d29-evidence-tester + d29-prod-sso-tester JWT mint + /api/v1/authz/me HTTP 200, evidence doc `docs/faz-23-evidence/2026-05-14-m1-23-9-cutover-closure-evidence.md`) | agent | 🟢 Closed | 23.9 | 2026-05-14 |
| R8 | 72h observation undetected incident → silent breakage | Low | High | **Low** | 25 PrometheusRule + 4 SLO alerts + dashboard 15-panel | ops | 🟢 Mitigated | 23.9 | 2026-05-09 |
| R9 | D43 outage fallback test fail under real outage | Medium | High | **Medium** | T1.4 D43 partial: PR #457+#462+#463+#464+#467+#468 source-ready; first controlled drill 2026-05-10 00:18-00:24Z **SMTP-only receipt** (Mailpit `[FIRING:1] NotifyServiceAbsent` 00:22:33Z); Slack leg sentinel-only (`drill-slack-mock.local` NXDOMAIN — runbook Step 6 unkanıt) — board #853; prod helm-values direct-fallback receiver/route eksikti → PR #855 staged config kapatır; prod activation owner-gated (Vault seed + helm upgrade + dual-receipt smoke) — board #854. Codex thread `019e4234` Session 42 audit: **partial mitigation** olarak yeniden etiketlendi (eski "mitigated by first controlled drill" overclaim). | ops | 🟡 Partial | 23.2.D | 2026-05-19 |
| R10 | Multi-tenant migration data drift / cross-tenant leak | High | Critical | **Critical** | Faz 21 öncesi pre-migration audit + dry-run + per-tenant isolation test | dev | 🔴 DEFER | Faz 21 | — |
| R11 | Tempo OTLP collector deploy breaks tracing path | Low | Medium | **Low** | MANAGEMENT_TRACING_ENABLED=false pre-cutover + canary deploy | ops | 🟡 Active | 23.8 | 2026-05-09 |
| R12 | Provider config rollback transaction race (atomic switch) | Low | High | **Low** | provider_config_history immutable rows + cache invalidate test; T1.3 backend Testcontainers integration test FULL ACCEPTANCE 2026-05-10 (platform-backend PR #140 MERGED — 4 test methods CI GREEN: atomic_switch + concurrent_switch_race + cache_invalidate + rollback_on_fail; ProviderConfigService.switchActive @Transactional SERIALIZABLE + TransactionSynchronization.afterCommit cache invalidation; Codex iter-1 RED → iter-2 AGREE) | dev | 🟢 Mitigated | 23.2.C | 2026-05-10 |
| R13 | Webhook fan-out cap exhausted → DLQ flood | Medium | Medium | **Medium** | T1.6 abuse guards FULL ACCEPTANCE 2026-05-09 23:45Z (PR #134 + #455 + Session 41 acceptance evidence: 100×202 + 5×429 burst + RATE_LIMITED audit rows + notify_abuse_blocked_total Prometheus counter; webhookFanoutCap=10 HARD safety limit; PiiRedactor whitelist OK) | dev | 🟢 Mitigated | 23.2.F | 2026-05-09 |
| R14 | Frontend bundle size regression (in-app inbox + preference UI) | Low | Medium | **Low** | Bundle analyzer + threshold gate + lazy-load | dev | 🟡 Active | 23.4 + 23.5 | 2026-05-09 |
| R15 | Audit retention legal challenge (90 day insufficient for some KVKK clauses) | Low | High | **Low** | Configurable retention-days + sub-faz drift review (30/180/365) | legal | 🟡 Active | 23.2.B (legal retention drift) | 2026-05-09 |
| R16 | Cross-cluster Prometheus federation cardinality explosion | Medium | Medium | **Medium** | Federation design + cardinality budget + rollback plan | ops | 🟡 Active | 23.8 federation | 2026-05-09 |
| R17 | Vault root token compromise (operator credential) | Low | Critical | **Medium** | break-glass-token.sh + audit log + Vault audit device + token rotation | ops | 🟡 Active | — | 2026-05-09 |
| R18 | OpenFGA tuple drift (auth-service ↔ permission-service ↔ notify) | Medium | High | **Medium** | DD-5 cross-repo guard + tuple seed CommandLineRunner + integration test | dev | 🟢 Mitigated | — | 2026-05-09 |
| R19 | Mass notification sending storm (abuse / compromised key) | Low | Critical | **Medium** | T1.6 abuse guards FULL ACCEPTANCE 2026-05-09 23:45Z (sliding window rate limit max-per-window=100/(orgId, topicKey)/60s window; first 429 at request #101 acceptance evidence; RATE_LIMITED audit + notify_abuse_blocked_total counter; critical bypass dar scope) | ops | 🟢 Mitigated | 23.2.F | 2026-05-09 |
| R20 | Audit log immutability bypass via direct DB access | Low | High | **Low** | V8 trigger no_update/delete + DB role privilege restriction | dev | 🟢 Mitigated | — | 2026-05-09 |
| R21 | Provider rate-limit / quota exhaustion (Mailgun/Slack/SMS) → silent throttling | Medium | High | **Medium** | Per-provider quota dashboard + 429 alert + fallback chain (R13 ile partial örtüşür ama explicit external-throttling failure mode) | ops + dev | 🟡 Active | 23.2 + 23.3 | 2026-05-09 |
| R22 | GHCR / artifact registry outage → image pull fail blocks rollout | Low | High | **Low** | imagePullPolicy:IfNotPresent + node-cached images + secondary registry mirror plan + manual import runbook | ops | 🟡 Active | — (cross-cutting) | 2026-05-09 |
| R23 | Microsoft Graph mail adapter deferral leaves SMTP as single active mail path | Low | High | **Low** | SMTP Office 365 path (`ai@acik.com` + App Password) canonical ve LIVE; Entra App Registration `acik-mail-graph-api` + Mail.Send Application permission + tenant-wide admin consent **asset olarak korunur** (en ağır setup tamamlandı); client_secret + ApplicationAccessPolicy + Vault `graph_*` seed + ConfigMap flag + digest bump + smoke send 5-adım atomic reactivation chain documented in [ADR-0024](../adr/0024-graph-mail-adapter-defer.md) + [RB-graph-mail-adapter-activation.md](../runbooks/RB-graph-mail-adapter-activation.md); reactivation triggers: (a) Microsoft App Password deprecation tenant-impact, (b) SMTP AUTH tenant policy break, (c) outbound 587 ISP/firewall block recurrence, (d) ops/security tactical decision, (e) provider migration. Monitor: Microsoft Tech Community + roadmap.microsoft.com App Password deprecation announcements; cluster outbound 587 health periodically. | ops | 🟡 Active | 23.X / v1.x | 2026-05-20 |
| R24 | JetSMS VFO channel ErrorCode=04 (Biotekno OTP allowlist provisioning gap) | Medium | Medium | **Medium** | PR-A3.2 cluster smoke 2026-05-20: VFO channel routing logic LIVE (`channel resolved VFO: topic_key=auth.mfa-otp` log proven) ama JetSMS provider Biotekno tarafında VFO outbound sender ID OTP allowlist provisioning gap → ErrorCode=04 reject. **Mevcut config ile risk aktif**: test overlay'de `auth.mfa-otp,auth.password-reset-otp` allowlist açık; bu topic'ler kısa mesajda VF'ye düşmüyor, VFO'ya gidip reject ediliyor. **Operational workaround** (provider provisioning tamamlanana kadar): (a) `NOTIFY_ADAPTERS_SMS_JETSMS_CHANNEL_OTP_TOPIC_KEYS=""` blank yapmak — tüm OTP topic'ler default VF'den çıkar; veya (b) ilgili topic'leri allowlist'ten çıkarmak. Mitigation: Biotekno müşteri temsilcisi ile sender ID OTP provisioning chain'i; provider tarafı çözülünce allowlist tekrar açılınca VFO routing automatic devreye girer (code side LIVE). Audit: actual_channel propagation (VF accepted path) kanıtı [docs/faz-23-evidence/2026-05-20-23-3-2-jetsms-multipart-context-routing-evidence.md](../faz-23-evidence/2026-05-20-23-3-2-jetsms-multipart-context-routing-evidence.md). | ops + provider | 🟡 Active | 23.3.2 + 23.X | 2026-05-20 |

---

## Status Legend

- 🟢 **Mitigated**: risk addressed, ongoing monitoring sufficient
- 🟡 **Active**: in progress, mitigation partially implemented
- 🔴 **Pending**: mitigation not yet started, blocker for related sub-faz
- ⏳ **DEFER**: future-faz dependency

## Owner Roles

- **agent**: Claude/Codex automated work
- **dev**: backend/frontend code work
- **gitops**: kustomize/k8s manifest work
- **ops**: cluster operator / Vault / DB
- **legal**: legal/KVKK review
- **user**: kullanıcı manuel action (browser SSO etc)

---

## Closed Risks (Archive)

| ID | Risk | Closure Reason | Closed Date |
|---|---|---|---|
| (None yet — will be populated as risks are closed during Faz 23 cycle) |

---

## Risk Review History

- 2026-05-09 (Session 39 bootstrap): Initial 20 risks identified during PM artifact creation. R4/R5/R8/R18/R20 marked Mitigated based on Session 39 Codex review evidence.
- 2026-05-09 (Codex iter-2 absorb PR #441): R1 owner extended `ops → ops + legal` (NetGSM commercial contract). 2 yeni risk: R21 (provider rate-limit external throttling) + R22 (GHCR registry outage). Toplam aktif risk: 22.
- 2026-05-10 (Session 42 PR #482 + #483 + #485 absorb): R1 mitigation row extended — Vault path infrastructure 🟢 LIVE (canonical kv/platform/notification-orchestrator + 4 NetGSM keys (username/password/msgheader/dlr_token all empty fail-closed) + ESO 9/9 Ready + 4/4 pod env vars injected). Sub-faz 23.3 → 23.3.1. Last review 2026-05-09 → 2026-05-10. Contract activation pending R1 ETA 2026-05-30. R12 🔴 Pending → 🟡 Active (T1.3 backend Testcontainers spawn_task chip user-side cross-repo platform-backend).
- 2026-05-19 (SMS provider kararı — kullanıcı): SMS primary **NetGSM → JetSMS** (canlı sözleşme + HTTP API), secondary **İletimerkezi → NetGSM**. R1 severity **High → Medium** + semantik daraltıldı: artık SMS primary activation blocker değil, yalnızca NetGSM secondary failover acceptance blocker (JetSMS-only degraded mode SMS gönderir). Probability/Impact High/High → Medium/Medium. Multi-provider PR sequence Codex `019e3f82` AGREE.

## Next Review

- **2026-05-12** (post 23.9 72h observation closure): R7 (browser verify), R8 (observation completion), R9 (outage fallback drill if 23.2.D started)
- **2026-05-25** (23.2 closure milestone): R2/R12/R13/R19 (Faz 23.2.A..F implementation gates)
- **2026-06-08** (23.3 SMS milestone): R1 (NetGSM secondary contract — failover acceptance), R3 (DKIM activation)
