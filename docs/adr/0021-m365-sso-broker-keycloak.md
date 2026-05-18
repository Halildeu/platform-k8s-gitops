# ADR-0021 — Microsoft 365 SSO via Keycloak Identity Brokering

> **Status**: Accepted — v1 link-only uygulandı; **v2 auto-provision amendment ile değiştirildi** (D3/D4 superseded — aşağıdaki "v2 Amendment" bölümüne bkz.)
> **Implementation State**: v1 link-only test+prod apply edildi (2026-05-17); v2 auto-provision `platform-test`'te apply + 4-katman verify PASS, prod `serban` apply pending (2026-05-18)
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

### D3 — Multi-tenant erişim sınırı
Multi-tenant Entra app = Microsoft tarafında herhangi bir Entra org kullanıcısı authenticate olabilir. Platform erişim sınırı v1/v2'de farklı:
- **v1 (bu ADR)**: erişim sınırı **link-only** — yalnız mevcut bir `serban` kullanıcısı, re-authentication ile doğrulayarak girer. `tid` (tenant) allowlist (`scripts/keycloak/m365-broker-config.json` `allowed_tenants`) v1'de **audit-only**: `entra_tid` user attribute'una yazılır, girişi reddetmek için kullanılmaz.
- **v2**: custom authenticator SPI `tid` allowlist'i **hard-gate** eder + izinli tenant'lar için auto-provisioning.

v1 "tenant allowlist ile gated" **değildir** — gate link-only + re-auth'tur; allowlist v1'de yalnız audit kaydıdır.

### D4 — v1 link-only / v2 SPI auto-provision
- **v1 (bu ADR scope'u)**: First Broker Login flow **link-only** — `idp-create-user-if-unique` + `idp-email-verification` execution'ları DISABLED. Federe giriş yalnız **mevcut** bir `serban` kullanıcısına bağlanır: aday eşleşme email ile bulunur, kullanıcı mevcut hesabın parolasıyla **re-authentication** yaparak link'i doğrular (kör email-link yok; realm SMTP'siz çalışır). Eşleşme yoksa veya re-auth başarısızsa giriş reddedilir. Sonuç: `subscriberId`/org zaten mevcut kullanıcıda → eşleme işi YOK; `entra_tid`/`entra_oid` audit attribute olarak (`syncMode=FORCE`) yazılır. SPI gerektirmez.
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

Microsoft button render + callback · mevcut `platform-test` kullanıcısı M365 ile login → re-authentication ile mevcut hesaba link · pre-provision edilmemiş (eşleşmeyen) kullanıcı deny · linked kullanıcının KC user attribute'larında `entra_tid` + `entra_oid` (Admin API read-back — v1'de bunlar JWT claim'i **değil**) · JWT'de `subscriberId` (mevcut mapper, değişmedi) · `/api/v1/authz/me` 200 · local username/password fallback hâlâ çalışıyor · logout/relogin.

## Rollback

IdP alias disable/hide veya remove. Local username/password login fallback kaldığı için kullanıcı auth yolu korunur — federe giriş geri alınsa da platform erişimi kesilmez.

## Sonuçlar

- (+) Enterprise SSO; app kod değişikliği yok; broker pattern Microsoft'u izole eder.
- (+) v1 SPI gerektirmez — hızlı, düşük risk.
- (−) v1 link-only: yeni federe kullanıcı self-onboard edemez — admin önce `serban`'da kullanıcıyı oluşturmalı. v2 SPI bunu açar.
- (−) Prod realm config-as-code değil; IdP canlı `kcadm.sh` apply ile yönetilir (script idempotent + runbook ile azaltıldı).

## v2 Amendment (2026-05-18) — Auto-Provisioning

> **Status**: Accepted · **Decision authority**: Codex thread `019e3b72` (cross-AI consensus)
> **Supersedes**: D3 + D4 (v1 link-only) — erişim sınırı ve provisioning v2'de değişti. D1, D2, D5, D6, D7 geçerli kalır.

**Neden**: v1 link-only canlıda yetersiz çıktı — link-only yalnız ÖNCEDEN var olan bir `serban` kullanıcısına bağlanır; `serban` realm'i çalışanlarla doldurulmamış (14 kullanıcı, neredeyse hepsi test/canary) → gerçek çalışanlar M365 ile giremedi ("user does not exist"). M365 dizini canlı/sürekli güncel kaynak; statik pre-provision sürdürülemez (kullanıcı kararı 2026-05-18: otomatik provizyon).

