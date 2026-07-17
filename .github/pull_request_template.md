## Özet

<!-- 1-2 cümle: ne değişti ve neden -->

## Tip

- [ ] feat — yeni özellik/manifest/runbook
- [ ] fix — bug/drift düzeltme
- [ ] refactor — pattern değişim (kustomize/overlay/ESO)
- [ ] docs — runbook/handoff/plan
- [ ] chore — CI/config/dependency

## Kapsam

- [ ] Kustomize base değişim (dikkat: tüm overlay'lere yansır)
- [ ] Overlay-specific (test/prod/eso)
- [ ] Helm values (ingress-nginx/argocd/monitoring/loki/tempo/external-secrets)
- [ ] ArgoCD Application CR
- [ ] Monitoring (PrometheusRule/Probe/Grafana dashboard/Recording rules)
- [ ] Bootstrap script (install-*, apply-*, exporter)
- [ ] Dokümantasyon (runbook, handoff, plan)

## Test Planı

<!-- Nasıl doğrulanacak? Build sanity / cluster apply / smoke -->

- [ ] `kubectl kustomize <path>` build PASS (değişen path için)
- [ ] Shell scripts `shellcheck` temiz (varsa)
- [ ] YAML lint temiz (CI otomatik)
- [ ] Runbook referans güncellendi (varsa)
- [ ] PLAN.md D-karar kaydı (mimari değişim ise)

## Operational urgency

> **DiD-1 SLA monitor entegrasyonu**: bir PR prod-overlay'i değiştirecekse ve
> incident veya time-sensitive hotfix ise `Critical-Fix: yes` koyun. Otomatik
> olarak `critical-fix` label uygulanır ve `critical-fix-sla-monitor.yml`
> cron'u prod-deploy lag'ini izler (1h warning, 4h tracking issue). Detay:
> `docs/runbooks/RB-critical-fix-sla-monitor.md`.
>
> Default `no` — yalnız hotfix sınıfı PR'lar için `yes` koyun. Operator
> manuel label'lama da hâlâ geçerli; bu trailer ek-otomasyon, replacement değil.

```yaml
Critical-Fix: no
# Source-Fix: <Halildeu/platform-web#640>          # opsiyonel, follow-up scope
# Expected-Prod-SLA: 4h                            # opsiyonel, default 4h
```

## Kontrol Listesi

- [ ] **D29 3-katman:** Değişim Up / Functional / Zanzibar-ready katmanlarının hangisini etkiler?
- [ ] **D30 immutable:** Image tag değişimi varsa `sha-<short>` (moving tag YASAK)
- [ ] **D30 atomic cutover:** selfHeal=false prod Application bozulmadı mı?
- [ ] **D17 scale-to-zero:** Overlay test replicas=0 patch korundu mu (selective apply)
- [ ] **No-closure language:** "kapandı/bitti/gün sonu/pause" yok (CI check)
- [ ] **IP sanitize:** Dış kullanıcı-facing response/doc'ta iç ağ IP yok
- [ ] **Handoff update:** Büyük delta ise `docs/session-handoff-<latest>.md` güncel

## Cross-AI Peer Review (HARD RULE — provider seviyesinde)

> **ZORUNLU** (V2.1-GOV-1): Code yazan AI sağlayıcı (provider) ≠ Reviewer sağlayıcı. Aynı sağlayıcının farklı session/subagent'i de YASAK. CI gate `gate-cross-ai-audit` aşağıdaki structured field'ları validate eder.
>
> Detay: `docs/performance/PERF-INIT-V2-prod-readiness-v9.1.md` §7.

```yaml
# Cross-AI structured field enum — CI parser bu blok'u okur (## Cross-AI heading altı, scoped)
Implementer AI:   Claude
Reviewer AI:      Codex
Codex thread:     019eXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX
Verdict:          AGREE
Verdict reason:   <1-2 cümle>
Same-provider exception: N/A
# Exception reason: <≥10 karakter — sadece "Same-provider exception: user-explicit-approval" durumunda zorunlu>
# Cross-AI exempt reason: <≥10 karakter — sadece "Codex thread: N/A" durumunda zorunlu, örn. "docs-only handoff PR, no code change">
Absorb edilen düzeltmeler: <liste veya N/A (AGREE initial verdict)>
Consultation commit: <40-char exact PR HEAD SHA>
Claude receipt: provider=anthropic; requested=claude-opus-4-8; actual=claude-opus-4-8; verdict=AGREE; ref=<session-or-evidence>
MiniMax receipt: provider=minimax; requested=minimax/MiniMax-M3; actual=minimax/MiniMax-M3; verdict=AGREE; ref=<session-or-evidence>
Codex receipt: provider=openai; requested=gpt-5.6-sol; actual=gpt-5.6-sol; verdict=AGREE; ref=<session-or-evidence>
```

**Field semantik** (Codex `019e2693` REVISE absorb):
- `Implementer AI` / `Reviewer AI`: known-canonical providers `Claude` / `Codex` / `Gemini` / `Other` (alias tolerance: `Anthropic Claude`, `OpenAI Codex`, `Google Gemini`)
- `Consultation commit`: PR'ın exact 40-karakter head SHA'sı; üç receipt aynı head'i incelemelidir.
- `Claude/MiniMax/Codex receipt`: exact provider + requested/actual model + `AGREE` + denetlenebilir session/evidence referansı. Eksik, mismatched veya non-`AGREE` receipt fail-closed'dur.
- Implementer ile aynı provider'ın receipt'i zorunlu challenger'dır ancak bağımsız reviewer sayılmaz; `Implementer AI` / `Reviewer AI` provider ayrımı ayrıca korunur.
- `Codex thread`: full UUID (kısa hash YASAK); `N/A` sadece **`Cross-AI exempt reason:`** field dolu ise (docs-only/governance exempt durumlarda)
- `Same-provider exception: user-explicit-approval` → zorunlu **`Exception reason:`** field (≥10 karakter, commit/comment evidence link)
- `-` alias YASAK; explicit `N/A` + reason field zorunlu

## Referans

- İlgili PLAN.md D-kararlar: `<D<N>>`
- Runbook referans: `<docs/...>`
- Dev repo bağımlılık (platform-ssot): `<PR # veya YOK>`
- Ops bağımlılık (Vault/sysadmin): `<varsa>`

## Boundary declaration (ADR-0011 §2.3)

> **ZORUNLU**: `gate-pr-boundary-declaration` CI gate (BG-1) bu blok'un eksiksiz doldurulmasını ister. En az bir madde işaretli olmalı; `none of the above` işaretli ise diğer 6 işaretsiz olmalı. credential-read/write/state-mutation (production)/boundary-cross/user-communication işaretli ise PR'a `user-approval-required` label eklenmeli ve User-approval evidence link verilmelidir. Detay: `docs/RB-adr-0011-bg-1-pr-boundary-declaration.md`.
>
> Boundary guidance + 3 gray-area kararı: `docs/RB-adr-0011-bg-2-sandbox-blocking-playbook.md` (BG-2 playbook).
>
> **`user-communication`** (ADR-0013 D45 BG-NOTIFY-1): Notification orchestration prod template/workflow/audience/provider değişikliği — blast radius (kaç kullanıcıya gider) + sample render + recipient class + opt-out effect + rollback strategy zorunlu.

This PR includes:

- [ ] credential-read
- [ ] credential-write
- [ ] state-mutation (test cluster)
- [ ] state-mutation (production)
- [ ] boundary-cross
- [ ] user-communication
- [ ] none of the above (Codex consensus only)

User-approval evidence: `<link veya N/A — N/A sadece "none of the above" için kabul edilir>`
