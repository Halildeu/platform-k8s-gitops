# DOCS-WORKFLOW – Dokümantasyon Süreci Rehberi (Compact)

> Transition Durumu: Bu dosya transition-active rehber katmanındadır.
> Canonical OPO authority için
> `docs/OPERATIONS/OPO-AUTHORITY-MAP.v1.md`,
> `docs/OPERATIONS/AI-MULTIREPO-OPERATING-CONTRACT.v1.md` ve
> `standards.lock` kullanılır.

Bu doküman, proje içindeki tüm yazılı dokümanların (PB, PRD, Story, Acceptance,
Tech-Design, ADR, Test-Plan, Runbook vb.) **nasıl üretileceğini ve güncelleneceğini**
tek ve tutarlı bir workflow halinde tanımlar.

Amaç:
- Dokümanların DEV-GUIDE süreciyle hizalı, izlenebilir ve güncel kalmasını sağlamak.

Kapsam:
- `docs/` altındaki tüm doküman tipleri
- Agent ve insanların dokümantasyon ile çalışma biçimi

-------------------------------------------------------------------------------
1. TEMEL İLKELER
-------------------------------------------------------------------------------

- Dokümantasyon koddan ayrı değil, **aynı ürünün parçasıdır**.
- Her dokümanın amacı net olmalı; gereksiz içerik yazılmaz.
- Tüm ID ve dosya adları `NUMARALANDIRMA-STANDARDI.md` kurallarına uyar.
- Tüm klasör yerleşimi `DOCS-PROJECT-LAYOUT.md` ile uyumlu olur.
- Stil ve başlık yapısı `STYLE-DOCS-001.md` ile uyumludur.
- Tarih/saat içeren tüm raporlar ve loglar kod ile sistem saatinden üretilir; AI tahmini zaman kullanılmaz.
- Her yeni doküman uygun template’ten (`docs/99-templates/**`) türetilir.
- Aynı bilgi farklı dokümanlarda tekrar edilmez; referans verilerek bağlanır.

-------------------------------------------------------------------------------
2. GELİŞTİRME SÜRECİNE GÖRE DOKÜMAN AKIŞI
-------------------------------------------------------------------------------

Bu bölüm, `DEV-GUIDE` içindeki 6 adımı doküman perspektifinden özetler:
Discover → Shape → Design → Build → Validate → Operate

2.1 Discover – Problemi Anla
- Amaç: İş problemini ve hedefi netleştirmek.
- Dokümanlar:
  - `docs/01-product/PROBLEM-BRIEFS/PB-xxxx-*.md`
- Workflow:
  - Gerekirse yeni PB aç; yoksa mevcut PB’yi güncelle.
  - Hedef metrikleri, varsayımları ve sınırları yaz.

2.2 Shape – Ürün Davranışını Tanımla
- Amaç: Kullanıcı ve sistem davranışını tanımlamak.
- Dokümanlar:
  - `docs/01-product/PRD/PRD-xxxx-*.md`
- Workflow:
  - PB’den gelen problem için PRD hazırla veya güncelle.
  - Kullanıcı akışlarını, non-goals ve kabul alanını netleştir.

2.3 Design – Teknik Tasarım
- Amaç: Çözümün teknik olarak nasıl uygulanacağını tarif etmek.
- Dokümanlar:
  - `docs/02-architecture/services/<servis>/TECH-DESIGN-*.md`
  - `docs/02-architecture/services/<servis>/ADR/ADR-xxxx-*.md`
  - `docs/02-architecture/services/<servis>/DATA-MODEL-*.md` (varsa)
- Workflow:
  - PRD’yi referans alarak teknik tasarım yaz.
  - Kritik kararları ADR ile kayıt altına al.
  - Veri modeli değişiyorsa DATA-MODEL dokümanını ekle/güncelle.

2.4 Build – Geliştirme
- Amaç: Kod ve testleri üretmek.
- Dokümanlar:
  - `docs/03-delivery/STORIES/STORY-xxxx-*.md`
  - `docs/03-delivery/TEST-PLANS/TP-xxxx-*.md`
- Workflow:
  - Her anlamlı iş parçası için Story aç veya mevcut Story’yi güncelle.
  - Gerekirse Test Plan dokümanı oluştur; kapsam ve stratejiyi netleştir.

