# Runbook — Microsoft 365 SSO Broker (Keycloak Identity Brokering)

> ADR-0021. Codex architecture consensus: thread `019e365b`.
>
> **Scope**: Platforma "Microsoft 365 ile giriş" — Keycloak `serban` realm'ine
> Microsoft Entra ID OIDC identity provider eklenmesi. v1 = link-only
> (mevcut kullanıcıya bağlama; SPI yok).
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

> **Hangi tenant ID'ler allowlist'e?** Kendi org'unun tenant ID'si + giriş
> yapmasına izin vereceğin diğer org'ların tenant ID'leri. Multi-tenant app
> olduğu için başka org'un admini ilk kullanımda consent verir; allowlist
> Keycloak tarafında kimin gerçekten gireceğini belirler.

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

Script idempotent (desired-state apply): `microsoft` OIDC identity provider +
claim mapper'lar (`tid→entra_tid`, `oid→entra_oid`, email, ad) + link-only
first-broker-login flow oluşturur/günceller. Exit 0 = PASS.

## 🤖 ADIM 5 — Test realm browser smoke

`https://testai.acik.com` login sayfasında:

- [ ] "Microsoft 365" butonu render oluyor
- [ ] İzinli tenant kullanıcısı (önce `platform-test`'te oluşturulmuş, email
      eşleşen) → Microsoft'a redirect → geri dönüş → giriş başarılı
- [ ] Eşleşmeyen kullanıcı → giriş reddedilir (link-only)
- [ ] JWT'de `subscriberId` + `entra_tid` + `entra_oid` claim'leri var
- [ ] `/api/v1/authz/me` 200
- [ ] Local username/password login hâlâ çalışıyor (fallback)
- [ ] Logout → relogin temiz

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
- ❌ v1'de `groups` / Graph permission isteme — v2 SPI işi.

## Referanslar

- ADR-0021 — Microsoft 365 SSO via Keycloak Identity Brokering
- `scripts/keycloak/setup-m365-broker.sh` · `m365-broker-config-form.html`
- Codex thread `019e365b`
