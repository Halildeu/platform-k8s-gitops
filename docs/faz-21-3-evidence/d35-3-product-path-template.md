# D35-3 — Product Path UI Persona Evidence (mfe-access "Veri Erişimi")

> **Template — kopyala, doldur, `docs/faz-21-3-evidence/<YYYY-MM-DD>-d35-3-ui-persona-<run-id>.md` adıyla kaydet.**
>
> Tier semantik: D35-3 = D35 ladder son halka. Backend REST chain (D35-2-full) PASS olmadan D35-3 koşulmaz; UI fail olursa D35-2-full kanıtı bağımsız durur (Codex `019dd409` ayrı tier kararı).

**Tier**: D35-3
**Date**: <YYYY-MM-DD UTC>
**Cluster**: k3d-test on staging-sw
**Permission-service image digest**: `sha256:219b053777478fa048fbe04b4f990f477a1091d2e2a49c0691e18c340a5c9406` (sha-943bd5f, V25 alignment)
**Frontend image / build**: `<mfe-access build hash veya GHCR digest>` (PR `platform-web#34` sha-`57dc28e8` mfe-access Veri Erişimi panel — 5 tab + assign UI + 4-locale i18n + 28 tests)
**Codex thread**: `019dd409` (D35-3 prereq strategy)
**Operator**: <agent-name veya operatör adı; gerçek persona browser session burada>
**Upstream evidence**:
- D35-2-full PASS: `docs/faz-21-3-evidence/<YYYY-MM-DD>-d35-2-full-<run-id>.md`

## What this evidence proves

mfe-access **Veri Erişimi** ekranı üzerinden **gerçek kullanıcı persona'sı** ile:
1. Tarayıcıdan login (Keycloak SSO + persona oturumu)
2. mfe-access "Veri Erişimi" sekmesine navigate
3. Yeni scope grant: kullanıcı + organizasyon + scope_kind + scope_ref → "Ata" butonu
4. UI feedback: 201 + outbox/sync status; success toast / table row
5. Backend correlation: aynı request_id ile permission-service log + outbox row + FGA tuple
6. Revoke action: scope row "İptal Et" → 204 + UI tüm tablodan kaldırma
7. Backend correlation: REVOKE outbox PROCESSED + FGA tuple delete
8. Granted user UI flow'u: kendisine ait scopes listelendiğini görür (D35-3'ün D35-2 ile farkı: gerçek persona ekranı görüyor)

D35-3 PASS edilince Faz 21.3 D35 ladder **tam kapanır** (D35-0 + D35-1 + D35-2-full + D35-3).

## Prereq'ler

