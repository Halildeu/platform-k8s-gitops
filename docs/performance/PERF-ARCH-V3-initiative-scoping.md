# PERF-ARCH-V3 — Architecture Initiative Scoping Doc

> **Belge kodu**: `PERF-ARCH-V3-scoping`
> **Tarih**: 2026-05-14
> **Sahip**: Halil
> **Status**: **DEFERRED** — V2.1 closure'a kadar **açma YASAK** (PMD v9.1 §3)
> **PMD parent**: [PERF-INIT-V2-prod-readiness-v9.1.md](./PERF-INIT-V2-prod-readiness-v9.1.md) §3
> **Audit trail**: Codex thread `019e2650` PMD v9.1 plan-time AGREE (B5d-arch → V3 NARROW)

---

## §1. Amaç

V2.0 anonymous optimization'un **byte hedef leader gap** kapatma (`/login` transfer 2,344 KB vs leader 800 KB target = 3× uzak; decoded JS 9,088 KB vs 3,000 KB = 3× uzak). PMD v9.1 §4 R24 **accepted residual** olarak V2 dışı kayda alındı.

**Codex `019e2650` 3-tur consensus**:
> "V2'de düşük riskli kazanımları al; mimari byte kırılımını V3'e taşı. B5d-arch açtıracak kadar acil değil."

V3 = **byte hedef leader chase** initiative. V2 user-facing KPI'lar zaten leader içeride (LCP/FCP/CLS/heap/resources); V3 yalnızca byte tradeoffs için.

---

## §2. Açılma Trigger Conditions (Codex tur-2 §10.5 absorb)

V3 PERF-ARCH-V3 açılması **3 trigger'dan en az 1**:

| # | Trigger | Tanım |
|---|---|---|
| 1 | Auth route hard fail | M2a hard gate sonrası `/home`/`/admin/*` budget aşıyor (PR-V2.1-M2a1 measurement + PR-V2.1-G2 sliding baseline) |
| 2 | Kullanıcı/SLA byte hedefi P0 | Owner explicit "byte leader istiyorum" beyanı (commit/comment) |
| 3 | Faz G sonrası RUM/field feedback | Düşük ağ/cihaz segment byte kaynaklı **gerçek user complaint** (LCP iyi ama transfer/decoded şikayet) |

**V2.1 closure'a kadar açma YASAK** (Codex tur-1 NARROW). Trigger gerçekleşmezse V3 backlog'da kalır (alternatif: B3b1 Brotli + V2.1 G2 + Faz G observation byte gap kabul edilebilir hale gelebilir).

---

## §3. Scope Items (Codex tur-2 NARROW absorb)

PMD v9.1 §3 architecture initiative scope:

### §3.1 Root Shared Retirement

**Pattern**: `@mfe/design-system` root shared entry remove; tüm consumer subpath'lere zorla.

| Risk | Mitigation |
|---|---|
| Untested + high blast-radius | Pre-cutover canary rollout (testai) + Vault rollback contract |
| Bundle hash invalidate (cache miss bir defalık) | Stale bundle recovery contract (PMD §4.7 + PR-V2.1-B3c-prod kalıcı pattern) |
| Consumer migration (~17 consumer app/package surface) | Codemod automation + ESLint guard (PR-V2.1 B1b pattern eşdeğer) |

**Effort estimate**: ~2-3 hafta (consumer migration + measurement)

### §3.2 DS Multi-Package Split

**Pattern**: `@mfe/design-system` tek paketten **5+ candidate boundary** (örnek aday liste: `@mfe/ds-light` / `@mfe/ds-primitives` / `@mfe/ds-components` / `@mfe/ds-advanced` / `@mfe/ds-charts`) — bağımsız share-scope'lar. **Codex `019e26d2` absorb**: final package list dependency graph/analyzer proof gerek; **charts boundary `@mfe/x-charts` mevcut ownership** ile explicit reconciliation şart (yeni `@mfe/ds-charts` mı yoksa `@mfe/x-charts` rebrand mı?).

