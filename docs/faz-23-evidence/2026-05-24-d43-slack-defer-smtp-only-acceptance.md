# Faz 23 v1 must-have #10 D43 Acceptance Redefinition — Slack DEFER, SMTP-Only

> **Status**: User decision absorbed 2026-05-24. D43 v1 acceptance redefined as SMTP-only direct Alertmanager fallback. Slack adoption deferred future trigger.

## 1. User Decision

**Verbatim** (2026-05-24, kullanıcı mesajı, drift cleanup + #1012 detay sonrası):

> "slack kullanmıyoruz. sonrasınd agelirse yapılacak."

İçerik: Slack kurum içi adoption şu an yok; Slack tabanlı operator alert kanalları (D43 outage fallback, T2.1.2 notify channel, M5 #alerts-d43-drill aktivasyon) **v1 closure scope dışı**. Future Slack adoption gelirse (Slack workspace kurulumu + admin onayı) reactivation chain ayrı sprint.

## 2. Strategic Consult Reference

**Codex MCP thread**: `019e5b9c-a0fa-7c13-888f-511ed508648a`
**Verdict**: REVISE plan (kullanıcı kararı absorb edilebilir; mevcut doküman/Helm desired-state Slack dual-leg çizgisini hâlâ taşıyor — düzeltilmesi gerek)
**Implementer**: Claude (Anthropic)
**Reviewer**: Codex (OpenAI) — provider-level HARD RULE

## 3. Redefined D43 v1 Acceptance

### Önceki (Slack dual-leg, deprecated)

```
D43 v1 acceptance:
  Alertmanager fan-out → direct-fallback receiver:
    - SMTP leg (Mailpit/operator inbox)
    - Slack leg (workspace #alerts-d43-drill)
  Dual-receipt verification required for must-have #10 🟢
```

### Sonraki (SMTP-only, current)

```
D43 v1 acceptance:
  Alertmanager fan-out → direct-fallback receiver:
    - SMTP leg only (operator ops inbox)
  Single-receipt verification sufficient for must-have #10 🟢
  Slack leg → future trigger (operator Slack workspace adoption)
```

### Acceptance gate (current)

- Test cluster: Mailpit `[FIRING:1] NotifyServiceAbsent` receipt 2026-05-10 00:22:33Z **historical evidence** retained
- Prod cluster: prod ops mail receipt via Alertmanager direct-fallback SMTP receiver — **pending operator action** (Vault seed + helm upgrade + synthetic alert + receipt)
- Slack leg evidence (`drill-slack-mock.local` NXDOMAIN sentinel + BL-008 webhook-receiver mock POST 2026-05-24) → **historical drill evidence only**; v1 acceptance kapısı DEĞİL

## 4. R9 Risk Register Update Pattern

**Before** (mock-receipt mitigated, dual-leg pending):
```
R9 | 🟢 Mitigated (mock-receipt) | BL-008 dual receipt drill |
   | Real Slack workspace #853 + prod activation #854 ext-bound |
```

**After** (SMTP-only acceptance, Slack defer):
```
R9 | 🟢 Mitigated (SMTP-only D43 v1 accepted; Slack DEFER per user decision 2026-05-24) |
   | Production-ready evidence requires prod cluster SMTP direct receipt + recovery proof |
   | Historical Slack mock drills (2026-05-10 sentinel + 2026-05-24 BL-008) retained as drill audit |
```

Codex strategic consult'a göre alternatif: tek aktif kanal monitoring riski ayrı **R27 single active operator alert channel** olarak izlenebilir (Accepted/Monitored veya DEFER). Bu opsiyonel — owner appetite kararı.

## 5. Faz 23 v1 Must-Have #10 Status

**Önceki**: 🟢 mock-receipt mitigated (dual-leg dil); real Slack + prod activation operator-external residual
**Sonraki**: 🟢 SMTP-only D43 v1 accepted (per user decision 2026-05-24); prod SMTP activation operator-bound; Slack DEFER future trigger

Aggregate Faz 23 v1 must-have: **10/10** korunur (must-have #10 acceptance kuralı yeniden yazıldı, status değişmedi).

## 6. Production-Ready Claim Boundary

**SMTP-only fallback için production-ready iddia çizgisi**:

- ✅ Alertmanager direct-fallback SMTP receiver staged (helm-values prod)
- ⏳ Prod Vault seed (`kv/platform/alertmanager-fallback` SMTP credentials) — operator
- ⏳ Prod helm upgrade + Alertmanager Operator v0.90.1 `auth_*_file` schema fix (board #854 yeniden scope: SMTP-only prod activation)
- ⏳ Prod synthetic D43 alert trigger + ops inbox receipt
- ⏳ Recovery/resolved alert evidence + secret/log discipline check

Tüm 5 gate kapanmadan **prod-ready iddiası kurulmaz**. Test cluster Mailpit receipt yalnızca test evidence.

### Multi-Channel Resilience (Optional Future Layer)

Codex consult önerisi: tek SMTP kanalı incident resilience için zayıf olabilir. Future layer adaylar (Slack alternative):
- Microsoft Teams Incoming Webhook
- PagerDuty / OpsGenie integration
- Kurum içi SMS ops listesi (NetGSM/JetSMS)
- Mevcut kurum içi alarm kanalı (kurum standart paging system)

Şu an scope dışı; **iddiası**: "SMTP-only operator alerting accepted; multi-channel incident paging not claimed."

## 7. Helm-Values + Alertmanager Config Cleanup

PR #855 ile staged Slack receiver config (`helm-values/kube-prometheus-stack/values-prod.yaml` + `values-test-d43-drill.yaml`) active GitOps desired-state'te kalmamalı. Cleanup hedefi:

- `direct-fallback` receiver active config **SMTP-only**
- `slack_configs` block kaldırılır (veya `.example` / runbook patch'a taşınır — future-only)
- `SLACK_WEBHOOK_URL` active ESO key set'inden çıkarılır
- `values-test-d43-drill.yaml` SMTP-only smoke'a çekilir (BL-008 historical evidence retained ama yeni acceptance kapısı olmaz)

Cleanup PR: Lane B (ayrı branch + Cross-AI review).

## 8. Issue Cascade Triage

| Issue | Önceki scope | Yeni karar |
|---|---|---|
| **#853** D43 drill execution sentinel limitation | Real Slack workspace receipt | **Close as deferred** — superseded by SMTP-only acceptance |
| **#854** Operator activation Slack Vault seed + helm + dual-receipt | Slack + SMTP prod activation | **Rescope** — "D43 prod activation — SMTP-only direct fallback smoke" (Slack components removed; prod SMTP auth schema fix retained) |
| **#855** Helm-values staged direct-fallback receiver (MERGED) | Slack + SMTP staged config | Cleanup tracking ekle (Lane B cleanup PR) — staged config superseded by Slack defer |
| **#1012** D43 Slack webhook seed | Real Slack webhook + Vault seed | **Close as not-planned** — Slack adoption deferred |

## 9. Cross-AI Audit Trail

- Codex strategic consult thread `019e5b9c` — REVISE plan; agent-actionable 7-step plan absorb
- Codex iter-N (post-impl review pending) — bu evidence doc + canonical edit'lerin AGREE'i alındıktan sonra merge

## 10. Tracked Lane'ler

| Lane | Konu | Branch | Status |
|---|---|---|---|
| **A** | Docs truth-sync (this evidence + 4 doc edit) | `roadmap-faz23-d43-slack-defer-docs-truthsync` | IN PROGRESS |
| **B** | Helm-values Slack section remove (values-prod + values-test-d43-drill) | TBD | PENDING |
| **C** | Issue cascade (#853 + #854 + #855 + #1012) | — | PENDING (post Lane A merge) |

## 11. Historical Evidence Retained

Slack adoption gelirse referans olarak korunan evidence'lar:
- `docs/faz-23-evidence/2026-05-10-r9-d43-drill-mitigated.md` — first controlled drill SMTP-only receipt + Slack sentinel NXDOMAIN finding
- `docs/faz-23-evidence/2026-05-24-bl008-r9-d43-drill.md` — BL-008 mock-receipt dual drill (webhook-receiver + Mailpit)
- `docs/runbooks/RB-notification-outage-fallback.md` — drill execution sequence (§Step 6 SMTP receipt validation; historical Slack receipt section marked DEFERRED per user decision 2026-05-24)
- `helm-values/kube-prometheus-stack/values-prod.yaml` (pre-cleanup snapshot via git history) — staged Slack receiver template

## 12. Boundary Statement (HARD)

- ✅ User decision absorbed; D43 acceptance redefined SMTP-only
- ✅ Production-ready claim DEĞİL — prod activation operator-bound
- ✅ Historical Slack drill evidence kalır (audit-only)
- ✅ Future Slack reactivation chain açık — workspace adoption + Vault seed + helm re-add + drill rerun
- ✅ No-Closure Language — "kapandı/bitti" iddiası kurulmaz; "Slack DEFER + SMTP-only redefinition + prod activation pending" durum açık
- ✅ Multi-channel resilience iddiası YOK — single SMTP channel accepted; future layer (Teams/PagerDuty/SMS/kurum içi) opsiyonel

## 13. Related

- ADR-0013 §D43 — original dual-leg architecture decision (historical reference; superseded for v1 by this addendum)
- ADR-0013 §D46 — must-have #10 "observability + outage fallback" — channel sayısı non-mandated, sadece "notification-service bypass" gereksinimi
- PLAN.md row 38 Faz 23 — must-have aggregate update reference

---

**Decision date**: 2026-05-24
**User**: Halil Koçoğlu
**Codex strategic thread**: `019e5b9c-a0fa-7c13-888f-511ed508648a`
**Implementer**: Claude (Anthropic) — this session
