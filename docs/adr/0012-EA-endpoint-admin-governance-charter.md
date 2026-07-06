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

### Destructive command sınıfları — D35-EA Ladder (Extended, 2026-06-09 reconciliation)

> **§0 Governance Drift Reconciliation (Faz 22.6, Codex `019ea961` REVISE→AGREE):**
> Bu charter'ın eski **düz 0..5** ladder'ı ile 2026-04-29 mutabakat raporundaki
> **4-A..E** modeli çelişiyordu (mutabakat'ta interactive/arbitrary-exec tier'ı
> vardı, burada yoktu). Aşağıdaki **extended ladder** artık canonical'dır;
> traceability için OLD→NEW mapping verilmiştir. **Runtime (özellikle 22.6 remote
> access) bu reconciliation MERGE + [#1388](https://github.com/Halildeu/platform-k8s-gitops/issues/1388) acceptance olmadan açılmaz.**

**Top-level ladder:**
- **D35-EA-0**: Read-only inventory (probe, list)
- **D35-EA-1**: Identity discovery (read user/device metadata)
- **D35-EA-2**: Benign command (non-destructive: notification, metadata fetch)
- **D35-EA-3**: Configuration push — **yalnız non-destructive, reversible,
  policy-bounded config** (örn. reversible policy/registry tweak) — **dual-control
  gate**. *Sınırlayıcı kural: güvenlik kapatma, service-disable, network-isolate,
  registry ile tamper/credential-exposure → 4-A/4-C/4-E/4-F'ye yükselir (tier
  escalation bypass kapalı).*
