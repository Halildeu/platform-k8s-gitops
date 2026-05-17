# Session Handoff — 2026-05-17 — V3-B1a-dedup (`@mfe/design-system` hostOnly)

> **Belge kodu**: `session-handoff-2026-05-17-v3-b1a-dedup`
> **Tarih**: 2026-05-17
> **Sahip**: Halil
> **Format**: D28 5-alan handoff
> **Önceki handoff**: `session-handoff-2026-05-17-v3-b1a-bundle-taxonomy.md` (PR #729 — V3-B1a)

---

## 1. Bağlam — Bu Session Ne Yaptı

Önceki handoff (#729) **B1a-dedup**'ı sıradaki P0 olarak bırakmıştı (handoff'un
çerçevesi: "chart-lib 7× dedup, ~55 MB tasarruf"). Bu session kullanıcı
"devam edelim / devam" zinciriyle B1a-dedup yürütüldü — ama **gerçek-tarayıcı
verification problemi YENİDEN ÇERÇEVELEDİ** (V3-B2 dersi tekrar: headline figür
browser'da reprodüksiyon vermedi).

---

## 2. İddia — 1 platform-web PR MERGED + bu handoff PR

| # | Repo | PR | Merge SHA | Konu |
|:-:|---|:-:|---|---|
| 1 | platform-web | #570 | `fcb919dd` | `@mfe/design-system` hostOnly — 5× loadShare dup fix |
| 2 | platform-k8s-gitops | (bu PR) | — | B1a-dedup handoff + PERF-DEBT-V3 backlog STATUS |

---

## 3. İspatlar — LIVE Evidence

### Reframing — browser verification (testai shell, `claude-in-chrome` MCP)

`testai.acik.com/access/roles` (real shell, `mfe-access` = non-chart MFE route)
fresh reload, temiz resource buffer:

- **Chart "dedup" → DE-SCOPED**: chart filtresine tek eşleşen `echarts-imports`
  shim (**0 KB decoded**); `ag-charts`/`echarts` heavy chunk + `chunk-V72SK3YL`
  **inmedi**. Chart stack lazy code-split → non-chart route indirmiyor.
  Handoff'un "~64.6 MB chart dedup" başlığı user-facing initial-load problemi
  DEĞİL (build-artifact gerçeği kalır; düşük öncelik hygiene).
- **GERÇEK bulgu**: `/access/roles` tek route'ta **5 ayrı `@mfe/design-system`
  loadShare chunk** iniyor (shell + 4 admin remote) — her biri ~1.75 MB
  transfer / ~6.45 MB decoded. Route JS toplamı 9.7 MB transfer; bunun
  **~8.8 MB'ı (~%91)** design-system, 5× kopya. MF singleton dedupe ETMİYORDU
  — 6 remote DS'i `singleton()` (not `hostOnly()`) deklare etmişti
  (`mf-shared-scope-audit.md` "remote-bundles-canonical" drift'i).

### PR #570 — `@mfe/design-system` hostOnly (`fcb919dd`)

- 6 remote vite config (`suggestions/ethic/access/audit/users/reporting`):
  `@mfe/design-system` → `hostOnly('@mfe/design-system')` (`import: false` —
  host share-scope'tan tüket). Shell (canonical provider) dokunulmadı.
- Build kanıtı: 6/6 remote temiz build; `loadShare__design-system` chunk
  6 remote dist'inin **hepsinden kalktı** (önce ~6.4 MB decoded each);
  `mfe-suggestions` dist/assets ~13 MB → 6.7 MB.
- CI **24/24 pass** (+1 manual-skip), 0 fail. Codex `019e3333` REVISE→AGREE
  (strateji) + AGREE (implementation) — generated shared-map doğrulandı:
  `{ singleton:true, requiredVersion:'*', import:false, version:'0.0.0' }` +
  host-required `get()`.
- `bundle-duplication-v3b1a.md` §7 — browser reconcile (§7.1 chart de-scope,
  §7.2 design-system bulgu, §7.3 fix).

---

## 4. İspatlanamaz — Open Items

- **POST-DEPLOY BROWSER VERIFY PENDING** — #570 platform-web `main`'e merged
  ama **testai'ye deploy EDİLMEDİ**. HARD RULE "Tarayıcıdan Sonuç
  Doğrulanmadan İş Bitmedi" → B1a-dedup **"done" değil**; browser
  payload-diff post-deploy zorunlu (sıradaki P0, §5).
- `@mfe/shared-http` / `@mfe/i18n-dicts` aynı `singleton()` drift'ini taşıyor
  (aynı `sharedProdOnly` blokları) — ölçülmedi, ayrı PR. `@mfe/auth` da
  `singleton()` ama prior auth/impersonation kırılma yüzeyi → ayrı + dikkatli.
- Chart build-time dup (her MFE dist'inde lazy chart chunk) — düşük öncelik.

---

## 5. Sıradaki Agent P0 Aksiyon Listesi

### P0 — #570'i testai'ye deploy + browser payload-diff verify

1. **Image**: `CI - Web Image Build + GHCR Push` (platform-web `main`, #570
   merge push — run `25977542488`) tamamlanınca yeni `sha-XXXXXXX` GHCR'da.
   `gh run list --repo Halildeu/platform-web --branch main` ile sha'yı al.
2. **Digest bump**: gitops `kustomize/overlays/test/kustomization.yaml`
   frontend image digest'ini yeni `sha-XXXXXXX`'e bump et (mevcut pin
   `sha-b782cb2` çevresi — `frontend`/`platform-web` images bloğu).
3. **Apply**: testai cluster'a selective apply + `rollout status`
   (HARD RULE 7 — SSH+kubectl yetkisi).
4. **Browser verify** (`claude-in-chrome` MCP, kullanıcı authenticated
   testai oturumu, fresh reload):

   ```js
   performance.getEntriesByType('resource')
     .filter((e) => /design_mf_2_system|loadShare__.*design/i.test(e.name))
     .map((e) => ({ n: e.name.split('/').pop().slice(0,60),
       enc: Math.round((e.encodedBodySize||0)/1024) }));
   ```

   **Kabul kriteri**: `/remotes/{users,audit,reporting,access}/…design_mf_2_system…`
   FULL chunk'ları (önce 4× ~1.75 MB transfer) **inmemeli**; shell DS provider
   en fazla 1×. Route JS transfer ~7 MB düşmeli (9.7 → ~2.9 MB civarı).
   access/users/audit/reporting route smoke — console'da MF
   `Shared module '@mfe/design-system' must be provided by host` / loadShare
   error **OLMAMALI**.

### P1 — `@mfe/shared-http` + `@mfe/i18n-dicts` hostOnly

Aynı `singleton()` → `hostOnly()` conversion, ayrı PR + browser smoke
(`mf-shared-scope-audit.md` pattern). `@mfe/auth` AYRI ele alınmalı (riskli).

### P1 — `mf-shared-keys.mjs` `sharedProdOnly` guard

`scripts/diagnostics/mf-shared-keys.mjs` şu an yalnız `sharedCore` 7 core
dep'i denetliyor → DS `sharedProdOnly` drift'ini KAÇIRDI. `sharedProdOnly`
internal `singleton()`-vs-`hostOnly()` drift guard ekle (bu drift sınıfını
yakalar).

### Düşük öncelik

Chart build-hygiene (lazy chunk per-MFE dup); shell ANALYZE `mf-preload`
regex; V3-B1b/c (LCP+FCP); V3-B2 harness reconcile (`PERF_AUTH_PASSWORD`);
M2a1 daily seed (2026-05-29); O2/O4/O5 owner-gated.

**Referans**: platform-web `docs/performance/bundle-duplication-v3b1a.md` §7;
`docs/performance/mf-shared-scope-audit.md`; `PERF-DEBT-V3-backlog-tracking.md`
Wave V3-B1 STATUS.

---

## 6. Cross-AI Thread Chain

- `019e32ff` — V3-B1a (PR #564) implementation review (PARTIAL→AGREE).
- `019e3333` — B1a-dedup: strateji consult (REVISE — "browser-verify first")
  → browser evidence → AGREE (DS hostOnly, scope-narrowed) → implementation
  review (AGREE).

---

## 7. HARD RULE Compliance

- ✅ Continuous Autonomous Mode — V3-B1a → B1a-dedup durmadan zincir.
- ✅ Cross-AI Peer Review — PR #570 Codex (OpenAI) review; implementer ≠ reviewer.
- ✅ CI Kırmızıyken Merge YASAK — #570 24/24 pass; 0 red.
- ✅ Admin Merge YASAK — normal squash, 0 admin bypass.
- ✅ No Fake Work — chart "dedup" browser'da reprodüksiyon vermedi → fix
  YAZILMADI, de-scope edildi; gerçek bulgu (DS 5×) browser-verified fix aldı.
- ✅ Tarayıcıdan Doğrula — B1a-dedup investigation browser-driven; post-deploy
  verify P0 olarak açık bırakıldı (henüz "done" denmedi).
- ✅ AI-Native Forensic Cleanup — `archive/2026/05/perf-v3-b1a-dedup-pr570`.
- ✅ Session Otomatik Açma — context doygunluğu + deploy-faz başı → handoff.

---

## 8. Boundary declaration (ADR-0011 §2.3)

- [ ] credential-read
- [ ] credential-write
- [ ] state-mutation (test cluster)
- [ ] state-mutation (production)
- [ ] boundary-cross
- [x] user-communication
- [ ] none of the above

User-communication justification: docs-only session handoff + PERF-DEBT-V3
backlog STATUS update. B1a-dedup kod değişimi platform-web PR #570'te (ayrı
repo, zaten merged). Bu gitops PR cluster state mutation / credential /
manifest değişimi içermez — pure handoff.

User-approval evidence: HARD RULE Pre-Production Full Authority (2026-04-29) +
Continuous Autonomous Mode + Session Otomatik Açma/Handoff HARD RULE
(2026-05-09). PR label: `user-approval-required`.

---

## 9. Cross-AI Peer Review

```
Implementer AI:   Claude
Reviewer AI:      Codex
Codex thread:     019e3333-5ce1-7971-a5ee-3f70a0ae814d
Verdict:          AGREE
Same-provider exception: N/A
Verdict reason:   B1a-dedup (platform-web #570) — DS hostOnly fix Codex
019e3333 tarafından strateji + implementation iki turda AGREE'lendi. Bu
gitops PR docs-only handoff; yeni implementation YOK; o trail'i + PERF-DEBT-V3
backlog STATUS'unu konsolide eder.
```

🤖 Generated with [Claude Code](https://claude.com/claude-code)
