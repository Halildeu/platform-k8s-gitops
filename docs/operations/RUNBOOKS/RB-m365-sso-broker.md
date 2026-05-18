# Runbook — Microsoft 365 SSO Broker (Keycloak Identity Brokering)

> ADR-0021. Codex architecture consensus: thread `019e365b`.
>
> **Scope**: Platforma "Microsoft 365 ile giriş" — Keycloak `serban` realm'ine
> Microsoft Entra ID OIDC identity provider eklenmesi. **v2 = auto-provision**
> (ADR-0021 v2 amendment, Codex `019e3b72`): izinli Entra tenant'ından M365 ile
> giren çalışana eşleşen KC hesabı yoksa kullanıcı OTOMATİK açılır; tek-tenant
> endpoint hard-gate. v1 link-only superseded.
>
> **Roller**: 🧑 = operator (sen — Entra portal + Vault), 🤖 = agent (Claude —
> kcadm apply + smoke).

## Genel akış

```
🧑 1. Entra app registration          → client ID + secret + tenant ID'ler
🧑 2. Config form doldur               → m365-broker-config.json + Vault komutu
🧑 3. Vault'a secret yaz (staging-sw)
🤖 4. setup-m365-broker.sh → platform-test realm
🤖 5. Test realm browser smoke
🤖 6. setup-m365-broker.sh → serban (prod) + prod browser smoke
```

---

## 🧑 ADIM 1 — Microsoft Entra app registration

Microsoft Entra admin center (`entra.microsoft.com`) → **Identity → Applications
→ App registrations → New registration**.

1. **Name**: `Platform SSO` (serbest).
2. **Supported account types**: **"Accounts in any organizational directory
   (Any Microsoft Entra ID tenant - Multitenant)"**.
   → Kişisel Microsoft hesaplarını İÇEREN seçeneği SEÇME.
3. **Redirect URI**: platform **"Web"**, değer:
   `https://testai.acik.com/realms/platform-test/broker/microsoft/endpoint`
4. **Register**.
5. Kayıttan sonra **Authentication → Add a platform / Add URI** ile ikinci
   redirect URI'yi ekle:
   `https://ai.acik.com/realms/serban/broker/microsoft/endpoint`
6. **Overview** sayfasından kopyala:
   - **Application (client) ID** (GUID)
   - **Directory (tenant) ID** (kendi org'unun tenant ID'si — allowlist'e girer)
7. **Certificates & secrets → Client secrets → New client secret**:
   - Description: `keycloak-m365-broker`
   - Expires: **6 veya 12 ay** (rotation runbook §rotation)
   - **Add** → açılan satırdaki **Value**'yu HEMEN kopyala (sayfadan çıkınca
     bir daha gösterilmez).
8. **API permissions**: Microsoft Graph → Delegated → `openid`, `profile`,
   `email` ekli olsun → **Grant admin consent for <tenant>**.
9. (Opsiyonel) **Token configuration**: tenant ID token'da `email` claim'i
   default vermiyorsa → **Add optional claim → ID → email**.

> **Hangi tenant ID allowlist'e?** v2 auto-provision **tam olarak 1** izinli
> tenant gerektirir (script fail-fast) — kendi org'unun Directory (tenant) ID'si.
> Bu tek tenant IdP OIDC endpoint'ine gömülür (`/{tid}/`) → **hard-gate**: yalnız
> bu tenant'ın kullanıcıları kimlik doğrulayabilir, başka tenant Microsoft
> tarafında durur. Çok-tenant gerekirse tenant başına ayrı IdP alias (ayrı iş).

## 🧑 ADIM 2 — Config form

`scripts/keycloak/m365-broker-config-form.html` dosyasını tarayıcıda aç
(Claude Code'da Launch preview panel'inde de görünür). Doldur:

- **A — Entra App**: Application (client) ID, Client secret (Value), secret
  expiry tarihi.
