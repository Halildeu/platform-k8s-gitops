# ADR-0012-EA — Endpoint Admin Service Governance Charter

> **Status**: ACTIVE (5 clarify question RESOLVED 2026-05-02)
> **Date**: 2026-05-01 (draft) → 2026-05-02 (resolved fill-in PR-8b)
> **Sprint**: "Prod post-cutover compliance" PR-8 + PR-8b fill-in
> **Codex thread**: `019dd895-17c1-79f0-b652-e316f64d4d79` (mutabakat raporu PR #270, iter-3 AGREE) + `019de00f-4b40-75c1-8ead-01b79c5819c1` (sprint review)
> **Provenance**: Cross-repo governance assessment `docs/2026-04-29-endpoint-admin-service-uyum-mutabakati.md` (962 satır, PR #270 merged) + 2026-05-02 kullanıcı fill-in mesajı (5 cevap)
>
> **Konvansiyon**: ADR-0012 numarası mevcut ([@RequireModule WebMvcTest defer]); bu charter `0012-EA` (Endpoint Admin) namespace'i ile ayrı dosya.

## Bağlam

Faz 22 ile yeni domain: **Endpoint Admin** — Windows endpoint'lerin merkezi yönetimi (group policy push, command exec, audit, identity discovery). 4 component:

1. **Backend service** (`platform-backend/endpoint-admin-service/`) — Go REST API, OIDC + RequireScope middleware, OpenFGA cross-service authz consumer
2. **Agent** (`platform-agent` — ayrı repo) — Windows binary (Go), enrollment, heartbeat, command exec, identity discovery
3. **Web UI** (`platform-web/apps/mfe-endpoint-admin/`) — admin portal MFE
4. **GitOps manifest** (`platform-k8s-gitops/kustomize/base/apps/endpoint-admin-service/`) — bu repo, deploy disipline

**Cross-component bağlantılar** (PR #270 mutabakat + 2026-05-02 user fill-in):
- 4 component, 4 farklı repo (NOT monorepo + agent yine ayrı; user 2026-05-02 kararı)
- OpenFGA tuple writer permission-service üstünden (cross-service tuple discipline)
- D35-EA ladder (0..5) D35 Zanzibar ladder ile paralel ama ayrı domain
- ADR-0011 governance layer pattern (DD/AC/BG) → endpoint-admin için "DD-EA-1..7 + BG-EA-1" analog
- Code signing: supply-chain RoT (build-time pipeline), Vault/ESO runtime secret DEĞİL (user 2026-05-02 düzeltme)

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

## Sonuç (ACTIVE)

5 clarify question RESOLVED 2026-05-02. Charter ACTIVE durumda; manifest skeleton PR #312 ile zaten merge'lendi (PR-9). Bu PR-8b ile:
- ADR'da `Open Questions` → `Resolved Questions` (kullanıcı kararları)
- Architecture: 4-component, 4-repo yapı
- Code signing: supply-chain RoT separate pipeline note
- Pilot tier: acik.local-only initial scope
- Manifest düzeltmeleri (configmap.yaml + secret-stub.yaml)
- PLAN.md Faz 22 entry update

Sub-faz roadmap finalized:
- **22.1** (Lab) — `platform-agent` skeleton + Parallels lab + lab-only-evidence imza
- **22.2** (IT-owned pilot) — `acik.local` domain-joined + Azure Trusted Signing + agent enrollment
- **22.3** (Restricted) — sınırlı gerçek kullanıcı + EDR allowlist + IT onayı

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
