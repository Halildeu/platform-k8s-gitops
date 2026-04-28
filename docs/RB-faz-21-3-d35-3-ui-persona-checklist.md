# RB Faz 21.3 D35-3 — mfe-access UI Persona Flow Checklist

> **Tetikleyici**: D35-3 evidence run (D35-2-full PASS sonrası).
> **Authority**: kullanıcı/operatör browser oturumu açar; agent skeleton + correlation queries hazırlar.
> **Codex**: `019dd409` "agent skeleton + screenshot placeholder hazırlayabilir; gerçek kullanıcı/persona bilgisi, browser oturumu ve screenshot/video capture operatörle veya credential-safe browser akışıyla yapılmalı."

## Kapsam

mfe-access "Veri Erişimi" panel (PR `platform-web#34` sha-`57dc28e8`) üzerinden **gerçek persona** ile end-to-end UI flow. 5 sekme + ScopeAssignModal + 4-locale i18n + nested Routes + 28 tests landed; bu checklist o UI'yi ayrı admin + granted persona'larıyla yürütür.

## Browser hazırlık

- [ ] Chrome veya Firefox, **DevTools Network tab açık** (XHR/Fetch filter)
- [ ] DevTools Console tab açık (UI error log için)
- [ ] Browser cache fresh (incognito veya hard refresh) — mfe-access mikro frontend bundle eski sürümü cache'lemiş olabilir
- [ ] **Screenshot tool** hazır (macOS: ⌘⇧4; Linux: gnome-screenshot; ya da OBS gibi video kayıt)
- [ ] **Çoklu persona için 2 browser session**: 1 normal + 1 incognito (Step 4'te aynı tarayıcıda hem admin hem granted'i koşmak için)

## Persona setup (Keycloak runbook tamamlandıktan sonra)

> `docs/RB-faz-21-3-d35-3-keycloak-admin-jwt.md` Step 2-3 sonrası.

- [ ] **Admin persona** (`d35-admin-persona`): Keycloak'ta create edildi
- [ ] Admin için `module:ACCESS#can_manage` + `can_view` tuple seedlendi (`docs/RB-faz-21-3-d35-3-prereq-tuple-seed.md` Step 2)
- [ ] **Granted persona** (`d35-granted-persona`): Keycloak'ta create edildi
- [ ] Granted için `module:ACCESS#can_view` tuple seedlendi (opsiyonel, sadece UI'dan kendi listesini görmesi gerekiyorsa)

## D35-3 evidence template doldurma sırası

Her UI step'inde:
1. UI'da işlemi yap
2. Browser DevTools network tab'da ilgili API call'u tespit et
3. Screenshot al + isimlendir (`<step>-<short-desc>.png`)
4. Backend correlation query'sini operatör shell'inde koş
5. D35-3 evidence template'inin ilgili alanına kayıtları ekle

> Template: `docs/faz-21-3-evidence/d35-3-product-path-template.md`

## Step 1 — Login (admin persona)

- [ ] Browser: `https://testai.acik.com` aç
- [ ] Keycloak SSO ekranı: `d35-admin-persona` username + password ile giriş
- [ ] Login sonrası dashboard render (≤3s)
- [ ] DevTools Application tab → Cookies → Keycloak realm cookie var

**Screenshot**: `01-admin-login-dashboard.png`
**Network**: Keycloak token endpoint 200 (`/realms/<realm>/protocol/openid-connect/token`)

**Failure modes**:
- 401: password yanlış
- Realm SSO redirect döngüsü: client config check (Keycloak admin runbook Step 1)

## Step 2 — Navigate to "Veri Erişimi"

- [ ] Sidebar/top-nav: "Erişim Yönetimi" / "Access Management" gir
- [ ] mfe-access bundle yüklenir (Network'da `mfe-access*.js` 200)
- [ ] 5 sekme görünür (PR-E `feat: faz-21-3-pr-e`): Veri Erişimi sekmesine tıkla
- [ ] data-access ekranı render

**Screenshot**: `02-veri-erisimi-tab.png`
**Console**: error 0
**Network**:
- `mfe-access-*.js` 200 (bundle hash kaydet — D35-3 evidence "frontend image / build" alanına)
- `GET /api/v1/access/scope?orgId=1` 200

## Step 3 — Yeni grant: ScopeAssignModal

- [ ] "Yeni Erişim Ata" butonuna tıkla → modal açılır
- [ ] Form alanları:
  - **User**: dropdown'dan `d35-granted-persona` seç
  - **Organization**: dropdown'dan veya sabit `AÇIK` (UI policy'ye göre)
  - **Scope kind**: "Şirket" (Company) seç
  - **Scope ref**: dropdown'dan `Mikrolink Bilişim` (UI bunu OUR_COMPANY.COMP_ID=1 → `["1"]` JSON'una çevirmeli)