- **B — İzin verilen tenant'lar**: her org için bir satır — Tenant ID + etiket.
  (Platform org / subscriberId alanları v1'de boş bırakılabilir — v2 içindir.)

**Üret** → iki çıktı:
- `m365-broker-config.json` — **İndir**, `scripts/keycloak/` altına koy
  (secret İÇERMEZ, repo'ya commit edilebilir).
- Vault komutu — Adım 3'te kullanılır.

Form tamamen yereldir — secret tarayıcıdan dışarı çıkmaz.

## 🧑 ADIM 3 — Client secret → Vault

Formun ürettiği komutu **staging-sw** sunucusunda çalıştır:

```bash
vault kv put kv/platform/keycloak-m365-broker client_secret='<VALUE>'
```

Secret'ı dosyaya, commit'e veya sohbete yapıştırma. Bu adımdan sonra agent'a
"config + secret hazır" de.

---

## 🤖 ADIM 4 — Test realm apply (`platform-test`)

```bash
M365_CONFIG=scripts/keycloak/m365-broker-config.json \
M365_CLIENT_SECRET="$(vault kv get -field=client_secret kv/platform/keycloak-m365-broker)" \
  bash scripts/keycloak/setup-m365-broker.sh
```

Script idempotent (desired-state apply): single-tenant `microsoft` OIDC identity
provider + claim mapper'lar (`tid→entra_tid`, `oid→entra_oid`) + hardcoded
`viewer` default-role mapper + `first broker login m365 auto-provision` flow
oluşturur/günceller; 4 katmanlı read-back verify. Exit 0 = PASS.

## 🤖 ADIM 5 — Test realm browser smoke (v2 auto-provision)

`https://testai.acik.com` login sayfasında:

- [ ] "Microsoft 365" butonu render oluyor
- [ ] İzinli tenant'tan, `platform-test`'te KC hesabı OLMAYAN M365 kullanıcısı
      login → Microsoft redirect → dönüş → KC kullanıcısı **OTOMATİK oluşturulur**
      → giriş başarılı (deny DEĞİL)
- [ ] Auto-created kullanıcıda: `entra_tid` + `entra_oid` attribute, `viewer`
      realm rolü, `emailVerified=true` (Admin API read-back)
- [ ] Eşleşen mevcut KC kullanıcısı M365 ile login → link akışı (re-auth) →
      duplicate kullanıcı oluşmaz
- [ ] `/api/v1/authz/me` 200 + temsilî bir salt-okunur route (veri-görünürlük —
      yalnız KC rolü değil, OpenFGA explicit-scope da gözlemlenir)
- [ ] Aktive edilen kullanıcıya mail GİTMEZ (KC SMTP'siz; notification yok)
- [ ] Local username/password login hâlâ çalışıyor (fallback)
- [ ] Logout → relogin temiz
- [ ] (mümkünse) izinli tenant DIŞINDAN M365 hesabı → Microsoft tarafında durur

## 🤖 ADIM 6 — Prod apply (`serban`)

Test smoke PASS sonrası:

```bash
CONFIRM_PROD_M365_BROKER=serban REALM=serban \
M365_CONFIG=scripts/keycloak/m365-broker-config.json \
M365_CLIENT_SECRET="$(vault kv get -field=client_secret kv/platform/keycloak-m365-broker)" \
  bash scripts/keycloak/setup-m365-broker.sh
```

Sonra `https://ai.acik.com` public browser smoke (Adım 5 listesi prod için).

---

## Rollback

IdP'yi devre dışı bırak — kullanıcı auth yolu korunur (local login fallback):

```bash
docker exec platform-kc-prod /opt/keycloak/bin/kcadm.sh update \
  identity-provider/instances/microsoft -r serban -s enabled=false
```

Tamamen kaldırma: `kcadm.sh delete identity-provider/instances/microsoft -r serban`.

## Client secret rotation

Entra → Certificates & secrets → yeni secret üret → `vault kv put` ile güncelle
→ `setup-m365-broker.sh` yeniden koş (IdP secret'ı converge eder) → eski Entra
secret'ı sil. Tetik: expiry yaklaşması, sızıntı şüphesi.

## NE YAPMA

- ❌ Client secret'ı git'e / config JSON'a / log'a yazma — yalnız Vault.
- ❌ `serban` realm'e doğrudan prod apply — önce `platform-test` smoke.
- ❌ Entra app'i "personal Microsoft accounts dahil" multi-tenant yapma.
- ❌ `groups` / Graph permission isteme — gerekmiyor (`tid`/`oid`/`email` yeter).
- ❌ `allowed_tenants`'a 1'den fazla tenant koyma — script fail-fast (çok-tenant ayrı IdP alias işi).
- ❌ Prod ilk apply'de eski link-only flow'u silme — rollback için tut.

## Referanslar

- ADR-0021 — Microsoft 365 SSO via Keycloak Identity Brokering
- `scripts/keycloak/setup-m365-broker.sh` · `m365-broker-config-form.html`
- Codex thread `019e365b`
