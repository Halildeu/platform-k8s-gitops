# Faz 22.2 Trusted Signing Onboarding (Operator Infrastructure Prep Checklist)

> **Status**: DRAFT — Operator infrastructure prep checklist; agent docs-only (Azure/GitHub/cert/timestamp/RBAC setup operator-side, agent dokunmaz)
> **Scope**: Faz 22.2.A non-domain Windows pilot (A2 BYOD + A3 Entra-joined + A4 Workplace-registered) için Authenticode signed binary distribution prerequisite. A1 lab cihazları için time-boxed unsigned exception kabul edilebilir (RB-faz22-non-domain-windows-pilot.md §7.3).
> **Tracked by**: ADR-0012-EA "22.2 pre-req docs (22.1'de hazırlanır)" section (7-item Codex iter-3 PR-8d/PR-8e) + RB-faz22-non-domain-windows-pilot.md §7 Signed Distribution Policy
> **TRACKING-ROADMAP refs**: AG-018 trusted signing pipeline (TODO) + AG-024 Signed update manifest verification (TODO)
> **Codex strategic thread**: `019e5b38-cce8-71b3-ad84-07de7e99ab7a` REVISE iter-1 with `ready_for_impl=true` for docs-only operator infrastructure prep checklist
> **Hard constraint**: Azure RBAC, GitHub OIDC, certificate profile, timestamp endpoint **operator/security/Azure tenant admin tarafı**; agent dokunmaz (no credential, no RBAC mutation, no cert/key generation, no operator action).

---

## 1. Amaç

Faz 22.2.A non-domain Windows pilot ile A2 BYOD + A3 Entra-joined + A4 Workplace-registered tier'larda Authenticode signed binary distribution **prerequisite gate**'ini operator infrastructure prep checklist olarak dokümante etmek. ADR-0012-EA "22.2 pre-req docs" 7 item'ı operator action plan halinde sıralar.

**Codex `019e5b38` Q7 önerisi**: bu doküman **operator infrastructure prep checklist** olarak kalır; agent Azure RBAC, GitHub OIDC, certificate profile veya timestamp endpoint kurmuş gibi yazmaz.

## 2. ADR-0012-EA 7-Item Operator Checklist

### Item 1 — Azure Trusted Signing Onayı

**Sorumluluk**: Azure tenant admin + security architect + DPO/legal (corporate policy)
**Agent**: docs-only (referans)

**Adımlar**:
- [ ] Azure Trusted Signing (Microsoft) hizmetinin kurum Azure tenant'ında **enable** edilmesi
- [ ] Tenant admin onayı (Microsoft Entra ID admin role gerek)
- [ ] Faturalandırma / subscription planı (Trusted Signing pay-as-you-go veya Reserved)
- [ ] Hizmet bölge seçimi (örn. West Europe, East US — corporate data residency uyumu)
- [ ] Service terms acceptance + compliance review (DPO + legal)

**Referans**: https://learn.microsoft.com/en-us/azure/trusted-signing/

**Status (2026-05-24)**: ⏳ pending (operator/security action)

### Item 2 — CI Auth Modeli (GitHub OIDC + Workload Identity)

**Sorumluluk**: GitHub repo admin + Azure RBAC admin
**Agent**: docs-only (referans)

**Adımlar**:
- [ ] GitHub Actions `azure/login@v2` action ile OIDC workload identity federation kurulumu
- [ ] Azure App Registration (workload identity) oluşturma
- [ ] Federated credential GitHub repo + branch + environment için (örn. `repo:Halildeu/platform-agent:ref:refs/heads/main`)
- [ ] **Uzun ömürlü secret YOK** — sadece short-lived OIDC token (HARD constraint per ADR-0012-EA pre-req item 2)
- [ ] Azure RBAC role assignment workload identity için (Trusted Signing Certificate Profile Signer role)
- [ ] GitHub repo Actions secret/variable seti: `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID` (no client_secret)

**Referans**: https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/configuring-openid-connect-in-azure

**Status (2026-05-24)**: ⏳ pending (operator/GitHub admin action)

### Item 3 — Certificate Profile (Subject Metadata + OID + EKU)

**Sorumluluk**: Security architect + Azure Trusted Signing admin
**Agent**: docs-only (referans)

**Adımlar**:
- [ ] Certificate profile oluşturma (Azure Trusted Signing portal)
- [ ] **Subject metadata** (issuer alanları):
  - `CN`: corporate name (örn. `Halildeu Endpoint Agent`)
  - `O`: organization name
  - `L`: locality
  - `S`: state
  - `C`: country (e.g. `TR` for Turkey)
