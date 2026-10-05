# Faz 35 Etik Speak — prod activation overlay (INACTIVE SKELETON)

> ⚠️ **BU OVERLAY ROOT KUSTOMIZATION.YAML'DA DAHIL DEĞİLDİR.**
> `platform-prod` ArgoCD Application bu klasörü şu anda reconcile etmiyor.
> Aktivasyon **ES-311 imzalar + ES-312 pilot release gate** ile ayrı PR olarak
> yapılır.

## Ön koşullar (all-must-pass) — activation öncesi

Tüm bu koşullar sağlanmadan bu overlay `kustomize/overlays/prod/kustomization.yaml` resources listesine **EKLENMEZ**:

1. **ES-303**: Reveal API + WORM implementation `main`'e merge (Codex spawn task #378f775d).
2. **ES-306**: Backend security hardening — rate-limit + input sanitization + `hasAuthorization` empty-check fix (Codex spawn task #077fd546).
3. **ES-309**: Prod backup pipeline canlı + rehearsal başarılı.
4. **ES-311 7-imza pack** tamam:
   - Legal counsel + Privacy officer + Secret owner + Compliance officer + Business owner + Reveal Officer + Emergency contact.
5. **Prod provision scripts** çalıştı:
   - Prod PG + Vault + Keycloak + OpenFGA cell hazır.
   - `PENDING_FAZ35_PROD_*` placeholders bu dosyalarda **canlı değerlerle değiştirildi**.
6. **Prod image digest'leri** signed provenance ile hazır (test digest'leri prod-promote gate'siz kullanılamaz).
7. **ES-312 pilot release gate** owner-signed.

## Aktivasyon prosedürü

`docs/runbooks/RB-faz35-real-reporter-open.md` — 3-faz açılış rehberi.

Özetle:

1. Prod provision scripts (Vault + KC + OpenFGA) çalıştır → `PENDING_*` değerleri topla.
2. Bu overlay dosyalarındaki `PENDING_*` placeholder'ları **yeni PR** ile canlı değerlerle değiştir.
3. `kustomize/overlays/prod/kustomization.yaml` resources listesine `- activation/etik-speak` **ekle**.
4. PR merge + ArgoCD sync + smoke.

## Placeholder değerleri (aktivasyon PR'ında değiştirilir)

- `PENDING_FAZ35_PROD_VAULT_ROLE_ID` → `secretstore.yaml` — prod Vault AppRole role_id
- `PENDING_FAZ35_PROD_ETHICS_SERVICE_DIGEST` → `kustomization.yaml` — signed image sha256 (ghcr.io/halildeu/platform-backend-ethics-service)
- `PENDING_FAZ35_PROD_ETIK_SPEAK_PUBLIC_DIGEST` → `kustomization.yaml` — signed image sha256 (public web)
- `PENDING_FAZ35_PROD_ETIK_SPEAK_MANAGER_DIGEST` → `kustomization.yaml` — signed image sha256 (manager web)

`ethics-service-config.yaml` (base) içinde `ERP_OPENFGA_STORE_ID` + `ERP_OPENFGA_MODEL_ID` prod overlay'de override edilecek (base test store'a pinned).

## Kill-switch

`../deactivation/etik-speak/` — panic-off overlay (3 workload replicas=0 + public ingress kaldır). `RB-faz35-emergency-kill-switch.md` prosedürü.

## Host + servis contract

- `etik.acik.com` — canonical public reporter (byte-identical `speakup.acik.com` alias)
- `speakup.acik.com` — public reporter alias
- `ai.acik.com/ethic/` — staff manager UI (public prod host, canonical Acık suite)
- `ai.acik.com/api/v1/ethics/*` — staff case API

**Cookie boundary**: Public reporter host'ları `Domain=.acik.com` **KULLANMAZ**; `__Host-` prefix ile host-only. Suite session cookie'leri public host'lara akmaz.

**NetworkPolicy** — test overlay ile aynı isolation pattern; prod'da monitoring namespace + prod-specific ipBlock'lar (PG + Vault + KC container IP'leri prod'ta farklı).

## Referanslar

- `docs/faz-35-evidence/2026-07-21-e2e-smoke.md` — test cell canlı kanıtı
- `docs/faz-35-evidence/2026-07-21-es3-prep.md` — ES-3 hazırlık + gap analiz
- `docs/runbooks/RB-faz35-real-reporter-open.md` — go-live prosedür
- `docs/runbooks/RB-faz35-emergency-kill-switch.md` — panic-off
- `docs/runbooks/RB-faz35-incident-response.md` — SEV1/2/3 diagnostic
- `docs/runbooks/RB-faz35-legal-reveal-request.md` — reveal ceremony
- `docs/legal/faz35-privacy-notice-tr.md` — reporter aydınlatma
- `docs/legal/faz35-retention-policy.md` — retention + erasure
- Board: [Project #8](https://github.com/users/Halildeu/projects/8)
