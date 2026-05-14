# M3-Supplement OpenFGA Notification Model Extension — Plan-Time Decision (2026-05-14)

> **Status**: 🟡 Plan-time consensus (Codex `019e2651` AGREE Yol A) — implementation ayrı sprint (10-16h)
> **Sub-Faz**: 23.2 v2 (charter scope clarification — Layer 2 channel-level authz)
> **Trigger**: Session 49 M2 D29-Functional evidence sırasında Layer 2 hard-deny pattern bulgu
> **Codex Thread**: `019e2651-749f-71b1-a72a-578a290cb5c5`

---

## 1. Bağlam

M2 D29-NOTIFY-Functional 3-channel LIVE evidence (Session 49 PR #597) sırasında:
- **Layer 1** (NotifyOrgAccessGuard JWT `org_id`) → LIVE ALLOW + DENY both verified
- **Layer 2** (channel-level OpenFGA `subscriber:X #can_receive template:Y` tuple check) → **bypass** (NOTIFY_AUTHZ_ENABLED=false temporary) — production-ready değil

Mevcut OpenFGA model'inde **`subscriber`** + **`template`** + **`notification_topic`** type'ları **YOK**:
```
Mevcut types: user, organization, company, project, warehouse, branch, module, action, report
```

ERP-only model — notification authz için extension gerek.

---

## 2. Karar (Codex Yol A AGREE)

**Yol A seçildi**: Mevcut OpenFGA store (`01KPP0CFP4G82K42Y6NYSPT4JF` "erp-stage") içinde **authorization model revision** ile yeni notification type'ları ekle.

### Rationale
- **ADR-0013 D38/D41 uyumlu**: notification permission-service Zanzibar plane reuse (charter authority)
- **Single store**: permission-service config değişmez (STORE_ID + MODEL_ID env aynı kalır, sadece MODEL_ID yeni revision'a bump)
- **D46 #5 must-have** OpenFGA hard-deny + org boundary korunur
- Yol B (ayrı store) eliminate: 24-40h effort, permission-service multi-store routing complexity
- **Yol C RED** (PG ACL-only): D41 violation, backwards step

### Yeni Type Model (Codex önerdiği refinement)

```
type subscriber
  relations
    define member: [user]

type notification_topic
  relations
    define can_receive: [subscriber]
    define can_publish: [service_account, user]

type notification_template
  relations
    define topic: [notification_topic]
    define can_receive: can_receive from topic
    define can_publish: can_publish from topic

type service_account
  # outbox source service authority
```

**Critical design decision** — Topic-based inheritance:
- Grant `subscriber:1299 #can_receive notification_topic:test.d29.email`
- Template miras alır: `notification_template:t1` → topic `test.d29.email` → subscriber 1299 can_receive ✅
- Per-template grant **YASAK** (governance complexity, future-proof topic federation kolayı)

### Compatibility

Backend AuthzClient mevcut çağrı:
```java
authzClient.check("subscriber", principalId, "can_receive", "template", templateId)
```

Object_type `template` (deprecated) → migrate to `notification_template`. Geçici dual-write veya backend code update gerek:
- Geçici: model'e hem `template` hem `notification_template` ekle (parallel)
- Long-term: backend AuthzClient çağrısı `notification_template` object_type'a güncelle

---

## 3. Effort Estimate (Codex)

**Yol A minimal v2** (10-16 saat):
1. Authorization model JSON draft (1-2h)
2. Model write via OpenFGA REST API (0.5h)
3. permission-service `ERP_OPENFGA_MODEL_ID` env update + ESO refresh (1h)
4. Tuple seed runbook + scripted seed for `subscriber:1299#can_receive notification_topic:test.d29.email` (2h)
5. Backend AuthzClient backwards compat patch (3-4h) — `template` veya `notification_template` accept
6. Live test: `NOTIFY_AUTHZ_ENABLED=true` + intent submit allow + deny + delivery row evidence (2-3h)
7. ADR-0013 addendum + Charter 23.2 v2 marker update (1-2h)
8. Codex peer review chain + merge (1-2h)

**Yol A full** (16-24h): + `can_publish` source service authority + external recipient policy

---

## 4. Sıra Önerisi (Codex)

**M3-supplement / "23.2 v2 OpenFGA model extension" — M3 closure ile paralel**.

R2 KVKK legal external bağımlı **değil** (ayrı yüzey). M3 core "R2 external pending" kalabilir; bu iş hemen başlatılabilir.

Final production-ready / D29-Authorized full Zanzibar-ready claim için **M3-supplement evidence şart**:
- `NOTIFY_AUTHZ_ENABLED=true` LIVE
- 3-channel allow case **DELIVERED** + deny case **BLOCKED_BY_AUTHZ** evidence

---

## 5. Implementation Sprint Plan (Sonraki Agent için)

### Phase 1 — Model + Seed (4-6h)
1. OpenFGA authorization model JSON draft (`docs/notify/openfga-notification-model.dsl`)
2. Model write API: `POST /stores/{store_id}/authorization-models`
3. Yeni MODEL_ID Vault'a yaz (`kv/platform/openfga/model_id`) + ESO sync
4. permission-service pod restart + new model_id verify
5. Test tuple seed: `subscriber:1299 → can_receive → notification_topic:test.d29.email`
6. OpenFGA check API test (allow case + deny case manual)

### Phase 2 — Backend Integration (3-5h)
7. AuthzClient `notification_template` object_type compatibility (backwards compat dual-check)
8. Backend test deploy + smoke
9. Notify intent submit allow + deny live evidence

### Phase 3 — Governance (3-5h)
10. ADR-0013 addendum (notification model extension decision)
11. Charter 23.2 v2 marker entry
12. Tuple seed runbook (`docs/runbooks/RB-notify-openfga-tuple-seed.md`)
13. Codex peer review chain + merge + drift verify

---

## 6. Out-of-scope (Bu plan-time doc için)

- Model write/seed implementation — Phase 1 ayrı PR
- Backend code update — Phase 2 platform-backend repo
- Production cluster (k3d-prod) notification authz — pre-prod test cluster verify sonrası
- External recipient (email → opaque ID) authz tuple seed strategy — separate design Phase 1+ scope

---

## 7. Cross-AI

Implementer AI: Claude
Reviewer AI: Codex
Codex thread: 019e2651-749f-71b1-a72a-578a290cb5c5
Verdict: AGREE
Absorb edilen düzeltmeler: Yol A model refinement (`notification_template` over `template`); topic-based inheritance pattern; per-template grant YASAK governance discipline; M3-supplement parallel R2 KVKK independent; effort 10-16h minimal v2 vs 16-24h full

---

## 8. Karar (tek cümle)

OpenFGA notification model extension — **Yol A** (mevcut `erp-stage` store + authorization model revision); 4-type extension (`subscriber`, `notification_topic`, `notification_template`, `service_account`) + topic-based inheritance pattern; **10-16h minimal v2** effort; M3-supplement parallel (R2 independent); implementation ayrı sprint Phase 1/2/3 sequence.
