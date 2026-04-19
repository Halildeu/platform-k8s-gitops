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
