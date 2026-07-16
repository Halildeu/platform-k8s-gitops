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
| **A1** | Brute-force protection (`failureFactor=5` + 10-param converge) | ✅ bu sürüm |
| A2 | ROPC migrasyon → `frontend.directAccessGrants=false` | sonraki PR |
| A3 | redirectUri + webOrigins narrowing | sonraki PR |
| B | Conditional-OTP privileged (admin/manager) | ayrı flow PR |

Sonraki slice'lar aynı script'in `DESIRED_JSON` bloğuna eklenir (tek declarative kaynak).

## Ortam-kapsam (HARD RULE)

| Realm | Container | Yetki |
|---|---|---|
| `platform-test` | `platform-kc-test` (127.0.0.1:8082) | 🤖 **agent-otonom** (pre-prod, test-env credential/security serbest) |
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
