# RB-nonprefix-naming-policy-rollout – Nonprefix Naming Policy Enable

ID: RB-nonprefix-naming-policy-rollout
Service: docs-ci
Status: Draft
Owner: @team/platform

Not: Bu runbook, policy flip’i **merge sonrası main** üzerinde uygulamak için hazırlanmıştır.

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

- Prefix/template kapsamı dışında kalan dosya/klasör isimlerini kanonik hale getiren policy’yi hard gate’e almak.

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

- Policy: `docs-ssot/03-delivery/SPECS/nonprefix-naming-policy.v1.json`
- SSOT: `docs-ssot/00-handbook/DOC-NONPREFIX-NAMING-SSOT.json`
- Checker: `scripts/check_doc_folder_file_naming.py` (policy-aware)
- CI: `.github/workflows/doc-qa.yml` (policy enabled=true iken ihlal varsa FAIL)

Ön koşul:
- `docs/03-delivery/guides/**` GUIDE migration merge olmuş olmalı (guides naming policy hard gate).

-------------------------------------------------------------------------------
3. BAŞLATMA / DURDURMA
-------------------------------------------------------------------------------

Enable (hard gate aç):
1) Lokal rapor üret:
   - `python3 scripts/check_doc_folder_file_naming.py`
2) Policy flip:
   - `docs-ssot/03-delivery/SPECS/nonprefix-naming-policy.v1.json` → `enabled: true`
3) PR aç → doc-qa PASS olmalı.

Disable (hard gate kapat / rollback):
1) Aynı dosyada `enabled: false` yap.
2) PR aç → doc-qa PASS olmalı.

-------------------------------------------------------------------------------
4. GÖZLEMLEME / LOG / METRİKLER
-------------------------------------------------------------------------------

- Local report:
  - `.autopilot-tmp/flow-mining/nonprefix-naming-report.md`
- CI:
  - doc-qa workflow output (required checks)
- Minimum metrik:
  - `violations` sayısı (0 hedefi)

Not:
- Policy enabled=false iken checker non-blocking çalışır; rapor yine üretilir.

-------------------------------------------------------------------------------
5. ARIZA DURUMLARI VE ADIMLAR
-------------------------------------------------------------------------------

- [ ] Arıza senaryosu 1 – Policy enable sonrası doc-qa FAIL (naming ihlali)
  - Given: `scripts/check_doc_folder_file_naming.py` ihlal raporluyor.
  - When: `nonprefix-naming-policy.v1.json` enabled=true yapılıp PR açılıyor.
  - Then: doc-qa FAIL beklenir.
  - Adımlar:
    1) `.autopilot-tmp/flow-mining/nonprefix-naming-report.md` içindeki ihlalleri listele.
    2) Çözüm seçenekleri:
       - (A) Dosyayı kanonik isim/konuma taşı/yeniden adlandır.
       - (B) Bilinçli exception ise `DOC-NONPREFIX-NAMING-SSOT.json` allowlist kuralını güncelle.
    3) Lokal doc-qa: `python3 scripts/run_doc_qa_execution_log_local.py --out-dir .autopilot-tmp/execution-log`
    4) PASS olunca policy flip PR’ını tekrar dene.

- [ ] Arıza senaryosu 2 – False positive / aşırı kısıtlayıcı allowlist
  - Given: İşlevsel olarak doğru bir dosya, naming kuralı nedeniyle ihlal sayılıyor.
  - When: enabled=true sonrası CI FAIL ediyor.
  - Then: SSOT allowlist kuralı güncellenmeli veya dosya kanonik hale getirilmeli.
  - Adımlar:
    1) SSOT kuralını minimum genişlet (en dar regex ile).
    2) Değişiklik sonrası raporu tekrar üret (violations düşmeli).

-------------------------------------------------------------------------------
6. ÖZET
-------------------------------------------------------------------------------

- enabled=false → raporla ve ihlalleri temizle.
- enabled=true → hard gate; ihlal varsa CI FAIL.
- Rollback yalnız policy flip ile yapılır (kod değişikliği gerekmez).

-------------------------------------------------------------------------------
7. LİNKLER (İSTEĞE BAĞLI)
-------------------------------------------------------------------------------

- SSOT: `docs-ssot/00-handbook/DOC-NONPREFIX-NAMING-SSOT.json`
- Policy: `docs-ssot/03-delivery/SPECS/nonprefix-naming-policy.v1.json`
- Checker: `scripts/check_doc_folder_file_naming.py`
- CI: `.github/workflows/doc-qa.yml`
- Local execution log: `.autopilot-tmp/execution-log/execution-log.md`
