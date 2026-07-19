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

## Cross-AI İstişare Modu

> Varsayılan `none`; kesin review yalnız ayrı bağlamdaki
> `codex exec --ephemeral --sandbox read-only` ile yapılır. Rutin review exact
> `gpt-5.3-codex-spark` + `xhigh`; governance/security/migration/production
> review exact `gpt-5.6-sol` + `xhigh` kullanır. Claude, MiniMax, Cursor, wrapper, başka
> provider/model ve AI uygulama penceresi receipt kanalı değildir.
> Detay: `docs/context-priority-rules.md` §11.

```yaml
# CI parser bu structured alanları ## Cross-AI altında okur.
Implementer AI: Codex
Consultation mode: none
Consultation reason: <neden none|single seçildi; en az 10 karakter>
# Consultation class: routine|high-impact # yalnız single; model seçimini bağlar
# Verdict: AGREE # yalnız single
# Consultation base tip: <single exact target tip>
# Consultation base: <single exact merge-base>
# Consultation commit: <single exact head>
# Consultation scope: <single content SHA-256>
# Codex receipt: provider=openai; requested=<scope-class exact model>; actual=<aynı exact model>; effort=xhigh; sandbox=read-only; ephemeral=true; base_tip=<sha>; base=<sha>; head=<sha>; scope=<sha256>; verdict=AGREE; ref=<owner evidence API ref>; sha256=<body sha256>
```

**Field semantik**:
- `none`: receipt yok; rutin implementation/test için somut gerekçe zorunlu;
  governance path, eksik changed-files veya `auto-promotion/` en az `single` ister.
- `single`: `Consultation class` zorunludur; `routine` exact Spark'a,
  `high-impact` exact SOL'a bağlanır. Bilinen governance/security/migration/
  production yollarında yalnız `high-impact` kabul edilir. Scope sınıfına uygun
  exact direct Codex model receipt'i + `xhigh` +
  read-only/ephemeral execution + exact base/head/scope + `AGREE`; bu kalite
  kapısı bağımsız-provider konsensüsü sayılmaz.
- Claude ve MiniMax receipt her modda fail-closed reddedilir.
- Provider çıktısı kullanıldıysa fetched evidence, freshness, response digest,
  exact model ve redaction kontrolleri fail-closed kalır.

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