- [ ] **Object Identifier (OID)**: KVKK + sektör uyumu için corporate-specific veya Microsoft default
- [ ] **Extended Key Usage (EKU)**: `1.3.6.1.5.5.7.3.3` (Code Signing); endpoint-agent.exe için yeterli
- [ ] Certificate validity period: typical 1-3 yıl (renewal plan documented)
- [ ] Backup/recovery key management: HSM-backed (Microsoft Azure Key Vault Managed HSM) önerilen

**Referans**: https://learn.microsoft.com/en-us/azure/trusted-signing/concept-trusted-signing-cert-profiles

**Status (2026-05-24)**: ⏳ pending (operator/security action)

### Item 4 — RFC 3161 Timestamp Endpoint

**Sorumluluk**: Security architect (sağlayıcı seçimi)
**Agent**: docs-only (referans)

**Adımlar**:
- [ ] Timestamp authority (TSA) seçimi:
  - **Option A**: Azure Trusted Signing default TSA (Microsoft) — RFC 3161 compliant, ücretsiz
  - **Option B**: DigiCert TSA (`http://timestamp.digicert.com`)
  - **Option C**: Sectigo / Comodo TSA
  - **Option D**: Corporate internal TSA (varsa)
- [ ] TSA URL'nin signing pipeline'da kullanılması:
  ```
  signtool sign /fd SHA256 /tr <TSA_URL> /td SHA256 /a endpoint-agent.exe
  ```