2.5 Validate – Kabul ve Test
- Amaç: PRD ile uyumluluğu doğrulamak.
- Dokümanlar:
  - `docs/03-delivery/ACCEPTANCE/AC-xxxx-*.md`
  - `docs/03-delivery/TEST-PLANS/TP-xxxx-*.md`
- Workflow:
  - Story ile hizalı AC dokümanını Given/When/Then formatında yaz.
  - Test Plan üzerinde sonuçları ve kapsam değişikliklerini işaretle.

2.6 Operate – Yayın ve Operasyon
- Amaç: Üretim ortamında stabil ve izlenebilir çalışmayı sağlamak.
- Dokümanlar:
  - `docs/04-operations/RUNBOOKS/RB-*.md`
  - `docs/04-operations/MONITORING/MON-*.md`
  - `docs/04-operations/RELEASE-NOTES/REL-*.md`
- Workflow:
  - Servis bazında tek Runbook’ı güncel tut.
  - Önemli metrik ve alarmlar için Monitoring dokümanı yaz.
  - Her release için kısa ve net Release Notes hazırla.

-------------------------------------------------------------------------------
3. DOKÜMAN TİPİNE GÖRE WORKFLOW ÖZETİ
-------------------------------------------------------------------------------

3.1 Problem Brief (PB)
- Ne zaman?
  - Yeni veya tam anlaşılamamış bir problem olduğunda.
- Nerede?
  - `docs/01-product/PROBLEM-BRIEFS/PB-xxxx-*.md`
- Akış:
  - Tür: PB → doğru klasörü seç.
  - Yeni ID: `NUMARALANDIRMA-STANDARDI.md` adımlarına göre üret.
  - Template: `docs/99-templates/PROBLEM-BRIEF.template.md` kullan.

3.2 PRD
- Ne zaman?
  - Çözümün ürün davranışı netleştirilirken.
- Nerede?
  - `docs/01-product/PRD/PRD-xxxx-*.md`
- Akış:
  - PB’ye referans ver.
  - Kullanıcı akışlarını ve acceptance ile ilişkisini açık yaz.

3.3 Story
- Ne zaman?
  - Geliştirme yapılabilir parçalara bölündüğünde.
- Nerede?
  - `docs/03-delivery/STORIES/STORY-xxxx-*.md`
- Akış:
  - `STORY.template.md` üzerinden başlat.
  - Story’yi DEV-GUIDE aşamalarına göre güncel tut (özellikle Build/Validate).

3.4 Acceptance (AC)
- Ne zaman?
  - Story için test edilebilir davranış netleştiğinde.
- Nerede?
  - `docs/03-delivery/ACCEPTANCE/AC-xxxx-*.md`
- Akış:
  - Story ID ile hizalı ID kullan (`STORY-0007` ↔ `AC-0007`).
  - Given/When/Then formatında, uygulanabilir test senaryoları yaz.

3.5 Test Plan (TP)
- Ne zaman?
  - Feature/epic bazında test kapsamı gerekliyse.
- Nerede?
  - `docs/03-delivery/TEST-PLANS/TP-xxxx-*.md`
- Akış:
  - Template: `TEST-PLAN.template.md`.
  - Story ve Acceptance dokümanlarına referans ver.

3.6 Tech-Design / ADR / Data-Model
- Ne zaman?
  - Teknik çözüm kararı gerektiğinde veya mimari değişiklik olduğunda.
- Nerede?
  - `docs/02-architecture/services/<servis>/TECH-DESIGN-*.md`
  - `docs/02-architecture/services/<servis>/ADR/ADR-xxxx-*.md`
  - `docs/02-architecture/services/<servis>/DATA-MODEL-*.md`
- Akış:
  - SERVIS bazlı dizinleri kullan (`DOCS-PROJECT-LAYOUT.md`).
  - Önemli kararları ADR olarak, detayları TECH-DESIGN içinde tut.

3.7 Runbook / Monitoring / Release Notes
- Ne zaman?
  - Üretim çalışma biçimi, alarm ve sürüm notları gerektiğinde.
- Nerede?
  - `docs/04-operations/RUNBOOKS/RB-*.md`
  - `docs/04-operations/MONITORING/MON-*.md`
  - `docs/04-operations/RELEASE-NOTES/REL-*.md`
