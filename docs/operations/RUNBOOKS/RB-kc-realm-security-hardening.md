# Runbook — Keycloak Realm Güvenlik Hardening (declarative desired-state)

> board #2476 · Codex (OpenAI) plan-time thread `019f69f6` (REVISE ×3 absorb → AGREE).
> Script: [`scripts/keycloak/harden-realm-security.sh`](../../../scripts/keycloak/harden-realm-security.sh)
>
> **Amaç**: `platform-test` / `serban` (prod) realm güvenlik ayarlarını **review-able,
> idempotent, recreate-deterministic, drift-detect edilebilir** bir kaynaktan
> converge etmek. "kcadm patch + kc-export-cron backup" YETMEZ (Codex): backup
> felaket-kurtarmadır; bu script desired-state + field-level drift + test→prod
> promotion + **fail-closed rollback** verir.
>
> **Roller**: 🤖 = agent/CI (TEST realm otonom) · 🧑 = owner (PROD gate).
>
> **Precondition**: script realm **YARATMAZ**. Mevcut realm başka bootstrap/restore
> katmanından (compose seed / KC realm import) gelmeli; realm yoksa `guard_realm`
> fail-closed durur. Bu script yalnız güvenlik alanlarını converge eder.

## Kapsam — slice'lar

| Slice | İçerik | Durum |
|---|---|---|
| **A1** | Brute-force protection (`failureFactor=5` + 10-param converge) — `harden-realm-security.sh` | ✅ LIVE (PR #2479) |
| **A2a** | Confidential `smoke-client` substrate + Vault secret — [`setup-smoke-client.sh`](../../../scripts/keycloak/setup-smoke-client.sh) | ✅ bu sürüm (source-ready + platform-test live shape/secret/grant kanıtı) |
| **A2b.1** | Token contract: `ENDPOINT_ADMIN` scope-mapping + `smoke-runtime-v1` (userId + aud×6) + `smoke-notify-v1` (org_id, optional) — [`setup-smoke-token-contract.sh`](../../../scripts/keycloak/setup-smoke-token-contract.sh) | 🟡 **LIVE PARTIAL / Needs Verify** — KC desired-state + token projection live; permission `/authz/me` audience-only 200; **endpoint-admin allow/deny + variant scoped 200 + notification 202 + impersonation 201 pending** (persona seed — ayrı fixture paketi) |
| **A2b.2** | 4 TEST runbook + core smoke script repoint (`client_id=frontend` → `smoke-client`) | ✅ bu sürüm (docs: RB-22-1-1-be-009-openfga-live + RB-faz-21-3-d35-3-keycloak-admin-jwt + RB-faz-23-1-pr5-deploy-verify + RB-zanzibar-canary + runbook-auth-impersonation-broker-secret + RB-bl011 (prod pattern note); scripts: faz22/smoke-endpoint-admin-domain-ops + faz22-remote-ops/devkey-cert-autorenew + faz22-remote-ops/agentpc2-update-agent-v0214 + faz24/provision-meeting-intelligence-access + faz35/reconcile-test-permission-writer-identity). Faz35 ethics scripts + ATS scripts A2c-blocker migration note aldı (A2b.3 dependency: smoke-client optional scope extension). |
| A2b.3 | ATS + ETHICS token kontratı — **#2746, karar VERİLDİ: Opsiyon B (ayrı client)** | A2c ÖNCESİ zorunlu. 2026-07-27 ölçümü: `ats.*` client-scope'ları 0 protocol mapper + boş scope-mapping taşıyor, yani `scope` claim'ine sadece string ekler. ATS scriptlerinin tükettiği `resource_access[ats-api].roles` built-in `roles` mapper'ından gelir ve client scope'uyla filtrelenir: `frontend.fullScopeAllowed=true` (filtresiz) vs `smoke-client.fullScopeAllowed=false` + 0 `ats-api` rol eşlemesi → optional scope eklemek `resource_access` ÜRETMEZ. Dolayısıyla "optional scope opt-in" yolu yapısal olarak çalışmaz; dar rol eşlemeli ayrı `smoke-ats-v1` gerekir. |
| **A2c** | `frontend.directAccessGrantsEnabled=false` | **BLOCKED on A2b.3** — Faz25 ATS scope opt-in + Faz35 ethics scope opt-in tamamlanmadan flip DAG=false ROPC break eder (fullats-application-smoke, provision-test-openfga/ethic-entitlement/keycloak, verify-test-openfga-authz). Ayrı cutover PR. Gözlem tarafı hazır: A2-obs login event logging LIVE olduğu için flip'in etkisi ölçülebilir. |
| A2-obs | Login event logging (`eventsEnabled` + 7g retention) — `harden-realm-security.sh` desired-state | ✅ **LIVE** (2026-07-24) |
| A3 | redirectUri + webOrigins narrowing | ⚠️ **CANLIDA UYGULANMIŞ, DESIRED-STATE'TE YOK** (2026-07-27 ölçümü: `frontend` redirectUris=1 `https://testai.acik.com/*`, webOrigins tek origin, wildcard yok — ama `harden-realm-security.sh` bu alanları YÖNETMİYOR). **Düzeltme:** `--apply` bu daraltmayı GERİ ALMAZ — script yalnız `realms/$REALM` seviyesindeki skaler alanları yönetir, `clients/*`'a hiç dokunmaz. Gerçek boşluk daha keskin: TEST realm'indeki `frontend` client'ını **oluşturan hiçbir repo kaynağı yok** (realm import yok, client-create scripti yok), yani daraltmanın desired-state'i hiç mevcut değil — client yeniden oluşturulursa yeniden üretilmez. 2026-07-27'de repo'nun fiilen kontrol ettiği yüzey makine-zorunlu hale getirildi: `tests/operations/test_keycloak_client_origin_invariant.py` (fixture'larda wildcard `webOrigins`/`redirectUris` yasak; `dev-local-realm.json`'daki iki `["*"]` → `["+"]` düzeltildi). Canlı TEST/PROD client'larını desired-state'e almak ayrı bir yüzey gerektirir: mevcut engine tek kaynak + skaler varsayıyor, client-seviyesi liste alanları ve ortam-parametrik hostname ister. |
| B | Conditional-OTP privileged | ⚠️ **AKIŞ HAZIR + DAVRANIŞ KANITLI, AMA BAĞLANMADI — owner kararı bekliyor.** 2026-07-27: bağlandı, aynı gün geri alındı, `browserFlow` desired-state'ten çıkarıldı. Sebep: "kimseyi etkilemiyor" ölçümüm YANLIŞTI. `roles/requires-mfa/users` yalnız **doğrudan** atamayı döner; rol asıl olarak **composite** ile dağılıyor ve ters yönü hiç sormamıştım. `requires-mfa`'yı içeren roller: `MEETING_ADMIN`, `ENDPOINT_ADMIN`, `TRANSCRIPT_ADMIN`, `ethics-manager`, `remote-bridge-approver`, `remote-bridge-operator` → **34 tekil kullanıcı** (admin hesabı + gerçek kişiler dahil), örneklenenlerin neredeyse hiçbirinde OTP kayıtlı değil. Yani bağlamak 34 kişiyi sonraki girişte TOTP kurulumuna zorluyordu. |

> **A2c karar kuralı (A2-obs ile ölçüme bağlandı, 2026-07-24).** A2c'nin önündeki
> engel bir "ekip kararı" değil, **veri yokluğuydu**: realm event logging **kapalıydı**
> (`eventsEnabled: false`), dolayısıyla `frontend` üzerinden hâlâ ROPC kullanan bir
> tüketici var mı **kimse bilmiyordu**. `harden-realm-security.sh` desired-state'ine
> `eventsEnabled: true` + `eventsExpiration: 604800` (7 gün) eklendi ve uygulandı
> (drift-korumalı; rollback snapshot'ı `--apply` çıktısında).
>
> Risk hatırlatması: `frontend` **public client** + `directAccessGrants=true` →
> parola grant'ı **client kimlik doğrulaması olmadan** çalışıyor. A2c'nin kapattığı
> risk tam olarak bu.
>
> **Karar sorgusu** (7 gün biriktikten sonra koşulur):
>
> ```bash
> docker exec platform-kc-test /opt/keycloak/bin/kcadm.sh get events \
>   -r platform-test --limit 200 \
>   | python3 -c "import json,sys; d=json.load(sys.stdin); \
>       f=[e for e in d if e.get('clientId')=='frontend' \
>          and (e.get('details') or {}).get('grant_type')=='password']; \
>       print('frontend ROPC login:', len(f)); \
>       [print(' ', e.get('userId'), e.get('ipAddress')) for e in f[:10]]"
> ```
>
> - Sonuç **0** → A2c güvenle uygulanır (kimse ROPC kullanmıyor).
> - Sonuç **>0** → çıktıdaki `userId`/`ipAddress` hangi tüketicinin `smoke-client`'a
>   taşınması gerektiğini **doğrudan** söyler; A2b.2 repoint deseni uygulanır.
>
> Kaydın çalıştığı kanıtlandı: ROPC token mint sonrası
> `type=LOGIN client=smoke-client grant_type=password` event'i kaydedildi.

Realm-level slice'lar `harden-realm-security.sh` `DESIRED_JSON`'a eklenir; **client-level** işler ayrı
resource-specific script'lerde (Codex: realm ve client farklı lifecycle/rollback semantiği).

> **A2b.1 ile kapanan A2a sınırı**: aşağıdaki "token kontratı YOK" tespiti **A2b.1'de giderildi**
> (scope-mapping + `smoke-runtime-v1` + `smoke-notify-v1` live). Tarihsel kayıt olarak korunuyor:
>
> **A2a kapsam sınırı (o anki dürüst durum)**: `smoke-client` **token üretiyor** (confidential ROPC, negatif
> grant'lar fail-closed) ama **hedef servislerin tüketebileceği token kontratı henüz YOK**:
> `fullScopeAllowed=false` + scope-mapping boş → `realm_access` düşer; `userId`/`org_id`/audience
> mapper'ları yok; ve **`azp=smoke-client` consumer allow-list'lerinde bulunmuyor** (ör.
> `endpoint-admin-service` `SECURITY_AUTH_ALLOWED_CLIENT_IDS: frontend,admin-cli,serban-web,account`)
> → token doğru olsa bile reddedilir. Bunlar **A2b.1**'in işi. A2a ≠ #2476 kapanışı.

### A2a `--rotate-secret` failure window

Rotation iki bağımsız sistem arasında **atomik değildir**:

1. Keycloak yeni client secret üretir
2. Yeni secret Vault'a yazılır
3. Vault↔Keycloak parity read-back yapılır

Keycloak rotation başarılı fakat Vault write/read-back başarısız olursa **KC ve Vault
geçici olarak mismatch kalır**. Script fail-closed non-zero döner ve başarı iddiasında
bulunmaz. A2a anında henüz runtime consumer YOK → blast radius substrate ile sınırlı;
**A2b.1 sonrası** aynı failure gerçek smoke consumer kesintisi üretir (o aşamada
rotation maintenance window gerektirir + rotation sonrası tüm token-mint acceptance'ı
yeniden koşulur).

**Recovery**:
- `--apply` mismatch'i **sessizce düzeltmez** ve yeniden rotate etmez (bilinçli fail-closed)
- Operator mevcut KC secret + Vault state'ini doğrular
- Vault erişimi düzeldikten sonra **explicit `--rotate-secret`** ile kontrollü rotation
  (yeni secret üretir; "current KC secret'ı Vault'a reconcile et" modu A2a'da YOK)
- Final gate: KC↔Vault parity + password grant `TOKEN` + `client_credentials` → `unauthorized_client`

## Ortam-kapsam (HARD RULE)

| Realm | Container | Yetki |
|---|---|---|
| `platform-test` | `platform-kc-test` (127.0.0.1:8082) | 🤖 **agent-otonom** yürütme (pre-prod). ⚠️ Yürütme otonomisi ≠ audit sınıfı: credential **read/write** içeren işler (ör. A2a Vault secret seed/rotation) ADR-0011 §2.3 boundary declaration + `user-approval-required` label + approval-evidence disiplinine tabidir. |
| `serban` (prod) | `platform-kc-prod` (127.0.0.1:8081) | 🧑 **owner-gated** — `CONFIRM_PROD_HARDEN=serban` env zorunlu |

> `CONFIRM_PROD_HARDEN=serban` yalnız **intent-guard**'dır (yanlış-realm'e kaza-apply
> engeli); operatör kimliği/onayı DEĞİL. Gerçek owner approval kanıtı dış
> workflow / board kaydında tutulur.

## Modes

```bash
# Drift raporu (MUTASYON YOK) — exit 0=converged, 2=drift
ssh halil@staging-sw 'REALM=platform-test bash -s -- --check' \
  < scripts/keycloak/harden-realm-security.sh

# Apply — pre-state snapshot → converge → postcondition assert (exit 0=PASS, 3=postcond-fail)
ssh halil@staging-sw 'REALM=platform-test bash -s -- --apply' \
  < scripts/keycloak/harden-realm-security.sh

# Rollback — fail-closed: snapshot realm-guard + full-key + type validate →
#            pre-rollback snapshot → geri yaz → read-back assert (exit 0=PASS, 1/3=fail)
ssh halil@staging-sw 'REALM=platform-test bash -s -- --rollback /home/halil/.kc-harden-snapshots/realm-platform-test-<TS>-apply.XXXXXX.json' \
  < scripts/keycloak/harden-realm-security.sh
```

Script host'ta `docker exec` ile kcadm çağırır (stdin-pipe → checkout'a bağımlı değil).

> **Secret disiplini**: admin password stdout/log'a **yazılmaz**; `kcadm config
> credentials` çağrısı sırasında kısa süre process argv'de taşınır (referans
> `setup-m365-broker.sh` ile aynı model). Bu nedenle bu script'te `set -x`,
> process-dump ve komut-satırı gözlemi **YASAK**. Snapshot dosyaları `umask 077`
> + `install -m 700` ile 0600/0700 oluşur.

## A1 — brute-force desired-state (10 alan, canlı KC 26.5.5'ten doğrulandı)

| Alan | Değer | Neden |
|---|---|---|
| `bruteForceProtected` | `true` | Asıl hardening — KAPALI'ydı |
| `bruteForceStrategy` | `MULTIPLE` | Wait-escalation modeli (KC26 default; her lockout eskale eder) |
| `failureFactor` | `5` | Endüstri-standardı eşik (30'du) |
| `permanentLockout` | `false` | Temp lockout — kalıcı hesap kaybı yok |
| `maxTemporaryLockouts` | `0` | `permanentLockout=false` ile tutarlı — permanent'a geçmez |
| `waitIncrementSeconds` | `60` | Her lockout blok artışı |
| `maxFailureWaitSeconds` | `900` | Bekleme süresinin **üst sınırı** (sabit süre değil) |
| `minimumQuickLoginWaitSeconds` | `60` | Quick-login penceresi |
| `quickLoginCheckMilliSeconds` | `1000` | 1sn içinde tekrar = quick-login |
| `maxDeltaTimeSeconds` | `43200` | 12h sonra sayaç reset |

### Kanıt (2026-07-16, throwaway persona)

```
correct-PRE-lockout : 200            ← doğru şifre önce çalışıyor
wrong-1..5          : 401 ×5         ← 5 başarısız deneme
correct-POST-lockout: invalid_grant  ← doğru şifreyle BİLE reddedildi
brute-force record  : "disabled": true  ← hesap geçici kilitli (+ quick-login koruması)
```

Persona sonunda silindi + brute-force kaydı temizlendi (kullanıcı login-user'ına dokunulmadı).

## Break-glass — kilitlenen hesabı açma

`permanentLockout=false` + `maxTemporaryLockouts=0` olduğu için lockout **kalıcı
değildir**. Temporary lockout süresi failure-count, quick-login detection ve
`bruteForceStrategy=MULTIPLE`'a göre hesaplanır; **yapılandırılmış üst sınır 900s**
(sabit 15dk DEĞİL). Acil manuel açma:

```bash
# Kullanıcı uid'ini bul
docker exec platform-kc-test /opt/keycloak/bin/kcadm.sh get users -r platform-test -q username=<user> --fields id
# Brute-force kaydını temizle (anında açar)
docker exec platform-kc-test /opt/keycloak/bin/kcadm.sh delete attack-detection/brute-force/users/<uid> -r platform-test
# Realm-geneli tüm kilitleri temizle (acil)
docker exec platform-kc-test /opt/keycloak/bin/kcadm.sh delete attack-detection/brute-force/users -r platform-test
```

> `master` realm admin'i platform-test brute-force'undan **etkilenmez** (ayrı realm) — operatör break-glass yolu korunur.

## Rollback (fail-closed)

Her `--apply` öncesi FULL realm snapshot `~/.kc-harden-snapshots/realm-<realm>-<TS>-apply.XXXXXX.json`
(0600, unique). `--rollback <snap>` sırası:

1. Snapshot **login öncesi** tek seferde validate: `.realm == $REALM` (cross-realm
   kaza engeli) + 10 yönetilen alanın **tamamı** mevcut (eksik → fail-closed) +
   her alan doğru tip (bool/int/str; bool≠int).
2. Rollback ÖNCESİ mevcut hardened state ayrıca snapshot'lanır (çift-yön geri-dönüş).
3. Snapshot değerleri geri yazılır.
4. Read-back: current managed alanlar snapshot ile eşleşmeli (yoksa `exit 3`).

Herhangi bir validasyon hatası → **hiçbir mutasyon yapılmadan** durur.

## Prod mirror (🧑 owner-gated)

Test kanıtı sonrası prod'a **owner onayıyla**:

```bash
ssh halil@staging-sw 'CONFIRM_PROD_HARDEN=serban REALM=serban bash -s -- --check' \
  < scripts/keycloak/harden-realm-security.sh   # önce drift gör
# owner onayı (board kaydı) → --apply
```

Prod realm `serban`; `CONFIRM_PROD_HARDEN=serban` olmadan script fail-closed durur.

## NE YAPMA

- ❌ Realm güvenlik ayarını kcadm ile **elle** değiştirme — declarative kaynak dışında drift oluşur.
- ❌ `permanentLockout=true` yapma (test) — operatör/persona kalıcı kilitlenir, break-glass zorlaşır.
- ❌ Prod'a `CONFIRM_PROD_HARDEN` olmadan apply denemesi (zaten fail-closed).
- ❌ Snapshot'ları silme — rollback kaynağı.
- ❌ `set -x` / process-dump ile çalıştırma — admin password argv'de kısa süre görünür.

## Referanslar

- board #2476 · Codex thread `019f69f6`
- `scripts/keycloak/harden-realm-security.sh`
- `scripts/keycloak/setup-m365-broker.sh` (kcadm idempotent pattern kaynağı)
- Global HARD RULE — Credential/Güvenlik Ortam-Kapsamlı (test serbest / prod owner-gated)

## A2b.1 — smoke-client token contract (Codex `019f6b1d` v3.2 SEAL)

`setup-smoke-token-contract.sh` **yalnız Keycloak**'ı converge eder; **consumer manifest mutasyonu YOK**.

```bash
ssh halil@staging-sw 'REALM=platform-test bash -s -- --check' < scripts/keycloak/setup-smoke-token-contract.sh
ssh halil@staging-sw 'REALM=platform-test bash -s -- --apply' < scripts/keycloak/setup-smoke-token-contract.sh
```

**Exit sözleşmesi (her iki mod, canonical audit'ten):**

| exit | Anlam |
|---|---|
| `0` | `SAFE` — converged (apply'da: mutasyon gerekmedi veya postcondition PASS) |
| `2` | `MISSING` — yalnız **güvenli eksik** var (`--check`); `--apply` bunları yaratır |
| `3` | `UNSAFE` — **`--check`**: güvenli-olmayan mevcut state · **`--apply`**: ya pre-mutation barrier (hiç mutasyon yapılmadı) ya stage-2 barrier (scope yaratıldı, association YAPILMADI) ya da postcondition-fail |
| `1` | audit/girdi/mutasyon hatası (kısmi state kalmış olabilir → `--check` ile doğrula) |

> **Snapshot bütünlüğü**: kcadm okuma hatası **"boş state" sayılmaz**. Bir GET başarısız olursa
> audit `UNSAFE: snapshot incomplete` verir ve mutasyon yapılmaz — aksi halde script, okunamayan
> bir scope-mapping'i "yok" sanıp **bilinmeyen canlı state üzerinde** mutasyon yapardı.

### Desired (v3.2)

| Nesne | İçerik |
|---|---|
| `smoke-runtime-v1` (**default**) | `userId` (attr/claim=`userId`, **jsonType=String**) + audience ×6: `endpoint-admin-service`, `permission-service`, `variant-service`, `notification-orchestrator`, `auth-service` (custom) + `account` (**gerçek client audience**) |
| `smoke-notify-v1` (**optional**) | `org_id` (attr/claim=`org_id`, String) — `scope=openid smoke-notify-v1` ile capability switch |
| realm scope-mapping | yalnız `ENDPOINT_ADMIN` (`composite=false` preflight'ta doğrulanır; `fullScopeAllowed=false` kalır) |

### Neden bunlar YOK (Codex gerekçeleri — değiştirmeden önce oku)

- **Consumer `azp` allow-list'e `smoke-client` EKLENMEZ.** endpoint-admin validator semantiği `audience OR azp OR client_id`; allow-list'e eklemek **audience binding'ini bypass eden** bir fallback açar ve "doğru audience ile geçti" kanıtını yok eder. Canlı allow-list `frontend,admin-cli,serban-web,account` olarak **kalır**.
- **`notify-canary`'ye DOKUNULMAZ.** Shared scope (`frontend`'de **DEFAULT**), mapper sayısı **0** → yalnız scope-string marker'ı; backend onu **okumuyor** (guard sırası `org_id → tenant_id → allowed_orgs → default`, ve TEST'te `NOTIFY_SECURITY_DEFAULT_ORG_ID=""`). Sessizce sahiplenip mutate etmek frontend'in tüm token'larını etkilerdi.
- **`tenant_id` mapper EKLENMEZ** — aynı `org_id` attribute'unun ikinci alias'ı; gereksiz token genişlemesi.
- **`VARIANT_SCOPE_CANARY` / generic `ADMIN` EKLENMEZ** — variant allow otoritesi permission DB/OpenFGA `allowedScopes` + numeric `PROJECT:<id>`; token rolü değil.
- **`userId` `long` DEĞİL, `String`** — canlı `frontend` mapper'ı String; auth-service hem number hem numeric-string kabul ediyor. `long` yapmak smoke'a özgü parity sapması yaratırdı.
- **Client-level mapper eklenmez** — mapper'lar scope-owned; read-back client mapper sayısını `0` bekler.

### Canlı kanıt (2026-07-16, throwaway persona; token transcript'e yazılmaz)

```
apply read-back : smoke-runtime-v1=7 mapper · smoke-notify-v1=1 · default/optional assoc ✓ · scope-mapping=[ENDPOINT_ADMIN] ✓
token projection: azp=smoke-client · aud⊇6 · beklenmeyen aud yok · userId='987654' (String, ^[0-9]+$)
                  admin ENDPOINT_ADMIN ✓ / viewer yok ✓ / generic ADMIN yok ✓
                  normal: org_id+tenant_id YOK · notify: org_id='default' · scope'ta notify-canary YOK
                  client_credentials → unauthorized_client ✓
consumer        : permission /authz/me → 200  **canlı allow-list'te smoke-client YOK iken**
                  (= azp fallback ile değil, audience ile geçti — Codex acceptance kombinasyonu)
                  endpoint-admin token-yok → 401 (fail-closed) · admin persona → 403 (aşağıya bak)
                  variant 1204/1205 → 403/403 (persona'da VARIANTS_READ + PROJECT:1204 seed yok — beklenen)
```

### Fail-closed kanıtı (canlı drill, 2026-07-16 — iddia değil, koşuldu)

Script'in "UNSAFE state'te hiçbir mutasyon yapmaz" sözleşmesi TEST realm'de geri-alınabilir drill ile kanıtlandı:

```
1. UNSAFE üret : notify-canary → smoke-client optional association (elle)
2. --check     : [UNSAFE] notify-canary OPTIONAL association'da olmamalı (live d=False o=True / beklenen d=False o=False)
                 VERDICT=UNSAFE:1 → exit 3
3. --apply     : "SAFETY BARRIER: UNSAFE state — HİÇBİR mutasyon yapılmadı (exit 3)"
                 → çıktıda TEK BİR mutasyon satırı ("+ …") YOK; drift silinmedi/düzeltilmedi
4. drill geri al: notify-canary unbind
5. --check     : VERDICT=SAFE → exit 0
```

Ayrıca idempotency: converged state'te `--apply` → "zaten converged — mutasyon yok (exit 0)".

**Scalar-claim invariant canlı doğrulandı**: `multivalued`/`aggregate.attrs` audit'e eklendiğinde
canlı mapper'larda bu alanların **hiç set edilmediği** ortaya çıktı (`live=None`) → audit `UNSAFE`
verdi (script kendi düzeltmedi). Scope'lar silinip `--apply` ile yeniden yaratıldı (create → **ikinci
barrier** → association → scope-mapping) → `13/13 [OK] VERDICT=SAFE`. Token projection tekrar koşuldu:
`userId='987654'` skaler string (`^[0-9]+$`, liste DEĞİL) · `org_id='default'` skaler · `aud ⊇ 6` ·
`azp=smoke-client` · admin `ENDPOINT_ADMIN` · normal token'da `org_id` yok — **8/8 PASS**.
Gerekçe: `jsonType.label=String` tek başına skaler garantisi değildir; `multivalued=true` claim'i
string listesine çevirip auth-service'in `Long.parseLong` beklentisini sessizce bozardı.

### `--apply` non-atomic (dürüst sınır)

scope create + association + scope-mapping **tek transaction değildir**. Ara adım başarısız olursa
kısmi state kalabilir. Disiplin: **non-zero exit asla başarı değildir**; token mint etmeden önce
`--check` koş; kısmi state'i tahmin etme; UNSAFE yoksa `--apply`'ı tekrar çalıştır (idempotent);
exact read-back `0` vermeden acceptance başlatma. (A2a'daki rotation failure-window dürüstlüğünün
A2b.1 karşılığı.)

### Bilinen açık (A2b.1 acceptance'ı kapatmak için gereken — Codex: A2b.2'ye ERTELENMEZ)

- **endpoint-admin allow/deny**: doğru dış path **`/api/v1/endpoint-admin/endpoint-devices`**
  (gateway rewrite `/api/v1/endpoint-admin/<seg>` → `/api/v1/admin/<seg>`; gerçek controller
  `AdminEndpointDeviceController` = `/api/v1/admin/endpoint-devices`). `…/devices` **404 verir** —
  route yok, bug değil. Canlı sonuç: token-yok → **401** ✓ · viewer → **403** ✓ · admin persona →
  **403** (200 değil) çünkü `ENDPOINT_ADMIN` realm rolü tek başına yetmiyor; permission-service/OpenFGA
  persona state gerekiyor.
- **variant scoped 200**: persona'ya permission DB/OpenFGA `VARIANTS_READ` + numeric `PROJECT:1204` seed'i
  gerekir (`1204 → 200`, scope-dışı `1205 → 403`). Şu an 403/403 = yalnız fail-closed kanıtı.
- **notification 403/202**: `scope=openid smoke-notify-v1` + persona `org_id` eşleşmesi
  (`NOTIFY_SECURITY_DEFAULT_ORG_ID=""` → fallback kapalı; guard sırası `org_id → tenant_id → allowed_orgs → default`).
- **impersonation 403/201**: non-superAdmin → 403, gerçek superAdmin → 201 (`userId` claim + permission-service'e
  forward edilen bearer zinciri).

> **Persona seed script'e KOYULMAZ** (Codex): Keycloak client contract ile permission DB/OpenFGA persona
> state **farklı lifecycle ve rollback yüzeyleri**. Seed ayrı/idempotent bir TEST helper'ı olarak yürütülür.

### Ayrı truth-item (A2b.1'e karıştırılmadı — Codex)

`auth-service` audience enforcement: TEST overlay `SECURITY_JWT_AUDIENCE`/"strict validator" yorumu ile kaynak `SecurityConfigKeycloak` davranışı örtüşmüyor (env açıkça tüketilmiyor olabilir). Ayrı backend/GitOps PR + kendi rollout acceptance'ı gerekir (impersonation gibi hassas consumer'ı etkiler).

## A2c — `frontend` ROPC kapatıldı (LIVE 2026-07-27)

Sıralama önemliydi: **önce tüketiciler taşındı, sonra flip**. Böylece flip tek satırlık bir
değişikliğe indi ve geri alınabilir kaldı.

Taşınan ROPC tüketicileri (6 script, 2 PR):

```
#2991  faz35/provision-test-openfga.sh                  -> smoke-client
       faz35/verify-test-openfga-authz.sh               -> smoke-client
#2994  faz35/provision-test-keycloak.sh                 -> smoke-client
       faz35/provision-test-ethic-entitlement.sh        -> smoke-client
       faz24/repair-d35-permission-writer-credential.sh -> smoke-client
       ats/d29-smoke-receipt-chain.sh                   -> smoke-ats-v1
```

Envanteri **iki kez** eksik saydım. Ders: `client_id=frontend` literalini grep'lemek yetmez;
client değişkende (`WRITER_CLIENT="frontend"`) veya argümanda (`tok frontend ...`) olabilir.
Doğru tarama yetki akışından başlar:

```bash
grep -rl "grant_type=password" scripts/ | while read -r f; do
  printf "%-58s %s%s\n" "$f" \
    "$(grep -oE 'client_id=[A-Za-z0-9_${}.-]+' "$f" | sort -u | tr '\n' ' ')" \
    "$(grep -oE '[A-Z_]*CLIENT[A-Z_]*="[a-z0-9-]+"' "$f" | sort -u | tr '\n' ' ')"
done
```

### Flip kanıtı

```
ÖNCE   directAccessGrantsEnabled=True   frontend ROPC 200   smoke-client ROPC 200
SONRA  directAccessGrantsEnabled=False  frontend ROPC 400 unauthorized_client
                                        smoke-client ROPC 200
       standardFlowEnabled=True (dokunulmadı)
       GET /auth?client_id=frontend -> 200, giriş formu render edildi (8714 bayt)
       GET https://testai.acik.com/ -> 200
```

Flip yalnız **direct access grant**'ı kapatır; tarayıcının kullandığı authorization-code
akışı `standardFlowEnabled` altındadır ve dokunulmadı — yukarıdaki `/auth` kanıtı bunu
gösteriyor. Bu yüzden değişiklik tasarım gereği UI-etkili değil; tam tarayıcı oturumu
açmadım (test personası şifresini bir forma yazmak credential-handling sınırına girer).

### Dayanıklılık

`platform-test` realm'ini import eden hiçbir manifest `frontend` client'ını tanımlamıyor
(`bootstrap/local-fixtures/keycloak/dev-local-realm.json` ayrı bir dev realm'i), yani flip'i
sessizce geri alacak bir import yok. `run-platform-desktop-token-evidence-chain.sh` geçici
olarak DAG açıyor ama hedefi `platform-desktop` ve `trap ... EXIT` ile eski değeri geri
yazıyor — `frontend`'e dokunmuyor.

### Rollback

```bash
ssh aiserver 'docker exec platform-kc-test /opt/keycloak/bin/kcadm.sh update \
  clients/4dfdddf4-8464-44ad-bb3d-df9de8de62e1 -r platform-test \
  -s directAccessGrantsEnabled=true'
```

## B (privileged MFA) — durum, yanlış ölçüm ve yeniden bağlama koşulları

**Akış hazır ve davranışı kanıtlı**, ama şu an **bağlı değil** (`browserFlow=browser`) ve
`browserFlow` `harden-realm-security.sh` desired-state'inde **değil** — yani hiçbir
converge çalışması onu yeniden kurmaz.

Davranış kanıtı (2026-07-27, throwaway client+user sondası, sonra realm seviyesinde):

```
requires-mfa YOK  → yetki kodu ALINDI, OTP istenmedi
requires-mfa VAR  → 302 → login-actions/required-action?execution=CONFIGURE_TOTP
```

### Neden geri alındı — ölçüm hatası

Bağlamanın "kimseyi etkilemediğini" söylemiştim. **Yanlıştı.** `roles/requires-mfa/users`
yalnız **doğrudan** atamaları döndürür ve `0` verdi; rol asıl olarak **composite** ile
dağıtılıyor ve ben **ters yönü** (hangi roller `requires-mfa`'yı içeriyor) hiç sormamıştım.

```
requires-mfa'yı içeren roller : MEETING_ADMIN · ENDPOINT_ADMIN · TRANSCRIPT_ADMIN
                                ethics-manager · remote-bridge-approver · remote-bridge-operator
efektif taşıyan               : 34 TEKİL kullanıcı (admin hesabı + gerçek kişiler dahil)
OTP kayıtlı                   : örneklenenlerde neredeyse yok
```

Yani bağlamak 34 kişiyi sonraki tarayıcı girişinde TOTP kurulumuna zorluyordu — dormant
değil, canlı bir etki. Fark edildiği anda geri alındı.

### Rol miras zincirini doğru sorgulama

```bash
# YANLIŞ (yalnız doğrudan atama):
kcadm get roles/requires-mfa/users -r platform-test
# DOĞRU (ters yön — hangi composite içeriyor):
for r in $(kcadm get roles -r platform-test --fields name --format csv --noquotes); do
  kcadm get "roles/$r/composites" -r platform-test 2>/dev/null | grep -q '"requires-mfa"' && echo "$r içerir"
done
# ve kullanıcı bazında EFEKTİF rol:
kcadm get "users/<id>/role-mappings/realm/composite" -r platform-test
```

### Composite teslim tamamen BIRAKILDI — marker adı geçen insanlara doğrudan atanır

İlk tasarım `requires-mfa`'yı 6 ayrıcalıklı role composite child olarak ekliyordu. İki ölçüm
bunun yanlış olduğunu gösterdi.

**1) Otomasyon TOTP yapamaz.** Altı rolün 34 sahibinin dağılımı (2026-07-27 ölçümü):

| sınıf | sayı | örnekler |
|---|---|---|
| **İNSAN** | **4** | `admin@example.com`, `etik-staff@acik.com`, `halil.kocoglu@serban.com.tr`, `zeynep.akkilic@serban.com.tr` |
| belirsiz otomasyon | 4 | `codex-faz226-approver/creator`, `endpoint-admin-lock-approver/proposer` |
| sentetik persona | 26 | `ag028-*`, `ag029-*`, `ag042-*`, `c5persona-*`, `codex-*-smoke-*`, `rb-operator-*`, `ethics-manager-*-test`, `endpoint-admin-test-approver`, `test-recorder-182` |

34'ün **30'u otomasyon**. Bir script TOTP kaydını tamamlayamaz; akış bağlandığı an her
ENDPOINT_ADMIN smoke personası, her AG-0xx acceptance personası ve her remote-bridge
operator kimliği kırılırdı.

**2) Composite ebeveyni değiştirir ve kendi erişimini saklar.** Marker'ı composite child
yapmak `ethics-manager.composite`'ini `false`→`true` çevirdi ve Faz 35 zincirinde 4 kontrolü
düşürdü. Ayrıca `roles/requires-mfa/users` yalnız **doğrudan** atamayı döndüğü için `0`
okuyordu — oysa 34 kullanıcı efektif olarak taşıyordu. Etki alanı bariz sorguda görünmeyen
bir güvenlik kontrolü kötü bir kontroldür.

**Yeni tasarım:** marker hiçbir role composite yazılmaz; `DIRECT_MFA_USERS`'taki adı geçen
4 insana **doğrudan** atanır. Ebeveyn rolün şekli değişmez, bariz sorgu dürüst olur,
otomasyon hiç etkilenmez. Maliyeti listenin açık olması — bu yüzden `--check` ayrıcalıklı
rol taşıyıp listede olmayan insan-görünümlü kimlikleri **raporlar ama otomatik EKLEMEZ**;
birinin insan olduğuna karar vermek scriptin işi değil. `AUTOMATION_MARKERS`'a uyan bir
kimlik listeye konursa `--apply` hata verip durur.

Guard: `tests/operations/test_privileged_mfa_delivery_invariant.py` — composite'e POST
yazımını, listedeki otomasyon kimliğini ve (yeniden composite'e dönülürse) şekil-pinli rol
çakışmasını reddeder. Eski `test_mfa_composite_target_shape_invariant.py` kaldırıldı:
composite hedefi kalmadığı için boş yere geçiyordu.

**OTP kayıt penceresi 34 hesaptan 4 kişiye indi** — kalan tek soru bu 4 kişinin ne zaman
TOTP kaydedeceği.

### Mutlu yol kanıtı (2026-07-27) — kayıt → oturum ÇALIŞIYOR

Önceki kanıt yalnız *tetiklemeyi* gösteriyordu (rol yok → OTP yok, rol var → `CONFIGURE_TOTP`).
Sizden 4 gerçek hesap için MFA'yı silahlandırmanızı istemek, **kayıt sonrası girişin
çalıştığını** göstermeden yanlış olurdu. Tek kullanımlık persona ile ölçüldü
(`browserFlow` test süresince bağlandı, `finally` ile `browser`'a geri alındı; persona silindi):

```
persona oluştu + requires-mfa doğrudan atandı            PASS
akış test için bağlandı                                   PASS
giriş formu servis edildi                                 PASS
şifre kabul → TOTP kaydı talep edildi              http=200  PASS
kayıt formunda gizli totpSecret var (len=20)              PASS
TOTP kaydı kabul → authorization code verildi      http=302  PASS
kod access token'a değiştirildi                    http=200  PASS
ikinci giriş yeniden-kayıt DEĞİL, OTP kodu istiyor http=200  PASS
yanlış OTP reddedildi                              http=200  PASS
saklanan credential'lar: ['password', 'otp']
DB'deki credential_data: {"subType":"totp","digits":6,"period":30,"algorithm":"HmacSHA1"}
```

**Yani asıl bilinmeyen kapandı:** `requires-mfa` taşıyan bir kullanıcı TOTP kaydını
tamamlayabiliyor ve kullanılabilir bir oturum alıyor. Akışın *özel* kısmı (role bağlı
CONDITIONAL subflow) uçtan uca çalışıyor.

**KanıtlanMAYAN:** scriptli istemcimin, sonraki bir girişte **saklanan** credential'ın
kabul ettiği bir kod üretmesi. Üç anahtar türetmesi denendi (form'daki ham secret, DB'deki
değer, base32); kayıt aşamasında **aynı** hesaplama KC tarafından kabul edildiği hâlde
giriş formunda reddedildi. Bu bir **harness sınırı** — admin API secret'ı gizliyor ve
farkı izole edemedim; akışın meşru kullanıcıyı reddettiğinin kanıtı **değil**: ikinci giriş
stok `kc-otp-login-form` + `auth-otp-form` ile karşılıyor ve saklanan credential standart
TOTP/6/30/HmacSHA1. Ayrım önemli olduğu için olduğu gibi yazıldı.

Pratik sonuç: 4 kişiden ilki kaydını yaptıktan sonra **gerçek bir tarayıcıyla tek bir giriş
denemesi** bu boşluğu kapatır. Bağlamayı ondan sonra kalıcı yapmak en güvenli sıra.

### Yeniden bağlamanın ön koşulları

1. Etkilenen 34 kullanıcının listesi owner ile netleşir (hangileri gerçek kişi, hangileri test personası)
2. OTP kayıt penceresi planlanır (kim, ne zaman kaydeder)
3. Tercihen `requires-mfa` composite'lerden çıkarılıp **hedefli** atanır — o zaman kapsam öngörülebilir olur
4. Bağlandıktan sonra `browserFlow` desired-state'e geri konur, aksi halde canlı/desired drift kalır

Bağlama ve geri alma komutları:

```bash
ssh aiserver 'docker exec platform-kc-test /opt/keycloak/bin/kcadm.sh update realms/platform-test -s browserFlow=browser-privileged-mfa'
ssh aiserver 'docker exec platform-kc-test /opt/keycloak/bin/kcadm.sh update realms/platform-test -s browserFlow=browser'
```