**D3' — Tenant hard-gate (single-tenant endpoint)**: Erişim sınırı artık IdP OIDC endpoint seviyesinde hard-gate. `microsoft` IdP `/organizations/` multi-tenant endpoint yerine tek-tenant `/{tid}/` endpoint'lerini (authorize/token/jwks) + tek-tenant `issuer` kullanır. Yalnız izinli Entra tenant'ının (`m365-broker-config.json` `allowed_tenants` — tam 1 kayıt, script fail-fast) kullanıcıları Microsoft tarafında token alır; başka tenant Keycloak'a hiç ulaşamaz. SPI gerekmez — gate Microsoft + IdP config ile sağlanır. Çok-tenant gerekirse tenant başına ayrı IdP alias.

**D4' — Auto-provision first-broker-login flow**: `first broker login m365 auto-provision` — built-in "first broker login" stock kopyası: `idp-create-user-if-unique`=ALTERNATIVE (eşleşme yoksa kullanıcı OTOMATİK oluşturulur), `Handle Existing Account`=ALTERNATIVE (eşleşen varsa link akışı), `idp-email-verification`=DISABLED (realm SMTP'siz; existing-account re-auth ile doğrulanır). `trustEmail=true` → auto-created kullanıcı `emailVerified` gelir. Yeni kullanıcı Hardcoded Role IdP mapper ile varsayılan `viewer` (salt-okunur, least-privilege) realm rolü alır (`syncMode=IMPORT` — admin sonradan revoke edebilir). `entra_tid`/`entra_oid` FORCE mapper'ları korunur.

**authn ≠ authz (D2 geçerli)**: Auto-provision kullanıcıyı Keycloak'ta oluşturur + platforma SOKAR (login + `viewer` shell erişimi). ADR-0008 explicit-scope hâlâ geçerli — iş verisi görünürlüğü OpenFGA explicit-scope tuple'larından gelir, KC realm rolünden DEĞİL. Auto-created kullanıcının veri görmesi ayrı bir authz-plane provizyon adımı gerektirebilir; test realm browser smoke'ta `/api/v1/authz/me` + temsilî salt-okunur route ile doğrulanır.

**Mail**: Her iki KC realm SMTP'siz (`smtpServer` boş) + `notification-orchestrator`'da welcome/aktivasyon maili tetikleyicisi yok → auto-provision sessizdir, aktive edilen kullanıcıya mail gitmez.

**Rollback**: Eski `first broker login m365 link-only` flow rollback için korunur (script default silmez; `CLEANUP_OLD_M365_LINK_ONLY_FLOW=1` opt-in). Rollback = IdP `firstBrokerLoginFlowAlias`'ı eski flow'a geri bağla + endpoints/trustEmail revert.

**Existing passwordless kullanıcılar**: M365 e-postası mevcut bir KC kullanıcısıyla eşleşen ama lokal parolası olmayan kullanıcı, link akışında parola re-auth'a düşer ve tamamlayamaz. Bu kullanıcılar için admin pre-link (federated identity kaydı) ayrı bir işlemdir — yeni çalışanlar (asıl hedef) auto-create ile etkilenmez.

**v2 smoke kriterleri (test realm gate — D7 fazlandırma geçerli)**: Microsoft button render · izinli tenant'tan, KC hesabı OLMAYAN M365 kullanıcısı login → KC kullanıcısı OTOMATİK oluşturulur (deny DEĞİL) · auto-created kullanıcıda `entra_tid`/`entra_oid` attribute + `viewer` realm rolü + `emailVerified=true` · eşleşen mevcut kullanıcı → link akışı (re-auth) · `/api/v1/authz/me` 200 + temsilî salt-okunur route · local username/password fallback çalışıyor · aktive edilen kullanıcıya mail gitmez. **v1 §"Smoke kriterleri" ("pre-provision edilmemiş kullanıcı deny") artık geçerli DEĞİL** — v2'de auto-create.

## Referanslar

- Codex thread `019e3b72` — v2 auto-provision cross-AI consensus
- Codex thread `019e365b` — M365 broker (v1) architecture consensus
- `scripts/keycloak/setup-m365-broker.sh` — idempotent apply script
- `scripts/keycloak/m365-broker-config-form.html` — operator config input formu
- `docs/operations/RUNBOOKS/RB-m365-sso-broker.md` — operator runbook
- ADR-0008 (multi-org explicit scope), ADR-0014 (MFE auth transport)