- Akış:
  - Runbook: servis başına tek dosya; sürekli güncel tutulur.
  - Release Notes: her release’te yeni kayıt eklenir.

-------------------------------------------------------------------------------
4. AGENT VE İNSAN İŞBİRLİĞİ
-------------------------------------------------------------------------------

- İnsan:
  - Problem, karar ve iş önceliğini belirler.
  - Dokümanların anlamlı ve doğru olduğundan emin olur.
- Agent:
  - Doğru dokümanları bulmak, okumak ve taslak üretmek için kullanılır.
  - `AGENT-CODEX.docs.md` içindeki okuma sırasına uyar.

Önerilen çalışma biçimi:
- İnsan, hangi iş üzerinde çalışıldığını ve mevcut ID’leri belirtir (varsa).
- Agent, ilgili STORY/PRD/TECH-DESIGN/TP/AC dokümanlarını okur.
- Agent, STYLE-DOCS-001’e uygun taslak/patche hazırlar; insan onayıyla birleşir.

-------------------------------------------------------------------------------
5. CHECKLIST – YENİ DOKÜMAN / GÜNCELLEME ÖNCESİ
-------------------------------------------------------------------------------

Her yeni doküman veya büyük güncelleme öncesi:

- [ ] Doğru türü seçtim mi? (PB, PRD, STORY, AC, TP, TECH-DESIGN, ADR, RB vb.)
- [ ] Doğru klasörü seçtim mi? (`DOCS-PROJECT-LAYOUT.md`)
- [ ] Doğru ID formatını kullandım mı? (`NUMARALANDIRMA-STANDARDI.md`)
- [ ] Uygun template’ten başladım mı? (`docs/99-templates/**`)
- [ ] Diğer dokümanlara (PB/PRD/Story/AC/TP/ADR) referans verdim mi?
- [ ] İçerik kısa, net ve madde madde mi? (`STYLE-DOCS-001.md`)

-------------------------------------------------------------------------------
6. UYGULAMA ADIMLARI – PRATİK ÖRNEK
-------------------------------------------------------------------------------

Senaryo: Yeni bir backend özelliği için dokümantasyon akışı.

1) Discover
   - Gerekirse yeni `PB-xxxx-<konu>.md` aç veya mevcut PB’yi güncelle.
2) Shape
   - İlgili `PRD-xxxx-<feature>.md` dokümanını oluştur/güncelle; kabul alanını netleştir.
3) Design
   - İlgili servis altında `TECH-DESIGN-<servis>-<konu>.md` yaz.
   - Kritik kararları `ADR-xxxx-<karar>.md` ile kaydet.
4) Build
   - Geliştirme işleri için `STORY-xxxx-<konu>.md` dosyalarını aç.
   - Gerekliyse `TP-xxxx-<konu>.md` ile test planı yaz.
5) Validate
   - Her Story için `AC-xxxx-<konu>.md` oluştur; Given/When/Then koşullarını yaz.
   - Test sonuçlarını Acceptance / Test Plan içinde izlenebilir kıl.
6) Operate
   - Servis runbook’unu (`RB-<servis>.md`) ve ilgili Monitoring/Release Notes dokümanlarını güncelle.

-------------------------------------------------------------------------------
7. ÖZET
-------------------------------------------------------------------------------

Bu doküman, `DEV-GUIDE`, `DOCS-PROJECT-LAYOUT`, `NUMARALANDIRMA-STANDARDI` ve
`STYLE-DOCS-001` ile uyumlu olarak:
- hangi adımda hangi dokümanın üretileceğini,
- hangi klasörde hangi ID formatının kullanılacağını,
- agent ve insanların dokümantasyon üzerinde nasıl birlikte çalışacağını
özetler.

Dokümantasyon workflow’u için tek referans kılavuzdur.

-------------------------------------------------------------------------------
8. KOD TARAFI İLE ENTEGRASYON (ÖZET)
-------------------------------------------------------------------------------

Build / Validate aşamasında agent’ın tetikleyebileceği başlıca script setleri:

