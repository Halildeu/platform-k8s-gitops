# ADR-0012-EA — Endpoint Admin Service Governance Charter

> **Status**: ACTIVE (5 clarify RESOLVED + 22.1 scope clarify 2026-05-02 PR-8c + 2026-05-21 truth refresh #924 + 2026-05-22 truth refresh #982 — BE-016/BE-017/BE-011 merged)
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
| Backend service | `Halildeu/platform-backend` | `endpoint-admin-service/` sub-dir; **Plan C H1+H2 + BE-014A MERGED canonical `origin/main` (2026-05-22)**. H1 source PR #288 (mergeCommit `8e2589c1`) + H2 api-gateway integration PR #291 (mergeCommit `161296cf`) + **BE-014A backend PR #293 (mergeCommit `c8f244c4`)** (4 deny audit event types + noRollbackFor durability invariant + NOT_SUPPORTED regression guard). Test cluster image artifact post-merge final main SHA (`sha256:fd7a9c54f7919bdb...` endpoint-admin BE-014A bytecode + `sha256:84500b5ebe162b` api-gateway). **GitOps ConfigMap fix #961 MERGED `a29fd55f`** + **BE-014A gitops digest #965 MERGED `90922f30`** + **#963 PM refresh MERGED `d07e36a9`**. **C.5.persona D29-EA Live JWT 6/6 matrix VERIFIED LIVE** + **BE-014A Functional 5/5 HMAC smoke VERIFIED LIVE 2026-05-22T09:52Z** (4 deny event types EMITTING + 7 DB audit rows + durability invariant live-runtime proven on test deployment). |
| Agent | `Halildeu/platform-agent` | GitHub remote + Go scaffold mevcut; PR #1-#5 ile CI, build/test, lab-only-evidence signing, BG-EA-1, gitleaks, SBOM ve board evidence foundation var. `docs/TRACKING-ROADMAP.md` Parallels Windows 11 service/installer/local-user/tamper MVP evidence satırlarını taşıyor; bugünkü recheck'te Windows VM stopped olduğu için live smoke yeniden koşulmadı. |
| Web UI MFE | `Halildeu/platform-web` | `apps/mfe-endpoint-admin/` kaynak kodu `origin/main`de mevcut; runtime route/flag acceptance backend main reconciliation + D29-EA Secured kanıtı sonrası. |
| GitOps manifest | `Halildeu/platform-k8s-gitops` (bu repo) | `kustomize/base/apps/endpoint-admin-service/` + test overlay digest pin mevcut; **#961 ConfigMap fix mergeCommit `a29fd55f` MERGED 2026-05-22** (SPRING_PROFILES_ACTIVE=k8s + endpoint-admin gateway routes 22/23/24). Live check: Deployment 1/1, health UP, **C.5.persona Live JWT 6/6 matrix VERIFIED LIVE + DB audit row** (#960). |

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

## 22.1 sub-track scope (PR-8c clarify + PR-8d Codex revize)

**Önemli düzeltme** (PR-8c): 22.1 sıfırdan skeleton DEĞİL. Backend ve agent için mevcut state'ler var; 22.1 lab/release **hardening** + integration smoke hazırlığı yapılır.

**Codex revize sertleştirmesi** (PR-8d, thread `019de00f`): Sub-faz milestone numaralama + ephemeral signing pattern + 22.1 invariantları + 22.2 pre-req docs çerçevesi.

### 2026-05-21 Truth Refresh (#924)

Bu bölüm, eski 2026-05-02/05-05 ara notlarını override eden güncel takip notudur. D29 dili korunur: **Up != Functional != Secured**.

| Track | Güncel durum | Kalan gate |
|---|---|---|
| **Backend source** | **Plan C H1+H2 + BE-014A MERGED 2026-05-22**: H1 PR #288 mergeCommit `8e2589c1` + H2 PR #291 mergeCommit `161296cf` + **BE-014A backend PR #293 mergeCommit `c8f244c4`** (4 deny audit event types + noRollbackFor durability invariant + NOT_SUPPORTED regression guard). Final main D30 immutable images: endpoint-admin `sha256:fd7a9c54...` (BE-014A bytecode) + api-gateway `sha256:84500b5ebe162b...`. **C.5.persona Live JWT 6/6 + BE-014A Functional 5/5 HMAC smoke VERIFIED LIVE on test deployment 2026-05-22T09:52Z** post-#961 ConfigMap fix + #965 gitops digest. | BE-011 agent full lifecycle (heartbeat/command/result) + BE-013 full HMAC lifecycle (BE-014A consume/deny path live yarı-kanıt) + BE-016 audit hash-chain + D35-EA-3+ destructive saga. |
| **Backend live** | Test cluster digest pin `sha256:fd7a9c54...` (endpoint-admin BE-014A, gitops PR #965 superseded #956 H1) + api-gateway `sha256:84500b5ebe162b...` (gitops PR #957) + **#961 ConfigMap fix `a29fd55f`** + **#965 BE-014A gitops digest `90922f30`** + **#963 PM refresh `d07e36a9`**. **D29-EA Secured VERIFIED LIVE on test deployment**: synthetic OpenFGA 5/5 (#959) + Live JWT 6/6 persona matrix + **BE-014A Functional 5/5 HMAC smoke (4 deny event types EMITTING via DENIED_DEVICE_MISMATCH + DENIED_REVOKED + DENIED_ALREADY_CONSUMED + DENIED_EXPIRED) + 7 DB audit rows + performed_by_subject=agent forensic correlation + durability invariant live-runtime proven (403/409 throw + audit row PERSIST via noRollbackFor=ResponseStatusException)** + OpenFGA pod authz log deny path observable. | BE-013 full HMAC lifecycle (BE-014A consume/deny path live yarı-kanıt; full path BE-011 ile bağlanır); BE-011 agent full lifecycle; BE-016 audit integrity hash-chain. |
| **GitOps** | Test overlay includes endpoint-admin base and digest pin; `services.yaml` test enabled, prod deferred. | Prod overlay/workflow remains 22.2+; no prod activation in 22.1. |
| **Web** | `platform-web/origin/main` has `apps/mfe-endpoint-admin` source files. | Runtime route/flag acceptance after backend main + Secured evidence; no eager route enablement. |
| **Agent** | `platform-agent/origin/main` has Go scaffold, CI/release hardening foundation, successful `main` CI run `26030514275`, lab-only signed artifact evidence, and historical Parallels Windows 11 service/installer/local-user/tamper MVP evidence in `docs/TRACKING-ROADMAP.md`. Fresh temp worktree test/build/windows-package PASS. | Backend live enrollment/heartbeat integration, Windows identity inventory, trusted signing, EDR/allowlist, and IT EndpointPilot deployment remain pending. Also fix capability mismatch before pilot: Windows currently reports disable/enable local-user capability while executor would return `UNSUPPORTED`. |
| **IT** | Scope remains `acik.local`; BOREAS/CESS outside initial phase. | EndpointPilot OU + 1-3 IT-owned Windows devices + inventory baseline. |

Evidence-weighted progress snapshot (2026-05-22 — Plan A/B/C + C.5.persona Live JWT full chain MERGED) — **[superseded by "2026-05-22 Truth Refresh (#982)" below — BE-016/BE-017/BE-011 merged + api-gateway D30 drift; aşağıdaki tablo BE-016 öncesi historical snapshot]**:

| Milestone | Progress | Acceptance boundary |
|---|---:|---|
| 22.0 Governance / repo split | ~95% ⬆️ | PR #944 truth-refresh MERGED, #924 closed Done; Plan A/B/C chain + C.5.persona ConfigMap fix + BE-014A chain MERGED autonomous + cross-AI peer review chain (13 thread) |
| 22.1 Lab foundation | ~80% ⬆️ | GitOps Up/basic Functional + agent lab foundation + **PR #7 AG-013 capability fix MERGED** (verification fresh Windows smoke #8 pending); **C.5.persona D29-EA Live JWT 6/6 matrix VERIFIED LIVE**; BE-011 full lifecycle pending |
| 22.1 Backend canonicalization | **~95%** ⬆️⬆️ | **H1 source PR #288 MERGED mergeCommit `8e2589c1`** + **H2 source PR #291 MERGED mergeCommit `161296cf`** + **BE-014A backend PR #293 MERGED mergeCommit `c8f244c4`** (4 deny audit + noRollbackFor + NOT_SUPPORTED regression guard); final main D30 immutable images (endpoint-admin `sha256:fd7a9c54...` BE-014A bytecode + api-gateway `sha256:84500b5e...`) + GitOps overlay digest pins LIVE (#961 + #965); **C.5.persona Live JWT 6/6 + BE-014A Functional 5/5 HMAC smoke VERIFIED LIVE 2026-05-22T09:52Z (7 DB audit rows + 4 deny event types EMITTING + durability invariant live-runtime proven on test deployment)**; BE-011 agent full lifecycle (heartbeat/command/result) + BE-013 full HMAC lifecycle (BE-014A consume/deny path live yarı-kanıt) + BE-016 hash-chain pending |
| 22.2 IT pilot readiness | ~10% | `acik.local` scope known; EndpointPilot OU/devices/trusted signing/EDR pending (operator-bound) |
| Faz 22 overall | **~70-75%** ⬆️⬆️⬆️ | Not prod-ready; not password-reset-ready; **BE-014A Functional acceptance VERIFIED LIVE on test deployment** + **C.5.persona Live JWT 6/6 matrix VERIFIED**; next gates: BE-011 agent full lifecycle, BE-016 hash-chain, WEB runtime acceptance, Windows fresh smoke, IT pilot, prod overlay activation |

Cross-AI peer review chain (Plan C + C.5.persona + BE-014A zinciri, 14 thread total — son 019e4f1e bu PR'ın review thread'i):
- `019e4c3f` — plan-time consult (Hybrid 2-PR strategy AGREE)
- `019e4c81` — H1 post-impl (REVISE → AGREE; .gitignore restore + ci-image-push 4 guard fix)
- `019e4c95` — C.4 endpoint-admin digest bump (REVISE → AGREE; structured body absorb)
- `019e4caa` — H2 source post-impl (AGREE; ConfigMap parity warning for next PR)
- `019e4cb6` — H2 gitops digest bump (REVISE → AGREE; "legacy prefix NO-OP in SCG 4.3.3+" — **later overruled by 019e4eaa with dep analysis**)
- `019e4cc2` — #958 docs refresh (REVISE → AGREE; 5 refresh locations + 4 tutarsızlık absorb)
- `019e4e8d` — C.5.persona strategic consult Q1=A REVISE (live JWT zorunlu, synthetic yetmez)
- `019e4eaa` — #961 ConfigMap fix AGREE + ready_to_merge: true (spring-boot-properties-migrator dep analysis ile prior 019e4cb6 overruled; legacy prefix FİİLEN effective in SCG 4.3.3 fat jar)
- `019e4eb9` — #963 PM artifact refresh iter-2 AGREE (5 stale-truth absorbed)
- `019e4ed6` — BE-013+BE-014 plan-time strategic REVISE (BE-014A dar scope; heartbeat scheduler defer)
- `019e4ee1` — BE-014A backend PR #293 iter-3 AGREE+ready_to_merge (transaction rollback → noRollbackFor pattern; comment correction + NOT_SUPPORTED regression guard)
- `019e4efb` — BE-014A gitops digest PR #965 iter-3 AGREE+ready_to_merge (narrative düzeltme CARRIES bytecode + live HMAC smoke pending → VERIFIED LIVE post-smoke)
- `019e4f15` — BE-014A Functional live smoke strategic verdict path A' (real enrollment + HMAC canonical; encryption reverse engineering YOK)
- `019e4f1e` — #967 PM refresh BE-014A Functional VERIFIED iter-N REVISE absorb (production-proven → live-runtime on test deployment; canonical stale-truth sweep)

### 2026-05-22 Truth Refresh (#982)

BE-016 / BE-017 / BE-011 merge sonrası canonical truth. Tracked by [#982](https://github.com/Halildeu/platform-k8s-gitops/issues/982).

| Alan | 2026-05-22 truth |
|---|---|
| BE-016 | MERGED — audit hash-chain (`platform-backend#295` `ff7d4843`) + Flyway enablement (`#297`). Gitops #968/#971 Done. V5 Flyway migration test cluster Postgres'te `4→v5` uygulandı. |
| BE-017 | MERGED — destructive command dual-control gate (`platform-backend#300` `dd6b1eab`). Gitops digest bump #980 (`d702d678`). Cross-AI Codex `019e50e0` RED→absorb→AGREE. Gitops tracking #978 Done. |
| BE-011 | MERGED — agent↔backend wire-contract reconciliation (`platform-agent#9` `2e49f8b`). Gitops tracking #974 Done. |
| endpoint-admin-service D30 | ✅ MATCH — live pod imageID `sha256:1a1d0aac…` == GitOps desired (BE-017 image, BE-014A `fd7a9c54`'i supersede eder). |
| api-gateway D30 | ❌ DRIFT — live `sha256:6137bb2c…` ≠ desired `sha256:84500b5e…`. Route 401 fail-closed çalışıyor; imageID match KAPALI DEĞİL. Ayrı resolution track. |
| Pending acceptance gate | BE-011 real agent lifecycle smoke · Windows fresh smoke #8 (`platform-agent#8`) · Web runtime acceptance · IT pilot (22.2). |

prod-ready / password-reset-ready İDDİA EDİLMEZ — 22.1 test runtime + source-side merge seviyesi.

### Sub-faz milestone'ları (Codex sırası)

| Milestone | Konu | Önkoşul |
|---|---|---|
| **22.1.0** | **Agent CI/release foundation** (mandatory ilk) — go test + cross-build + paket + lab-only-evidence imza + BG-EA-1 + gitleaks + SBOM + release dry-run | — |
| **22.1.1** | BE-009 OpenFGA live (Up + Functional + Secured ayrı kanıt; admin allow/deny + unauthenticated deny + tuple/model seed + gateway behavior + audit trace) | — |
| **22.1.2** | BE-013 maintenance token live (token issuance/validation/expiry/deny/audit; OpenFGA ile çakışmayan bakım yetki modeli) | BE-009 yetki modeli (acceptance sırası) |
| **22.1.3** | GitOps lab reconcile + DD-EA-1 + DD-EA-5 minimal ESO allowlist (paralel 22.1.1/22.1.2 ile) | — |
| **22.1.IT** | EndpointPilot OU + 1 IT-owned Windows 10/11 cihaz inventory baseline | **Async IT track** — mühendislik onu beklemez |

### Track ↔ repo dağılımı

| Track | 22.1 scope (Lab) | 22.2 scope (IT-owned acik.local) |
|---|---|---|
| **Agent (`platform-agent`)** ana track | CI workflow setup + go test/lint + Windows amd64 cross-build + paket (exe + ps1 + zip + SHA256SUMS) + **ephemeral lab signing** + BG-EA-1 + gitleaks + SBOM + Parallels Win11 install/start/status/stop/uninstall + tamper protection live evidence (CI-driven artifact üzerinden tekrar üretilebilir) | Authenticode trusted signing (Azure Trusted Signing) + MSI/signed zip + EDR allowlist + agent enrollment live + heartbeat backend integration |
| **Backend (`platform-backend/endpoint-admin-service/`)** paralel | BE-009 OpenFGA live gate (Up + Functional + Secured) + BE-013 maintenance token live gate (token expiry/audit) + BG-EA-1 (platform-backend repo'da paralel) | Agent-backend integration smoke + BE-011 cross-component live + BE-014..BE-019 |
| **GitOps (`platform-k8s-gitops`)** | endpoint-admin-service test overlay tier=lab reconcile (replicas=1, digest pin) + DD-EA-1 manifest contract drift gate + DD-EA-5 minimal ESO allowlist (sadece OIDC + audit DSN + maintenance/enrollment) + BE-009/BE-013 live evidence runbook | DD-EA-3 prod deploy digest-pin workflow + `deploy-endpoint-admin-prod.yml` + DD-EA-4 deploy-side trusted signing verification + prod replicas/approval gate |
| **Web (`platform-web/apps/mfe-endpoint-admin/`)** | **22.1 DIŞI** (Codex AGREE — mock MFE contract drift'i sahte yüzeyle perdeler) | Ana iş (admin portal MFE) WEB-001 başlangıç |
| **AD/IT (`acik.local`)** | EndpointPilot OU + 1 IT-owned Windows 10/11 cihaz hazırlığı | Pilot cihaz enrollment + agent live deployment + 1-3 cihaz inventory baseline |

**Acik.local ölçeği**:
- Toplam ~800 cihaz domain'inde
- Pilot OU `EndpointPilot`: 1-3 test cihaz (22.2 başlangıç) — minimum 1 cihaz 22.2 unlock için yeter
- Domain-wide deployment **22.3+ scope** (gradual rollout, EDR allowlist + IT onayı şart)

## 22.1 invariantları — yapılMAYACAK (Codex revize)

22.1 boyunca **kesinlikle yapılmaz**:

- ❌ **Password reset** (lokal SAM, AD, Entra, M365 — hepsi Faz 22.2+ scope; AG-016 BLOCKED)
- ❌ **Arbitrary file access** (Desktop/Documents/Downloads whitelist 22.2+; AG-017 RISK gate)
- ❌ **Destructive command execution** (D35-EA-3/-4/-5 dual-control gate 22.2+)
- ❌ **BOREAS / CESS** domain işlemleri (initial scope acik.local only; 22.3+)
- ❌ **Trusted signing olmadan EndpointPilot dışı dağıtım** (lab-only-evidence imza Parallels lab cihazlarına yetkilidir, IT-owned cihazlara değil)
- ❌ **Web MFE** (22.2'de WEB-001 ile başlar)
- ❌ **Prod overlay endpoint-admin-service aktivasyon** (22.1'de test overlay scope; prod 22.2+)

## 22.1 ephemeral signing pattern (Codex revize)

**Önemli düzeltme**: Self-signed PFX'i GitHub Secret olarak SAKLAMAYIZ. Lab-only-evidence imza her CI run'da **ephemeral cert** ile yapılır:

```yaml
# .github/workflows/ci-build-test.yml (örnek pattern)
- name: Generate ephemeral self-signed cert (lab-only-evidence)
  shell: pwsh
  run: |
    $cert = New-SelfSignedCertificate -Type CodeSigning \
      -Subject "CN=platform-agent-lab-evidence-${{ github.run_id }}" \
      -KeyExportPolicy Exportable \
      -KeySpec Signature -KeyLength 2048 \
      -CertStoreLocation Cert:\CurrentUser\My
    $thumbprint = $cert.Thumbprint
    Export-PfxCertificate -Cert "Cert:\CurrentUser\My\$thumbprint" \
      -FilePath ./lab-cert.pfx \
      -Password (ConvertTo-SecureString -String "ephemeral" -Force -AsPlainText)
    echo "thumbprint=$thumbprint" >> $env:GITHUB_OUTPUT

- name: Sign with ephemeral cert
  run: |
    signtool sign /f ./lab-cert.pfx /p ephemeral \
      /tr http://timestamp.digicert.com /td sha256 /fd sha256 \
      ./endpoint-agent.exe

- name: Verify signature
  run: signtool verify /pa /v ./endpoint-agent.exe

- name: Upload artifact (with thumbprint + verify log)
  uses: actions/upload-artifact@v7
  with:
    name: endpoint-agent-lab-evidence-${{ github.run_id }}
    path: |
      ./endpoint-agent.exe
      ./lab-cert.pfx
      ./signtool-verify.log
```

**Sonuç**: Persistent private key yok, GitHub Secret'a kalıcı PFX yüklenmez. Artifact'te thumbprint + verify log evidence olarak kalır. 22.2 trusted signing geçişinde **operasyon borcu yok**.

## 22.2 scope amendment — Non-domain Windows primary scope (2026-05-24)

> **User decision 2026-05-24**: Endpoint-admin Faz 22.2 primary production scope **non-domain Windows yönetimi** (workgroup / standalone / BYOD) olarak yeniden tanımlanır. Domain-joined `acik.local` IT pilot ikincil opsiyonel scope olarak korunur. **Codex strategic thread `019e5afc-2ce2-7811-9d98-73ff6eac1434`** REVISE iter-1 with `ready_for_impl=true` for docs-only scope realignment (full pilot scope still REVISE pending operator action).

### Sub-scope split

| Sub | Tanım | Mevcut evidence | Status (2026-05-24) |
|---|---|---|---|
| **22.2.A** | **Non-domain Windows primary** (workgroup / standalone / BYOD) | gitops PR #1021 (`4ecb71dc`) BE-011 + AG-013 WORKGROUP smoke HALILKOOLUB735; platform-agent PR #10 (`402bdc1`) + PR #11 (`fa778a67`) tracking; gitops PR #1032 (`507f57c4`) BE-017 dual-control fixture test cluster; platform-agent PR #13 (`ab1eb0ee`) CI automation script + workflow | **PRIMARY — substantive evidence cover** (single VM/no-soak; production-ready DEĞİL) |
| **22.2.B** | **Domain-joined IT pilot** (`acik.local`) — opsiyonel ikinci scope | gitops PR #1037 Gate 0 VPN routing BLOCKER + PR #1039 (`61a5136a`) evidence/runbook; platform-agent PR #14 (`ef7ded6f`) precheck helper | **OPSIYONEL** — operator-bound (VPN routing + DC reachability + EDR allowlist + trusted signing); 22.2.A overall blocker DEĞİL |

### Non-domain taxonomy (Codex Q8 absorb)

- **A1 Workgroup / standalone Windows** — 22.2.A primary (current `HALILKOOLUB735` evidence)
- **A2 BYOD unmanaged Windows** — 22.2.A primary (consent + uninstall + privacy/KVKK boundary + local-admin/install)
- **A3 Entra-joined / Azure AD-joined (AD domain olmayan)** — 22.2.A primary (agent install/enroll/heartbeat/inventory read-only); Entra/Graph/Intune management ikinci gate
- **A4 Workplace-registered only** — 22.2.A read-only inventory/support; tenant/MDM aksiyonları scope dışı
- **B1 Hybrid Azure AD-joined** — 22.2.B (AD DS join + DC/Kerberos/GPO/cached credential riskleri)
- **B2 `acik.local` AD domain-joined** — 22.2.B optional pilot
- **C Mobile (iOS/Android)** — Faz 22.2 scope dışı; Faz 23.7.b mobile push veya ayrı future device-management fazı

**Detection surface**: `Win32_ComputerSystem.PartOfDomain` + `Domain` + `Workgroup`; `dsregcmd /status` (`DomainJoined`, `AzureAdJoined`, `WorkplaceJoined`, tenant/device id); MDM/Intune enrollment state.

### Faz 22.2 overall % (Codex Q5 absorb — iki katman)

- **22.2.A non-domain primary**: ~78% (strong evidence — PR #1021 BE-011 + AG-013 + #1032 BE-017 fixture + PR #13 CI automation source; **eksik**: self-hosted CI run, 2+ standalone/BYOD device, 24-72h soak, identity classification `dsregcmd`/logged-in identity, signed distribution / support / KVKK boundary)
- **22.2.B `acik.local` optional**: ~25% (Gate 0 evidence + runbook + helper; VPN/DC/domain join/pilot smoke/EDR/signing operator-bound waiting)
- **Composite Faz 22.2 portfolio**: ~67% (A primary güçlü, B optional blocker ayrı taşındığı için makul; `85%` veya tek-numara yazılmaz — closure dili yasak)

### Boundary (HARD constraints korunmuş)

- **NOT prod-ready** / **NOT password-reset-ready** / **NOT domain-wide rollout-ready** (22.2.A primary scope için bile single-VM/no-soak baseline)
- **No new runtime evidence claimed** (mevcut PR #1021 evidence reclassified, retake yok; tarihsel boundary korunur)
- **Destructive command flow** (LOCK_USER_LOGIN/DISABLE_LOCAL_USER) — Faz 22.2.A non-domain real device'lerde **non-destructive only** (COLLECT_INVENTORY/inventory_refresh); BE-017 dual-control test cluster fixture ile destructive contract kanıtlandı (PR #1032), prod real device'de değil
- **Trusted signing + EDR allowlist** — 22.2 unlock öncesi 5 evidence sınıfı (Agent + Backend + GitOps + IT) hâlâ geçerli (Codex iter-3 PR-8d/PR-8e); ama 22.2.A scope için "EndpointPilot OU" satırı obsolete (non-domain primary için EndpointPilot OU şart değil; signed distribution + EDR allowlist + privacy/KVKK boundary genel geçer)
- **22.2.B Gate 0 VPN BLOCKER** (gitops #1037) sadece B scope için; A scope için BLOCKER DEĞİL

### Sıradaki adımlar (post-amendment)

1. handoff §5 P1 + PLAN.md row 37 scope split update (bu PR scope'unda)
2. RB-faz22-endpoint-pilot-it-owned.md header note "22.2.B optional acik.local domain-joined runbook" reframe (mevcut §1-§10 acik.local-specific olarak kalır; bu PR scope'unda)
3. PR #1021 evidence doc reclassification note (bu PR scope'unda, küçük üst-not — Codex Q2 (b))
4. gitops #1037 body+title update — "22.2.B optional scope blocker only" (ayrı gh issue edit, no PR)
5. platform-agent #12 status reflect — "Needs Verify; non-blocking 22.2.A repeatability label" (ayrı gh issue edit, no PR)
6. **Follow-up** (ayrı PR, sonraki tur): `RB-faz22-non-domain-windows-pilot.md` (non-domain primary scope için operasyon runbook'u — 2+ device, soak, CI/manual evidence, identity taxonomy, consent/privacy, signed artifact gates)

## 22.2 pre-req docs (22.1'de hazırlanır)

Codex revize: 22.2 Authenticode trusted signing geçişi öncesi 22.1 boyunca aşağıdaki dokümantasyon **netleşir**:

1. **Azure Trusted Signing onaylı mı?** Default tercih ADR'da; sahip onayı + tenant/subscription owner netleşmesi
2. **CI auth modeli**: GitHub OIDC (`azure/login@v2` ile workload identity); uzun ömürlü secret YOK
3. **Certificate profile**: subject metadata, OID, EKU
4. **Timestamp endpoint**: RFC 3161 sağlayıcı (Azure veya DigiCert)
5. **Role assignments**: Azure RBAC — Trusted Signing Identity Verifier + Trusted Signing Certificate Profile Signer
6. **Release promotion modeli**: beta lab artifact (22.1 ephemeral) → IT pilot signed artifact (22.2 Trusted Signing) ayrımı; **artifact naming** + tag scheme
7. **Trusted signed artifact olmadan EndpointPilot dışı yok** invariant doc

Bu dokümantasyon `docs/22-2-trusted-signing-onboarding.md` dosyasında 22.1 son haftasında hazırlanır.

## 22.1 → 22.2 geçiş kriteri (Codex revize sertleştirme)

Dört evidence sınıfı + 5 invariant kontrolü → 22.2 unlock:

### Evidence sınıfları (Up + Functional + Secured ayrı kanıt)

| Track | Evidence |
|---|---|
| **Agent** | CI'den üretilen lab-evidence artifact ile Parallels Win11'de install/start/status/stop/uninstall + tamper protection live; `signtool verify /pa` çıktısı + thumbprint artifact'te. Yerel evidence tarihsel kanıt; release-driven yeniden koş |
| **Backend** | BE-009 OpenFGA live: admin allow + admin deny + unauthenticated deny + tuple seed + audit trace (Up: pod ready + Functional: API 200/401/403 + Secured: deny tarafı RBAC enforced); BE-013 maintenance token: issuance + validation + expiry + revoke + audit (Up + Functional + Secured) |
| **GitOps** | test overlay rollout digest match + pod imageID === GHCR digest + ESO secret sync + 0 placeholder secret kalıntısı (DD-EA-5 enforce kanıtı) |
| **IT** | EndpointPilot OU oluşturuldu + minimum 1 IT-owned Windows 10/11 cihaz inventory baseline (BIOS, OS version, AD join state, agent reachability) |

### Invariant kontrol (yukarıdaki 5 yapılMAYACAK)

22.2 unlock öncesi 5 invariantın **violated edilmediği** docs'ta kanıtla teyit edilir.

## 22.1 PR seti — sertleştirilmiş (Codex 6 PR + IT action)

| # | PR/Action | Repo | Milestone |
|---|---|---|---|
| 1 | Agent CI workflow (go test + lint + Windows amd64 cross-build + paket + ephemeral lab signing + release artifact dry-run) | `platform-agent` | 22.1.0 |
| 2 | Agent BG-EA-1 + gitleaks + SBOM hardening (22.1.0 ile birlikte veya hemen ardı) | `platform-agent` | 22.1.0 |
| 3 | Backend BE-009 OpenFGA live gate (k8s smoke + Up/Functional/Secured runbook) | `platform-backend` (kod) + `platform-k8s-gitops` (manifest reconcile + runbook) | 22.1.1 |
| 4 | Backend BE-013 maintenance token live gate (image + GitOps + Up/Functional/Secured runbook) | `platform-backend` + `platform-k8s-gitops` | 22.1.2 |
| 5 | GitOps lab reconcile + DD-EA-1 + DD-EA-5 minimal ESO allowlist | `platform-k8s-gitops` | 22.1.3 |
| 6 | Docs evidence/runbook + 22.2 pre-req docs (Trusted Signing onboarding) | `platform-k8s-gitops` | 22.1.3 sonu |
| **IT** | EndpointPilot OU + 1 IT-owned cihaz inventory baseline | **Kullanıcı/IT (PR değil)** | 22.1.IT async |
| 🚫 | Web PR | — | **22.2'ye bırak** |
| 🚫 | Prod deploy workflow endpoint-admin | — | **22.2** |

## Sprint süre

Codex: 1 hafta agresif, **8-10 iş günü daha gerçekçi**. Hedef "22.1 evidence pack üretildi + 22.2 no-go listesi netleşti" — takvim değil **evidence-driven**.

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

Sub-faz roadmap finalized **(HISTORICAL — superseded by 2026-05-24 "22.2 scope amendment" section above; 22.2 split into 22.2.A non-domain primary + 22.2.B `acik.local` optional)**:
- **22.1** (Lab) — agent local state review + GitHub remote bootstrap + Windows artifact packaging + lab-only-evidence imza + backend BE-009/BE-013 paralel + gitops manifest reconcile + EndpointPilot OU hazırlığı
- ~~**22.2** (IT-owned acik.local pilot)~~ → **SUPERSEDED**; see "22.2 scope amendment (2026-05-24)" section for canonical 22.2.A non-domain primary + 22.2.B `acik.local` optional split
- **22.3** (Restricted) — sınırlı gerçek kullanıcı + EDR allowlist + IT onayı + staged rollout (non-domain primary scope + opsiyonel `acik.local` 800 cihaz gradual)

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
