# Dev Repo Handoff Bundle — platform-ssot (Zanzibar-25 ardıl + ADR-0002 post-ESO)

> **Source:** K8s-6 Seviye 1 + Seviye 2 scope (2026-04-19) + ADR-0002 post-ESO-Faz-3
> **Target:** platform-ssot session / ops / CI
> **Format:** 4 bağımsız iş — her biri ayrı PR veya paralel yürütülebilir
> **Son güncelleme:** 2026-04-19 ESO Faz 3 canlı DONE sonrası (Codex PR #12 iter-3 REVISE)
> **Priority sırası:** S2-B3 (P1 D29 blocker) → S2-B4 schema build (P1 testai image gap) → S1-B2 (P1 paralel drift) → S2-B (W1 kapatıldı, W3 devam)

---

## 1. Özet Tablo

| ID | İş | Scope | Blocker mı | Referans doküman |
|---|---|---|---|---|
| **S2-B3** | Keycloak `smoke-client` confidential client | Realm config (backend/keycloak/exports/serban-realm.json) + Vault seed | ✅ D29 Zanzibar-ready full acceptance (testai allow probe) | [handoff-smoke-client-keycloak.md](handoff-smoke-client-keycloak.md) |
| **S2-B4** | schema-service immutable image build | Dev repo CI schema-service artifact push (sha-<new>) | ⚠ D30 HARD RULE ihlal (overlay hâlâ main-stable) | Aşağıda §2.2 |
| **S1-B2** | auth-service `application-k8s.yml` hardcoded NS default fix | 2 default URL → shortname | ❌ ConfigMap override maskeliyor | [handoff-auth-hardcoded-ns-fix.md](handoff-auth-hardcoded-ns-fix.md) |
| **S2-B (W1)** | ghcr-pull ESO | **KAPATILDI** k8s-gitops #11 merge | — | [handoff-S2-B-artifact-hardening.md](handoff-S2-B-artifact-hardening.md) |
| **S2-B (W3)** | digest pin CI (deploy-backend.yml) | 7 servis main-stable → sha-<short> auto-bump | ⚠ D30 HARD RULE long-term uyum | [handoff-S2-B-artifact-hardening.md](handoff-S2-B-artifact-hardening.md) §W3 |

**Codex apply-order uzlaşısı (FR2) + ADR-0002:** ESO path/AppRole ops + smoke-client paralel → shortname refactor apply → ArgoCD. "Aynı pencereye çok iş yığma."

**ADR-0002 post-Faz-3 net durum:**
- K8s-gitops ESO Faz 3 canlı (CSS Ready, 7 ES Synced, 10/10 pod Running)
- testai.acik.com D29 katman 1+2 (Up + Functional) ✓
- D29 katman 3 (Zanzibar-ready allow probe) **BLOCKED smoke-client (S2-B3)**
- Prod cutover (ai.acik.com) bu handoff kapandıktan sonra (ADR-0002 Faz F+G)

---

## 2. Kopyala-Yapıştır Prompt'lar

### 2.1 — S2-B3 smoke-client (en yüksek öncelik)

```
TASK: smoke-client Keycloak confidential client (K8s-6 S2 ilk blocker)
From: K8s-6 S1-E6 Codex tamamlanma review
Priority: P1 (D29 Zanzibar-ready full acceptance blocker)

Detay: platform-k8s-gitops/docs/handoff-smoke-client-keycloak.md

Özet: admin-cli direct_access_grants=false. Synthetic allow+deny smoke için
confidential client gerek. Keycloak realm serban içinde smoke-client (veya
canary-load birleşik) confidential + direct_access_grants + service_accounts.
Secret Vault'ta kv/platform/keycloak/smoke-client. Lokal realm export'a seed.

Kabul: curl -d grant_type=client_credentials + client_id + client_secret →
access_token → /variants (authenticated) 2xx, /variants (unauthorized) 403.

Not: Zanzibar-25 canary-load dedicated client varsa aynı kullanılabilir
(kontrol: directAccessGrantsEnabled=true + serviceAccountsEnabled=true).

Codex istişaresi: küçük scope, tek turlu consult yeterli.
```

### 2.2 — S2-B4 schema-service immutable image build (NEW)

```
TASK: schema-service immutable artifact gap kapanış
From: ADR-0002 ESO Faz 3 canlı sonrası (2026-04-19)
Priority: P1 (D30 HARD RULE ihlal; overlay hâlâ main-stable)

Bağlam:
- platform-k8s-gitops test overlay (kustomize/overlays/test/kustomization.yaml:42-48)
  7 servis sha-3923901 (immutable), AMA schema-service hâlâ `main-stable` (moving tag).
- Dev repo main branch'te schema-service'te son commit'ten beri değişiklik yok → CI
  skip yapıyor, sha-<short> image yaratmıyor.
- Cutover öncesi D30 uyum için schema-service'in de immutable tag'i olmalı.

Yapılacak:
1. platform-ssot/backend/schema-service'te trivial bir no-op change yap
   (örn. README.md güncellemesi veya version comment)
2. main branch'e merge et → CI otomatik build + GHCR push (sha-<new-short>)
3. k8s-gitops repo'ya PR: overlays/test/kustomization.yaml schema-service
   newTag: main-stable → sha-<new-short>
4. Apply + doğrulama (pod imageID == GHCR digest)

Beklenen output:
- GHCR: ghcr.io/halildeu/platform-ssot-schema-service:sha-<short>
- Canlı: schema-service pod imageID sha-<short> digest eşleşir

Codex istişaresi: ÇOK küçük scope, consult gereksiz; sadece CI doğrulama.
```

### 2.3 — S1-B2 auth-service hardcoded NS default

```
TASK: auth-service application-k8s.yml hardcoded NS default fix
From: K8s-6 session, retrospektif ping-pong Madde 1 uzlaşı
Priority: P1 paralel (küçük PR, K8s-6 Seviye 1 bloke etmez)

Referans dokümanı:
platform-k8s-gitops/docs/handoff-auth-hardcoded-ns-fix.md

Özet: backend/auth-service/src/main/resources/application-k8s.yml satır 99
civarı permission.service.base-url ve user.service.base-url default değerleri
hardcoded "http://permission-service.platform-prod.svc.cluster.local:8090"
(ve user eşdeğeri) var. Namespace-local shortname default'a çevrilmeli:
"http://permission-service:8090", "http://user-service:8089".

Drift gerekçesi: test namespace override olmazsa prod default devreye girer →
NXDOMAIN. Çift doğruluk kaynağı (dev repo default ≠ K8s ConfigMap override).

Teyit grep:
  grep -rn "platform-prod.svc.cluster.local" backend/*/src/main/resources/application-k8s.yml
K8s-6 tespiti: sadece auth-service'te; yine de grep çalıştır, başka servis
varsa aynı pattern'e çevir.

Kabul: grep sıfır "platform-prod.svc.cluster.local" fallback + mvn test PASS +
CI build + GHCR push yeni sha-<short> tag.

Codex istişaresi: küçük scope, tek turlu consult yeterli.
```

### 2.4 — S2-B W3 digest pin CI (W1 KAPATILDI)

```
TASK: S2-B W3 Digest Pin CI (W1 ghcr-pull KAPATILDI k8s-gitops #11 merge)
From: K8s-6 Seviye 2 scope + ADR-0002 post-Faz-3
Priority: P1 (D30 Immutable Artifact HARD RULE long-term uyum)

Not: W1 (ghcr-pull ExternalSecret) platform-k8s-gitops'ta canlı çalışıyor
(PR #11 merge sonrası CSS Ready + ghcr-pull Synced=True). Bu handoff
yalnız W3 için; W1 bölümünü SKIP et.

Detay: platform-k8s-gitops/docs/handoff-S2-B-artifact-hardening.md

Özet:
W1 — ghcr-pull Secret ESO ile Vault'tan auto-inject:
  - Vault path: kv/gitops/ghcr-token (username + password=PAT read:packages)
  - AppRole eso-runtime read policy (kv/data/gitops/ghcr-token)
  - K8s-6 repo hazır: overlays/test/eso + overlays/prod/eso (Codex iter-5
    Opsiyon B — workload ns, base/eso değil)
  - Bu PR'da iş: Vault path seed + AppRole policy

W3 — platform-ssot deploy-backend.yml her build sonunda K8s-gitops'a PR açmalı:
  - Her servis için "kustomize edit set image <svc>=...:sha-<short>"
  - Permission-service pilot pattern (sha-3923901); kalan 7 servis için yayma
  - Hedef: overlay test+prod 0 "main-stable" tag kalmalı
  - Opsiyonel ileriki iyileştirme: full digest pin (@sha256:...)

Kabul:
- kubectl -n platform-test get secret ghcr-pull (type docker-registry) VAR
- ExternalSecret Synced status
- Deploy-backend her run K8s-gitops'a commit/PR açıyor
- Overlay'de main-stable tag yok (sha-<short> tüm 8 servis)
- Pod imageID == GHCR digest (D30 PASS)

Codex istişaresi: Plan-time önerilir (ClusterSecretStore naming + refresh
interval + digest pin stratejisi sha-<short> vs @sha256:...).
```

---

## 3. Cross-Referans

- **K8s-6 thread:** `019d9a75-4299-7313-85bb-003a7de680eb`
- **K8s-6 PLAN.md:** 2026-04-19 entry (Seviye 1 deploy-sonrası + Seviye 2 scope)
- **K8s-6 ESO manifest hazır:** `kustomize/base/eso/` (3 dosya, apply S2-C1 pencere)
- **K8s-6 permission-service pilot tag:** `sha-3923901` (overlay test+prod, D30 kanıt)
- **Codex FR2 uzlaşı:** ESO + smoke-client paralel, shortname apply sonra, ArgoCD en son

---

## 4. K8s-6 ile Geri-Bağ

Her PR merge + CI yeni image tag push sonrası K8s-6 tarafı bilgilendirilir:
- **S1-B2:** auth-service yeni `sha-<short>` → overlay test+prod işlenebilir (opsiyonel, ConfigMap override zaten maskeliyor)
- **S2-B3:** smoke-client secret Vault'ta → K8s-6 S2-B3 acceptance smoke tuple B (authenticated allow) kanıtlanabilir
- **S2-B W1:** ESO Secret Synced → K8s-6 reschedule testi (GHCR pull kanıt)
- **S2-B W3:** Her PR auto-open → K8s-6 ArgoCD (S2-C1 sonrası) auto-sync

---

## 5. No Closure Rule

Bu handoff'lar "tamam bitti gün sonu" kapatma değil. K8s-6 paralel işler devam eder (ESO install, shortname apply, ArgoCD install, D32 staging-sw-2 bootstrap). Dev repo tamamlamaları K8s-6 ilgili fazlarının **kanıt** aşamasını açar, "bugün bitmiş" anlamına gelmez.
