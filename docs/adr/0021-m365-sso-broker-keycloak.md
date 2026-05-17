# ADR-0021 — Microsoft 365 SSO via Keycloak Identity Brokering

> **Status**: Accepted
> **Implementation State**: scaffolding (PR-0 — bu ADR + config form + idempotent setup script); test-realm apply + smoke pending operator Entra app registration
> **Date**: 2026-05-17
> **Decision authority**: Codex thread `019e365b` (cross-AI architecture consensus — kod yazan Claude, mimari onaylayan Codex)
> **Predecessors**: ADR-0002 (single-host dual-cluster — KC host-compose stateful tier), ADR-0008 (multi-org explicit scope Zanzibar), ADR-0014 (MFE Auth Transport Contract)

## Bağlam

Platforma "Microsoft 365 ile giriş" eklenecek — kurumsal kullanıcılar M365 / Microsoft Entra ID (Azure AD) hesaplarıyla giriş yapabilsin. Mevcut auth durumu (canlı doğrulandı 2026-05-17):

- Keycloak 26.5.5, host-compose (ADR-0002 D6 stateful tier). Prod realm `serban` (`https://ai.acik.com/realms/serban`), test realm `platform-test`.
- `serban` realm: external identity provider **YOK** — 14 kullanıcı, hepsi KC-yerel username/password.
- Public SPA client `frontend` (PKCE); frontend bootstrap ADR-0014 (5-fazlı transport FSM).
- Backend `serban` issuer + JWKS ile JWT doğruluyor; token'da `subscriberId` claim mapper var.
- Authz düzlemi: permission-service + OpenFGA (Zanzibar), ADR-0008 multi-org explicit scope.

Kullanıcı kararları: M365 tenant admin erişimi var; Entra app **multi-tenant**; local username/password login **fallback olarak kalır**.

## Karar

### D1 — Broker pattern
Keycloak `serban` realm'ine Microsoft Entra ID **OIDC identity provider** eklenir. Uygulamalar (frontend + backend) yalnız Keycloak ile konuşmaya devam eder — Microsoft sadece Keycloak'ın upstream IdP'sidir. Frontend/backend kod değişikliği yok; ADR-0014 PKCE akışı aynı kalır.

### D2 — Güvenlik invariantı: authn ≠ authz
Entra'dan gelen kimlik doğrulama sinyali, platform org/scope/authz grant'i **değildir**. ADR-0008 explicit-scope kuralı geçerli: kullanıcı explicit scope atanmadan veri görmez. `organization#member` yalnız tenant binding'dir, data grant değildir.

### D3 — Multi-tenant gating
Multi-tenant Entra app = Microsoft tarafında herhangi bir Entra org kullanıcısı authenticate olabilir. Platform **gated** kalır — primary key Entra `tid` (tenant ID) allowlist; email domain yalnız yardımcı sinyal. İzin verilen tenant listesi `scripts/keycloak/m365-broker-config.json` `allowed_tenants` alanında.

### D4 — v1 link-only / v2 SPI auto-provision
- **v1 (bu ADR scope'u)**: First Broker Login flow **link-only** — "Create User If Unique" DISABLED. Federe giriş yalnız **mevcut** bir `serban` kullanıcısına (doğrulanmış email eşleşmesi) **link** eder. Eşleşme yoksa giriş reddedilir. Sonuç: `subscriberId`/org zaten mevcut kullanıcıda → eşleme işi YOK; `tid`/`oid` audit attribute olarak yazılır. SPI gerektirmez.
- **v2 (ayrı ADR/sprint)**: Custom Keycloak authenticator SPI — `tid` allowlist hard-gate + `entra_tid → org/subscriberId` mapping ile izinli tenant'lar için açık self-onboarding.

v1, Codex `019e365b` "SPI deploy edilemezse → auto-create kapalı, pre-provision/pre-link" fallback'iyle birebir; küçük kullanıcı tabanı (14) + `registrationAllowed=false` posture'ı ile uyumlu.

### D5 — Identity key
Platform kimlik anahtarı email değil, **`tid` + `oid`** (Entra object ID). Email yeniden atanabilir; `tid+oid` kalıcı. v1 link email eşleşmesiyle yapılır ama `entra_oid` kalıcı bağ olarak attribute'a yazılır.

### D6 — Config-as-code
IdP idempotent `kcadm.sh` script (`setup-m365-broker.sh`) ile yönetilir — `setup-impersonation-broker.sh` pattern'i. Repo'ya sanitized desired-state (config JSON, secret HARİÇ) + script + runbook girer. Client secret Vault'tan (`kv/platform/keycloak-m365-broker`) gelir, git'e asla yazılmaz. Full realm-export config-as-code ayrı bir migration işi — bu ADR scope'unda değil.

### D7 — Fazlandırma
Önce `platform-test` realm: IdP + browser smoke + token claim + `/authz/me` + local password fallback kanıtlanır. Sonra `serban` prod. Prod smoke public browser/edge yolundan alınır — internal curl tek başına yetmez.

## Entra app registration spec (operator)

- App type: Web. Supported account types: **"Accounts in any organizational directory"** (multi-tenant work/school; kişisel Microsoft hesapları HARİÇ).
- Redirect URI'lar:
  - `https://testai.acik.com/realms/platform-test/broker/microsoft/endpoint`
  - `https://ai.acik.com/realms/serban/broker/microsoft/endpoint`
- Broker alias `microsoft` — **stable** (alias değişimi redirect URI path'ini değiştirir).
- Scopes: `openid`, `profile`, `email`. v1'de `groups` / `offline_access` / Graph permission YOK.
- Client credential: client secret (6-12 ay expiry, Vault + rotation runbook). Certificate/private_key_jwt daha güçlü posture — v2 değerlendirmesi.
- KC IdP config invariantları: store tokens off, sync mode import (platform-owned attribute'lar korunur), first-broker-login flow stock blind auto-create DEĞİL (D4 link-only), local password fallback kalır.

## Smoke kriterleri (test realm gate — prod öncesi zorunlu)

Microsoft button render + callback · izinli tenant kullanıcısı login (mevcut hesaba link) · eşleşmeyen kullanıcı deny · JWT'de `subscriberId` + `entra_tid`/`entra_oid` · `/api/v1/authz/me` 200 · local username/password fallback hâlâ çalışıyor · logout/relogin.

## Rollback

IdP alias disable/hide veya remove. Local username/password login fallback kaldığı için kullanıcı auth yolu korunur — federe giriş geri alınsa da platform erişimi kesilmez.

## Sonuçlar

- (+) Enterprise SSO; app kod değişikliği yok; broker pattern Microsoft'u izole eder.
- (+) v1 SPI gerektirmez — hızlı, düşük risk.
- (−) v1 link-only: yeni federe kullanıcı self-onboard edemez — admin önce `serban`'da kullanıcıyı oluşturmalı. v2 SPI bunu açar.
- (−) Prod realm config-as-code değil; IdP canlı `kcadm.sh` apply ile yönetilir (script idempotent + runbook ile azaltıldı).

## Referanslar

- Codex thread `019e365b` — M365 broker architecture consensus
- `scripts/keycloak/setup-m365-broker.sh` — idempotent apply script
- `scripts/keycloak/m365-broker-config-form.html` — operator config input formu
- `docs/operations/RUNBOOKS/RB-m365-sso-broker.md` — operator runbook
- ADR-0008 (multi-org explicit scope), ADR-0014 (MFE auth transport)
