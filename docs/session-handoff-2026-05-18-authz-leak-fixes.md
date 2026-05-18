# Session Handoff — 2026-05-18 — Authz Leak Fixes (Sidebar + Shell Header İK)

> Format: D28 5-alan + sıradaki agent P0 aksiyon listesi
> Önceki session worktree silindiği için bu doküman yeniden oluşturuldu (commit kaybı recovery).

## 1. Bağlam (neden bu handoff)

Kullanıcı, yetkisi olmayan kullanıcıların gated feature'ları gördüğü/erişebildiği iki authorization leak bildirdi:

1. **Sidebar Schema Explorer leak** — THEME modül yetkisi olmayan kullanıcı sidebar'da "Şema Gezgini" görüyor, tıklayınca `/unauthorized`.
2. **Shell header İK (HR) leak** — header İK mega-menüsündeki Öneriler/Etik öğeleri yetkiye bağlı değildi; modül yetkisi olmayan kullanıcı görüyor + tıklayınca `/unauthorized`.

Ayrıca sıradaki agent için 3 backlog (P0 project-scope E2E, P1 permission-service @WebMvcTest slice fix, P2 model.fga drift) ve M365 SSO broker setup işlendi.

## 2. İddia (bu session'da ne yapıldı — MERGED PR'lar)

| PR | Repo | Başlık | Durum |
|---|---|---|---|
| #240 | platform-backend | test(permission-service): @WebMvcTest slice context-load fix (ImpersonationContextExtractor bean) | MERGED |
| #242 | platform-backend | feat(permission-service): add SUGGESTIONS + ETHIC permission modules | MERGED (merge commit `74916a8c`) |
| #585 | platform-web | fix(mfe-shell): gate Schema Explorer sidebar item by THEME module | MERGED |
| #587 | platform-web | feat(mfe-shell): gate Suggestions + Ethic by SUGGESTIONS/ETHIC modules | MERGED (merge commit `cffdfc8d`) |

**Backend (#240)**: 6 `@WebMvcTest` slice sınıfına `@MockitoBean ImpersonationContextExtractor` eklendi — `ImpersonationContextFilter` (@Component) slice context'te auto-pick ediliyordu, bean yokluğu 28 testi düşürüyordu. 38 test run, 0 fail.

**Backend (#242)**: `PermissionCatalogService.MODULES` listesine `SUGGESTIONS` ("Öneri ve Fikir") + `ETHIC` ("Etik Raporlama") modülleri eklendi. `PermissionDataInitializer.buildAdminGranules()` bu iki modülün MANAGE granule'ünü admin role'e seed ediyor.

**Frontend (#585)**: `Sidebar.tsx` — `buildSidebarNavItems(sa, hasModule)` pure fonksiyonu extract edildi; `schema-explorer` öğesi `disabled: !canThemeAdmin` + yetki yoksa `href: undefined`. `header-search.config.ts` `tool-schema` öğesine `permission: THEME` + `isSearchableItemVisible()` pure predicate (super-admin bypass explicit). `useGlobalSearch.ts` bu predicate'i kullanıyor.

**Frontend (#587)**: `MODULE_KEYS` += `SUGGESTIONS`, `ETHIC`. `header-navigation.config.ts` İK grubu `suggestions`/`ethic` öğelerine `module:` eklendi → `any-child` gate sayesinde modülü olmayan kullanıcıda İK grubu tamamen düşüyor. `header-search.config.ts` `nav-suggestions`/`nav-ethic` öğelerine `permission:` eklendi. `AppRouter.tsx` `/suggestions` + `/ethic` route'ları `<ProtectedRoute requiredModule=...>` ile sarıldı.

**M365 SSO**: `setup-m365-broker.sh` `platform-test` realm'inde çalıştırıldı (3 script bug fix: kcadm flow path %20 encode, `docker cp` öncesi `chmod 0644`, Step 3 stderr unsuppress) — apply 5/5 PASS. Prod Vault'a `kv/platform/keycloak-m365-broker` client_secret yazıldı.

## 3. İspatlar

- 4 PR `gh pr view` ile MERGED doğrulandı.
- Backend #242 image build `CI - Image Build + GHCR Push` → `success`, headSha `74916a8c`.
- Frontend #587 build → `success`, headSha `cffdfc8d`.
- #240 test run: 38 test, 0 fail / 0 error (`-Djacoco.skip=true`, local JDK 25 ↔ JaCoCo 0.8.12 uyumsuzluğu nedeniyle).
- M365 broker apply: 5/5 step PASS, browser smoke `prompt=select_account` doğrulandı.

## 4. İspatlamaz (henüz CANLI DEĞİL)

- **#242 / #585 / #587 testai cluster'a deploy EDİLMEDİ.** Fix'ler `main`'de ama testai pod'larında eski image çalışıyor. Authz leak browser'da hâlâ açık.
- P0 project-scope live grant → OpenFGA → RLS E2E: trigger blocker çözüldü (fixture seed + V21 join doğrulandı) ama canlı grant superadmin JWT'ye bağlı, tamamlanmadı.
- M365 prod realm (`serban`) apply yapılmadı (sadece `platform-test`).

## 5. Bilinen Boşluk + Sıradaki Agent P0 Aksiyon Listesi

### P0 — testai deploy (HARD RULE: browser-verify olmadan iş bitmedi)

`kustomize/overlays/test/kustomization.yaml`:
- **permission-service** image bloğu (satır ~638-826, digest satır **826**): #242 build'ine bump. Image tag `sha-74916a8`; digest GHCR'dan resolve et:
  `gh api /orgs/halildeu/packages/container/platform-backend-permission-service/versions --jq '.[] | select(.metadata.container.tags[]? == "sha-74916a8") | .name'`
- **platform-web-frontend-testai** image bloğu (digest satır **2142**, şu an `sha-6ea6185`): #587 build'ine bump. Image tag `sha-cffdfc8`; digest GHCR'dan resolve et benzer şekilde.

Sıra: **backend önce** (permission-service rollout) → sonra frontend. Selective apply tercih (blast radius). `kubectl --context k3d-test -n platform-test apply -k ...` + `rollout status`.

**Deploy sonrası ZORUNLU (HARD RULE)**: browser console + network sweep — modül yetkisi OLMAYAN kullanıcıda:
- Sidebar'da "Şema Gezgini" görünmemeli / tıklanamaz olmalı
- Header İK grubu görünmemeli (Öneriler/Etik)
- Cmd/Ctrl+K global search'te bu öğeler çıkmamalı
- ADMIN kullanıcı erişimi KORUNMALI (regression check)

### P1 / P2

- M365 `setup-m365-broker.sh` 3-fix'i canonical PR olarak `platform-k8s-gitops`'a (server clone'da uncommitted). NOT: origin/main'de #787 + #793 setup-m365-broker.sh'a başka fix'ler getirmiş — merge conflict kontrolü gerek.
- M365 prod realm (`serban`) apply.
- P0 project-scope E2E: superadmin JWT ile live grant → OpenFGA tuple → RLS doğrulama.
- ShellHeader.tsx + AppLauncher.tsx dead-code temizliği; notify inbox/me 401 gateway fix.