- Doc QA:
  - `python3 scripts/docflow_next.py STORY-XXXX`
  - `python3 scripts/check_doc_templates.py`
  - `python3 scripts/check_doc_ids.py`
  - `python3 scripts/check_doc_locations.py`
  - `python3 scripts/check_story_links.py STORY-XXXX`
  - `python3 scripts/check_doc_chain.py STORY-XXXX`
  - `python3 scripts/check_governance_migration.py`

- Otopilot (seçici koşum):
  - `python3 scripts/docflow_next.py autopilot --max-run N [--force STORY-XXXX|--force-all]`
  - Kural: PROJECT-FLOW `M_STORY/M_AC/M_TP` → `maxAllowedM=min(...)` (M1→L1, M2→L2, M3→L3)
  - Delta: `currentLevel=state.lastSuccessLevel` (yoksa L0), `nextLevel=current+1`; `nextLevel<=maxAllowedLevel` ise çalışır; değilse skip; `--force` ile delta bypass (maxAllowedLevel aşılmaz)
  - Not: `min(M_STORY,M_AC,M_TP)` artmadıkça bir üst seviye koşmaz; `--force` yalnız istisnai durumdur.
  - STOP/BLOCKED kontrat eksikliğidir; FAIL gerçek hatadır.
  - State/summary çıktıları `web/test-results/ops/` altındadır (repo'ya commit edilmez)
  - L2 scope seçimi: `--impact all|auto|web|backend` (local default `all`, ci default `auto`; diff okunamazsa `all`).
  - Log capture (best-effort): `--capture-logs on-fail|always|never` (default `on-fail`, çıktı: `web/test-results/ops/logs/**`).
  - Playwright (L3) env: `PW_AUTH_MODE=token_injection` iken token `PW_TEST_TOKEN` veya `KEYCLOAK_TOKEN_URL/CLIENT_ID/CLIENT_SECRET`; `PW_READONLY_ENFORCE=1` iken `/api/` write istekleri violation sayılır.

- Lint / Style:
  - Backend için:
    - `./scripts/run_lint_backend.sh`
  - Backend + Web birlikte:
    - `python3 scripts/run_lint_all.py`

- Testler:
  - Backend:
    - `./scripts/run_tests_backend.sh` (opsiyonel modül parametresi ile)
  - Web:
    - `./scripts/run_tests_web.sh` (veya mode: `unit|e2e|quality|all`)
  - Backend + Web unit:
    - `python3 scripts/run_tests_all.py`

- Release / Operasyon:
  - `python3 scripts/release_smoke_check.py`
  - `python3 scripts/check_slo_sla.py metrics.json`
  - `python3 scripts/check_runbooks_links.py`
  - `python3 scripts/check_release_docs.py`

- Security:
  - Backend:
    - `./scripts/check_security_backend.sh`
  - Web:
    - `./scripts/check_security_web.sh`
  - Backend + Web:
    - `python3 scripts/check_security_all.py`

- Data Pipelines:
  - SQL stil kontrolleri:
    - `python3 scripts/check_data_sql_style.py`
  - Pipeline exception kontrolleri:
    - `python3 scripts/check_data_pipelines.py`
  - Tümü birlikte:
    - `python3 scripts/check_data_all.py`

- Mimari Tutarlılık (ADR / TECH-DESIGN → Kod):
  - Servis bazında TECH-DESIGN dizinleri ile backend modül yapısı:
    - `python3 scripts/check_arch_vs_code.py`
  - Backend mikroservis iç iskelet standardı:
    - `python3 scripts/check_backend_service_layout.py`
  - Web MFE iç iskelet standardı:
    - `python3 scripts/check_web_mfe_layout.py`
  - Acceptance içindeki Kanıt/Evidence referansları:
    - `python3 scripts/check_acceptance_evidence.py`
  - (Opsiyonel) PROJECT-FLOW içindeki 🟩 Done STORY ID'leri için kod/test referansı:
    - `python3 scripts/check_project_flow_vs_code.py`
    - Not: Bu kontrol, kod içinde `STORY-XXXX` tag/referansı kullanıyorsan anlamlıdır.
      Kullanmak istemiyorsan `--report` ile sadece rapor alabilir veya bu adımı atlayabilirsin.

Agent, kullanıcı “Bu projeye başla / test et / sadece Doc QA çalıştır” dediğinde,
AGENT-CODEX.* dosyalarındaki kurallara ve bu script setine göre hangi
adımların çalıştırılacağını belirler.
