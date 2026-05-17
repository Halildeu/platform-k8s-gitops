# Session Handoff — 2026-05-17 (Session 69) — M365 SSO broker `platform-test`'te apply'lı (5/5 PASS); browser smoke + prod apply pending. Prod-deploy PR-1 merged, operator setup bekliyor

> Format: D28 5-alan + sıradaki agent aksiyon listesi
> Önceki handoff: `session-handoff-2026-05-17-session-68-prod-deploy-architecture.md`
> Codex thread'ler: prod-deploy PR-1 review `019e362d`, M365 mimari + PR-0/bugfix review `019e365b`, (devralınan) prod-deploy 4-PR planı `019e35d1`

---

## 1. Bağlam

Session 68 handoff'u (#750) P0 olarak Codex `019e35d1` 4-PR prod-deploy
mimari planını (PR-1'den başla) devretti.

Bu session (69) iki hat yürüttü:

**Hat A — prod-deploy PR-1 (Session 68 P0):**
- `deploy-prod-gitops.yml` kalıcı prod-deploy workflow'u inşa edildi —
  `workflow_dispatch`-only, `environment: production`, `concurrency:
  prod-gitops-sync`; `argocd app get/diff/sync/wait` primitive'i `kubectl
  port-forward svc/argocd-server` + scoped API token üzerinden. Codex `019e362d`
  review → #780 MERGED.

**Hat B — M365 SSO (kullanıcı yön değişikliği):**
Kullanıcı session ortasında yeni iş açtı: "Microsoft 365 girişi" (kurumsal
M365 / Entra ID SSO). Keycloak hazırlık + altyapı değerlendirildi → M365 broker
initiative başladı:
- **Mimari konsensüs** — Codex `019e365b`: Keycloak identity brokering, gated
  multi-tenant Entra OIDC, v1 link-only / v2 SPI. ADR-0021.
- **PR-0 scaffolding** — ADR-0021 + operator config form (client-side HTML) +
  `setup-m365-broker.sh` (idempotent kcadm apply) + runbook. Codex `019e365b`
  REVISE→REVISE-2→AGREE → #783 MERGED.
- **Entra app registration** — Chrome MCP ile yapıldı: app "Platform SSO",
  multi-tenant ("Tüm kiracılara izin ver"), 2 redirect URI (test+prod realm
  broker endpoint), client secret (expiry 2026-11-13).
- **Vault secret** — `kv/platform/keycloak-m365-broker` v1, `client_secret`
  yazıldı (prod Vault, `bootstrap-drill/vault-init-prod.json` token).
- **Test apply** — `platform-test` realm: `setup-m365-broker.sh` **5/5 PASS**
  (apply sırasında ortaya çıkan 3 first-run bug fix sonrası). Bağımsız kcadm
  doğrulaması yapıldı.
- **3 bug fix canonicalize** — URL-encode + hardened temp-JSON transfer +
  stderr un-suppress → #784 MERGED.

Handoff sebebi: kullanıcı explicit "hand off" dedi (Session Otomatik Açma HARD
RULE tetik #1 context derinliği — `/compact` sonrası). Sıradaki adım (M365 test
browser smoke) kullanıcı-katılımlı interaktif Microsoft login adımı gerektirir;
taze full-context session ister.

---

## 2. İddia — bu session (69) MERGE edilen PR'lar

Tümü CI yeşil, **normal squash** (`--admin` yok), `ai-post-merge-cleanup.sh`
archive tag'li. Cross-AI: implementer Claude, reviewer Codex.

| PR | Konu | Merge | Codex |
|----|------|-------|-------|
| #780 | `deploy-prod-gitops.yml` ArgoCD sync workflow (prod-deploy PR-1) — `workflow_dispatch`-only, `environment: production`, `argocd app sync` via port-forward + scoped token; `helm-values/argocd/values.yaml` `prod-gitops-sync` apiKey account + RBAC | `4817a9d` 14:17Z | `019e362d` AGREE |
| #783 | M365 SSO broker scaffolding (PR-0) — ADR-0021 + `m365-broker-config-form.html` + `setup-m365-broker.sh` + `RB-m365-sso-broker.md` | `ac0f552` 15:45Z | `019e365b` REVISE→REVISE-2→AGREE |
| #784 | `setup-m365-broker.sh` 3 first-run bug fix — kcadm path URL-encode (`%20`), hardened temp-JSON transfer (`docker exec -i "umask 077; cat >"`, host temp 0600), stderr un-suppress | `c375049` 17:57Z | `019e365b` REVISE→AGREE |

Bu handoff PR'ı ek olarak `scripts/keycloak/m365-broker-config.json`'u repo'ya
commit eder — secret İÇERMEZ (yalnız `client_id` + `tid` + discovery URL); form
tasarımı gereği repo-committable artifact, `setup-m365-broker.sh` bunu tüketir.
Session boyunca untracked'di (lokal üretildi + staging-sw'ye scp'lendi).

---

## 3. İspatlar

**prod-deploy PR-1 (#780):**
- `deploy-prod-gitops.yml` — CI yeşil, Codex `019e362d` AGREE. Workflow
  `kubectl apply`/`set image`/`exec` yasak; yalnız `argocd app get/diff/sync/
  wait` + `kubectl get/logs/rollout status`. Branch guard + ancestor check +
  diff exit-code 0/1/≥2 + requiresPruning + resource whitelist gate'leri.
- `helm-values/argocd/values.yaml` — `accounts.prod-gitops-sync: apiKey` + RBAC
  `p, prod-gitops-sync, applications, get/sync, default/platform-prod`.
- **NOT canlı**: workflow merge edildi ama operator setup yapılmadı (§5 P0-B).

**M365 PR-0 (#783):** 4 dosya merged, CI yeşil, Codex `019e365b` AGREE
(`ready_to_merge=true`). Merge hiçbir cluster mutate etmedi (script manuel
apply tool'u, `workflow_dispatch` değil).

**Entra app registration** (kanıt: Chrome MCP oturumu):
- App "Platform SSO" oluşturuldu — multi-tenant, `client_id`
  `3b709448-3e67-4a6f-9bfd-a38a376ad339`.
- 2 redirect URI (test + prod realm broker endpoint), client secret üretildi
  (Value bir kez gösterildi → Vault'a yazıldı, expiry 2026-11-13).

**Vault secret:** `kv/platform/keycloak-m365-broker` v1 — `client_secret`
yazılı (kullanıcı + staging-sw agent raporu doğruladı; test apply'ın PASS olması
script'in secret'ı Vault'tan okuyabildiğini ispatlar).

**M365 test apply — `platform-test` realm 5/5 PASS** (bağımsız kcadm doğrulama):
- `microsoft` IdP — `providerId=oidc`, `enabled=true`.
- link-only first-broker-login flow — `idp-create-user-if-unique` +
  `idp-email-verification` execution'ları `DISABLED` (federe giriş yalnız
  mevcut kullanıcıya bağlanır, auto-create yok).
- `entra-tid` + `entra-oid` claim mapper'ları — `oidc-user-attribute-idp-mapper`,
  `syncMode=FORCE`.

**#784 3 bug fix:** `bash -n` syntax OK, `shellcheck -S warning` temiz. Fix
kanıtı `platform-test` 5/5 PASS apply'ında (yukarıda).

---

## 4. İspatlamaz

- 🟠 **M365 test browser smoke YAPILMADI.** Test login sayfasında "Microsoft
  365" butonu render oluyor — ama tam interaktif login click-through (Microsoft
  redirect → sign-in → re-auth → link → claim/attribute doğrulama → `/authz/me`
  → negatif link-only testi → local fallback → logout/relogin) **koşulmadı**. Runbook `RB-m365-sso-broker.md`
  Adım 5 madde 2-8 pending. HARD RULE — Tarayıcıdan Doğrulanmadan İş Bitmedi:
  M365 SSO **"tamamlandı" sayılmaz**.
- 🟠 **M365 prod apply (`serban` realm) YAPILMADI** — ADR-0021 D7 + Codex
  `019e365b` `YES_FOR_TEST_FIRST` gereği test browser smoke yeşillenmeden prod'a
  geçilmez.
- 🟠 **prod-deploy PR-1 operator setup YAPILMADI** — ArgoCD helm upgrade
  (#780'deki `values.yaml` `prod-gitops-sync` account + RBAC) + API token üretimi
  + GitHub `production` env secret `ARGOCD_PROD_SYNC_TOKEN`. Bunlar olmadan
  `deploy-prod-gitops.yml` koşamaz.
- 🟠 **Q4 schema-service prod rollout HÂLÂ YAPILMADI** (Session 67/68'den
  devralındı) — `k3d-prod` schema-service hâlâ `sha256:b660b25a...` (eski, 13+
  gün). PR-1 operator setup'a bağımlı.
- Codex `019e35d1` 4-PR prod-deploy planının PR-2/PR-3/PR-4'ü başlamadı.
- Entra **admin consent**: `halil.kocoglu` Global Admin rolüne sahip değil →
  Entra'da admin-consent butonu disabled. Multi-tenant app'in bir tenant'tan ilk
  girişinde consent prompt'u çıkabilir; temel OIDC scope'ları (`openid profile
  email`) normalde user-consent yeter, ama tenant "tüm app'ler admin onayı
  ister" politikasındaysa Global Admin gerekir → smoke anında izlenir.

---

## 5. Bilinen Boşluk + Sıradaki Agent P0

### 🟠 P0-A — M365 test browser smoke (yarım kalan interaktif işin tamamlanması)

**Önkoşul (link-only v1):** federe giriş yalnız **mevcut** bir `platform-test`
Keycloak kullanıcısına bağlanır. Smoke'tan önce, M365 test hesabının email'i ile
**eşleşen email'e sahip** bir `platform-test` kullanıcısı doğrula/oluştur.

**Adımlar** (`RB-m365-sso-broker.md` Adım 5 + negatif test):
1. Browser (Chrome MCP) → test login host (`testai.acik.com` veya realm login
   URL'i) → "Microsoft 365" butonu.
2. Microsoft login sayfasına redirect → **interaktif credential** — kullanıcıya
   devret (agent Microsoft şifresi giremez).
3. Callback → re-authentication → mevcut `platform-test` kullanıcısına link.
4. **Claim/attribute doğrula** — iki ayrı yüzey:
   - **JWT**: platform token'ında `subscriberId` claim'i mevcut (link-only;
     mevcut kullanıcının claim'i taşınır).
   - **KC user attribute** (kcadm / Admin API read-back, **JWT DEĞİL**):
     `entra_tid` + `entra_oid` user attribute olarak yazılmış. v1'de bunlar JWT
     claim değil — `oidc-user-attribute-idp-mapper` Entra claim'ini KC user
     attribute'una yazar; JWT'ye taşınması v2 client protocol mapper işi.
5. `/authz/me` 200 + beklenen scope/projeksiyon.
6. **Negatif link-only testi**: email'i hiçbir `platform-test` kullanıcısıyla
   eşleşmeyen M365 hesabı ile giriş → **reddedilmeli** (v1 invariant: auto-create
   yok; runbook Adım 5'te bu negatif kontrol mevcut).
7. Local username/password fallback hâlâ çalışıyor (regression check).
8. Logout → relogin (idempotent link).
9. Browser console + network temiz (HARD RULE — Deploy Sonrası Console Verify).

**İzle:** admin consent (§4 son madde). Bloklanırsa → Global Admin consent
verir veya AÇIK HOLDING tenant admin'i kullanılır; smoke sonucu "tenant
admin-consent policy ile bloklandı" olarak ayrı da kapanabilir.

### 🟠 P0-B — prod-deploy PR-1 operator setup + Q4 schema-service prod rollout (Session 68'den devralındı — bayat live-risk; M365 prod'un ARKASINA atılmaz)

Q4 schema-service prod rollout yeni iş değil: desired-state #749'da merged, prod
canlı hâlâ eski `sha256:b660b25a...` digest'inde (13+ gün bayat). Session 68 bunu
zaten P0 devretti — M365 prod apply (P0-C) bunun önüne geçemez.

1. ArgoCD helm upgrade — #780'deki `helm-values/argocd/values.yaml`
   (`prod-gitops-sync` apiKey account + RBAC) staging-sw ArgoCD'ye uygula.
2. `prod-gitops-sync` account için API token üret → GitHub `production`
   environment secret `ARGOCD_PROD_SYNC_TOKEN`.
3. `deploy-prod-gitops.yml`'i Q4 schema-service rollout için ilk kez koş
   (Session 68 §5 "Q4 first-use" — `resources` filtreli ilk run + acceptance
   smoke; detay session-68 handoff §5).
4. Codex `019e35d1` 4-PR planının PR-2 (image-only workflow emekli) / PR-3 (RBAC
   least-priv) / PR-4 (promotion ledger CI) hatları.

### 🟠 P0-C — M365 prod apply (`serban` realm) + prod browser smoke

Bağımlılık: P0-A yeşil **ve** P0-B (prod-deploy/Q4) önceliğinin bilinçli ele
alınmış olması.

**Preflight (ZORUNLU — staging-sw clone hizalama):** staging-sw'deki clone'da
`setup-m365-broker.sh` #784 öncesi (hardening'siz) sürüm taşıyor. Prod apply'dan
**önce** orada script güncellenmeli — eski script ile prod apply doğrudan risk:
```bash
git checkout scripts/keycloak/setup-m365-broker.sh && git pull
```

Apply:
- `setup-m365-broker.sh` `serban` realm'ine + prod Keycloak'a apply.
- **Önce doğrula:** prod realm için secret hangi Vault'ta — `kv/platform/
  keycloak-m365-broker` prod Vault'a yazıldı; script'in prod apply'da bu path'i
  okuduğunu teyit et.
- Aynı `m365-broker-config.json` (realm-agnostic) kullanılır.
- Prod browser smoke — P0-A ile aynı 9 madde, prod login host'unda.

### 🔵 P1 — (opsiyonel) `platform-bootstrap-writer` AppRole

Token-free otomatik Vault apply için AppRole; prod apply öncesi önerilir
(zorunlu değil — root token ile de çalışır).

---

## Sıradaki Session İçin İlk Komut

```bash
cd /Users/halilkocoglu/Documents/platform-k8s-gitops
git fetch origin main && git log origin/main --oneline -6
cat docs/session-handoff-2026-05-17-session-69-m365-sso-test-apply.md   # bu doc
# P0-A: M365 test browser smoke — RB-m365-sso-broker.md Adım 5 madde 2-8
#       (link-only önkoşul: email-eşleşen platform-test kullanıcısı)
```
