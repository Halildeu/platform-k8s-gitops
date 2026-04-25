# RB-log-digest – PR Failure Digest (workflow_run → comment upsert)

ID: RB-log-digest  
Service: github-actions  
Status: Draft  
Owner: @team/platform

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

- PR check workflow’ları FAIL olduğunda, ilgili run’ın loglarından “ilk hata bloğu”nu çıkarıp
  PR’a marker’lı tek bir comment olarak idempotent şekilde yazmak (spam üretmeden).

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

- Bu runbook yalnızca `Halildeu/platform-ssot` repo’sundaki GitHub Actions otomasyonunu kapsar.
- Kapsanan workflow’lar: `ci-gate`, `Web QA`, `Layout QA`, `Doc QA`, `security-guardrails`.
- Ortamlar: GitHub Actions.
- Sorumlu ekip: Platform.
- Local SSOT policy: Fix/patch işlemleri yalnızca lokal yapılır (bkz. RB-insansiz-flow).

-------------------------------------------------------------------------------
3. BAŞLATMA / DURDURMA
-------------------------------------------------------------------------------

- Başlatma: `.github/workflows/log-digest.yml` repo'da enabled olduğunda otomatik çalışır.
- Durdurma (kill switch):
  - Workflow’u GitHub UI’dan disable et, veya
  - `.github/workflows/log-digest.yml` içindeki `workflow_run.workflows` listesinden workflow adlarını çıkar.

-------------------------------------------------------------------------------
4. GÖZLEMLEME / LOG / METRİKLER
-------------------------------------------------------------------------------

- Loglar:
  - GitHub Actions Run logları (Workflow run linki digest içinde yer alır).
  - PR yorumları: marker `<!-- log-digest:v1 -->` içeren tek bir comment.
- Metrikler (minimum):
  - “Digest workflow success rate” (manuel gözlem: run’lar yeşil mi?)
  - “Time-to-digest” (workflow_run completion → comment update gecikmesi).

-------------------------------------------------------------------------------
5. ARIZA DURUMLARI VE ADIMLAR
-------------------------------------------------------------------------------

- [ ] Arıza senaryosu 1 – PR bulunamıyor (noop):
  - Given: workflow_run event’i PR’dan gelmiştir,  
    When: `scripts/log_digest.py` PR numarasını bulamaz (`pull_requests[]` boş + commit->pulls boş),  
    Then: Bu durum “noop” kabul edilir; run logundan run_id/head_sha doğrulanır.

- [ ] Arıza senaryosu 2 – API/permissions (403/404):
  - Given: `log-digest` workflow’u çalışır,  
    When: Actions logs endpoint veya PR comment endpoint 403/404 döner,  
    Then: `.github/workflows/log-digest.yml` permissions kontrol edilir:
    `actions: read`, `pull-requests: write`, `issues: write`.

- [ ] Arıza senaryosu 3 – Yorum boyutu limitine takılma:
  - Given: Job logları büyük veya çok sayıda FAIL vardır,  
    When: Comment body limitine yaklaşır,  
    Then: Digest otomatik truncate eder; tam detay için run linki kullanılır.

-------------------------------------------------------------------------------
6. ÖZET
-------------------------------------------------------------------------------

- `log-digest` workflow’u, FAIL olan PR check’lerinde tek bir PR comment’i güncelleyerek
  “ilk hata bloğu” görünürlüğünü artırır ve spam üretmez.

-------------------------------------------------------------------------------
7. LİNKLER (İSTEĞE BAĞLI)
-------------------------------------------------------------------------------

- Doğal akış: docs/04-operations/RUNBOOKS/RB-insansiz-flow.md
- STORY: docs/03-delivery/STORIES/STORY-0302-release-deploy-e2e-v0-1.md
- ACCEPTANCE: docs/03-delivery/ACCEPTANCE/AC-0302-release-deploy-e2e-v0-1.md
- Workflow: .github/workflows/log-digest.yml
- Script: scripts/log_digest.py