- [ ] "Kaydet" / "Onayla" butonu

**Screenshot**: `03a-modal-form-filled.png`

> Submit edildiğinde ne olmalı:

- [ ] Loading state (spinner)
- [ ] **Success toast** veya inline mesaj
- [ ] Listeye yeni satır eklenir
- [ ] (Opsiyonel) tupleSyncStatus kolonu PENDING → PROCESSED transition (UI poll/refresh)

**Screenshot**: `03b-grant-success-toast.png`, `03c-new-row-listed.png`

**Network**:
- `POST /api/v1/access/scope` 201 — response body:
  - `scopeId` numeric
  - `scopeKind` "COMPANY"
  - `openFgaObjectType` "company"
  - `openFgaObjectId` **"wc-our-company-1"** (V25 namespace; eğer `wc-company-` görürsen V25 alignment regresyonu)
  - `tupleSyncStatus` "PENDING"
  - `outboxId` numeric

**Backend correlation** (operatör shell):
```bash
SCOPE_ID="<UI'dan response.scopeId>"
ssh halil@staging-sw "docker exec platform-pg-test psql -U platform -d reports_db -c \
  \"SELECT id, user_id, org_id, scope_kind, scope_source_table, scope_ref, granted_by \
    FROM data_access.scope WHERE id = ${SCOPE_ID};\""
# Beklenen: scope_source_table='OUR_COMPANY' + scope_ref='[\"1\"]'

ssh halil@staging-sw "docker exec platform-pg-test psql -U platform -d reports_db -c \
  \"SELECT status, tuple_object, processed_at FROM data_access.scope_outbox WHERE scope_id = ${SCOPE_ID};\""
# Beklenen: status='PROCESSED' (poll'dan sonra), tuple_object='company:wc-our-company-1'
```

**Gate**: DB row + outbox PROCESSED + tuple V25 namespace.

## Step 4 — Granted persona perspektifi (opsiyonel)

> Sadece `module:ACCESS#can_view` granted için seedlenmişse. Aksi halde `403 GET /api/v1/access/scope` döner ve UI hata gösterir; bu davranış da loglanabilir negatif test olarak.

- [ ] Yeni incognito session aç → `d35-granted-persona` ile giriş
- [ ] mfe-access "Veri Erişimi" tabına gir
- [ ] **Kendi sahip olduğu scope'u görür**: 1 satır, "Şirket / Mikrolink Bilişim"
- [ ] (Opsiyonel) farklı persona'nın scope'unu **görmez** (cross-user list isolation)

**Screenshot**: `04-granted-persona-self-list.png`

**Network**:
- `GET /api/v1/access/scope?userId=<granted_uid>&orgId=1` 200 — array length 1

## Step 5 — Revoke action

- [ ] Admin sessiona dön (incognito kapat veya logout/login)
- [ ] Step 3'te oluşan satırı bul → "İptal Et" / "Revoke" butonuna tıkla
- [ ] Confirmation dialog → "Onayla"
- [ ] Listeden satır kaldırılır VEYA "İptal Edildi" badge'i ile gri görünür (UI policy)
- [ ] Success toast

**Screenshot**: `05a-revoke-confirm.png`, `05b-revoke-success.png`