- [ ] TSA reachability test (signing pipeline CI hat'ında)
- [ ] Backup TSA (primary fail durumunda)
- [ ] TSA audit log retention (compliance — TSA tarafında)

**Referans**: RFC 3161 — Internet X.509 Public Key Infrastructure Time-Stamp Protocol (TSP)

**Status (2026-05-24)**: ⏳ pending (operator/security action)

### Item 5 — Azure RBAC Role Assignments

**Sorumluluk**: Azure tenant admin + RBAC admin
**Agent**: docs-only (referans)

**Adımlar**:
- [ ] **Trusted Signing Identity Verifier** role (org-wide; identity verification approval)
- [ ] **Trusted Signing Certificate Profile Signer** role (per certificate profile; signing operation)
- [ ] Role assignments scope:
  - **Workload identity (GitHub OIDC App Registration)**: `Trusted Signing Certificate Profile Signer`
  - **Security architect / signing approval role**: `Trusted Signing Identity Verifier`
  - **Audit reviewer**: `Reader` (Trusted Signing audit log access)
- [ ] Periodic RBAC review (quarterly; access right minimization)
- [ ] Just-in-time (JIT) elevation for sensitive operations (PIM kullanımı önerilen)

**Referans**: https://learn.microsoft.com/en-us/azure/trusted-signing/how-to-signing-account-role-assignments

**Status (2026-05-24)**: ⏳ pending (operator/security action)

### Item 6 — Release Promotion Modeli (Lab → IT Pilot Signed)

**Sorumluluk**: CI/CD admin + release manager
**Agent**: docs-only (referans + artifact naming)

**Adımlar**:
- [ ] Artifact naming convention:
  - **Lab ephemeral** (22.1 lab + 22.2.A A1 lab cihazları): `endpoint-agent-lab-<sha>.exe` (unsigned veya self-signed lab-only cert)
  - **IT pilot signed** (22.2.A A2/A3/A4 + 22.2.B + 22.3 restricted): `endpoint-agent-signed-<version>.exe` (Authenticode + RFC 3161 timestamp)
  - **Production** (22.2.A geniş kapsam + 22.3 production): `endpoint-agent-prod-<version>.exe` (Authenticode + EV cert + extended audit)
- [ ] Tag scheme:
  - Lab: `lab/<branch>/<sha>`
  - IT pilot: `pilot/v<major>.<minor>.<patch>`
  - Production: `prod/v<major>.<minor>.<patch>`
- [ ] Release pipeline gate:
  - Lab → IT pilot: trusted signing pipeline + signed artifact verify (`signtool verify /pa`)
  - IT pilot → production: full release approval + extended audit + EDR allowlist coordination
- [ ] Artifact storage:
  - Lab: GitHub Actions artifact (14 gün retention)
  - IT pilot: GitHub Releases (corporate access)
  - Production: GitHub Releases + Azure Blob Storage backup (long-term retention)

**Referans**: ADR-0012-EA "22.2 pre-req docs" item 6 + RB-faz22-non-domain-windows-pilot.md §7

**Status (2026-05-24)**: ⏳ pending (operator/CI admin action)

### Item 7 — Trusted Signed Artifact Olmadan EndpointPilot Dışı Yok Invariant

**Sorumluluk**: ADR governance + operator policy
**Agent**: docs-only (invariant statement)

**Invariant statement**:

> **22.2 Trusted Signing Invariant** (ADR-0012-EA pre-req item 7):
> A2 BYOD + A3 Entra-joined + A4 Workplace-registered + 22.2.B `acik.local` IT pilot + 22.3 restricted production cihazları için **Authenticode trusted signed artifact olmadan kurulum YASAK**.
>
> İstisna **sadece**:
> - 22.1 lab evidence cihazları (Parallels W11 lab)
> - 22.2.A A1 standalone lab cihazları (mevcut HALILKOOLUB735 + 2 fresh Parallels VM per A1 multi-VM issue #1044)
>
> Lab exception **time-boxed + SHA-pinned** (RB-faz22-non-domain-windows-pilot.md §7.3 template; max 30 gün; yenileme yeni evidence + ADR review).

**Status (2026-05-24)**: Invariant statement documented; enforcement gate = AG-024 (Signed update manifest verification) MERGED + release promotion gate active. AG-024 backend MERGED öncesi operator manual enforcement.

## 3. Implementation Sequencing

ADR-0012-EA "22.2 pre-req docs" items'ın sıralı infaz akışı:

```
Item 1 (Azure Trusted Signing onaylı)
  ↓
Item 5 (Azure RBAC role assignments)
  ↓
Item 3 (Certificate profile setup)
  ↓
Item 4 (Timestamp endpoint seçimi)
  ↓
Item 2 (GitHub OIDC + workload identity federation)
  ↓
Item 6 (Release promotion modeli — artifact naming + tag scheme + storage)
  ↓
Agent CI pipeline integration (AG-018 implementation — TODO)
  ↓
Item 7 (Trusted signed invariant enforcement — AG-024 implementation TODO)
  ↓
A2/A3/A4 pilot acceptance unlock
```

## 4. Operator Action Checklist (Top-Level)

| Item | Status | Owner | Effort |
|---|---|---|---|
| 1. Azure Trusted Signing onaylı | ⏳ pending | Azure tenant admin + security | 0.5-2 gün (approval timeline) |
| 2. CI Auth (GitHub OIDC) | ⏳ pending | GitHub admin + Azure RBAC | 0.5-1 gün |
| 3. Certificate profile | ⏳ pending | Security architect | 0.5-1 gün |
| 4. Timestamp endpoint | ⏳ pending | Security architect | 0.5 gün |
| 5. Azure RBAC role assignments | ⏳ pending | Azure tenant admin | 0.5 gün |
| 6. Release promotion modeli | ⏳ pending | CI/CD admin + release manager | 1-2 gün (artifact naming + tag + storage) |
| 7. Trusted signed invariant doc | ✅ documented (this doc) | Agent docs-only | done |

Toplam operator effort: ~3-7 gün (Azure approval timeline dahil)

## 5. Boundary (HARD)

- **DRAFT only** — operator/security/Azure tenant admin review required before infrastructure prep
- **Agent docs-only** — Azure RBAC, GitHub OIDC, certificate profile, timestamp endpoint setup **operator-side**; agent dokunmaz (no credential, no RBAC mutation, no cert/key generation)
- **No actual Azure tenant id / subscription id / certificate thumbprint** in this template (placeholders only)
- **AG-018 + AG-024 backend gate** — backend trusted signing pipeline implementation + signed manifest verification TRACKING-ROADMAP backlog TODO; operator infrastructure prep prerequisite
- **A1 lab exception** — `RB-faz22-non-domain-windows-pilot.md §7.3` time-boxed SHA-pinned unsigned exception (30 gün max)
- **NOT prod-ready** — pilot infrastructure prep only; production deployment ayrı release pipeline + EV cert + extended audit

## 6. Tracked by

- ADR-0012-EA "22.2 pre-req docs" section (7 item canonical)
- RB-faz22-non-domain-windows-pilot.md §7 Signed Distribution Policy
- gitops PR #1043 RB MERGED `47fca508`
- AG-018 trusted signing pipeline (TRACKING-ROADMAP TODO)
- AG-024 Signed update manifest verification (TRACKING-ROADMAP TODO)
- 22-2-byod-consent-template.md (BYOD consent paralel)
- 22-2-kvkk-data-inventory.md (KVKK paralel)
- Codex strategic `019e5b38` Q7 trusted signing onboarding absorb
