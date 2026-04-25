# RB-pr-bot – PR Automation (PR Bot + Merge Bot)

ID: RB-pr-bot  
Service: github-actions-pr-bot  
Status: Draft  
Owner: @team/platform

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

- `fix/**` ve `wip/**` branch push’larında PR yoksa `main`’e PR açmak.
- PR üzerinde tek bir marker comment’ini idempotent şekilde upsert etmek.
- `wip/**` için PR’ı Draft yapmak (mümkünse).
- `merge_policy=bot_squash` ise (PR draft değilse) PR’a `pr-bot/ready-to-merge` label’ını eklemek.
- Merge-Bot ile (label + QA PASS) koşullarında PR’ı `squash merge` etmek.

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

- Trigger scope:
  - push: `fix/**`, `wip/**`, `docs/**`, `ops/**`
  - manuel: `workflow_dispatch`
- SSOT:
  - Kurallar: `docs-ssot/04-operations/PR-BOT-RULES.json`
  - Template’ler: `docs/04-operations/pr-bot-templates/*.md`
  - Marker: `<!-- pr-bot:rules -->`
  - Merge gate label: `pr-bot/ready-to-merge`
  - Merge policy: `merge_policy` (örn. `bot_squash` / `none`)
- Kapsam dışı:
- Fork repo'larda otomasyon (güvenlik nedeniyle koşmaz).
  - PAT zorunluluğu (yalnız org/repo policy `GITHUB_TOKEN write` kısıtlıysa opsiyonel fallback).
- Local SSOT policy: Fix/patch işlemleri yalnızca lokal yapılır (bkz. RB-insansiz-flow).

-------------------------------------------------------------------------------
3. BAŞLATMA / DURDURMA
-------------------------------------------------------------------------------

- Başlatma (otomatik):
  - `fix/**`, `wip/**`, `docs/**`, `ops/**` branch’lerine push → PR Bot tetiklenir.
  - QA workflow’ları SUCCESS olunca → Merge-Bot tetiklenir (workflow_run).
- Başlatma (manuel):
  - GitHub Actions → “PR Bot” → Run workflow.
- Durdurma / devre dışı bırakma:
  - `.github/workflows/pr-bot.yml` ve `.github/workflows/pr-merge.yml` workflow’larını disable et veya branch filter’larını kaldır.

-------------------------------------------------------------------------------
4. GÖZLEMLEME / LOG / METRİKLER
-------------------------------------------------------------------------------

- Gözlem:
  - GitHub Actions run logs.
  - Job “Step Summary” içinde PR URL ve yapılan aksiyonlar (create/update/noop/merge).
- Kritik sinyaller:
  - 401/403: auth/permission sorunu (token veya org policy).
  - 4xx/5xx: GitHub API hata dönüşleri (rate limit, permission, invalid payload).

-------------------------------------------------------------------------------
5. ARIZA DURUMLARI VE ADIMLAR
-------------------------------------------------------------------------------

- [ ] Arıza senaryosu 1 – 401/403 (token/permission):
  - Given: Workflow koşuyor ama PR create/comment API’si 401/403 dönüyor.  
    When: `GITHUB_TOKEN` write izinleri repo/org policy ile kısıtlı.  
    Then:
    - Repo Settings → Actions → “Workflow permissions” kontrol et (read-only olabilir).
    - Gerekirse `secrets.GH_PR_BOT_TOKEN` (fine-grained) tanımla ve scope’u minimum tut.

- [ ] Arıza senaryosu 2 – Duplicate comment:
  - Given: PR’da birden fazla bot yorumu oluşuyor.  
    When: Marker satırı comment body’de yok veya değişmiş.  
    Then:
    - `PR-BOT-RULES.json` içindeki `comment_marker` sabit kalsın.
    - Template’lerde marker yazma; marker yalnız bot tarafından prepend edilmeli.

- [ ] Arıza senaryosu 3 – Draft set edilemiyor:
  - Given: `wip/**` için PR draft olmalı.  
    When: GraphQL mutation yetkisi yok veya API hata dönüyor.  
    Then:
    - Draft dönüşümü “best-effort” olarak kalır; comment upsert devam eder.
    - Gerekirse PR’a “draft” niyetini belirten bir label/comment eklenir (fallback).

- [ ] Arıza senaryosu 4 – Ready label eklenemiyor:
  - Given: `merge_policy=bot_squash` ama PR’da `pr-bot/ready-to-merge` yok.  
    When: Label create/add API’si permission/policy nedeniyle fail oluyor.  
    Then:
    - `.github/workflows/pr-bot.yml` içinde `issues: write` olduğundan emin ol.
    - Label’ı repo'da bir kez manuel oluştur (fallback) ve tekrar dene.

- [ ] Arıza senaryosu 5 – Merge-Bot merge etmiyor:
  - Given: QA PASS ama PR merge olmuyor.  
    When: PR draft, label eksik, head SHA değişti veya `mergeable_state != clean`.  
    Then:
    - PR’da `pr-bot/ready-to-merge` label’ı var mı kontrol et.
    - PR’ın son commit’i için tüm check’ler “success” mı kontrol et.
    - Repo branch rules “required reviews” istiyorsa insansız merge mümkün olmayabilir.

-------------------------------------------------------------------------------
6. ÖZET
-------------------------------------------------------------------------------

- Güvenlik modeli: Primary `GITHUB_TOKEN`, policy kısıtında opsiyonel `GH_PR_BOT_TOKEN`.
- SSOT dosyası ve template’ler değiştiğinde, bot davranışı deterministik olarak güncellenir.

-------------------------------------------------------------------------------
7. LİNKLER (İSTEĞE BAĞLI)
-------------------------------------------------------------------------------

- Doğal akış: docs/04-operations/RUNBOOKS/RB-insansiz-flow.md
- Workflow: .github/workflows/pr-bot.yml
- Workflow: .github/workflows/pr-merge.yml
- SSOT: docs-ssot/04-operations/PR-BOT-RULES.json
- Templates: docs/04-operations/pr-bot-templates/
- SLO/SLA: docs/04-operations/SLO-SLA.md
