# Session Handoff — 2026-05-17 (Session 69 devamı) — M365 test browser smoke TAM PASS; `setup-m365-broker.sh` 2-bug script fix + prod apply sıradaki

> Format: D28 5-alan + sıradaki agent aksiyon listesi
> Önceki handoff: `session-handoff-2026-05-17-session-69-m365-sso-test-apply.md` (PR #785)
> Codex thread'ler: M365 flow-bug fix recipe `019e3796`, M365 mimari `019e365b`

---

## 1. Bağlam

PR #785 (Session 69 handoff) P0-A olarak "M365 test browser smoke"u devretti.
Kullanıcı bu session'da smoke'u tetikledi (`halil.kocoglu@serban.com.tr` M365
hesabını link hedefi olarak verdi). Smoke koşuldu — **tam kapsamlı PASS** — ve
yol boyunca merged `setup-m365-broker.sh`'te (PR #783/#784) **2 gerçek bug**
ortaya çıktı. Her ikisi de `platform-test` realm'inde **canlı düzeltildi** (kcadm)
ve smoke yeniden koşulup doğrulandı.

Handoff sebebi: smoke COMPLETE (pre-completion natural break) + script fix
intricate idempotent bash (flow execution surgery + user-profile JSON merge)
gerektiriyor; taze full-context session ister (Session Otomatik Açma HARD RULE
tetik #1 + #4). **Test realm çalışır + düzeltilmiş durumda** — script fix yalnız
canlı-kanıtlı kcadm dizilerini script'e taşımak (cross-AI PR).

---

## 2. İddia — bu fazda yapılanlar

**MERGE edilen PR yok** — bu faz canlı `platform-test` realm kcadm düzeltmeleri +
browser smoke. Script fix sıradaki PR (§5 P0).

Yapılanlar:
- `platform-test` smoke user oluşturuldu: `halil.kocoglu@serban.com.tr`.
- **Bug #1 (flow detection)** — `platform-test` `first broker login m365
  link-only` flow'una `idp-detect-existing-broker-user` eklendi (kcadm).
- **Bug #2 (user-profile)** — `platform-test` user-profile'a `entra_tid` +
  `entra_oid` attribute'ları deklare edildi (kcadm).
- M365 browser smoke baştan sona koşuldu (Chrome MCP) — login + link + negatif
  test + local fallback dahil.

---

## 3. İspatlar — M365 test browser smoke (tam kapsamlı PASS)

Chrome MCP ile end-to-end (`testai.acik.com`, `platform-test` realm):

- ✅ **M365 login → broker → link → platform**: M365 girişi (`halil.kocoglu@serban.com.tr`)
  → Keycloak `microsoft` IdP broker callback → first-broker-login → "Account
  already exists" (`idp-confirm-link`) → "Add to existing account" →
  re-authentication (lokal parola) → `testai.acik.com/home`'a giriş.
- ✅ **Federated link**: `federatedIdentities: [{identityProvider: microsoft,
  userId: 7iqNdsAfnFckz4Y3pJTL4cJ6evbe4mUpe-D1uTy5LQI, userName:
  halil.kocoglu@serban.com.tr}]`.
- ✅ **link-only**: platform JWT `sub` = mevcut lokal kullanıcı id'si (yeni
  kullanıcı yaratılmadı). `iss`/`email`/`preferred_username` doğru.
- ✅ **entra_tid/entra_oid** (Bug #2 fix sonrası): `entra_tid =
  6f49871e-cb5b-4b2f-b986-5b68f16365b9` — `m365-broker-config.json` izinli
  tenant ("AÇIK HOLDING") ile birebir; `entra_oid = 426c3cf9-5119-499d-96e8-2073d2e904ab`.
  KC user attribute olarak yazıldı (JWT claim değil — v1 tasarımı doğru).
- ✅ **`/api/v1/authz/me` → 200** — M365-federe token platform tarafından kabul.
- ✅ **Console temiz** — yeni JS hatası yok (yalnız 1 benign ag-grid lisans DEBUG).
- ✅ **Seamless relogin** — çıkış sonrası M365 ile tekrar giriş confirm-link/
  re-auth olmadan doğrudan home (link idempotent).
- ✅ **Local fallback** — username/password ile giriş çalışıyor (M365 broker
  lokal auth'u bozmadı).
- ✅ **Negatif link-only testi** — smoke user silinince M365 girişi temiz
  reddedildi: *"User halil.kocoglu@serban.com.tr authenticated with identity
  provider microsoft does not exist."* — user count 13 sabit (**auto-create yok**).
  Smoke user sonradan yeniden oluşturuldu + federated link kcadm ile geri eklendi.

🟡 Not: `/api/v1/notify/inbox/me` + SSE → 403 — bare smoke kullanıcısının
subscriber/org provizyonu yok; M365-SSO defekti değil, kullanıcı-provizyon
meselesi. JWT'de `subscriberId` claim'i yok (aynı sebep — bare kullanıcı).

---

## 4. İspatlamaz

- 🔴 **`setup-m365-broker.sh` HÂLÂ 2 bug taşıyor** (kod düzeltilmedi). Test realm
  canlı kcadm ile düzeltildi ama script aynı — script ile yapılacak her yeni
  apply (özellikle **prod `serban`**) aynı 2 bug'ı üretir. §5 P0.
- 🟠 **M365 prod apply (`serban` realm) YAPILMADI** — fixed script gerektirir.
- staging-sw clone hâlâ #784 sürümü (script fix sonrası `git pull` gerekir).
- prod-deploy PR-1 operator setup + Q4 schema-service prod rollout — PR #785 §5
  P0-B'den hâlâ bekliyor (bu fazda dokunulmadı).

---

## 5. Bilinen Boşluk + Sıradaki Agent P0

### 🔴 P0 — `setup-m365-broker.sh` 2-bug fix + cross-AI PR

İki bug, `platform-test`'te canlı-kanıtlı kcadm dizileriyle düzeltildi; aynı
mantık script'e taşınmalı. Codex recipe thread: `019e3796`.

#### Bug #1 — first-broker-login mevcut-kullanıcı tespiti yok

**Kök neden:** Script Step 2, built-in "first broker login" flow'unu kopyalayıp
`idp-create-user-if-unique`'i DISABLED yapıyor. Ama bu authenticator Keycloak'ta
hem "yoksa oluştur" hem **"varsa tespit et + `EXISTING_USER_INFO` set et"**
yapar. Disable → tespit de ölür → `idp-confirm-link` `EXISTING_USER_INFO` null
görür, log `KC-SERVICES0019: No duplication detected` → `AuthenticationFlowException`
→ eşleşen kullanıcı olsa bile login reddedilir.

**Fix (script Step 2'ye, `idp-create-user-if-unique`+`idp-email-verification`
DISABLED edildikten SONRA, `if [ "$VERIFY_ONLY" != "1" ]` içinde):**

```
# 1. "User creation or linking" subflow alias'ı: top-level flow executions'ta
#    authenticationFlow==true && description=="Flow for the existing/non-existing
#    user alternatives" olan execution'ın displayName'i.
#    (authentication/flows yalnız TOP-LEVEL flow listeler — subflow alias oradan BULUNAMAZ.)
# 2. idp-detect-existing-broker-user yoksa O SUBFLOW'a ekle:
#    kcadm create "authentication/flows/<SUBFLOW_ALIAS_ENC>/executions/execution" -s provider=idp-detect-existing-broker-user
#    (NOT: endpoint .../executions/execution — .../executions DEĞİL.)
# 3. detect → REQUIRED:  kcadm update "authentication/flows/<TOPFLOW_ENC>/executions" -b '{"id":"<detectId>","requirement":"REQUIRED"}'
# 4. "Handle Existing Account" subflow → REQUIRED (ALTERNATIVE'den; aynı update pattern).
# 5. detect, "Handle Existing Account"tan ÖNCE çalışmalı:
#    kcadm create "authentication/executions/<detectId>/raise-priority" — detect.index < handle.index olana dek (loop, ~1 raise yeter).
```

Doğru hedef yapı:
```
User creation or linking (REQUIRED)
├─ idp-create-user-if-unique        DISABLED
├─ idp-detect-existing-broker-user  REQUIRED   (detect.index < handle.index)
└─ Handle Existing Account          REQUIRED
   ├─ idp-confirm-link              REQUIRED
   └─ Account verification → idp-username-password-form REQUIRED, idp-email-verification DISABLED
```

#### Bug #2 — `entra_tid`/`entra_oid` user-profile'da deklare değil

**Kök neden:** Keycloak 26 Declarative User Profile, `unmanagedAttributePolicy`
DISABLED iken deklare edilmemiş attribute'ları **sessizce düşürür**.
`platform-test` (ve büyük olasılıkla `serban`) realm'de policy DISABLED,
deklare attribute'lar: `username,email,firstName,lastName,userId,subscriberId,
org_id`. `entra_tid`/`entra_oid` yok → `entra-tid`/`entra-oid` IdP mapper'ları
çalışsa da yazımları kalıcı olmuyor.

**Fix (script'e, Step 4 mapper'larla birlikte; idempotent):**

```
# kcadm get users/profile -r $REALM → JSON
# attributes[] içinde entra_tid/entra_oid yoksa append:
#   {"name":"entra_tid","displayName":"Entra Tenant ID","permissions":{"view":["admin"],"edit":["admin"]},"multivalued":false}
#   {"name":"entra_oid","displayName":"Entra Object ID","permissions":{"view":["admin"],"edit":["admin"]},"multivalued":false}
# kcadm update users/profile -r $REALM -f <container-path>
# (mevcut profili KORU — yalnız append; subscriberId/org_id vb. silme.)
```

#### Step 5 verify — eklenecek assertion'lar

Mevcut FLOW_VERIFY yalnız create-if-unique + email-verification DISABLED kontrol
ediyor. Ek:
- `idp-detect-existing-broker-user` = REQUIRED
- `idp-detect-existing-broker-user`.index < "Handle Existing Account".index
- "Handle Existing Account" = REQUIRED
- `idp-confirm-link` = REQUIRED
- `idp-username-password-form` = REQUIRED
- user-profile `attributes`'ta `entra_tid` + `entra_oid` mevcut

#### PR akışı
1. Branch + `setup-m365-broker.sh` Step 2 (flow) + Step 4 (user-profile) + Step 5
   (verify) düzelt. `bash -n` + `shellcheck -S warning` temiz.
2. Mümkünse `VERIFY_ONLY=1` ile `platform-test`'te idempotent re-run — flow zaten
   düzeltildi, script'in onu bozmadan doğruladığını teyit et.
3. Cross-AI: Codex review (HARD RULE — implementer Claude, reviewer Codex).
4. ADR-0011 boundary declaration + PR body formatı (bkz. PR #783/#784/#785).
5. CI yeşil → normal squash → `ai-post-merge-cleanup.sh`.

### 🟠 P0 — M365 prod apply (`serban`) — fixed script ile

Script fix merge sonrası: staging-sw clone `git pull` →
`CONFIRM_PROD_M365_BROKER=serban REALM=serban ... bash setup-m365-broker.sh` →
prod browser smoke (§3'teki 9 madde, prod login host'unda). Önce prod realm için
`serban` user-profile'ın `entra_tid`/`entra_oid` deklare edip etmediğini de
script halletmeli (Bug #2 fix realm-agnostic).

### 🟠 P0 — prod-deploy PR-1 operator setup + Q4 schema-service rollout

PR #785 §5 P0-B'den devralındı — değişmedi. ArgoCD helm upgrade + API token +
`ARGOCD_PROD_SYNC_TOKEN` + `deploy-prod-gitops.yml` ilk Q4 run.

### Test realm güncel durum (sıradaki agent için)

- `platform-test` `first broker login m365 link-only` flow — **düzeltildi**
  (detect eklenmiş, doğru yapı). Script idempotent re-run bozmamalı.
- `platform-test` user-profile — `entra_tid`/`entra_oid` **deklare edildi**.
- Smoke user `halil.kocoglu@serban.com.tr` (id `64d8d83c-fb73-437b-9785-b73dae72b218`)
  — var, M365 linked, lokal parola set. M365 + local login ikisi de çalışır.

---

## Sıradaki Session İçin İlk Komut

```bash
cd /Users/halilkocoglu/Documents/platform-k8s-gitops
git fetch origin main && git log origin/main --oneline -6
cat docs/session-handoff-2026-05-17-m365-smoke-complete.md   # bu doc
# P0: setup-m365-broker.sh — Bug #1 (flow detect) + Bug #2 (user-profile) fix
#     Codex recipe thread 019e3796; canlı-kanıtlı kcadm dizileri §5'te
```
