# ADR-0028 — BL-009 (DKIM CNAME Publish) + BL-022 (NetGSM Secondary Contract) Plan-Out / Demand-Reactivated

**Status**: Accepted
**Date**: 2026-05-25
**Authors**: Kullanıcı (explicit decision) + Cross-AI review (Codex `019e6045` iter-1 PARTIAL absorb)
**Supersedes**: None (governance ADR; teknik runtime değişikliği yok)
**Related**: ADR-0024 (Graph mail adapter defer — asset-preserved precedent), ADR-0027 (D43 Teams Power Automate defer — Hibrit C precedent), R1 (NetGSM secondary), R3 (DKIM), BL-009, BL-022

---

## Context

Faz 23 v1 prod SMS lane 2026-05-25 fully delivered (BL-011 LIVE — PR #1071). Closure handoff backlog'da iki external dependency satırı kalmıştı:

1. **BL-022 NetGSM Secondary Contract** — Kullanıcı kararı 2026-05-23: "NetGSM sözleşmesi kısa vadede yapılmayacak". JetSMS-only degraded mode kabul edilen kalıcı işletim durumu. `NetGsmProvider` + `SmsAdapter` failover facade + Vault/ESO altyapısı asset-preserved dormant. R1 ⏳ DEFER status'unda Active Risks tablosunda izleniyordu, ancak fiilen "aktif risk değil, parked" diye işaretliydi.

2. **BL-009 DKIM CNAME Publish** — Kullanıcı kararı 2026-05-25 (PR #1061 + Codex `019e5bfb` AGREE): Office 365 Native CNAME pattern alternatifi nedeniyle SMTP relay LIVE; DKIM CNAME ek security/deliverability upgrade'di. "Şimdilik yapmayalım, sonra yaparız — tam erteleme değil, defer." 5 trigger-based reactivation condition listed idi (mail-tester ≥9/10 / DMARC strict / spam placement / tenant + DNS registrar window / security-compliance mandate).

Kullanıcı 2026-05-25 talimat: **"netgsm işi başka birinden talep gelene kadar bu haliyle kalacak çıkaralım plandan cname aynı aynı şekilde"** — iki item aktif planı, backlog tracking, board surface ve roadmap'tan çıkarılır; mevcut state dondurulur; **dış talep/ihtiyaç gelirse reactivation**.

## Decision

BL-009 + BL-022 her ikisi de **"Out of plan / Demand-reactivated / Asset-preserved"** statüsüne alınır. Aktif governance surface'ları (closure handoff, risk register Active Risks, milestones DoD listing, board issue, sprint-plan blocker, charter blocker listing) içinden temizlenir. Mevcut runtime/source state ve historical evidence korunur.

### Asset-preservation (her ikisi için)

**BL-022 NetGSM**:
- `NetGsmProvider` (REST v2) kod tabanı korunur
- `SmsAdapter` failover facade korunur (multi-provider abstraction)
- Vault `kv/platform/notification-orchestrator` NetGSM keys (username/password/msgheader/dlr_token) empty/fail-closed olarak dormant kalır
- ESO ExternalSecret entries dormant asset
- **Hiçbir code/manifest revert YAPILMAZ**

**BL-009 DKIM CNAME**:
- Backend `notify.dkim.strategy` enum (`app|relay|disabled`) korunur — şu an `relay` (Office 365 Native)
- SMTP relay LIVE prod sha-6307428
- DKIM signing keys + ProductionConfigValidator branch hardening dormant fallback
- Office 365 admin CNAME publish path (tenant DNS + DNS registrar) hazır kullanılmaz state
- **Hiçbir kod/strategy değişikliği YAPILMAZ**

### Active surface clean-up (governance only)

- **Closure handoff backlog**: BL-009 (§2 Sprint B) + BL-022 (§4 Strategic Decisions) aktif checklist satırları kaldırılır; yeni "Archived / Out of plan / Demand-reactivated" sub-section'a archive note olarak taşınır (no-checkbox format)
- **Risk register**: R1 NetGSM Active Risks tablosundan ayrı "Archived / Out of plan / Demand-reactivated records" sub-section'a taşınır; R3 DKIM mitigated status korunur ama BL-009 active trigger language collapse edilir
- **Milestones**: M4/M6b içindeki "R1 blocker değil" veya "BL-009 trigger-based DEFER" wording'leri archive reference'a daraltılır
- **Feature matrix**: A.4 SMS (NetGSM secondary) + H4/L1 (DKIM) row'larında "out-of-plan / demand-reactivated" wording
- **Sprint plan**: stale R1/BL-009 references collapse
- **Charter**: line 51 R1 + BL-009 references collapse
- **PLAN.md**: D40 satırındaki "R1 NetGSM secondary contract = failover acceptance blocker" dili daraltılır (no longer active blocker)

### Non-decisions

- ❌ M7 DoD formal azaltma claim'i YAPILMAZ (BL-009 + BL-022 zaten M7 DoD'da listed değil; Codex iter-1 Q2 doğrulandı)
- ❌ R1 + R3 "Closed" durumuna geçmez (Closed Risks archive yanlış sinyal; demand-reactivated ≠ closed)
- ❌ Yeni board issue açılmaz
- ❌ Code/manifests/Vault/DNS/KC/provider config değişmez

### Reactivation triggers (asset-preserved, demand-driven)

Bu trigger'lar **aktif review cadence DEĞİL** — sadece dış talep geldiğinde başvuru için historical reference olarak korunur:

**BL-022 NetGSM reactivation chain** (sözleşme talebi gelirse):
1. NetGSM sözleşme imzalanma
2. Vault NetGSM keys seed (`kv/platform/notification-orchestrator/netgsm_*`)
3. ConfigMap secondary provider enable
4. notification-orchestrator digest bump + rollout
5. Failover acceptance test (JetSMS down → NetGSM secondary kicks in)
6. R1 status update: 📦 Out of plan → 🟢 Mitigated (or appropriate)

**BL-009 DKIM CNAME reactivation chain** (security/deliverability talebi gelirse):
1. Trigger event: mail-tester score ≥9/10 hedef / DMARC strict upgrade / spam placement observed / tenant admin onayı / security-compliance mandate
2. Office 365 admin DKIM tenant enable
3. DNS registrar CNAME publish (`selector1._domainkey.acik.com` + `selector2._domainkey.acik.com`)
4. DNS propagation observe (24-48h)
5. mail-tester re-score
6. Backend `notify.dkim.strategy` flip option (app-side DKIM signing aktif edilebilir; relay path korunur)
7. R3 status update: 🟢 Mitigated (unchanged) — ek "upgraded" not düşülebilir

## Consequences

### Positive

- **Plan truth-sync**: Backlog + risk register + milestones + roadmap surface'ları gerçek aktif iş ile uyumlu hale gelir. M7 #759 Blocked status'unda BL-009/022 false-blocker yapmıyor; gerçek M7 unblock şartları (BL-014 FBL + BL-016 R24 Biotekno + BL-012 30-day soak) net görünür.
- **Audit trail korunur**: Asset-preserved pattern (R23/ADR-0024 precedent) ile mevcut implementation tarihsel referans + reactivation zinciri hazır.
- **No drift risk**: Kullanıcı kararı ADR ile mühürlü; gelecek ajanların aynı item'ları aktif backlog'a tekrar koyma riski engellendi.
- **Faz 23 v1 closure psikolojik temizlik**: 5-PR closure series (BL-028 B-with-lanes + BL-011 LIVE) sonrası kalan "DEFER ama plan'da" item'lar görünür yükü kaldırıyor.

### Negative

- **Reactivation maliyeti**: Eğer ileride dış talep gelirse, "asset-preserved" durumun tekrar aktive edilmesi için yeni Codex iter + plan-time consult + impl PR + smoke gerek (her zamanki release pattern). Bu maliyet kabul edilebilir çünkü demand-driven; speculative pre-implementation yok.
- **Historical complexity**: Closure handoff + risk register iki ayrı section (Active + Archived) ile genişler. Mitigation: ayrı sub-section sınırı net (Active Risks → Archived/Out-of-plan → Closed Risks).

### Neutral

- M7 DoD formal olarak değişmez (Codex iter-1 Q2 verdict: zaten listed değildi).
- 23.7.b/v1.1 patch milestone (Mobile FCM/APNS DEFER) bu ADR'dan etkilenmez (R25 governance ayrı; Faz 22.2 dependency demand-driven değil planned-DEFER).

## Alternatives Considered

### Alternative A: Inline `[ARCHIVED]` marker in active checklist

`[ ] BL-009/022` → `[📦 ARCHIVED]` inline marker active checklist'in içinde kalır.

**Rejected**: Kullanıcı "plandan çıkar" talimatı için yeterli değil — backlog yüzeyinde hâlâ aktif iş gibi görünür.

### Alternative B: Complete removal (sadece ADR'da tarihsel kayıt)

Tüm BL-009/022 referansları silinir, sadece ADR-0028 tarihsel kayıt tutar.

**Rejected**: Asset-preservation kanıtı + reactivation triggers + historical context audit için değerli. R23/ADR-0024 + R27/ADR-0027 precedent'leri bu pattern'i destekliyor.

### Alternative C (chosen): Archive sub-section + ADR-0028 + Active surface cleanup

**Hybrid pattern**: Aktif governance surface'larından temizle + ayrı archive sub-section + lightweight ADR ile mühürle. R23/ADR-0024 + R27/ADR-0027 precedent ile uyumlu.

## Cross-AI peer review

- **Implementer**: Anthropic Claude (Opus 4.7 1M context)
- **Reviewer**: OpenAI Codex
- **Codex thread**: `019e6045-72e5-72d0-8ac9-bbd5bf8403ad`
- **Iter chain**:
  - iter-1: PARTIAL — Pattern B + ADR-0028 + risk-register archive section recommended; M7 DoD formal azaltma yok kanıtlandı; R1 archive transfer + R3 BL-009 trigger language collapse önerildi
- **Provider farkı**: Anthropic ↔ OpenAI (HARD RULE 2026-05-05/14 compliance)

## Audit Trail

- Kullanıcı talimatı: 2026-05-25 chat session
- Önceki related kararlar:
  - R1 NetGSM DEFER asset-preserved: 2026-05-23 (kullanıcı kararı; risk register iter)
  - BL-009 DKIM trigger-based DEFER: 2026-05-25 (PR #1061 + Codex `019e5bfb` AGREE)
- Bu ADR + governance sweep PR: ayrı docs-only PR (this PR)

## References

- ADR-0024 — Graph mail adapter defer (asset-preserved precedent)
- ADR-0027 — D43 Teams Power Automate defer (asset-preserved Hibrit C precedent)
- R1 — NetGSM secondary contract (risk-register.md)
- R3 — DKIM mitigation (risk-register.md)
- BL-009 + BL-022 — Closure handoff backlog (archived sub-section)
- `NetGsmProvider` source: platform-backend (dormant)
- DKIM strategy enum: platform-backend `notify.dkim.strategy` (relay; app-side fallback dormant)