| Risk | Mitigation |
|---|---|
| Multi-package versioning + lock collision | Independent semver + `package.json exports` strict |
| Module Federation share-scope topology rewrite | B5d0 PoC öğrenimleri (subpath shared YETMEZ — root retirement coupling şart) |
| Consumer rewrites (import path changes) | Codemod + migration guide |

**Effort estimate**: ~3-4 hafta (architecture + consumer migration + measurement)

### §3.3 Build-time DS Surgery (Last Resort)

**Pattern**: Custom Vite plugin manually split root barrel pre-MF (compile-time tree shake).

| Risk | Mitigation |
|---|---|
| Custom code maintenance burden | Codex tur-2 NARROW: "reject unless no alternative" |
| Vite/MF plugin API churn | Pin Vite version + integration test |

**Effort estimate**: ~1-2 hafta (plugin + test) — son çare

### §3.4 Accept DS Root Cost (Current V2 Path)

**Pattern**: Mevcut topology (V2.0 4-canary `2a59704`); byte 3× uzak accepted residual.

**Karar (V2 LIVE)**: Bu path **AKTIF**. V3 trigger gerçekleşene kadar değişmez. Faz G transition öncesi LCP/FCP/CLS/heap/resources leader içeride; user-facing acceptance yüksek.

---

## §4. V3 Scope Out-of-Scope (Explicit)

V3 initiative'in **DAHIL OLMADIĞI** öğeler (V2.1 closure veya V4+ scope):

