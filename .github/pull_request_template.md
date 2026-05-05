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

## Kontrol Listesi

- [ ] **D29 3-katman:** Değişim Up / Functional / Zanzibar-ready katmanlarının hangisini etkiler?
- [ ] **D30 immutable:** Image tag değişimi varsa `sha-<short>` (moving tag YASAK)
- [ ] **D30 atomic cutover:** selfHeal=false prod Application bozulmadı mı?
- [ ] **D17 scale-to-zero:** Overlay test replicas=0 patch korundu mu (selective apply)
- [ ] **No-closure language:** "kapandı/bitti/gün sonu/pause" yok (CI check)
- [ ] **IP sanitize:** Dış kullanıcı-facing response/doc'ta iç ağ IP yok
- [ ] **Handoff update:** Büyük delta ise `docs/session-handoff-<latest>.md` güncel

## Codex İstişare (plan-time adversarial review)

- [ ] Codex plan-time review yapıldı — Thread: `<id>`
- [ ] VERDICT: AGREE / PARTIAL / REVISE / RED
- [ ] Absorb edilen düzeltmeler: `<liste>`

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
