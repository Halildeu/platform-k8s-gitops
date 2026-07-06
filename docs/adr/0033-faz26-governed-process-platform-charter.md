# ADR-0033 — Faz 26 Governed Process & Work Platform: Charter, Topology & Isolation

> **Status**: ACCEPTED (2026-06-30) — Cross-AI consensus: Codex `019f180a` (strateji 3-iter AGREE) + `019f18f8` (foundation AGREE) + owner onayı. Mavis (MiniMax) kanal 401-down, non-blocking (Cross-AI minimumu Anthropic+OpenAI ile karşılandı).
>
> **Scope**: Faz 26 = yeni **bağımsız ürün**. ADR-0002 (dual-cluster), ADR-0031 (Faz 24 two-server) **supersede edilmez**; bu karar Faz 26 için scoped. Faz 1-25 ile **karışmaz** (kullanıcı HARD RULE: "diğer fazlarla karışmamalı").

---

## Context

Owner, mevcut platform (on-prem K8s, OpenFGA/Vault/WORM/ollama/Workcube/Keycloak/GitOps) üstüne **yeni bağımsız bir ürün** istiyor: on-prem, KVKK-uyumlu, izin-farkında, AI-native **süreç-merkezli entegre yönetişim + work platformu** (tek bağlı graph; süreç↔risk↔kontrol↔KPI↔doküman↔görev↔çerçeve; any-entry pivot; "çiçek" UX). İlk dikey = TR kamu/regüle holding iç-kontrol + KVKK + kanıt yönetimi. Detay: `docs/faz-26-governed-process-platform-plan.md`.

## Decision

1. **Bağımsız ürün + izolasyon (HARD)**: ayrı namespace (`platform-gp-{test,prod}` öneri) · ayrı board (**GitHub Project #7**) · ayrı ADR serisi (0033+) · ayrı OpenFGA store · ayrı WORM bucket · ayrı Vault path. Faz 1-25 ile kod/namespace/board/store düzeyinde karışmaz.

2. **Repo stratejisi = A (Faz 24 precedent)**: yeni servisler **mevcut repolarda**, izolasyon namespace/board/store seviyesinde:
   - `gp-core-service` → **platform-backend** (graph/governance/evidence/execution; enforcement kernel)
   - `gp-ai-service` → **platform-ai** (RAG/IDP/PII; on-prem)
   - `mfe-gp` → **platform-web** (MF host + AG-Grid reuse)

3. **Minimal yeni servis (anti-duplikasyon)**: yalnız `gp-core` + `gp-ai` + `mfe-gp`. import = gp-core içinde modül (ayrı servis değil, MVP). governance/work/workflow faz büyüdükçe modül→servis ayrışır (gün-1 sprawl YASAK).

4. **Reuse (sıfır yazım)**: OpenFGA/permission-service (izin) · Vault/ESO · 7-yıl WORM/audit (ADR-0042) · Keycloak+M365 SSO · notification-orchestrator · **report-service** (raporlama) · **schema-service** (Workcube import keşfi) · **AG-Grid Enterprise** (grid — yeni grid kütüphanesi YASAK) · ollama/whisper · GitOps/ArgoCD.

5. **Topoloji**: gp-ai on-prem compute (ollama) **paylaşılan GPU host** üzerinde (ADR-0031 two-server deseni reuse); gp-core/mfe orchestration plane. Cross-server gerekirse mTLS/WireGuard (ADR-0031).

6. **Faz dizisi**: 26A→26B→27 (public release=26B+27)→28→29→30→31→32 (her faz releasable; plan §5).

7. **Desktop/mobil**: ilk release'de YOK; platform-desktop/mobile scaffold (Faz 24) reuse, ihtiyaç doğunca (Faz 29+/32+).

## Consequences

- ✅ Reuse-ağırlıklı → Faz 26A büyük ölçüde "bağla/uyarla". Mükerrer servis yok.
- ✅ İzolasyon → Faz 1-25 etkilenmez; ürün ayrı satılabilir/paketlenebilir.
- ⚠️ Paylaşılan GPU host + SSO + GitOps = tek nokta; kapasite/erişim koordinasyonu gerek.
- ⚠️ Repo-A → platform-backend/ai/web içinde Faz-26 modülleri governance label/dizin ile net ayrılmalı (karışmama).

## References
- Plan: `docs/faz-26-governed-process-platform-plan.md` · Acceptance: `docs/faz-26-26b-27-acceptance.md` · Ontology v2: `docs/faz-26-ontology-v1.md` · Build order: `docs/faz-26-gp-core-build-order.md`
- İlişkili ADR: 0034 (KVKK/data), 0035 (permission enforcement), 0002/0031/0042 (reuse)
- Cross-AI: Codex `019f180a` + `019f18f8`