- **D35-EA-4**: **Privileged / Destructive family** (sub-class'lı) — **dual-control + audit immutable**:
  - **4-A** bounded-remediation (service start/stop/disable, network-isolate, restart) — maker≠checker
  - **4-B** uninstall / decommission / **wipe** — dual-control + short-TTL + device-bound + single-use
    - **4-B-WIPE** (`system_format` / disk-wipe): irreversible data-destruction, **DEFAULT RED**, non-pilot, stricter gate (uninstall'dan ayrı risk profili)
  - **4-C** tamper-bypass — M-of-N (2/3) + time-box + auto-reenable + post-action audit
  - **4-D** password-reset (local/AD/Entra/M365) — test persona / IT-live M-of-N + ticket consent
  - **4-E** arbitrary / constrained-command-exec — **DEFAULT RED**; per-command allowlist + cooldown + command transcript + stdout/stderr redaction + hash-chain (**no video/screen recording**; transcript evidence **zorunlu**)
  - **4-F** interactive-remote-session (Faz 22.6, **YENİ**) — **DEFAULT RED**:
    - **4-F-PTY** full PTY/PowerShell: attended + M-of-N + cooldown + max-duration + **terminal-I/O recording MANDATORY** (tty/asciicast-style immutable transcript, video değil)
    - **4-F-REMOTE-CONTROL** screen/RDP relay: en sıkı, last/RED + **video recording MANDATORY** + input-event metadata; clipboard/drive/printer/file-transfer ayrı RED capability
    - **4-F-break-glass** unattended: pilotta KAPALI; explicit break-glass policy objesi + M-of-N
- **D35-EA-5**: **Pilot Endpoint Functional** — tier-restricted (IT-owned domain-joined VM)

**OLD (flat) → NEW (extended) mapping:**
| OLD | NEW |
|---|---|
| D35-EA-4 Service control | 4-A bounded-remediation |
| D35-EA-5 `software_uninstall` | 4-B uninstall |
| D35-EA-5 `system_format` | 4-B-WIPE |
| D35-EA-5 `password_reset` | 4-D password-reset |
| D35-EA-5 `service_disable` / `network_isolate` | 4-A bounded-remediation |
| (yok) | 4-E arbitrary-exec, 4-F interactive-session (mutabakat 4-A..E + yeni 4-F) |
| D35-EA-5 "pilot" semantiği | D35-EA-5 (pilot, korunur) |

**Dual-control**: 2 farklı user (her biri `endpoint:admin` rol) + approval gate;
ADR-0010 §2.5 boundary matrix. **Anti-coercion:** approver insan + role-distinct
+ asla requester (break-glass dahil). Detay broker tasarımı: [ADR-0033](0033-faz-22-6-remote-access-bridge-broker.md).

### Code signing supply-chain RoT

**Tier-aware sağlayıcı** (user 2026-05-02 fill-in):

| Tier | İmza zorunluluğu | Provider |
|---|---|---|
| Faz 22.1 Lab | Self-signed kabul (`lab-only-evidence` flag ile) | Lab self-signed cert (Parallels lab içinde geçerli) |
| Faz 22.2 IT-owned pilot | **Authenticode trusted signing ŞART** | **Azure Trusted Signing** (default tercih) |
| Faz 22.4 Restricted (historical, ex-22.3 — renamed 2026-05-26) | Authenticode + EDR allowlist + audit | Azure Trusted Signing veya alt. (DigiCert KeyLocker, Azure Key Vault HSM, on-prem HSM — IT/regülasyon ihtiyacına göre) |

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

### Governance guard (DD-EA + BG-EA) — 8 canonical + 2 proposed (DD-EA-8, DD-EA-9)

> **Numbering reconciliation (2026-06-09):** Canonical DD-EA-1..7 numaralandırması
> **korunur** (mutabakat raporundaki farklı 4/6/7 etiketleri drift idi; canonical
> bu charter'dır). **DD-EA-8 (Faz 22.6) ve DD-EA-9 (Faz 22.8) PROPOSED**'tur —
> **henüz CI gate olarak canlı DEĞİL**; toplam "10 guard" (DD-EA-1..9 + BG-EA-1)
> yalnız #1388 migration + CI implementasyonu sonrası geçerli olur.

ADR-0011 analog:
- **DD-EA-1**: Manifest contract drift (kustomize render bytes)
- **DD-EA-2**: OpenFGA tuple writer (only permission-service)
- **DD-EA-3**: Image digest pin (deploy workflow strict mode, ADR-0011 D30 ile uyumlu). **Update/release-channel sub-requirements (2026-06-09 extension):** agent update için **release-manifest digest pin** + **downgrade/rollback prevention** (version monotonicity) + **staged rollout + kill-switch**.
- **DD-EA-4**: Code signing verify — **container image: `cosign verify` on deploy**; **Windows agent / session artifacts: Authenticode + release-manifest signature** (tek "cosign" Windows imzasını temsil etmez). **Sub-requirements:** M-of-N release approval + **no signing material in image** (supply-chain RoT, build-time CI).
- **DD-EA-5**: Vault secret path (kv/platform/endpoint-admin/* allowlist; broker için ayrı `kv/platform/remote-access-broker/*`)
- **DD-EA-6**: Destructive command audit log (immutable storage)
- **DD-EA-7**: Identity discovery PII boundary (no PII in logs)
- **DD-EA-8** *(PROPOSED, Faz 22.6 — henüz CI gate canlı değil)*: **Remote Session Governance Guard** — CI gate (specified): capability → approved D35-EA tier map; 4-F için recording-required enforce; unattended yalnız break-glass policy objesiyle; **disabled feature advertise edilemez** (AG-013 precedent). Detay: [ADR-0033](0033-faz-22-6-remote-access-bridge-broker.md). *(Update-channel semantics DD-EA-3/DD-EA-4 altında korunur; ayrı guard'a çıkmaz.)*
- **DD-EA-9** *(PROPOSED, Faz 22.8 — henüz CI gate canlı değil)*: **Data Collection Governance Guard** — CI gate (specified): **bounded allowlist + agent-hardcoded denylist (class-based, policy ile gevşetilemez) + path canonicalization-before-decision (symlink/junction/UNC/ADS/long-path/container) + backend server-side mirror + dry-run-before-content + manifest-before-upload + post-upload quarantine DLP + disabled-not-advertised**. Ayrı **DC-EA data-collection severity axis** ile birlikte (aşağıda). Detay: [22.8 plan](../faz-22-endpoint-data-protection-plan.md) + [ADR-0035 evidence-storage-contract](0035-evidence-storage-contract.md).
- **BG-EA-1**: Per-PR boundary declaration (ADR-0011 BG-1 analog)

### DC-EA — Data-Collection Severity Axis (Faz 22.8, PROPOSED, D35-EA'dan AYRI)

> D35-EA "hangi agent action sınıfı çalışıyor?"; **DC-EA "data riski nedir?"**
> sorusuna cevap verir. İkisini karıştırmak ("read-only" kelimesi exfil riskini
> gizler) yasak. PROPOSED — runtime copy #1388 + §0 migration + DPO/legal olmadan yok.

- **DC-EA-0**: data collection disabled / capability absent (default)
- **DC-EA-1**: metadata-only dry-run — **içerik OKUNMAZ, hash YOK**
- **DC-EA-2**: bounded scheduled backup — company-managed allowlist + dual-control/policy
- **DC-EA-3**: offboarding company-data recovery — HR/IT/DPO gated + manifest review
- **DC-EA-4**: forensic collection — legal `case_id` + M-of-N + chain-of-custody
- **DC-EA-RED**: credential / browser profile / token / private-key / mailbox cache / DPAPI / registry hive / password-manager → **HER ZAMAN DENY**

> **DC-EA-RED "always deny" = routine / backup / offboarding için MUTLAK.** Forensic'te
> mahkeme kararı RED sınıfa erişim gerektiriyorsa bu 22.8C normal akış değildir:
> ayrı **legal/judicial exception + explicit case order + break-glass/legal-hold gate**.

### Pilot tier matrisi (user 2026-05-02 fill-in)

| Tier | Domain scope | Cihaz | Destructive | Imza | Audit |
|---|---|---|---|---|---|
| **22.1 Lab** | Parallels lab + lab-only AD veya none | Kontrolllü Windows test ortamı, gerçek kullanıcı yok | Lab içi tam destructive test | Self-signed (`lab-only-evidence`) | Local audit yeterli |
| **22.2 IT-owned pilot** | **`acik.local` domain only** (BOREAS/CESS kapsam dışı) | 1-3 IT-owned domain-joined Windows 10/11 + ayrı `EndpointPilot` OU + test domain user | Agent enrollment + heartbeat + inventory + identity discovery + maintenance token akışı (read + benign + scoped destructive) | **Authenticode trusted signing ŞART** (Azure Trusted Signing) | Audit immutable storage |
| **22.4 Restricted (historical, ex-22.3 — renamed 2026-05-26)** | acik.local + (sonra) BOREAS/CESS | Sınırlı gerçek kullanıcı/canlı cihaz | Code signing + EDR allowlist + audit + rollback + IT onayı şart | Authenticode + supply-chain pipeline | Full audit + dual-control |

**Şu an scope**: Sadece `acik.local`. **`BOREAS` ve `CESS` Faz 22.1/22.2 dışı** (3-domain inventory ID-001 altında future expansion).

**Faz 22.2 password reset**: scope-locked — `acik.local` only. Faz 22.4'e kadar (historical numbering — eski 22.3 Restricted artık 22.4 Restricted, §22.3 scope addition mass deployment kanalı ile ayrı):
- `local Windows` (NTLM, agent local) ✓
- `AD acik.local` (LDAP scoped query) ✓
- Entra → out of scope (BOREAS/CESS hibrit gerek)
- M365 → out of scope (aynı)

### Password reset connector (revised — acik.local first)

(extended ladder: **4-D password-reset** sınıfı — eski düz-ladder'da D35-EA-5 altındaydı; **Faz 22.2'den itibaren**):
- **Lokal Windows** (NTLM, agent-side) — Faz 22.1 lab + Faz 22.2 pilot
- **AD `acik.local`** (LDAP scoped query) — Faz 22.2 pilot
- **Entra (Azure AD Graph API)** — Faz 22.4+ (historical, ex-22.3+) (BOREAS/CESS hibrit gerektirir)
- **M365 (Microsoft Graph API)** — Faz 22.4+ (historical, ex-22.3+) (aynı)

### Identity discovery (parallel read-only, acik.local first)

**Faz 22.1 Lab + 22.2 Pilot scope** (`acik.local` only):
- Lokal Windows: NTLM hash, RID, group membership
- AD `acik.local`: LDAP query (sn, givenName, mail, member) — **scoped query**, full forest crawl YOK
- Probe-based commands: `Get-ADDomain`, `Get-ADForest`, `Get-ADTrust`, `nltest`, `dsregcmd` (agent-side)

**Future expansion (Faz 22.4+, historical numbering)**:
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
| 22.4 Restricted pilot (historical, ex-22.3) | Sınırlı gerçek kullanıcı/canlı cihaz; code signing + EDR allowlist + audit + rollback + IT onayı şart |

**Şu an scope**: Sadece `acik.local`. **BOREAS ve CESS Faz 22 dışı**.

### 4. Code signing provider ilk hedef

**RESOLVED**: Tier-aware. **Azure Trusted Signing default** (22.2'den itibaren mandatory).

| Tier | İmza | Provider |
|---|---|---|
| 22.1 Lab | Self-signed kabul (`lab-only-evidence` flag ile açıkça işaretli) | Lab self-signed cert |
| 22.2 IT-owned pilot | **Authenticode trusted signing ŞART** | Azure Trusted Signing (default) |
| 22.4 Restricted (historical, ex-22.3) | Authenticode + EDR allowlist + audit + rollback | Azure Trusted Signing veya alt: DigiCert KeyLocker, Azure Key Vault HSM, on-prem HSM (IT/regülasyon ihtiyacına göre) |

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
- Domain-wide deployment **22.4+ scope (historical, ex-22.3+)** (gradual rollout, EDR allowlist + IT onayı şart)

## 22.1 invariantları — yapılMAYACAK (Codex revize)

22.1 boyunca **kesinlikle yapılmaz**:

- ❌ **Password reset** (lokal SAM, AD, Entra, M365 — hepsi Faz 22.2+ scope; AG-016 BLOCKED)
- ❌ **Arbitrary file access** (Desktop/Documents/Downloads whitelist 22.2+; AG-017 RISK gate)
- ❌ **Destructive command execution** (D35-EA-3/-4/-5 dual-control gate 22.2+)
- ❌ **BOREAS / CESS** domain işlemleri (initial scope acik.local only; 22.4+ historical, ex-22.3+)
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

### Faz numbering note (2026-05-26)

Faz 22 sub-track numbering reassignment:
- **Eski "Faz 22.3 Restricted" tier** (advanced production pilot, code signing + EDR + audit + rollback + IT onay) artık **"Faz 22.4 Restricted"** olarak adlandırılır (semantik aynı, sadece numara değişti).
- **Yeni "Faz 22.3 scope addition"** (aşağıda) domain-wide mass deployment kanalı için kullanılır (ADR-0029, MSI + AD CS + GPO Software Installation).
- **Yeni "Faz 22.5 Software Deployment Quick Wins"** agent yüklendikten sonra ücretsiz WinGet + Approved Software Catalog ile yazılım inventory/install yüzeyini açar; 22.3 dağıtım kanalı yerine geçmez.
- Tarihsel referanslarda hâlâ "22.3 Restricted" görülebilir; semantik olarak 22.4 Restricted ile eş.
- Çakışma kuralı: §22.3 = scope addition (mass deployment); 22.4 = restricted tier (historical, ex-22.3); 22.5 = software deployment quick wins.

## 22.3 scope addition — Domain-wide mass deployment (2026-05-26)

> **User decision 2026-05-26**: 9-saatlik AGENTPC2 (10.9.2.98) GPO Scheduled Task pilot attempt fail oldu (cross-subnet firewall block DC 10.9.10.x → corp PCs 10.9.2.x + GPO Scheduled Task pattern unreliable). Discovery value: corp domain (~800 PC) için **manuel self-install çalışmaz, centralized mass deployment gerekir**. Kullanıcı pivot HYBRID (ManageEngine intermediate) reddetti, **Plan A** seçti (mevcut Faz 22 yapısı korunur + 22.3 domain-wide mass deployment scope ADD). **Bu amendment DEĞİL, ADDITION** — Faz 22.2 scope sub-track'leri (22.2.A non-domain primary + 22.2.B `acik.local` opsiyonel) **olduğu gibi korunur**; 22.3 paralel **üçüncü sub-track** olarak eklenir. Canonical ADR: [`docs/adr/0029-faz22-mass-deployment-mtls-msi-gpo.md`](./0029-faz22-mass-deployment-mtls-msi-gpo.md). Codex strategic thread `019e665f` (iter-1/2/3 absorbed) + iter-4 review thread `019e667f` REVISE iter-3 absorb in PR #1078 (gitops, cross-AI peer review chain — provider OpenAI xhigh reasoning effort).

### Sub-scope position (22.2 / 22.3 relationship)

| Sub | Tanım | Channel | Status (2026-05-26) |
|---|---|---|---|
| **22.2.A** | **Non-domain Windows primary** (workgroup / standalone / BYOD) | **Manual install** (operator/user-initiated) — agent installer + token/cert self-enrollment | **PRIMARY KORUNUR** — 22.3 amendment etmez |
| **22.2.B** | **Domain-joined IT pilot** (`acik.local` test PC subset) | **Manual install** (operator/IT-initiated) — 22.2.A ile aynı installer | **OPSIYONEL KORUNUR** — operator-bound (VPN/DC/EDR/signing) |
| **22.3** | **Domain-wide mass deployment** (`acik.local` ~800 PC) | **Automated channel** — MSI fixed UpgradeCode + GPO Software Installation Computer-assigned + AD CS code-signed + mTLS self-enroll (SAN URI:adcomputer:{objectGUID} primary identity) | **NEW** — paralel üçüncü channel, ramp 5→50→800 |

### Cross-scope invariants

- **Tek backend** (`endpoint-admin-service`) — 22.2.A/22.2.B/22.3 aynı device API sözleşmesini kullanır: test/pilot canonical base `https://mtls.testai.acik.com/api/v1/endpoint-agent`; prod canonical base `https://mtls.ai.acik.com/api/v1/endpoint-agent`
- **Tek agent codebase** (`platform-agent`) — `--auto-enroll` flag 22.3 için MSI ile yüklenir, 22.2.A/B manual install'da CLI invocation
- **Identity model: PARTIAL invariant — backend/audit ortak, enrollment binding farklı**:
  - **22.2.A non-domain primary** (workgroup/BYOD): AD computer object YOK → SAN URI:adcomputer:{guid} mekanizması GEÇERSİZ; manual single-use bearer token enrollment + future cert-based identity (TPM machine cert ile self-signed veya AD CS bypass — şu an açık)
  - **22.2.B `acik.local` opsiyonel IT pilot**: domain-joined manual installer ile bearer-then-mTLS-cert pattern (22.3 öncesi pattern; small-scale, AD CS template kullanılabilir ama small-scale için manual cert mint OK)
  - **22.3 domain-wide mass deployment**: AD CS SAN URI:adcomputer:{objectGUID} primary (GPO startup script + certreq 3-step flow + DirectorySearcher RSAT-free); mTLS-cert-only auto-enroll
  - **Common**: backend processing step 9 stable identity (22.3 SAN URI; 22.2.A/B bearer-derived device_id); audit chain BE-016 + BE-017 ortak
- **Tek audit chain** — BE-016 hash-chain + BE-017 dual-control 22.3 destructive command'lerde de uygulanır (no scope-specific bypass)
- **Test persona ayrı** — HARD RULE — Kullanıcı Aktif Credential'ına Dokunma YASAK: 22.3 pilot smoke için Halil'in kendi domain user'ı (`halilkocoglu@acik.local`) kullanılmaz; test persona (örn. `endpoint-agent-test-1` machine account + smoke service account) ile sınırlı

### Operator/IT-bound prerequisites (22.3 specific)

22.3 kanal için **operator/IT-bound** preflight artifact'ler (agent docs-only; operator execution gerekli):

- AD CS role install + machine-cert template (TPM-attested) + AutoEnrollment GPO
- AD CS code-signing template + agent-team-restricted issuance + revocation pipeline
- MSI UpgradeCode GUID assignment (immutable, governance-tracked)
- GPO Software Installation Computer-assigned package + WMI filter (test OU scope)
- Cross-subnet firewall rule (`mtls.testai.acik.com:443` reachability from corp PC subnets — 9-saatlik AGENTPC2 fail'in root cause'u; bu olmadan 22.3 pilot kuru çalışır)
- EDR allowlist (CrowdStrike/Defender — agent binary + persistence + scheduled task pattern false-positive yok)
- 5-PC pilot OU + 50-PC ramp OU + 800-PC production OU (separate scope, isolated rollback)

22.3 source-side iş (agent --auto-enroll feature, MSI WiX, backend mTLS endpoint, AD CS preflight script) **agent-actionable**; AD CS deployment + GPO konfigürasyonu + corp firewall rule + EDR allowlist + pilot OU **operator/IT-bound** (HARD RULE — Pre-Production Full Authority: agent end-to-end koşar ama irreversible/operator-only adımlar IT execution).

## 22.5 scope addition — Software Deployment Quick Wins (2026-05-27 → truth refresh 2026-05-29)

> **User decision 2026-05-27**: Endpoint-Enes agent üzerinden ücretsiz ve sektör standardına yakın program yönetimi isteniyor. Varsayılan yol **Microsoft WinGet + Approved Software Catalog**. Intune/SCCM/PDQ gibi ürünler referans/entegrasyon adayıdır; ilk yol değildir.
> **3-AI review absorb 2026-05-27**: Claude Code, Codex ve MiniMax/Mavis verdict'i **REVISE**. Yön doğru; install açılmadan önce backend catalog, command contract, detection/audit ve web visibility kapıları kapanmalı. Agent read-only AG-025/AG-026 source foundation başlamış durumdadır.
> **Truth refresh 2026-05-29 (this section)**: §22.5.1 / §22.5.1A / §22.5.1B / §22.5.1C / §22.5.2 (hardware quick wins only — AG-035 + BE-022 + BE-022Q + WEB-013; posture AG-030-033 still TODO) / §22.5.3 / §22.5.3A / §22.5.3B (BE-023 + WEB-014 only — AG-036 still TODO) source-MERGED across 4 repos; **backend/frontend/GitOps slices testai LIVE; agent slices HALILKOOLUB735 LIVE / operator-bound where SRB-AIDENETIMPC binary distribution still pending**. §22.5.4 source-MERGED (BE-021A + BE-021 + AG-027 LIVE source code); **end-to-end live install pilot smoke chain not yet executed** (runbook ready); AG-027L installer log redaction SOURCE-MERGED 2026-05-29 PM (platform-agent PR #32 `4f5e152`); **binary distributed + service health PASS; command-path live verification pending** (post-merge install + sentinel scrub + exit-code/duration wire-path check). §22.5.5 LIVE — full chain in WEB-014D (PR #683 + perf follow-up #693): `SoftwareCatalogTab.tsx` "Kur" button per catalog row → `InstallPreflightModal.tsx` PASS/WARN/BLOCK → `useCreateInstallMutation()` dispatch POST → "Son Kurulumlar" audit panel via `useListInstallAuditsQuery` with auto-refetch tag. Truth correction 2026-05-29 PM: original truth-refresh PR mis-flagged this as pending; verified by source-read (PR #1136 follow-up). §22.5.6 / §22.5.8 / §22.5.X unchanged. See `docs/state/current-state.md` 2026-05-29 PM delta + `docs/faz-22-software-deployment-plan.md` §0.1bis + §9.bis for honest acceptance gates and PR references.

### Position

22.5, agent dağıtım kanalı değildir. 22.2.A/22.2.B/22.3 ile agent cihaza geldikten sonra çalışan yazılım yönetimi kabiliyetidir.

| Sub | Tanım | Status (2026-05-29 refresh) |
|---|---|---|
| **22.5.1** | `AG-025` installed software inventory + `AG-026` WinGet readiness | **MERGED + LIVE** (`platform-agent` PR #20 `0eff2db`) |
| **22.5.1A** | `AG-025H` lightweight/full software inventory guard | **MERGED + LIVE** (`platform-agent` PR #21 `f3b5c68`) |
| **22.5.1B** | `WEB-011` read-only software + WinGet readiness visibility | **MERGED + LIVE** (`platform-web` PR #674 `70a038ac`) |
| **22.5.1C** | `AG-026A` WinGet source / egress readiness (source list, package query, proxy/TLS summary; install/upgrade yok) | **MERGED + LIVE** (`platform-agent` PR #22 + PR #25 `1e915a2` defensive wire shape; HALILKOOLUB735 LIVE verify 2026-05-29) |
| **22.5.1D** | `AG-026B` `--enrollment-token` CLI flag + `AG-026C` install.ps1 service env regkey + post-install enroll gate + `AG-026D` HMAC DPAPI persistence (operator enrollment friction) | **MERGED + LIVE** (`platform-agent` PR #26/#27/#28 + PR #29 `-Force` splat fix `97edf17`; HALILKOOLUB735 hydrate proof 2026-05-29) |
| **22.5.2** | `AG-035` hardware/device inventory + `BE-022` ingest/query + `BE-022Q` query API + `WEB-013` view (hardware quick wins) | **MERGED + LIVE** (`platform-agent` PR #24 `ef83531c`; `platform-backend` PR #322 V13 + PR #324 V14 + PR #325 BE-022Q `4ff2ceb4`; `platform-web` PR #700 `26e68658`; cluster digest 2026-05-29 = `sha256:76bacc004f...` sha-e3a0369 post backend #326 + gitops #1130). **BE-022Q LIVE scope = ingest + /latest + /history + web view**; `payload_hash` deep equality SQL `lower(bytea)` grammar bug tracked separately as backend source follow-up |
| **22.5.2 posture residual** | `AG-030` pending reboot + `AG-031` Defender/Firewall/BitLocker + `AG-032` local admin group + `AG-033` disk/RAM/uptime health | TODO |
| **22.5.2A** | `AG-037` Windows Update/hotfix posture + `AG-038` agent self-health/connectivity + `AG-039` critical services + `AG-040` startup/RDP/event summary | TODO |
| **22.5.3** | `BE-020` Approved Software Catalog API + provenance/hash/version policy | **MERGED + LIVE** (`platform-backend` PR #306 PR-A + PR #308 PR-B `5033f1c6`) |
| **22.5.3A** | `BE-020I` software inventory ingest/query path | **MERGED + LIVE** (`platform-backend` PR #310 + #311 shape fix) |
| **22.5.3B** | `BE-023` catalog compliance evaluator + `WEB-014` compliance/outdated view | **MERGED + LIVE** (`platform-backend` PR #313 + #314 + #315 `4aa29dd0`; `platform-web` WEB-014A/B/C/D PR #675/#676/#678/#682/#683/#693) |
| **22.5.3B residual** | `AG-036` outdated software inventory | TODO |
| **22.5.3C** | `BE-024` inventory diff/history + `BE-025` prohibited software detection | TODO |
| **22.5.4** | `BE-021A` install dry-run/preflight + `AG-027` approved install command + `BE-021` result/detection/audit | **SOURCE-MERGED, LIVE smoke pending** (`platform-backend` BE-021A PR #312 + BE-021 PR #317/#318/#321; `platform-agent` AG-027 PR #23 `7cf6f14`; 7-Zip end-to-end live dispatch smoke chain not yet executed) |
| **22.5.4 residual** | `AG-027L` installer exit-code/redacted log capture | **SOURCE-MERGED (platform-agent PR #32 `4f5e152`, 2026-05-29 PM); binary distributed + service health PASS; command-path live verification pending** |
| **22.5.5** | `WEB-012` approved install UI + `WEB-015` report/CSV export | **PARTIAL** (WEB-012 ≡ WEB-014D foundation merged PR #683 + #693; explicit pilot dispatch button + audit/result render UI on per-device drawer + WEB-015 CSV export TODO) |
| **22.5.5 ek** | `WEB-017` Endpoint Enrollment Management UI + `WEB-018` Envanteri Şimdi Topla + Donanım dedicated trigger | **MERGED + LIVE** (`platform-web` PR #701 `c0201c08` + PR #702 `e096837b`) |
| **22.5.6** | `AG-028` uninstall/detection + `AG-029` signed self-update | TODO |
| **22.5.8** | `BE-026` deployment rings/tags + `BE-027` maintenance window + `BE-028` rollout throttle/concurrency + `BE-029` approved package bundles | TODO |
| **22.5.X** | `AG-034` SMB/file actions discovery only; runtime deferred until whitelist + RBAC + audit + dual-control design | DEFERRED |

### Guardrails

- Raw shell yok.
- Rastgele URL/EXE/MSI install yok.
- Kullanıcıdan serbest package id alınmaz.
- Agent yalnız backend Approved Software Catalog item id'si ile install adapter'ını çalıştırır.
- Catalog item provenance/hash/version-policy taşır; WinGet community dahil her provider supply-chain kararından geçer.
- Install öncesi source/egress readiness + dry-run/preflight + compliance state
  kanıtlanmadan `AG-027` açılmaz.
- Outdated, prohibited, inventory diff, Windows Update posture ve diagnostics
  ilk aşamada read-only görünürlük sağlar; auto-upgrade, auto-uninstall,
  patch install, service restart, process kill veya registry edit yoktur.
- Rollout ring/window/throttle/bundle kontrolleri tek cihaz pilotundan sonra
  açılır; Faz 22.3 domain-wide MSI/GPO deployment yerine geçmez.
- HKCU software inventory default dışıdır. LocalSystem altında HKCU gerçek kullanıcıyı temsil etmez; HKCU ancak explicit opt-in + privacy review ile eklenir.
- Heartbeat/auto-enroll/lightweight inventory full software scan veya WinGet probe maliyetine yanlışlıkla girmemelidir.
- `includeSoftware=true` full app list'i bilinçli açar; default inventory sadece summary seviyesinde kalır.
- İlk pilot paket 7-Zip (`7zip.7zip`) ile sınırlıdır.
- Detection olmadan success kabul edilmez.
- Install/uninstall audit zorunludur.
- Geniş kapsamlı deployment ve uninstall dual-control + pilot kanıtı sonrası açılır.
- Pending reboot, Defender/Firewall/BitLocker, local admin ve device health işleri read-only inventory olarak başlar.
- Hardware/device inventory de read-only başlar: CPU, RAM, disk, manufacturer/model, BIOS version, TPM status, OS/build ve network summary.
- BitLocker recovery key, credential, product key, bearer token veya tam kullanıcı profili path'i toplanmaz.
- Serial number, MAC ve IP gibi alanlar policy-gated olur; default çıktı hash/masked/summary seviyesindedir.
- Product key, TPM key material, BitLocker recovery key, token veya credential hiçbir Faz 22.5 inventory payload'ında yer almaz.
- SMB/file actions bu scope'ta runtime değildir; yalnız discovery/guardrail çalışmasıdır.

### Related gates

- Domain pilot flow: 22.2.B / 22.3.
- Dual-control destructive command: BE-017 / D35-EA.
- Policy-based deployment: 22.3 MSI/GPO mass deployment.
- EDR allowlist + code signing: 22.2 / 22.3 / 22.4.

### Canonical docs

- Plan: [`docs/faz-22-software-deployment-plan.md`](../faz-22-software-deployment-plan.md)
- Runbook: [`docs/runbooks/RB-faz22-software-deployment-winget.md`](../runbooks/RB-faz22-software-deployment-winget.md)

**Detection surface**: `Win32_ComputerSystem.PartOfDomain` + `Domain` + `Workgroup`; `dsregcmd /status` (`DomainJoined`, `AzureAdJoined`, `WorkplaceJoined`, tenant/device id); MDM/Intune enrollment state.

### Faz 22.2 overall % (Codex Q5 absorb — iki katman)

- **22.2.A non-domain primary**: ~80% (strong evidence — PR #1021 BE-011 + AG-013 + #1032 BE-017 fixture + PR #13 CI automation source + **platform-agent PR #17 (`91ef533d`) AG-021/AG-022 identity source-foundation MERGED 2026-05-26** with `WORKGROUP`/`LOCAL` HALILKOOLUB735 read-only evidence, redact pass clean; **eksik**: self-hosted CI run, 2+ standalone/BYOD device, 24-72h soak, **BE-015 admin identity compliance API**, **AG-024 signed distribution / Authenticode**, **BE-019 KVKK boundary enforce**. *Identity classification **source path** artık DONE (AG-021/AG-022 source-foundation); **field acceptance** — multi-device classification + soak + BE-015 admin API + signed binary — operator/agent-extra gates altında pending; #1044 PASS DEĞİL, #1037 unblocked DEĞİL.*)
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

### Strategy B decision (2026-05-25) — HALILKOOLUB735 domain join + A1 baseline historical

**Trigger**: User 2026-05-25 — "aktif directory diyelim" (HALILKOOLUB735 mevcut VM `acik.local` domain'e join et) + ön koşul "hardiskde yer yok" (fresh VM provision şu an mümkün değil).

**Karar**:
- HALILKOOLUB735 mevcut VM `acik.local` domain'e join edilir (Strateji B)
- Strateji A (fresh ayrı VM domain join) **disk constraint** sebebiyle DEFER (operator action: Mac host cleanup / disk procure / VM disk compress unblock)
- Disk constraint çözülünce Strateji A revisit edilebilir (ek 2 fresh workgroup VM A1 multi-VM #1044 için + 1 fresh domain VM A2.B saf evidence için)

**Pre-condition** (Strateji B operator action chain):
1. **Parallels snapshot** `pre-domain-join-A1-baseline-2026-05-25` (rollback hattı zorunlu — disk +1-3GB delta)
2. **Mac corp VPN connect** (Gate 0 unblock; user 2026-05-25 "VPN bağlı şu an" ✅)
3. **Mac terminal `dig acik.local SRV`** — DC SRV record verify
4. **VM içi PowerShell admin** `Set-DnsClientServerAddress -InterfaceAlias Ethernet -ServerAddresses <corp-dns-ip>`
5. **Gate 0 precheck** reproducer (canonical `RB-faz22-acik-local-vpn-routing-setup.md` §5.3 — DNS/SRV + ports `53` DNS + `88` Kerberos + `135` RPC EPM + `389` LDAP + `445` SMB + `464` Kerberos password + `636` LDAPS + `9389` ADWS + `testai.acik.com:443` backend + `w32tm /stripchart` time sync ≤5min skew) → minimum `53/88/389/445` + time sync PASS şart (dynamic RPC `49152-65535` failure mode görünür dokümante)
6. **`Add-Computer`** — interactive credential (`Get-Credential`)
7. **Post-restart verify** + sanitized smoke + screenshot capture

**Post-action consequences** (truth-sync):
- **A1 baseline (PR #1021) historical mark** — workgroup smoke evidence pre-2026-05-25; yeni evidence doc'ta açık historical note
- **A1 multi-VM (#1044) BLOCKED** — disk constraint sebebiyle 3 fresh workgroup VM şimdi yok; Path 1 (disk cleanup) veya Path 2 (N=2 alternative) operator kararı bekleniyor
- **22.2.B `acik.local` opsiyonel scope unblock** — Gate 0 VPN ✅ + domain join sonrası IT pilot smoke açılır (D29-EA Secured persona + `COLLECT_INVENTORY` domain user context + Kerberos/LDAP/SMB evidence)

**Rollback paths** (sıralı tercih; AD cleanup AYRI GATE — bkz §15.4 önemli düzeltme):
1. **Parallels snapshot restore — VM-local atomic rollback** (recommended). VM state pre-join'e döner ama **AD'deki computer object orphan kalır**; ayrı post-rollback gate ile (a) AD object DN/SAM capture + (b) OU path identify + (c) delete/disable/reset owner kararı + (d) post-cleanup `nltest /dsgetdc:acik.local` + ADUC/PowerShell `Get-ADComputer HALILKOOLUB735` verify gerek. 1dk VM + 5dk AD coordination = ~6dk toplam.
2. `Remove-Computer -UnjoinDomainCredential (Get-Credential) -PassThru -Verbose -Restart` + AD object manual cleanup (operator interactive; AD cleanup yine zorunlu; 5-10dk)
3. VM rebuild from clean install (worst case; disk constraint sebebiyle uygulanamaz)

**Safety gates (rollback öncesi)** — accidental rollback engellemek için:
- Snapshot UUID confirm (`prlctl snapshot-list HALILKOOLUB735`)
- VM powered-off confirm (state=stopped)
- Post-join evidence freeze (rollback yapılırsa kanıt kaybı; operator deliberate decision)
- AD computer object cleanup owner pre-identify (IT/AD admin contact + plan present)
- Backend `endpoint_devices` table stale device decision (decommission via admin REST vs keep for forensic)
- Post-restore checklist: `(Get-WmiObject Win32_ComputerSystem).PartOfDomain = $false` + agent service running + backend stale-device action complete

**Risk register impact** (RB §16 risk register'a explicit row eklenmiştir; bu sub-section impact summary):
- BYOD-specific risk (consent / KVKK / uninstall self-service) — Strateji B HALILKOOLUB735 domain-joined corporate device olduğu için A2 BYOD scope DİŞI; bu risk sınıfı bu pilot tarafından artırılmaz (mevcut R9-A2 BYOD-class korunur, etkilenmez) — **impact note**, ayrı row gerekmez
- **§16 R-NEW row: A1 baseline state loss / historical-only evidence** — PR #1021 workgroup baseline domain join sonrası historical-only; snapshot rollback ile recovery, ama snapshot silindikten sonra reproduce için fresh VM gerek (disk constraint), Severity Low
- **§16 R-NEW row: AD computer object orphan after snapshot restore** — snapshot rollback VM state restore eder ama AD'deki computer object orphan kalır; AD admin coordination + cleanup gate zorunlu, Severity Medium
- **§16 R-NEW row: Disk pressure vs snapshot retention trade-off** — snapshot delta +1-3GB (Windows update / domain join sonrası büyür); uzun retention disk dolma riski, kısa retention rollback window kısalır, Severity Low

**Cross-AI peer review chain (Strateji B karar)**:
- Implementer: Claude (Anthropic) — Session 51 2026-05-25
- Reviewer: Codex (OpenAI) — thread `019e5be4-c665-7422-bb38-7f094522a197` (sequel — A2 BYOD appendix iter chain devamı, Strateji B karar log için yeniden danışma)
- Verdict: pending (post-impl review için yeni Codex turn submission)

**Boundary statement** (Strateji B post-action):
- **NOT production-ready** — single VM domain join, single device evidence, no soak, no rollback rehearsal beyond snapshot test
- **NOT password-reset-ready** — Faz 22.2 scope dışı (BE-017 destructive command fixture-only proven)
- **NOT domain-wide rollout-ready** — pilot scope 1 IT-owned VM; ~800 device domain rollout Faz 22.4+ (historical, ex-22.3+)
- 22.2.B opsiyonel scope smoke evidence → IT pilot smoke kanıt; bu evidence Faz 22.4 restricted tier (historical, ex-22.3) veya prod readiness için ön-koşul değil ama path açar

### Strategy D decision (2026-05-25) — DC-orchestrated domain-joined PC install (Strategy B revize)

**Trigger** — User clarification 2026-05-25 (Strategy B sonrası):
1. "rdp ile bağlıyız vpn üzerinden" — RDP+VPN topology
2. "doğrudan windows kurlu active domain bilgisayaraına bağlaıyım" — RDP target = **acik.local Domain Controller**
3. "domainin hepsi burda" — DC = domain authoritative source
4. "diğer bilgisayarlara kurulum yapabilir miyiz" — domain-joined corp PC'lere DC'den agent install

**Karar**:
- **Strategy B (Mac Parallels VM HALILKOOLUB735 domain join) GEREKSİZ** — HALILKOOLUB735 A1 baseline (PR #1021) dokunulmaz korunur
- **Strategy D primary**: DC-orchestrated PowerShell Remoting (`Invoke-Command`) ile domain-joined corp Windows PC'lere agent install + smoke
- DC kendisinde agent install YASAK (critical infrastructure scope dışı)

**Topology**:
```
Mac (developer host)
  ├─ Mac Parallels VM HALILKOOLUB735 (workgroup, A1 baseline — Strategy A scope, dokunulmaz)
  └─ Mac corp VPN → RDP → acik.local DC server
                            ├─ Read-only AD inventory (Get-ADComputer/User/OU)
                            └─ PowerShell Remoting (Invoke-Command) → domain-joined corp PC'ler (Strategy D pilot targets)
                                                                          ├─ Agent install (signed binary)
                                                                          ├─ Enroll + heartbeat + COLLECT_INVENTORY smoke
                                                                          └─ Audit verify
```

**Strategy D'nin avantajları (Strategy A/B/C yerine)**:
- **A1 baseline (HALILKOOLUB735) korunur** — historical mark gerek yok
- **Disk constraint sorun değil** — Mac VM provisioning gerek değil
- **Domain join komutu YOK** — corp PC'ler zaten domain-joined
- **Multi-PC paralel install** (1-3 hedef) → multi-device evidence A1 multi-VM (#1044) için workgroup alternatifi (domain-joined N-PC variant)
- **A1 multi-VM (#1044) için A1 baseline temiz kalır** — gerek olduğunda 2 fresh workgroup VM ayrı kapı (disk açılınca)
- **22.2.B IT pilot scope substantive evidence** — #1037 BLOCKED → Active

**Pre-condition** (operator + IT/SOC coordination):
1. ✅ Mac VPN bağlı + RDP DC erişim (user 2026-05-25 confirmed)
2. ✅ DC üzerinde AD PowerShell module + Get-AD* read access (Domain Admin)
3. ⏳ Hedef PC'ler seçim (1-3 candidate; EndpointPilot OU varsa oradan)
4. ⏳ WinRM enabled hedef PC'lerde (`Test-WSMan` per-target)
5. ⏳ Hedef PC backend reachable (`Test-NetConnection testai.acik.com:443` per-target)
6. ⏳ IT/SOC onayı (EDR allowlist + corp device agent install consent)
7. ⏳ Agent installer transfer yolu (Mac → DC → hedef PC; SMB share / RDP file drop)
8. ⏳ Backup/restore yolu IT teyit (image backup veya System Restore Point — uninstaller fallback default)

**Post-action consequences** (truth-sync):
- A1 baseline (PR #1021) **DOKUNULMAZ** — historical mark gerek yok; Strategy B historical (PR #1063) alternatif kalır
- A1 multi-VM (#1044) **BLOCKED disk constraint** + **Alternative path açık** (Strategy D N-PC variant)
- 22.2.B IT pilot scope (#1037) **BLOCKED Gate 0 VPN → Active** (DC erişim ✅)
- #1015 IT pilot readiness umbrella → Eligible (DC + domain PC erişim)

**Rollback paths** (per-target):
1. **Agent uninstall** via `installer.ps1 -Uninstall` (PowerShell Remoting Invoke-Command)
2. Service stop + remove + install dir + log dir cleanup
3. Backend `endpoint_devices` decommission (admin REST `DELETE`)
4. **AD computer object UNCHANGED** — domain join kalır (Strategy B'den farklı; Strategy D agent install/uninstall scope sadece)
5. IT'den image backup veya System Restore Point varsa (operator karar; default uninstaller yeterli)

**Risk register impact** (RB §16'ya cross-reference + Strategy D-specific):
- **WinRM blast radius / Domain Admin credential compromise** — PowerShell Remoting credential exposure = domain-wide attack surface; Severity **High** (Codex iter-1 HIGH absorb); mitigation: **JIT/scoped installer admin** (separate account, time-bound, EndpointPilot OU scope) + **EndpointPilot OU scoped WinRM/GPO** (no domain-wide WinRM enable) + **PowerShell transcription + script block logging** + **target allowlist** (per-pilot session) + **post-pilot disable/revert** (rollback installer admin + revoke WinRM GPO)
- **EDR allowlist coverage gap** — eksik allowlist = EDR alarm flood + missed real threat; Severity Medium; mitigation: SOC pre-coordination + per-target ticket; **10-item allowlist** (agent SHA + signer/thumbprint + service name + install path + process tree + parent context + service creation + install script hash + network destination + proxy/TLS inspection — detection outcome explicit)
- **Multi-PC consent/awareness** — corp-managed device A2 BYOD scope DIŞI; ama hedef PC kullanıcılarına bilgilendirme iyi pratik (notification dağıt); Severity Low; mitigation: IT/manager pre-notification
- **Agent installer transfer security** — Mac → DC → hedef PC chain; transit'te binary tamper riski (Severity Low); mitigation: **Mac-side authenticated fetch** (private release artifact) + **SHA256 + Authenticode verify** her hop'ta + **DC'ye credential taşınmaz** (Mac-side download, RDP/SMB transfer)

**Cross-AI peer review chain (Strategy D karar)**:
- Implementer: Claude (Anthropic) — Session 51 2026-05-25
- Reviewer: Codex (OpenAI) — yeni thread submission
- Verdict: pending (post-impl review için)

**Boundary statement** (Strategy D post-action, Codex iter-1 HIGH #1 absorb):

- **NOT production-ready** — pilot scope 1-3 lab Windows PC; ~800 device domain rollout Faz 22.4+ (historical, ex-22.3+)
- **NOT password-reset-ready** — Faz 22.2.B scope dışı (BE-017 destructive command fixture-only proven)
- **NOT GPO-mandatory** — pilot install ad-hoc per-target; GPO Software Installation Faz 22.4 production tier (historical, ex-22.3)
- **Trusted Signing MANDATORY pilot install** — Codex iter-1 HIGH #1 düzeltme: 22.2 IT-owned `acik.local` pilot için trusted signing kontratı ADR §138'de zaten **şart**; Strategy D bu kontratı düşürmez. Gerçek install öncesi **signed artifact + Authenticode signature verify hard gate** zorunlu. "A1 SHA-pinned lab-only-evidence" istisnası **Strategy D kapsamında uygulanMAZ** (A1 lab-only-evidence istisnası workgroup Mac Parallels lab smoke için; Strategy D corp PC pilot A1 kapsamı değil).
- **Real install pre-condition** (yeni hard gate): `signtool verify /pa /v /tw <agent.exe>` PASS + Trusted Signing tenant subject match + RFC 3161 timestamp valid + thumbprint allowlist match (operator runbook §2.4 + EDR ticket evidence)
- 22.2.B IT pilot smoke kanıt → Faz 22.4 restricted tier (historical, ex-22.3) önkoşul DEĞİL ama path açar; 22.2.B acceptance multi-PC + 24-72h soak + **signed artifact verify** ile substantive

**Strategy D detailed runbook**: bkz `docs/runbooks/RB-faz22-strategy-d-dc-orchestrated-install.md` (this PR scope).

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
| **22.4 Restricted (historical, ex-22.3 — renamed 2026-05-26)** | Signed MSI + signed update manifest + SBOM + SHA256/SHA512 | Intune / GPO / SCCM (kurumsal dağıtım) + signed update manifest + staged rollout |

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