- [ ] D35-2-full PASS (canlı kanıt dosyası mevcut)
- [ ] **Admin persona Keycloak hesabı**: `RB-faz-21-3-d35-3-keycloak-admin-jwt.md` runbook'u ile oluşturuldu
- [ ] **Granted persona Keycloak hesabı**: en az 1 normal user, scope alacak
- [ ] **`module:ACCESS#can_manage` admin persona için seedlendi** (UI grant butonu çalışsın)
- [ ] **`module:ACCESS#can_view` granted persona için seedlendi** (kendi scopes listesini görsün — opsiyonel, UI flow'a göre)
- [ ] **Browser**: Chrome/Firefox DevTools açık (network log için)
- [ ] **Screen recording**: video veya 4-6 screenshot capture aracı hazır

## Setup (operatör tek seferlik)

```bash
RUN_ID="d35-3-ui-$(date +%Y%m%d-%H%M)"

# Operatör Keycloak runbook tamamlanınca aşağıdakileri kendi env'inden export eder.
# Agent transcript'inde gerçek username/UUID görmesin — bu blok sadece şablon.
: "${ADMIN_PERSONA_USER:?set from RB-faz-21-3-d35-3-keycloak-admin-jwt.md Step 2}"
: "${GRANTED_PERSONA_USER:?set from RB-faz-21-3-d35-3-keycloak-admin-jwt.md Step 3}"
: "${GRANTED_PERSONA_UID:?Keycloak admin GET /users -> .[0].id; backend log correlation için kullanılır}"

ORG_NAME="AÇIK"
TENANT_COMPANY="Mikrolink Bilişim"  # OUR_COMPANY.COMP_ID=1 ile eşleşir

mkdir -p docs/faz-21-3-evidence
EVIDENCE="docs/faz-21-3-evidence/2026-XX-XX-d35-3-ui-persona-${RUN_ID}.md"
echo "# D35-3 evidence — ${RUN_ID}" > "${EVIDENCE}"
```

## UI persona flow checklist

> Her adımda **screenshot** + **timestamp** + **browser request URL** kaydet. Screenshot dosyaları repo'ya `docs/faz-21-3-evidence/screenshots/<run-id>/` altına eklenebilir veya operatör'ün secure storage'ına link verilebilir.

### Step 1 — Login (admin persona)

- [ ] `https://testai.acik.com/` aç
- [ ] Keycloak SSO ekranı görünüyor
- [ ] `${ADMIN_PERSONA_USER}` ile giriş yap
- [ ] Frontend açılınca dashboard ekranı görünür
- [ ] Browser cookie'lerinde Keycloak session token yerleşmiş (DevTools → Application → Cookies)

**Screenshot**: `01-login-success.png` (dashboard ilk render'ı)
**Capture**: timestamp + persona username
**Network log**: `<filter: keycloak>` → token endpoint 200

### Step 2 — Navigate to mfe-access "Veri Erişimi"

- [ ] Sidebar veya top-nav'dan "Erişim Yönetimi" / "Access Management" alanına gir
- [ ] mfe-access yüklenir (microfrontend boot — DevTools network log'da `mfe-access*.js` görmeli)
- [ ] "Veri Erişimi" sekmesi görünür (5 tab arasında — `feat: faz-21-3-pr-e mfe-access #34` sayesinde)
- [ ] Tab'a tıkla — `data-access` UI ekranı render

**Screenshot**: `02-veri-erisimi-tab.png` (boş/dolu liste)
**Network log**: mfe-access bundle hash + GET `/api/v1/access/scope?orgId=1` (admin'in görüş listesi)

### Step 3 — Yeni grant: "Erişim Ata" akışı

- [ ] "Yeni Erişim Ata" / "Add Access" butonu görünür → tıkla
- [ ] ScopeAssignModal açılır (4 form alanı: kullanıcı select + org + scope_kind + scope_ref)
- [ ] **User select**: `${GRANTED_PERSONA_USER}` seç
- [ ] **Organization select**: `${ORG_NAME}` (sabit veya dropdown — UI'ya göre)
- [ ] **Scope kind**: "Şirket / Company" seç
- [ ] **Scope ref**: `${TENANT_COMPANY}` (Mikrolink Bilişim) seç — UI bu değeri OUR_COMPANY.COMP_ID=1'e çevirip `["1"]` JSON'a dönüştürmeli
- [ ] "Onayla" / "Kaydet" butonuna tıkla
- [ ] **Loading state** görünür (spinner / disabled button)
- [ ] **Success feedback** görünür (toast veya inline mesaj)
- [ ] Listeye yeni satır eklenir: `${GRANTED_PERSONA_USER}` / `Şirket` / `Mikrolink Bilişim`
- [ ] Yeni satırda **tupleSyncStatus** gösterimi (PENDING → PROCESSED) — eğer UI bu kolonu render ediyorsa polling/refresh ile

**Screenshot**:
- `03a-modal-form-filled.png` (form doldurulmuş, henüz submit edilmemiş)
- `03b-grant-success.png` (success toast + yeni row)
- `03c-row-detail.png` (row'a tıklanınca detail panel — outbox status varsa)

**Browser network log**:
- `POST /api/v1/access/scope` → 201 (timestamp, response body kaydet)
- Subsequent `GET /api/v1/access/scope` (refresh çağrısı varsa) → 200 + array içinde yeni scope

**Backend correlation** (UI'dan tek bir scope_id aldıktan sonra):
```bash
SCOPE_ID="<UI'dan response.scopeId>"
ssh halil@staging-sw "docker exec platform-pg-test psql -U platform -d reports_db -c \
  \"SELECT id, user_id, org_id, scope_kind, scope_source_table, scope_ref, granted_by, granted_at \
    FROM data_access.scope WHERE id = ${SCOPE_ID};\"" >> "${EVIDENCE}"

ssh halil@staging-sw "docker exec platform-pg-test psql -U platform -d reports_db -c \
  \"SELECT id, status, tuple_object, processed_at \
    FROM data_access.scope_outbox WHERE scope_id = ${SCOPE_ID};\"" >> "${EVIDENCE}"
```

**Gate**:
- DB row: scope_source_table=`OUR_COMPANY` + scope_ref=`["1"]` (V25 contract)
- Outbox: tuple_object=`company:wc-our-company-1` + status=`PROCESSED`
- granted_by = admin persona UUID (controller authentication chain doğrulama)

### Step 4 — Granted persona perspektifi (yeni session, opsiyonel)

> Bu adım `module:ACCESS#can_view` granted persona için seedlenmişse mümkün; değilse skip ve evidence'a "skipped: can_view tuple not seeded" yaz.

- [ ] **Yeni incognito browser session** veya logout + farklı user login
- [ ] `${GRANTED_PERSONA_USER}` ile giriş yap
- [ ] mfe-access "Veri Erişimi" sekmesine gir
- [ ] **Kendi sahip olduğu scope'u görür**: `Şirket` / `Mikrolink Bilişim` (Step 3'te admin'in atadığı)

**Screenshot**: `04-granted-persona-self-list.png`

### Step 5 — Revoke action

- [ ] Admin persona ile dön (yeni session veya logout/login)
- [ ] Step 3'te oluşan satırı bul → "İptal Et" / "Revoke" butonuna tıkla
- [ ] **Confirmation dialog** görünür → onayla
- [ ] Listeden satır kaldırılır (veya "İptal" badge'i ile gri görünür — UI policy)
- [ ] **Success feedback** toast

**Screenshot**:
- `05a-revoke-confirm.png` (dialog)
- `05b-revoke-success.png` (post-state)

**Browser network log**:
- `DELETE /api/v1/access/scope/${SCOPE_ID}` → 204

**Backend correlation**:
```bash
ssh halil@staging-sw "docker exec platform-pg-test psql -U platform -d reports_db -c \
  \"SELECT id, status, action, tuple_object, processed_at \
    FROM data_access.scope_outbox WHERE scope_id = ${SCOPE_ID} ORDER BY id;\"" >> "${EVIDENCE}"
```

**Gate**: 2 outbox row, action ordered GRANT/REVOKE, ikisi de PROCESSED.

### Step 6 — Granted persona /check FLIP

> Backend log + OpenFGA check ile FLIP doğrulama.

```bash
STORE_ID=$(vault kv get -field=store_id kv/platform/openfga)
MODEL_ID=$(vault kv get -field=model_id kv/platform/openfga)
GRANTED_USER="user:${GRANTED_PERSONA_UID}"

curl -sf -X POST "http://${OPENFGA_URL}/stores/${STORE_ID}/check" \
  -H 'Content-Type: application/json' \
  -d "{
    \"authorization_model_id\": \"${MODEL_ID}\",
    \"tuple_key\": {
      \"user\": \"${GRANTED_USER}\",
      \"relation\": \"viewer\",
      \"object\": \"company:wc-our-company-1\"
    }
  }" | tee -a "${EVIDENCE}"
```

**Gate**: `{"allowed": false}` (revoke öncesi true idi → false; FLIP).

### Step 7 — Backend log correlation by request_id

```bash
# UI grant request'in backend logs üzerindeki trace_id ile son ~5dk
ssh halil@staging-sw "POD=\$(kubectl --context k3d-test -n platform-test \
  get pod -l app.kubernetes.io/name=permission-service \
  -o jsonpath='{.items[0].metadata.name}') && \
  kubectl --context k3d-test -n platform-test logs \$POD --since=5m | \
  grep -E 'data_access scope granted|data_access scope revoked|outbox.*PROCESSED|trace_id'" >> "${EVIDENCE}"
```

**Gate**: backend log'da grant + revoke + outbox PROCESSED satırları persona request'leriyle correlate eder; trace_id browser network log'undaki `X-Request-Id`/`traceparent` header ile eşleşir.

## D35-3 required captures (per docs/d35-evidence-template.md)

- [x] UI flow screenshot/video (Step 1-5 sırası)
- [x] User persona identity (admin + granted, both with username/UUID)
- [x] UI scope-grant action → backend log correlation (Step 3 + 7)
- [x] UI revoke action → backend log correlation (Step 5 + 7)
- [x] Browser network log (POST/DELETE/GET pattern)
- [x] mfe-access version + build info (Step 2)
- [x] Backend log correlation IDs (Step 7)

## Verdict

**Tier verdict**: PASS | FAIL | PARTIAL

**Failure modes** (eğer var):
- UI render kırık → mfe-access build/deploy
- POST 401/403 → JWT veya `module:ACCESS#can_manage` seed yok
- POST 422 → V25 trigger reject (scope_ref hatalı veya organization_company seed eksik)
- POST 500 → backend internal (V25 hizalama bug, encoder mismatch — D35-2-full geçti ise burada olmamalı)
- Outbox not PROCESSED → poller gate veya FGA unreachable

**Limitations**: production cluster (k3d-prod) kapsam dışı.

**Next**: D35-3 PASS → Faz 21.3 D35 ladder closure document (`docs/state/current-state.md` refresh + PLAN.md status update).

Completed: <UTC ISO timestamp>

## References

- ADR-0008 § "Object id encoding" (V25 transition map)
- ADR-0009 § D35 Evidence Ladder
- ADR-0010 §2.5 (operator/agent matrix)
- ADR-0011 §2.3 (cross-repo boundary)
- D35-2-full template: `docs/faz-21-3-evidence/d35-2-full-template.md`
- D35-2-limited (superseded by D35-2-full): `docs/faz-21-3-evidence/2026-04-28-d35-2-first-canli-eventual-consistency.md`
- mfe-access PR: `platform-web#34` sha-`57dc28e8` (5 tab + assign UI + 4-locale i18n + 28 tests)
- Prereq runbooks:
  - `docs/RB-faz-21-3-d35-3-prereq-tuple-seed.md`
  - `docs/RB-faz-21-3-d35-3-keycloak-admin-jwt.md`
  - `docs/RB-faz-21-3-d35-3-ui-persona-checklist.md`
- Codex thread: `019dd409` (D35-3 prereq strategy AGREE-with-revisions)
