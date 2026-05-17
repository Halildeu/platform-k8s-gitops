# Runbook — OpenFGA `report_group` Migration + report-service Authz Contract Fix

> Tetik: `d35-granted` (REPORT_VIEWER) gibi non-superadmin personalar `/api/v1/reports`'tan **0 rapor** alıyor; "Raporlar" nav görünür ama liste boş.
>
> Kaynak teşhis: Codex thread `019e34df` (6-tur consensus) + canlı testai OpenFGA sorguları.
>
> Statü: **PLAN — operatör + agent koordineli yürütülecek.** Canlı OpenFGA model değişimi içerdiği için adım adım uygulanır.

---

## 1. Bağlam ve kök neden

### 1.1 Belirti

`d35-granted` (userId 1205, roller REPORT_VIEWER + USER_VIEWER, superAdmin=false) impersonation ile:

- permission-service `/api/v1/authz/me` → `modules.REPORT: VIEW`, `permissions` içinde `REPORT_VIEW`, `reports` map 16 grup ALLOW, "Raporlar" nav görünür. ✓ (platform-backend PR #236 ile düzeldi)
- report-service `/api/v1/reports` → `200 []` (0 rapor). ✗

### 1.2 Kök neden — iki katman

**A. report-service authz sözleşme çelişkisi (kod bug'ı).**

report-service permission-service `/authz/me`'yi tüketmiyor; kendi `OpenFgaAuthzMeBuilder` sınıfı authz görünümünü doğrudan OpenFGA'dan kuruyor:

- `OpenFgaAuthzMeBuilder` → `listObjects(userId, "can_view", "report")` → `AuthzMeResponse.reports` map'ini **bireysel `report` obje id'leriyle** doldurur (HR_ANALYTICS, HR_DEMOGRAFIK, FIN_ANALYTICS …).
- `ReportAccessEvaluator.evaluate` gate-3 → `canViewReport(def.access().reportGroup())` → `reports.get(reportGroup)`. `reportGroup` = report tanım JSON'larındaki `access.reportGroup` (`HR_REPORTS`, `FINANCE_REPORTS`, `SALES_REPORTS`, `ANALYTICS_REPORTS`).
- `reports` map'i bireysel rapor id'leriyle dolu, **report-GRUP anahtarı içermiyor** → `canViewReport("HR_REPORTS")` her zaman `false` → `DENIED_REPORT_GROUP` → 31 raporun tamamı deny.
- Admin görür çünkü `evaluate` başında `isSuperAdmin()` short-circuit var; gate-3 non-superadmin'de hiç çalışmamış (latent bug).

`ReportAccessEvaluator` gate-3 yorumu ("Report group deny-default via authz.reports map") `reports` map'inin report-GRUP anahtarlarıyla dolması gerektiğini söylüyor — `OpenFgaAuthzMeBuilder` ise bireysel rapor id'leriyle dolduruyor. Açık sözleşme çelişkisi.

**B. OpenFGA modeli `report_group` tipini içermiyor.**

report-GRUP authz'sinin OpenFGA'da yaşaması için `report_group` tipi gerekir. Repo canonical `backend/openfga/model.fga` bu tipi içeriyor (R16 PR-B) ama testai store'una yüklü model versiyonu eski — `report_group` tipi yok.

### 1.3 Kanıt (canlı testai, 2026-05-17)

Store/model: servisler (permission-service + report-service `env`) → `ERP_OPENFGA_STORE_ID=01KPP0CFP4G82K42Y6NYSPT4JF`, `ERP_OPENFGA_MODEL_ID=01KPP0CFRWFDNRNZFNE72299EY`.

`port-forward svc/openfga 8080` + API:

```
list-objects {type:report,        relation:can_view, user:user:1205}
  → 12 obje: report:HR_ANALYTICS, HR_DEMOGRAFIK, FIN_ANALYTICS, HR_COMPENSATION,
    FIN_RATIOS, FIN_RECONCILIATION, HR_BENEFITS_LITE, HR_EXECUTIVE_SUMMARY,
    HR_PAYROLL_TRENDS, HR_SALARY_ANALYTICS, HR_FINANSAL, HR_EQUITY_RISK
list-objects {type:module,        relation:can_view, user:user:1205}
  → module:ACCESS, module:REPORT, module:USER_MANAGEMENT
list-objects {type:report_group,  relation:can_view, user:user:1205}
  → ERROR: type 'report_group' not found
```

→ Tuple'lar mevcut; sorun tuple eksikliği DEĞİL. Sorun (A) sözleşme çelişkisi + (B) eksik model tipi.

### 1.4 Model drift uyarısı (ayrı governance borcu)

testai canlı model ile repo `backend/openfga/model.fga` **`branch / company / organization / project / warehouse` tiplerinde ayrışıyor** — canlı model bu scope tiplerinde daha gelişmiş ilişkilere (admin/manager/member/viewer union + tupleToUserset inheritance) sahip; repo `model.fga` daha sade. Yani repo `model.fga`'yı **olduğu gibi POST etmek scope authz'sini geriletir**.

⚠️ **Bu yüzden migration, repo model.fga'yı değil, "canlı model + sadece `report_group` tipi" birleşimini kullanır (Faz 1 §3.1).**

Ayrı iş kalemi: repo `backend/openfga/model.fga`'nın canlı modelle yeniden hizalanması (CI `openfga-dsl-check` lane'i prod ile uyuşmayan bir dosyayı doğruluyor). Bu runbook kapsamı dışı.

---

## 2. Etki alanı ve ön koşullar

| Bileşen | Etki |
|---|---|
| OpenFGA store `01KPP0CFP4…` | Yeni authorization-model versiyonu (append-only — eski model bozulmaz) |
| Vault `kv/platform/<service>` | `ERP_OPENFGA_MODEL_ID` 5 serviste güncellenir |
| permission-service, report-service, core-data-service, variant-service, user-service | ESO refresh + rolling restart |
| report-service imajı | Kod fix (Faz 4) → yeni imaj build + digest pin |

Ön koşul: `ssh halil@staging-sw` + `kubectl --context k3d-test` erişimi; Vault token; agent'ın platform-backend + platform-k8s-gitops repo erişimi.

---

## 3. Faz 1 — OpenFGA model migration (`report_group` tipi ekle)

**Süre:** ~5 dk. **Blast radius:** sıfır (append-only; servisler model ID değişene kadar etkilenmez).

### 3.1 Birleşik model üret

Canlı modeli çek, sadece `report_group` tipini ekle (repo model.fga'yı KULLANMA — §1.4):

```bash
ssh halil@staging-sw 'kubectl --context k3d-test -n platform-test port-forward svc/openfga 18080:8080 >/tmp/pf.log 2>&1 &
  sleep 4
  curl -s "http://localhost:18080/stores/01KPP0CFP4G82K42Y6NYSPT4JF/authorization-models/01KPP0CFRWFDNRNZFNE72299EY" > /tmp/live-model.json
  kill %1'
scp halil@staging-sw:/tmp/live-model.json /tmp/live-model.json

# report_group tip tanımını canonical model.fga'dan render et
cd <platform-backend>/backend/openfga
grep -vE '^\s*#' model.fga | grep -v '^\s*$' > /tmp/model-stripped.fga
python3 render_model_json.py /tmp/model-stripped.fga > /tmp/canonical-model.json

# Birleştir: canlı 9 tip + report_group
python3 - <<'PY'
import json
live = json.load(open('/tmp/live-model.json'))['authorization_model']
canon = json.load(open('/tmp/canonical-model.json'))
rg = [t for t in canon['type_definitions'] if t['type'] == 'report_group'][0]
merged = {'schema_version': live['schema_version'],
          'type_definitions': live['type_definitions'] + [rg]}
if 'conditions' in live:
    merged['conditions'] = live['conditions']
json.dump(merged, open('/tmp/merged-model.json', 'w'))
print('types:', [t['type'] for t in merged['type_definitions']])
PY
```

Beklenen: `types: [user, organization, company, project, warehouse, branch, module, action, report, report_group]`.

### 3.2 Yeni authorization-model POST et

```bash
scp /tmp/merged-model.json halil@staging-sw:/tmp/merged-model.json
ssh halil@staging-sw 'kubectl --context k3d-test -n platform-test port-forward svc/openfga 18080:8080 >/tmp/pf.log 2>&1 &
  sleep 4
  curl -s -X POST "http://localhost:18080/stores/01KPP0CFP4G82K42Y6NYSPT4JF/authorization-models" \
    -H "Content-Type: application/json" -d @/tmp/merged-model.json
  kill %1'
```

Beklenen: `{"authorization_model_id":"01K…"}` — **NEW_MODEL_ID** olarak not al.

**Fail sinyali:** `validation_error` → merged JSON bozuk; §3.1 tekrar. **Devam eşiği:** geçerli `authorization_model_id` döndü.

### 3.3 Doğrula

```bash
# NEW_MODEL_ID ile report_group tipi sorgulanabilir olmalı
curl -s -X POST ".../stores/01KPP0CFP4…/list-objects" -d \
  '{"authorization_model_id":"<NEW_MODEL_ID>","type":"report_group","relation":"can_view","user":"user:1205"}'
```

Beklenen: `type_not_found` HATASI YOK (objeler boş olabilir — Faz 3 dolduracak).

---

## 4. Faz 2 — Vault model ID güncelleme + servis restart

**Süre:** ~10 dk. **Blast radius:** 5 servis rolling restart.

### 4.1 Vault `ERP_OPENFGA_MODEL_ID` güncelle

5 servis için `kv/platform/<service>` path'inde `ERP_OPENFGA_MODEL_ID` = `<NEW_MODEL_ID>`:

```bash
for svc in permission-service report-service core-data-service variant-service user-service; do
  vault kv patch kv/platform/$svc ERP_OPENFGA_MODEL_ID=<NEW_MODEL_ID>
done
```

(Tam path'ler ExternalSecret `remoteRef.key`'lerinde — `kustomize/base/apps/<svc>/ops/externalsecret.yaml`.)

### 4.2 ESO refresh + rolling restart

```bash
for svc in permission-service report-service core-data-service variant-service user-service; do
  kubectl --context k3d-test -n platform-test annotate externalsecret $svc \
    force-sync=$(date +%s) --overwrite
done
# secret render'ı bekle, sonra restart
for svc in permission-service report-service core-data-service variant-service user-service; do
  kubectl --context k3d-test -n platform-test rollout restart deploy/$svc
  kubectl --context k3d-test -n platform-test rollout status deploy/$svc --timeout=180s
done
```

### 4.3 Doğrula

```bash
kubectl --context k3d-test -n platform-test exec deploy/report-service -- \
  sh -c 'env | grep ERP_OPENFGA_MODEL_ID'
```

Beklenen: `ERP_OPENFGA_MODEL_ID=<NEW_MODEL_ID>`. Aynı kontrol permission-service için.

**Fail sinyali:** pod CrashLoop / authz 500 → §8 rollback. **Devam eşiği:** 5 servis Running + yeni model ID env'de.

---

## 5. Faz 3 — `report_group` tuple backfill

**Süre:** ~5 dk.

`report_group:<K>#can_view@user:<id>` tuple'ları permission-service `TupleSyncService` tarafından `reports.<GROUP>` granule'larından yazılır (REPORT_VIEWER / REPORT_MANAGER / FINANCE_* rolleri seed eder — `PermissionDataInitializer.DEFAULT_REPORT_GROUP_KEYS`). Model `report_group` tipini içermediği için bu yazımlar daha önce başarısız oluyordu; artık model hazır.

### 5.1 Backfill tetikle

permission-service `TupleSyncService` re-sync mekanizması:

- **Yöntem A (tercih):** permission-service'te rol-atama re-sync endpoint'i / boot-time reconcile varsa onu tetikle. (Kod: `TupleSyncService` + `RoleChangeEvent`; backfill endpoint mevcudiyetini doğrula.)
- **Yöntem B:** etkilenen kullanıcılar için rolü revoke+re-grant ederek `RoleChangeEvent` tetikle (test cluster güvenli).

### 5.2 Doğrula

```bash
curl -s -X POST ".../stores/01KPP0CFP4…/list-objects" -d \
  '{"authorization_model_id":"<NEW_MODEL_ID>","type":"report_group","relation":"can_view","user":"user:1205"}'
```

Beklenen: `{"objects":["report_group:HR_REPORTS","report_group:FINANCE_REPORTS","report_group:SALES_REPORTS","report_group:ANALYTICS_REPORTS"]}` (REPORT_VIEWER 4 grup seed eder).

**Devam eşiği:** d35-granted için ≥1 `report_group` objesi döndü.

---

## 6. Faz 4 — report-service kod fix (sözleşme hizalama)

**Statü: TASARIM — ayrı PR, cross-AI (Codex) review, CI yeşil, admin merge yok.**

### 6.1 Gate-3 fix — `OpenFgaAuthzMeBuilder` report-GRUP anahtarları

`report-service/.../authz/OpenFgaAuthzMeBuilder.java` — mevcut "(5) Report-level" bloğundan sonra ek blok:

```java
// (5b) Report-GROUP level — ReportAccessEvaluator gate-3 reportGroup
//      ("HR_REPORTS" …) anahtarını `reports` map'inde arar. listObjects
//      report_group ile bu anahtarları doldur.
for (String groupId : safeListObjects(userId, "can_view", "report_group")) {
    reportsMap.put(groupId, "ALLOW");
}
```

Sonuç: `reports` map'i hem bireysel rapor id'leri hem report-GRUP anahtarları içerir → gate-3 `canViewReport("HR_REPORTS")` doğru çalışır. `safeListObjects` graceful — model `report_group` içermese de boş döner (Faz 1 öncesi deploy güvenli).

### 6.2 Gate-2 namespace fix (ayrı bug)

31 rapor tanımının 16'sı `access.permission = "reports.<slug>.view"` istiyor (örn. `reports.hr-compensation-detay.view`). `OpenFgaAuthzMeBuilder` ise `reports.<dashboardKey-slug>.view` üretiyor (OpenFGA `report` obje id'sinden — `HR_COMPENSATION → hr-compensation`). Slug namespace uyumsuz.

Karar gerektirir (Codex 019e34df §4): ya rapor tanım slug'ları OpenFGA `report` object id namespace'ine hizalanır, ya `OpenFgaAuthzMeBuilder` açık bir catalog mapping kullanır. **Bu bir ürün/authz-model kararıdır — tahminle çözülmez; report-service registry sahibiyle netleştir.**

15 rapor `access.permission = "REPORT_VIEW"` kullandığından, §6.1 fix'i + Faz 3 backfill sonrası bu 15 rapor görünür hale gelir — gate-2 fix'i olmadan da report-group authz'si kanıtlanabilir. 16 granular rapor per-report grant ile kanıtlanır (§7.2).

### 6.3 Deploy

PR merge → image build → `kustomize/overlays/test` digest pin (gitops PR) → `kubectl set image` → tarayıcı console verify.

---

## 7. Faz 5 — Browser acceptance (kullanıcı asıl isteği)

Non-superadmin persona ile (admin KULLANMA — superAdmin scope bypass eder).

### 7.1 Per-report + report-group authz

1. Admin olarak `d35-granted`'ı impersonate et (sebep ≥10 karakter).
2. "Raporlar" → liste artık `> 0` rapor göstermeli (REPORT_VIEW + grup ALLOW olan 15 rapor).
3. Kanıt: ekran görüntüsü + `/api/v1/reports` network response (`count > 0`) + console temiz.

### 7.2 Per-report explicit grant

1. Admin olarak `d35-granted`'a tek bir granular rapor için per-report yetki ver ("Erişim & Roller" UI veya `report:<id>#can_view` granule).
2. Impersonate → o rapor görünür, diğer granular raporlar görünmez → per-report authz kanıtlanır.

### 7.3 Company-scope

1. `d35-granted` scope = COMPANY [38,39]. Bir raporu aç → veri yalnız şirket 38/39 satırlarını göstermeli.
2. Kanıt: rapor grid'i + network response payload.

### 7.4 Project-scope

`d35-granted`'ın PROJECT scope'u yok. Project-scope kanıtı için PROJECT scope'lu bir persona gerekir — operatör "Erişim & Roller"den project-scope'lu persona kurar, aynı akış.

---

## 8. Rollback

| Faz | Rollback |
|---|---|
| Faz 1 | Yok gerekmez — yeni model append-only, kullanılmıyor. |
| Faz 2 | Vault `ERP_OPENFGA_MODEL_ID` = eski `01KPP0CFRWFDNRNZFNE72299EY` → ESO refresh → 5 servis restart. |
| Faz 3 | Tuple backfill additive; gerekirse `report_group` tuple'ları silinir. |
| Faz 4 | report-service digest pin'i önceki sha'ya geri al → `kubectl set image`. |

Eski model ID hep geçerli kalır (OpenFGA append-only) → Faz 2 rollback anında authz'yi eski davranışa döndürür.

---

## 9. Referanslar

- Codex thread `019e34df` — 6-tur consensus (root cause + fix planı).
- platform-backend PR #236 — permission-service `/authz/me` REPORT projection invariant (MERGED, deployed; bu runbook'un ön-fazı).
- `report-service/.../authz/OpenFgaAuthzMeBuilder.java` — `reports` map kurucu.
- `report-service/.../access/ReportAccessEvaluator.java` — gate-1/2/3.
- `permission-service/.../service/TupleSyncService.java` — `REPORT_GROUP_KEYS` + tuple write.
- `backend/openfga/model.fga` + `render_model_json.py` + `init.sh` — model kaynağı.
- HARD RULE — TEST cluster scale-to-zero yasak; her servis replicas≥1.