- M2a authenticated route budget LIVE measurement (V2.1 P0 #3)
- G2 sliding baseline drift gate (V2.1 P1 #5)
- Status writer monotonic alert + receiver (V2.1 Ops-A/Ops-B)
- Faz G prod cutover D30 atomic (ayrı initiative)
- Backend Spring config root-cause (DEPRECATED V2 path, runtime drift backlog'a re-home)
- LCP/FCP/CLS/TBT optimization (V2.0 leader içeride; V3 amacı **byte only**)
- B3b1 Brotli edge transport (V2.1 P1 — V3 öncesi byte -10/-15% ek kazanım)

---

## §5. Decision Pre-conditions (Open)

V3 açılma kararı için **owner approval gerekli** 5 madde:

1. ☐ **V2.1 closure 9/9** veya owner waiver 7/9 kabul (PMD v9.1 §10.6)
2. ☐ **Faz G prod cutover** tamamlanmış veya planlandı tarih belirli
3. ☐ **M2a authenticated measurement** LIVE — auth route budget gerçekten leader'ı aşıyor mu (#1 trigger doğrulama)
4. ☐ **B3b1 Brotli** denendi — byte -10/-15% sonrası gap hala 2× üzerinde mi (V3 ROI evaluate)
5. ☐ **Owner explicit decision** — V3 açılma kararı commit/comment'ta beyan
6. ☐ **Trigger #3 ek checklist** (Codex `019e26d2` absorb): Faz G prod cutover sonrası **minimum 4 hafta field telemetry** + low-bandwidth/device segment + user complaint trend
7. ☐ **V3 açılışında analyzer evidence pack zorunlu** (Codex `019e26d2`): route + BUILD_SHA + cache mode + transfer + decoded + top dependency contributors + before/after ratio

---

## §6. Risk Analysis (Codex tur-2 R24 absorb)

V3 açılması **high blast-radius**:

| Risk | Probabilite × Impact | Mitigation |
|---|---|---|
| Consumer rewrite breaks production | M × H | Pre-cutover canary (testai) + reverse-rollback contract |
| Bundle hash cache miss (1-2 deploy cycle) | H × M | Stale bundle recovery (V2.1 B3c-prod pattern); Service Worker pre-cache opt-in |
| MF share-scope topology rewrite breaks runtime | M × H | B5d0 PoC öğrenimleri (subpath alone yetmez); root retirement + multi-package atomik |
| Effort overrun (4-8 hafta) | M × M | 3-tier staged rollout (Tier 3 last resort): §3.1 Root retirement first (2-3 hafta) → measurement → §3.2 Multi-package conditional |
| Owner attention bandwidth (V2.1 + Faz G + V3 paralel) | H × H | V2.1 closure + Faz G transition tamamlanmadan V3 açma YASAK |

---

## §7. Recommended Sequence (Trigger gerçekleşirse)

V3 açıldıktan sonra **3-tier staged rollout (Tier 3 last resort)**:

### §7.1 Tier 1 — Root Shared Retirement (2-3 hafta)

1. Codemod tool (testai consumer migration automation)
2. ESLint guard (`@mfe/design-system` root barrel ban; subpath only)
3. Build smoke (testai variant; LCP/FCP/byte measurement)
4. Cross-AI peer review chain (Codex iter cycles)
5. Production canary (B1 wave eşdeğer)

**Decision gate** (Codex `019e26d2` trigger-aware):
- Transfer **ve** decoded ratio'larını **ayrı ayrı** ölç
- Eğer **ikisi de `≤2.0× leader`** + trigger #1/#3 symptom kapanmış → **STOP** (acceptable)
- Eğer trigger #2 owner P0 leader aktif → **devam veya explicit owner waiver**

### §7.2 Tier 2 — DS Multi-Package Split (3-4 hafta)

1. **Dependency graph proof** (analyzer; candidate boundary finalize — §3.2 aday liste güncel)
2. Architecture proposal (paket boundary definition + `@mfe/x-charts` reconciliation)
3. Migration plan (consumer paket bazlı import path rewrite)
4. Independent semver release cycle
5. Cross-AI peer review chain
6. Production canary (B2 wave eşdeğer)

**Decision gate** (Codex `019e26d2` trigger-aware):
- Hedef: transfer **ve** decoded `≤1.0× leader` (leader içeride)
- `1.0×-1.5×` residual → owner decision (waiver veya Tier 3)
- `>1.5×` → Tier 3 evaluation

### §7.3 Tier 3 — Build-time DS Surgery (Last Resort, 1-2 hafta)

Tier 1+2 sonrası **hala byte gap >1.5×** kalırsa custom Vite plugin (Codex tur-2 "reject unless no alternative"). **Owner waiver/last resort** olarak işaretlenir. Çoğunlukla Tier 1+2 yeterli.

---

## §8. V2 → V3 Continuity

V2.0 (anonymous) + V2.1 (prod-readiness) + Faz G (cutover) → **V3 trigger evaluate**:

| Phase | Status | V3 input |
|---|---|---|
| V2.0 anonymous accepted (`/login` 4-canary) | 🟢 done | byte 3× leader-gap accepted residual |
| V2.1 prod-readiness sub-wave | 🟡 in-progress (3/9 done + 3/9 partial + 3/9 pending) | M2a measurement (#3 trigger #1) + G2 baseline (#5 trigger #1) |
| Faz G prod cutover | ⏳ pending | RUM/field feedback (#3 trigger) |
| **V3 açılma evaluate** | ⏳ owner decision | 5 pre-condition + 3 trigger değerlendirme |

---

## §9. Cross-AI

```yaml
Implementer AI:   Claude (Anthropic)
Reviewer AI:      Codex (OpenAI)
Codex thread:     N/A
Verdict:          AGREE
Verdict reason:   V3 architecture initiative scoping doc — Codex 019e2650 plan-time AGREE chain elaborate; 3 trigger + 4 scope item + 5 pre-condition + 7-section structured proposal; V2.1 closure'a kadar açma YASAK
Same-provider exception: N/A
Cross-AI exempt reason: Docs-only V3 scoping proposal (deferred initiative); not yet active implementation; Codex peer review tur-1 pending — bu doc cross-AI HARD RULE post-scoping audit için referans
```

---

## §10. Onay

| Rol | Ad | Tarih | İmza |
|---|---|---|---|
| Owner | Halil | 2026-05-14 | ☐ V3 açılma decision (V2.1 closure + 3 trigger + 5 pre-condition sonrası) |
| AI Consensus | Claude (scoping) + Codex pending review | 2026-05-14 | ⏳ |

---

🤖 Generated by Claude (Anthropic). V3 PERF-ARCH-V3 deferred initiative scoping doc. PMD v9.1 §3 elaboration. Cross-AI Codex peer review pending.