**Network**:
- `DELETE /api/v1/access/scope/${SCOPE_ID}` 204

**Backend correlation**:
```bash
ssh halil@staging-sw "docker exec platform-pg-test psql -U platform -d reports_db -c \
  \"SELECT id, action, status, tuple_object, processed_at \
    FROM data_access.scope_outbox WHERE scope_id = ${SCOPE_ID} ORDER BY id;\""
# Beklenen: 2 row — GRANT (PROCESSED), REVOKE (PROCESSED), her ikisi tuple_object='company:wc-our-company-1'
```

## Step 6 — /check FLIP

> Backend scripti olarak koş; UI bu kapıyı görmüyor.

```bash
GRANTED_UID=$(vault kv get -field=granted_persona_uid kv/platform/d35-3)
STORE_ID=$(vault kv get -field=store_id kv/platform/openfga)
MODEL_ID=$(vault kv get -field=model_id kv/platform/openfga)

ssh halil@staging-sw "curl -sf -X POST http://10.44.3.209:8080/stores/${STORE_ID}/check \
  -H 'Content-Type: application/json' \
  -d '{
    \"authorization_model_id\":\"${MODEL_ID}\",
    \"tuple_key\":{\"user\":\"user:${GRANTED_UID}\",\"relation\":\"viewer\",\"object\":\"company:wc-our-company-1\"}
  }'"
# Beklenen: {"allowed":false} — revoke öncesi true idi, FLIP confirmed
```

## Step 7 — Backend log correlation

```bash
ssh halil@staging-sw "POD=\$(kubectl --context k3d-test -n platform-test \
  get pod -l app.kubernetes.io/name=permission-service \
  -o jsonpath='{.items[0].metadata.name}') && \
  kubectl --context k3d-test -n platform-test logs \$POD --since=10m | \
  grep -E 'data_access scope (granted|revoked)|outbox.*PROCESSED'"
# Beklenen: GRANT log + REVOKE log + 2x outbox PROCESSED
```

D35-3 evidence template Step 7 alanına bu çıktıyı kaydet.

## Negative test plan (opsiyonel — D35-3 PASS sonrası)

UI flow PASS oldukça, regresyon kanıtı için negative tester adımları:

- [ ] **Geçersiz scope_ref**: UI'da kullanıcı `["999"]` (var olmayan COMP_ID) gönderse 422 dönmeli. UI hata mesajı render etmeli ("Scope reference rejected by data_access lineage guard")
- [ ] **Çift grant**: aynı user + org + scope_kind + scope_ref ile 2. POST 409 dönmeli ("Active scope already exists for ...")
- [ ] **JWT olmadan**: UI'dan logout sonra POST → 401 (Spring Security gate)
- [ ] **`module:ACCESS#can_manage` olmayan persona**: prereq tuple seed yapılmamış başka kullanıcı POST → 403 (`@RequireModule` enforce)

Bunlar ayrı evidence section'ında raporlanabilir; D35-3 minimum'unu kapatmak için zorunlu değil.

## Cleanup

D35-3 PASS sonrası test persona'ları silinebilir (Keycloak admin runbook Cleanup section). Tuple seed'ler bırakılabilir (test ortamı stabil tutmak için) veya silinebilir (`docs/RB-faz-21-3-d35-3-prereq-tuple-seed.md` Cleanup).

## References

- D35-3 evidence template: `docs/faz-21-3-evidence/d35-3-product-path-template.md`
- D35-2-full evidence template: `docs/faz-21-3-evidence/d35-2-full-template.md` (prereq)
- mfe-access PR: `platform-web#34` sha-`57dc28e8`
- ScopeAssignModal component: `platform-web/apps/mfe-access/src/features/data-access/ui/ScopeAssignModal.tsx`
- buildScopeRef helper: `platform-web/apps/mfe-access/src/features/data-access/lib/scopeRefBuilder.ts` (`["1"]` üretmeli)
- Codex thread `019dd409` skeleton + boundary direktifi
