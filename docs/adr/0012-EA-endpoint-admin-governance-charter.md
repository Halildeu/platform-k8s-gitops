# ADR-0012-EA — Endpoint Admin Service Governance Charter

> **Status**: ACTIVE (5 clarify RESOLVED + 22.1 scope clarify 2026-05-02 PR-8c)
> **Date**: 2026-05-01 (draft) → 2026-05-02 (PR-8b fill-in + PR-8c clarify)
> **Sprint**: "Prod post-cutover compliance" PR-8 + PR-8b fill-in + PR-8c clarify
> **Codex thread**: `019dd895-17c1-79f0-b652-e316f64d4d79` (mutabakat raporu PR #270, iter-3 AGREE) + `019de00f-4b40-75c1-8ead-01b79c5819c1` (sprint review)
> **Provenance**: Cross-repo governance assessment `docs/2026-04-29-endpoint-admin-service-uyum-mutabakati.md` (962 satır, PR #270 merged) + 2026-05-02 kullanıcı fill-in (5 cevap) + 2026-05-02 PR-8c scope clarify
>
> **Konvansiyon**: ADR-0012 numarası mevcut ([@RequireModule WebMvcTest defer]); bu charter `0012-EA` (Endpoint Admin) namespace'i ile ayrı dosya.

## Bağlam

Faz 22 ile yeni domain: **Endpoint Admin** — Windows endpoint'lerin merkezi yönetimi (group policy push, command exec, audit, identity discovery). 4 component, 4 repo'ya yayılı; **runtime manifest tek yerde, source kod ilgili platform repolarında** (PR-8c clarify):

| Component | Repo | Path / Status |
|---|---|---|
| Backend service | `Halildeu/platform-backend` | `endpoint-admin-service/` sub-dir; **sıfırdan değil — BE-009 OpenFGA live gate + BE-013 maintenance token live gate kod-test ve gitops runtime kanıtları MEVCUT** |
| Agent | `Halildeu/platform-agent` | `/Users/halilkocoglu/Documents/platform-agent` lokal mevcut; GitHub remote oluşturma/push pending. **22.1 sıfırdan skeleton DEĞİL** — local state review + remote bootstrap + build/release pipeline hardening |
| Web UI MFE | `Halildeu/platform-web` | `apps/mfe-endpoint-admin/` (mevcut MFE convention); 22.2'de aktif iş |
| GitOps manifest | `Halildeu/platform-k8s-gitops` (bu repo) | `kustomize/base/apps/endpoint-admin-service/` skeleton mevcut (PR #312); 22.1'de manifest reconcile (BE-009/BE-013 live gate referansı) |

**"Repo bölünmez" yorumu (PR-8c clarify)**:
> Runtime manifest ve GitOps desired-state tek yerde `platform-k8s-gitops` içinde tutulur. Uygulama kaynak kodu ilgili platform repolarında kalır. **"Repo bölünmez" ifadesi YALNIZ GitOps manifest governance için geçerlidir; kaynak kodun tek repo olması anlamına gelmez.**

**Cross-component bağlantılar**:
- 4 component, 4 farklı repo (PR-8b user fill-in)
- OpenFGA tuple writer permission-service üstünden (cross-service tuple discipline)
- D35-EA ladder (0..5) D35 Zanzibar ladder ile paralel ama ayrı domain
- ADR-0011 governance layer pattern (DD/AC/BG) → endpoint-admin için "DD-EA-1..7 + BG-EA-1" analog
- Code signing: supply-chain RoT (build-time pipeline), Vault/ESO runtime secret DEĞİL
- **Naming convention**: repo geniş tutulur (`platform-agent` — ileride macOS/Linux genişleme), binary/service endpoint odaklı (`endpoint-agent.exe`, `EndpointAgent` Windows service)

## Karar (ACTIVE)

### Architecture

**4-repo bileşen yapısı** (user 2026-05-02 fill-in):

| Component | Repo | Path / Default branch |
|---|---|---|
| Backend REST | `Halildeu/platform-backend` | `endpoint-admin-service/` (sub-dir, mevcut backend monorepo branch'leri) |
| Windows agent | `Halildeu/platform-agent` | repo root, `main` |
| Admin portal MFE | `Halildeu/platform-web` | `apps/mfe-endpoint-admin/` (mevcut MFE convention) |
| GitOps manifest | `Halildeu/platform-k8s-gitops` | `kustomize/base/apps/endpoint-admin-service/` |

**Backend service profil**:
- Manifest: `kustomize/base/apps/endpoint-admin-service/`
- Namespace: `platform-prod` (prod) + `platform-test` (test) — D6 stateful PG/KC/Vault paylaşır
- Image: `ghcr.io/halildeu/platform-backend-endpoint-admin-service:<digest>` (D30 immutable; `deploy-endpoint-admin-prod.yml` workflow_dispatch + `production` environment gate, `deploy-backend-prod.yml` pattern reuse)
- Replicas: prod 2 (zero-downtime), test 0 default (D17 scale-to-zero)
- Secrets: ESO yoluyla Vault'tan (`kv/platform/endpoint-admin/*`) — **runtime secrets only** (OIDC client secret, AD bind, audit DSN); code signing key burada DEĞİL
- Authz: permission-service Zanzibar plane'i kullanır; ayrı OpenFGA store değil

**Agent (`platform-agent`)**:
- Windows binary (Go cross-compile darwin/linux build → windows/amd64 artifact)
- Authenticode imza pipeline (Faz 22.2'den itibaren mandatory, Faz 22.1 lab-only-evidence)
- Enrollment, heartbeat, identity discovery payload'ı backend REST'e gönderir
- Bu repo (gitops) Vault path `kv/platform/endpoint-admin/agent-enrollment-secret` ESO ile platform-test/prod ns'lerine sync

**Admin portal MFE (`platform-web/apps/mfe-endpoint-admin/`)**:
- Module Federation pattern (mevcut mfe-access/mfe-users gibi)
- Auth: shell'in Keycloak OIDC client'ı reuse (yeni OIDC client opsiyonel)

### Authorization model (`@RequireModule` analog)

Go middleware: `RequireScope(scope, action)`:
- `scope`: `endpoint`, `policy`, `command`, `inventory`, `audit`
- `action`: `view`, `assign`, `execute`, `signoff`, `revoke`

OpenFGA tuple shape: `(user:<id>, can_<action>, scope:<scope-id>)`. Tuple writer endpoint-admin-service değil, **permission-service** (cross-service tuple discipline; ADR-0011 BG-1 ile uyumlu).

**Auth realm** (user 2026-05-02 fill-in):
- **Prod**: `serban` (canonical platform realm) — Keycloak `master` realm KULLANILMAYACAK
- **Test**: `platform-test`
- **Client**: mevcut `frontend` veya `platform-shell` client reuse opsiyonel; ayrı client gerekirse `endpoint-admin-portal`

### Destructive command sınıfları (5 + dual-control)

D35-EA ladder:
- **D35-EA-0**: Read-only inventory (probe, list)
- **D35-EA-1**: Identity discovery (read user/device metadata)
- **D35-EA-2**: Benign command (non-destructive: notification, metadata fetch)
- **D35-EA-3**: Configuration push (group policy, registry edit) — **dual-control gate**
- **D35-EA-4**: Service control (start/stop/restart) — **dual-control gate**
- **D35-EA-5**: Destructive (uninstall, format, password reset) — **dual-control gate + audit immutable**

5 destructive command sınıfı:
1. `system_format` — disk/partition/volume format
2. `password_reset` — local + AD + Entra + M365
3. `software_uninstall` — package remove (msi/exe/winget)
4. `service_disable` — service set startup=disabled
5. `network_isolate` — firewall isolate device

**Dual-control**: 2 farklı user'ın (her biri `endpoint:admin` rol)+approval gate. ADR-0010 §2.5 boundary matrix pattern.

### Code signing supply-chain RoT

**Tier-aware sağlayıcı** (user 2026-05-02 fill-in):

| Tier | İmza zorunluluğu | Provider |
|---|---|---|
| Faz 22.1 Lab | Self-signed kabul (`lab-only-evidence` flag ile) | Lab self-signed cert (Parallels lab içinde geçerli) |
| Faz 22.2 IT-owned pilot | **Authenticode trusted signing ŞART** | **Azure Trusted Signing** (default tercih) |
| Faz 22.3 Restricted | Authenticode + EDR allowlist + audit | Azure Trusted Signing veya alt. (DigiCert KeyLocker, Azure Key Vault HSM, on-prem HSM — IT/regülasyon ihtiyacına göre) |

**Önemli (user 2026-05-02 düzeltme)**: Code signing key Vault/ESO **runtime secret olarak taşınmıyor**. Bu supply-chain root-of-trust; **build-time CI pipeline** tarafında imza yapılır:
- Image manifest sign: cosign + Azure KMS (CI workflow build artifact)
- Windows agent binary sign: signtool + Azure Trusted Signing certificate (CI workflow `platform-agent` repo'da)
- Runtime cosign verify: deploy workflow + `kustomize/base/apps/endpoint-admin-service/` ConfigMap `COSIGN_KEY_REF` only **public key reference** (Azure KMS URI, signature payload sadece runtime'da verify edilir)

**ESO secret path scope** (`kv/platform/endpoint-admin/*` only):
- `oidc-client-secret` (Keycloak admin-portal client)
- `audit-log-dsn` (postgres/clickhouse connection)
- `ad-bind-credentials` (LDAP service account)
- `entra-app-credentials` (Graph API client/secret)
- `internal-api-key` (gateway → endpoint-admin)
- `agent-enrollment-secret` (agent registration token)

Code signing private key bu listenin DIŞINDA — supply-chain pipeline kapsamı.

### 8 governance guard (DD-EA + BG-EA)

ADR-0011 analog:
- **DD-EA-1**: Manifest contract drift (kustomize render bytes)
- **DD-EA-2**: OpenFGA tuple writer (only permission-service)
- **DD-EA-3**: Image digest pin (deploy workflow strict mode, ADR-0011 D30 ile uyumlu)
- **DD-EA-4**: Code signing verify (cosign verify on deploy)
- **DD-EA-5**: Vault secret path (kv/platform/endpoint-admin/* allowlist)
- **DD-EA-6**: Destructive command audit log (immutable storage)
- **DD-EA-7**: Identity discovery PII boundary (no PII in logs)
- **BG-EA-1**: Per-PR boundary declaration (ADR-0011 BG-1 analog)

### Pilot tier matrisi (user 2026-05-02 fill-in)

| Tier | Domain scope | Cihaz | Destructive | Imza | Audit |
|---|---|---|---|---|---|
| **22.1 Lab** | Parallels lab + lab-only AD veya none | Kontrolllü Windows test ortamı, gerçek kullanıcı yok | Lab içi tam destructive test | Self-signed (`lab-only-evidence`) | Local audit yeterli |
| **22.2 IT-owned pilot** | **`acik.local` domain only** (BOREAS/CESS kapsam dışı) | 1-3 IT-owned domain-joined Windows 10/11 + ayrı `EndpointPilot` OU + test domain user | Agent enrollment + heartbeat + inventory + identity discovery + maintenance token akışı (read + benign + scoped destructive) | **Authenticode trusted signing ŞART** (Azure Trusted Signing) | Audit immutable storage |
| **22.3 Restricted** | acik.local + (sonra) BOREAS/CESS | Sınırlı gerçek kullanıcı/canlı cihaz | Code signing + EDR allowlist + audit + rollback + IT onayı şart | Authenticode + supply-chain pipeline | Full audit + dual-control |

**Şu an scope**: Sadece `acik.local`. **`BOREAS` ve `CESS` Faz 22.1/22.2 dışı** (3-domain inventory ID-001 altında future expansion).

**Faz 22.2 password reset**: scope-locked — `acik.local` only. Faz 22.3'e kadar:
- `local Windows` (NTLM, agent local) ✓
- `AD acik.local` (LDAP scoped query) ✓
- Entra → out of scope (BOREAS/CESS hibrit gerek)
- M365 → out of scope (aynı)

### Password reset connector (revised — acik.local first)

(D35-EA-5 destructive sınıfı, **Faz 22.2'den itibaren**):
- **Lokal Windows** (NTLM, agent-side) — Faz 22.1 lab + Faz 22.2 pilot
- **AD `acik.local`** (LDAP scoped query) — Faz 22.2 pilot
- **Entra (Azure AD Graph API)** — Faz 22.3+ (BOREAS/CESS hibrit gerektirir)
- **M365 (Microsoft Graph API)** — Faz 22.3+ (aynı)

### Identity discovery (parallel read-only, acik.local first)

**Faz 22.1 Lab + 22.2 Pilot scope** (`acik.local` only):
- Lokal Windows: NTLM hash, RID, group membership
- AD `acik.local`: LDAP query (sn, givenName, mail, member) — **scoped query**, full forest crawl YOK
- Probe-based commands: `Get-ADDomain`, `Get-ADForest`, `Get-ADTrust`, `nltest`, `dsregcmd` (agent-side)

**Future expansion (Faz 22.3+)**:
- Entra: Graph API users.list (paginated)
- M365: Graph API mailboxes.list
- BOREAS, CESS: 3-domain inventory genişletme

**PII boundary (DD-EA-7)**: Discovery sonuçları audit log'a girer ama **logs/error trace'lere PII sızmaz**. Codex iter-2 emphasis. Backend (`platform-backend`) + Agent (`platform-agent`) + Web (`platform-web/apps/mfe-endpoint-admin/`) her birinde paralel guard.

## Resolved Questions (user 2026-05-02 fill-in)

5 clarify question RESOLVED. Cevap detayları:

### 1. Endpoint-admin kaynak repo URL ve default branch

**RESOLVED**: Yeni ayrı repo açılmayacak. 4-component yapısı **mevcut repolarda**:

| Component | Repo | Path / Branch |
|---|---|---|
| Backend REST | `Halildeu/platform-backend` | `endpoint-admin-service/` sub-dir, mevcut backend monorepo branch'leri |
| Windows agent | `Halildeu/platform-agent` (ayrı repo) | repo root, `main` |
| Admin portal MFE | `Halildeu/platform-web` | `apps/mfe-endpoint-admin/` (mevcut MFE convention) |
| GitOps manifest | `Halildeu/platform-k8s-gitops` (bu repo) | `kustomize/base/apps/endpoint-admin-service/` |

> Önerilen `Halildeu/endpoint-admin-service` ayrı repo **REDDEDİLDİ**. Backend platform-backend altında servis olarak ilerleyecek, agent ayrı repo (`platform-agent`) olarak kalacak.

### 2. Admin auth realm

**RESOLVED**: Aynı realm + opsiyonel ayrı client. Ayrı realm yok.
- **Prod**: `serban` (canonical platform realm) — Keycloak built-in `master` realm KULLANILMAYACAK
- **Test**: `platform-test`
- **Client**: web shell mevcut client ile çalışabiliyorsa mevcut reuse; ayrı client gerekirse `endpoint-admin-portal`

### 3. Pilot tier başlatma

**RESOLVED**: Lab first; ardından IT-owned acik.local; sonra Restricted.

| Sub-faz | Scope |
|---|---|
| 22.1 Lab | Parallels / kontrollü Windows test ortamı; self-signed `lab-only-evidence` kabul; gerçek kullanıcı yok; password reset YOK |
| 22.2 IT-owned pilot | `acik.local` domain-joined Windows 10/11 + ayrı `EndpointPilot` OU + 1-3 test cihaz + test domain user; agent enrollment, heartbeat, inventory, identity discovery, maintenance token akışı |
| 22.3 Restricted pilot | Sınırlı gerçek kullanıcı/canlı cihaz; code signing + EDR allowlist + audit + rollback + IT onayı şart |

**Şu an scope**: Sadece `acik.local`. **BOREAS ve CESS Faz 22 dışı**.

### 4. Code signing provider ilk hedef

**RESOLVED**: Tier-aware. **Azure Trusted Signing default** (22.2'den itibaren mandatory).

| Tier | İmza | Provider |
|---|---|---|
| 22.1 Lab | Self-signed kabul (`lab-only-evidence` flag ile açıkça işaretli) | Lab self-signed cert |
| 22.2 IT-owned pilot | **Authenticode trusted signing ŞART** | Azure Trusted Signing (default) |
| 22.3 Restricted | Authenticode + EDR allowlist + audit + rollback | Azure Trusted Signing veya alt: DigiCert KeyLocker, Azure Key Vault HSM, on-prem HSM (IT/regülasyon ihtiyacına göre) |

**Önemli düzeltme (user 2026-05-02)**: Signing key Vault/ESO **runtime secret olarak taşınmıyor**. Bu supply-chain root-of-trust; ayrı build-time pipeline konusu. ConfigMap `COSIGN_KEY_REF` yalnızca **public key reference** (Azure KMS URI), runtime cosign verify için.

### 5. Domain inventory otorite

**RESOLVED**: 3 domain var (5 değil; user 2026-05-02 düzeltme). İlk faz scope **sadece `acik.local`**.

**Mevcut 3 AD domain**:
- `acik.local`
- `BOREAS`
- `CESS`

**Initial scope (Faz 22.1 + 22.2)**: Sadece `acik.local`. BOREAS/CESS future expansion (3-domain inventory ID-001 altında).

**Authority modeli**: Hibrit
- **Teknik gerçek**: probe-based/read-only discovery (ADUC, `Get-ADDomain`, `Get-ADForest`, `Get-ADTrust`, `nltest`, `dsregcmd`, agent identity inventory)
- **İş/operasyon doğrulaması**: IT manager review gate

Yani: **probe-based evidence + IT review/sign-off** — tek tarafa bağımlı değil.

## 22.1 sub-track scope (PR-8c clarify)

**Önemli düzeltme**: 22.1 sıfırdan skeleton DEĞİL. Backend ve agent için mevcut state'ler var; 22.1 lab/release **hardening** + integration smoke hazırlığı yapılır.

| Track | 22.1 scope (Lab) | 22.2 scope (IT-owned acik.local) |
|---|---|---|
| **Agent (`platform-agent`)** ana track | Local state review + GitHub remote bootstrap + build/test pipeline + Windows artifact packaging (`endpoint-agent.exe` + ps1 install/uninstall + windows-amd64 zip + SHA256SUMS) + lab-only-evidence imza + Parallels lab Windows service test | Authenticode trusted signing (Azure Trusted Signing) + MSI/signed zip + EDR allowlist + agent enrollment live + heartbeat backend integration |
| **Backend (`platform-backend/endpoint-admin-service/`)** paralel | BE-009 OpenFGA live gate paralel + BE-013 maintenance token live gate paralel + `endpoint-admin-service` manifest reconcile (gitops bu repo) | Agent-backend integration smoke + BE-011 cross-component live |
| **GitOps (`platform-k8s-gitops`)** | Mevcut endpoint-admin-service manifest skeleton (PR #312) reconcile + BE-009/BE-013 live gate referansı | Overlay-specific deploy workflow (`deploy-endpoint-admin-prod.yml`) |
| **Web (`platform-web/apps/mfe-endpoint-admin/`)** | Mock/plan olabilir | Ana iş (admin portal MFE) |
| **AD/IT (`acik.local`)** | EndpointPilot OU oluşturma + 1-3 IT kontrollü Windows 10/11 test cihaz hazırlığı | Pilot cihaz enrollment + agent live deployment |

**Acik.local ölçeği** (user 2026-05-02 PR-8c bilgisi):
- Toplam ~800 cihaz `acik.local` domain'inde
- Pilot OU `EndpointPilot`: 1-3 test cihaz (sınırlı + IT kontrollü)
- Domain-wide deployment **22.3+ scope** (gradual rollout)

## Build artifact + distribution stratejisi (PR-8c clarify)

| Tier | Artifact | Distribution channel |
|---|---|---|
| **22.1 Lab** | `endpoint-agent.exe` + `install.ps1` + `uninstall.ps1` + `endpoint-agent-windows-amd64.zip` + `SHA256SUMS` + `lab-only-evidence` flag | GitHub Releases (private asset) veya repo artifact çıktısı; manuel install lab cihazlarda |
| **22.2 IT pilot** | Authenticode signed `.exe` + signed zip veya MSI + `release manifest signature` + EDR allowlist info | GitHub Releases (private asset, signed) + RDP/manuel veya `EndpointPilot` OU üzerinden GPO/Intune (IT kontrolü) |
| **22.3 Restricted** | Signed MSI + signed update manifest + SBOM + SHA256/SHA512 | Intune / GPO / SCCM (kurumsal dağıtım) + signed update manifest + staged rollout |

**GHCR kullanımı**: Container image değil, agent binary için **ana kanal değil** (GitHub Releases öncelikli). Backend container image GHCR'da kalır (deploy workflow değişmez).

## Sonuç (ACTIVE)

5 clarify RESOLVED + 22.1 scope clarify 2026-05-02 (PR-8b + PR-8c). Charter ACTIVE durumda; manifest skeleton PR #312 ile merge'lendi (PR-9), ADR fill-in PR #313 ile detaylandı (PR-8b), 22.1 scope düzeltmesi bu PR (PR-8c).

**Ana düzeltmeler kümesi**:
- ADR'da `Open Questions` → `Resolved Questions`
- Architecture: 4-component, 4-repo (kaynak kod ayrı, manifest tek)
- Code signing: supply-chain RoT separate pipeline (Vault/ESO runtime DEĞİL)
- Pilot tier: acik.local-only initial scope (BOREAS/CESS Faz 22 dışı)
- 22.1 scope clarify: agent ana track + backend paralel (BE-009/BE-013 live gate) + gitops manifest reconcile + AD/IT EndpointPilot OU; web 22.2'ye
- 800 cihaz acik.local ölçeği + 1-3 pilot test cihaz scope
- Naming: `platform-agent` repo + `endpoint-agent` binary

Sub-faz roadmap finalized:
- **22.1** (Lab) — agent local state review + GitHub remote bootstrap + Windows artifact packaging + lab-only-evidence imza + backend BE-009/BE-013 paralel + gitops manifest reconcile + EndpointPilot OU hazırlığı
- **22.2** (IT-owned acik.local pilot) — Authenticode trusted signing + agent enrollment + heartbeat backend integration + web MFE ana iş + 1-3 IT-owned Windows pilot cihaz
- **22.3** (Restricted) — sınırlı gerçek kullanıcı + EDR allowlist + IT onayı + staged rollout (acik.local 800 cihaz gradual)

## Bağlantılı kararlar

- **ADR-0010 §2.5**: boundary matrix (operator/agent authority); endpoint-admin'in destructive command sınıfları bu matrisi takip eder.
- **ADR-0011 BG-1 + DD-1..4**: governance layer pattern; DD-EA + BG-EA bunun analog'u.
- **Faz 19** (Codex 019dc0ef): kaynak repo decommission; endpoint-admin yeni repo, eski platform-ssot pattern'inden bağımsız.
- **PLAN.md Faz 22**: bu ADR'ın PLAN tarafındaki entry'si; sub-faz roadmap (22.1 lab, 22.2 pilot, 22.3 restricted).

## Sonraki adımlar

1. Bu PR (PR-8) merge → ADR draft kalıcı.
2. PR-9: `kustomize/base/apps/endpoint-admin-service/` skeleton (Deployment + ConfigMap + SA + ExternalSecret placeholder, image=`OVERLAY_MUST_OVERRIDE`, replicas=0 default fail-closed).
3. Kullanıcı 5 clarify cevabı → ADR fill-in follow-up PR (PR-8b).
4. 8 DD-EA + BG-EA workflow guard skeleton (post-sprint, ayrı tier).

## Referanslar

- PR #270: `docs/2026-04-29-endpoint-admin-service-uyum-mutabakati.md` (962 satır, Codex AGREE)
- ADR-0010: vault credential lifecycle + DR + operator/agent authority
- ADR-0011: drift detection + audit cadence + boundary governance
- Codex thread: `019dd895-17c1-79f0-b652-e316f64d4d79` + `019de00f-4b40-75c1-8ead-01b79c5819c1`
