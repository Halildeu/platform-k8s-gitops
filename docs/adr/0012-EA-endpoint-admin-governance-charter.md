# ADR-0012-EA — Endpoint Admin Service Governance Charter

> **Status**: DRAFT (Faz 22 başlangıç, kullanıcı 5-clarify pending)
> **Date**: 2026-05-01
> **Sprint**: "Prod post-cutover compliance" PR-8
> **Codex thread**: `019dd895-17c1-79f0-b652-e316f64d4d79` (mutabakat raporu PR #270, iter-3 AGREE) + `019de00f-4b40-75c1-8ead-01b79c5819c1` (sprint review)
> **Provenance**: Cross-repo governance assessment `docs/2026-04-29-endpoint-admin-service-uyum-mutabakati.md` (962 satır, PR #270 merged)
>
> **Konvansiyon**: ADR-0012 numarası mevcut ([@RequireModule WebMvcTest defer]); bu charter `0012-EA` (Endpoint Admin) namespace'i ile ayrı dosya.

## Bağlam

Faz 22 ile yeni service: **endpoint-admin-service** — Go + Windows agent + REST/queue admin API. Hedef: organizasyondaki Windows endpoint'lerin (Parallels lab + IT-owned domain VM + gerçek user device) merkezi yönetimi (group policy push, command exec, audit, identity discovery).

**Cross-repo bağlantılar** (PR #270 mutabakat):
- Manifest aynı repo + aynı namespace + G7 Operational Isolation (repo bölünmez)
- OpenFGA tuple writer permission-service üstünden (cross-service tuple discipline)
- D35-EA ladder (0..5) D35 Zanzibar ladder ile paralel ama ayrı domain
- ADR-0011 governance layer pattern (DD/AC/BG) → endpoint-admin için "DD-EA-1..7 + BG-EA-1" analog

## Karar (DRAFT)

### Architecture

**Service profil**:
- Manifest: `kustomize/base/apps/endpoint-admin-service/`
- Namespace: `platform-prod` (prod) + `platform-test` (test) — D6 stateful PG/KC/Vault paylaşır
- Image: `ghcr.io/halildeu/endpoint-admin-service:<digest>` (D30 immutable, deploy workflow `deploy-backend-prod.yml` benzeri ayrı `deploy-endpoint-admin-prod.yml`)
- Replicas: prod 2 (zero-downtime), test 0 default (D17 scale-to-zero)
- Secrets: ESO yoluyla Vault'tan (`kv/platform/endpoint-admin/*`)
- Authz: permission-service Zanzibar plane'i kullanır; ayrı OpenFGA store değil

### Authorization model (`@RequireModule` analog)

Go middleware: `RequireScope(scope, action)`:
- `scope`: `endpoint`, `policy`, `command`, `inventory`, `audit`
- `action`: `view`, `assign`, `execute`, `signoff`, `revoke`

OpenFGA tuple shape: `(user:<id>, can_<action>, scope:<scope-id>)`. Tuple writer endpoint-admin-service değil, **permission-service** (cross-service tuple discipline; ADR-0011 BG-1 ile uyumlu).

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

**Default sağlayıcı**: Azure Trusted Signing (Codex iter-3 AGREE: lab-only self-signed YETMEZ; gerçek RoT zorunlu).
- Image manifest sign: cosign + Azure KMS
- Go binary sign: signtool + Azure cert
- ESO `kv/platform/endpoint-admin/signing-cert` (bootstrap-writer scope)

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

### Pilot tier matrisi

3 sınıf (Codex iter-3):
- **Lab**: Parallels lab — full destructive test
- **Pilot**: IT-owned domain-joined VM — read-only + benign command + audit
- **Restricted**: Gerçek user device — read-only inventory + identity discovery + audit (no destructive)

### Password reset 4 connector

(D35-EA-5 destructive sınıfı):
- Lokal Windows (NTLM)
- AD (Active Directory LDAP)
- Entra (Azure AD Graph API)
- M365 (Microsoft Graph API)

### Identity discovery (parallel read-only)

- Lokal Windows: NTLM hash, RID, group membership
- AD: LDAP query (sn, givenName, mail, member)
- Entra: Graph API users.list (paginated)
- M365: Graph API mailboxes.list

**PII boundary (DD-EA-7)**: Discovery sonuçları audit log'a girer ama **logs/error trace'lere PII sızmaz**. Codex iter-2 emphasis.

## Open Questions (kullanıcı clarify)

ADR fill-in için 5 soru — kullanıcı async cevaplayabilir, ADR güncellenir.

### 1. Endpoint-admin kaynak repo URL ve default branch

**Soru**: Endpoint-admin-service kodu hangi repo'da?
- (a) Yeni repo `Halildeu/endpoint-admin-service` (default branch: main)?
- (b) Mevcut platform-backend repo içinde subdir (`endpoint-admin-service/`)?
- (c) Başka organisation/repo?

**Şu anki varsayım** (ADR draft): yeni repo, default branch main, GHCR push pattern platform-backend ile aynı.

### 2. Admin auth realm

**Soru**: Endpoint-admin admin portal hangi Keycloak realm'i kullanır?
- (a) Aynı `platform-test` / `master` (prod) realm — `endpoint:admin` role ekle
- (b) Ayrı realm `endpoint-admin` (test + prod) — operasyonel izolasyon
- (c) Mevcut realm + ayrı client (`endpoint-admin-portal`)

**Şu anki varsayım**: (c) — aynı realm + ayrı client. Codex iter-2 öneri: realm splitting overhead getirir, client-level izolasyon yeterli.

### 3. Pilot tier hangisi başlatılır?

**Soru**: Faz 22 deploy'da hangi pilot tier ile başlanır?
- (a) Sadece Lab (Parallels) — full destructive test, dış kullanıcı yok
- (b) Lab + Pilot (IT-owned VM) — paralel, audit boundary doğrulama
- (c) Pilot + Restricted (gerçek user) — production tier zaten

**Şu anki varsayım**: (a) Lab first, Pilot ve Restricted sonraki sub-faz (22.2, 22.3).

### 4. Code signing provider ilk hedef

**Soru**: Code signing sağlayıcısı:
- (a) Azure Trusted Signing — yıllık ücretli, gerçek RoT
- (b) Self-signed lab-only — geçici, prod-not-allowed
- (c) Başka sağlayıcı (GlobalSign, Sectigo)?

**Şu anki varsayım**: (a) Azure Trusted Signing (Codex iter-3 AGREE: gerçek RoT zorunlu).

### 5. 5 domain inventory otorite

**Soru**: 5 domain (Lokal Windows, AD, Entra, M365/hybrid, device ownership) için authoritative kim?
- IT manager (organizasyon içi)
- Cloud admin (Entra/M365)
- Endpoint-admin-service kendi keşif (probe-based)
- Hibrit (her domain için ayrı kaynak)

**Şu anki varsayım**: Hibrit — endpoint-admin probe-based discovery + IT manager authoritative reconciliation (manuel review gate).

## Sonuç (DRAFT)

Bu ADR draft Faz 22 kickoff için. PR-8 ile **charter çerçevesi** kabul edildi (ADR + PLAN entry); manifest skeleton PR-9'da. 5 clarify cevabı geldikçe ADR güncelleme follow-up PR'larla.

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
