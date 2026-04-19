# Dev Repo Handoff Bundle — platform-ssot (Zanzibar-25 ardıl)

> **Source:** K8s-6 Seviye 1 + Seviye 2 scope (2026-04-19)
> **Target:** platform-ssot session / ops / CI
> **Format:** 3 bağımsız iş — her biri ayrı PR veya paralel yürütülebilir
> **Priority sırası:** S2-B3 (P1, D29 blocker) → S1-B2 (P1 paralel, drift) → S2-B (P1, D30 uyum)

---

## 1. Özet Tablo

| ID | İş | Scope | Blocker mı | Referans doküman |
|---|---|---|---|---|
| **S2-B3** | Keycloak `smoke-client` confidential client | Realm config + Vault seed | ✅ D29 Zanzibar-ready full acceptance | [handoff-smoke-client-keycloak.md](handoff-smoke-client-keycloak.md) |
| **S1-B2** | auth-service `application-k8s.yml` hardcoded NS default fix | 2 default URL → shortname | ❌ ConfigMap override maskeliyor | [handoff-auth-hardcoded-ns-fix.md](handoff-auth-hardcoded-ns-fix.md) |
| **S2-B (W1+W3)** | ghcr-pull ESO + digest pin CI | ExternalSecret + deploy-backend.yml revize | ⚠ D30 HARD RULE full uyum | [handoff-S2-B-artifact-hardening.md](handoff-S2-B-artifact-hardening.md) |

**Codex apply-order uzlaşısı (FR2):** ESO path/AppRole ops + smoke-client paralel → shortname refactor apply → ArgoCD. "Aynı pencereye çok iş yığma."

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

### 2.2 — S1-B2 auth-service hardcoded NS default

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

### 2.3 — S2-B (W1 ESO + W3 digest pin CI)

```
TASK: S2-B Artifact Hardening (W1 ghcr-pull ESO + W3 digest pin CI)
From: K8s-6 Seviye 2 scope
Priority: P1 (D30 Immutable Artifact HARD RULE tam uyumu)

Detay: platform-k8s-gitops/docs/handoff-S2-B-artifact-hardening.md

Özet:
W1 — ghcr-pull Secret ESO ile Vault'tan auto-inject:
  - Vault path: kv/gitops/ghcr-token (username + password=PAT read:packages)
  - AppRole gitops-runtime read policy
  - K8s-6 repo zaten hazır: kustomize/base/eso/externalsecret-ghcr-pull.yaml
  - Bu PR'da iş: Vault path seed + AppRole policy + (eğer gerekirse) ESO
    ClusterSecretStore "vault-platform-gitops" tanımla

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
