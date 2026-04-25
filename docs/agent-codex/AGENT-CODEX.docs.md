# Doküman Geliştirme Görevleri

> Transition Durumu: Bu dosya transition-active rehber katmanındadır.
> Canonical kaynaklar:
> `standards.lock`,
> `docs/OPERATIONS/AI-MULTIREPO-OPERATING-CONTRACT.v1.md`,
> `docs/OPERATIONS/OPO-AUTHORITY-MAP.v1.md`.

Bu dosya, **[DOC]** tipindeki görevler için geçerlidir.

## 1. Amaç

- Problem Brief, PRD, Tech Design, Story, SPEC, Acceptance, Runbook vb. dokümanların
  tutarlı format ve dil ile yazılmasını sağlamak.
- Dokümanlar üzerinden yazılım sürecini izlenebilir kılmak.

## 2. Kapsam

- Yeni Problem Brief / PRD / Tech Design yazımı
- Yeni Story / Acceptance / ADR oluşturma
- Var olan dokümanların revizyonu
- Runbook / Monitoring / Release Notes hazırlama

## 3. Zorunlu Okuma

[DOC] işi alındığında agent:

1. `AGENTS.md`
2. `docs/OPERATIONS/OPO-AUTHORITY-MAP.v1.md`
3. `DOC-HIERARCHY.md`
4. `STYLE-DOCS-001.md`
5. `NUMARALANDIRMA-STANDARDI.md`
6. (DOCS-PRODUCTION / Direct-Gen ise) üretim kontratı:
   - `docs/03-delivery/SPECS/SPEC-0012-m3-direct-gen-production-system-v1.md`
   - `DOCS-PRODUCTION-AGENTS.md`
7. Uygun şablonlar:
	   - `docs/99-templates/PROBLEM-BRIEF.template.md`
	   - `docs/99-templates/PRD.template.md`
	   - `docs/99-templates/SPEC.template.md`
	   - `docs/99-templates/ADR.template.md`
	   - `docs/99-templates/TECH-DESIGN.template.md`
	   - `docs/99-templates/INTERFACE-CONTRACT.template.md`
	   - `docs/99-templates/STORY.template.md`
	   - `docs/99-templates/ACCEPTANCE.template.md`
	   - `docs/99-templates/TEST-PLAN.template.md`
   - `docs/99-templates/RUNBOOK.template.md`
   - `docs/99-templates/GUIDE.template.md`
   - `docs/99-templates/BM.template.md`
   - `docs/99-templates/BENCH.template.md`
   - `docs/99-templates/TRACE.template.md`
   - `docs/99-templates/DATA-CARD.template.md`
   - `docs/99-templates/MODEL-CARD.template.md`

Not: Yeni bir doküman (PB, PRD, STORY, AC, TP, ADR, RB, DATA, MODEL) açarken:
- ID türü ve formatı için her zaman `NUMARALANDIRMA-STANDARDI.md` içindeki akışı,
- Klasör seçimi için `DOCS-PROJECT-LAYOUT.md` içindeki dizin yapısını kullan.

## 3.1 DOCS-PRODUCTION (Direct-Gen) Notu

Bu repo’daki “doküman üretim akışı”, `PROJECT-FLOW` tablosundan bağımsız olarak:
BM → BENCH → TRACE → Delivery Pack (PB/PRD/SPEC/STORY/AC/TP) zinciridir.

SSOT:
- Kontrat: `docs/03-delivery/SPECS/SPEC-0012-m3-direct-gen-production-system-v1.md`
- Rol dağılımı: `DOCS-PRODUCTION-AGENTS.md`

## 4. Cevap Formatı

Doküman işlerinde cevap:

- **Örneklerden Öğrenilenler**
  - Benzer dokümanlardan çıkarılan kurallar / yapı.
- **Doküman Taslağı**
  - Başlıklar + her başlık altında kısa, net içerik.
- **Uygulama Adımları**
  - Hangi dosya adıyla, hangi path’te oluşturulacağı / güncelleneceği.

## 5. Sınırlar

- Agent, STYLE-DOCS-001’deki formatı bozmamalı, başlık yapısını korumalıdır.
- Dokümandaki içerik mümkün olduğunca “ne, neden, nasıl, ne zaman bitti” sorularına
  cevap verecek şekilde yapılandırılmalıdır.

## 6. Otomatik Planlama ve Adım Keşfi

[DOC] tipindeki görevlerde kullanıcıdan ayrıntılı “adım listesi” beklenmez.  
Agent, verilen komuta göre kendi planını çıkarır ve adım adım ilerler.

Varsayılan davranış:

1. İşin bağlamını anlama
   - Prompt’tan mümkünse Story / Epic / doküman ID’lerini çıkar:
     - Örn: `STORY-0004`, `AC-0004`, `TP-0004`, `RB-keycloak`, `NUMARALANDIRMA-STANDARDI.md`.
   - ID yoksa:
     - Gerekirse kullanıcıya kısa bir soru sor (“Hangi Story/konu?”) veya
     - `docs/03-delivery/PROJECT-FLOW.md` ve `DOC-HIERARCHY.md` üzerinden en yakın bağlamı bul.

2. Dokümanları parça parça okuma
   - Tüm repo’yu okumaz; sadece ilgili dosyaları ve bölümleri tarar:
     - İlgili alan transition rehberi
     - `DOCS-PROJECT-LAYOUT.md`, `NUMARALANDIRMA-STANDARDI.md`, `STYLE-DOCS-001.md`
     - İlgili STORY / AC / TP / TECH-DESIGN / RUNBOOK / RELEASE-NOTES dosyaları
   - Okumayı token limitini aşmadan, küçük parçalar hâlinde yapar.

3. Plan çıkarma
   - Kullanıcının verdiği cümleleri yalnız “ipucu” olarak görür; zorunlu adım listesi değil.
   - Kendi içinde 3–7 maddelik kısa bir plan oluşturur (keşif → tasarım → uygulama).
   - Planı işler ilerledikçe günceller; gerekiyorsa adımları birleştirir/böler.

4. Durum takibi
   - STORY / AC / TP dokümanlarında:
     - `Status:` alanını ve checkbox’ları ([ ] / [x]) okuyup
       hangi adımların tamamlandığını anlar.
     - `PROJECT-FLOW.md` tablosundaki satırı referans alarak hangi aşamada
       olduğumuzu yorumlar.
   - Acceptance (AC) dokümanlarında:
     - İş birden fazla alanı etkiliyorsa senaryoları modül bazlı grupla
       (örn. `### Backend`, `### Web`, `### Data`, `### Operations`).
     - Mümkünse her modül için kısa “Kanıt/Evidence” (path/komut) ekle;
       böylece kod içine STORY-ID gömmeden izlenebilirlik sağlanır.
   - Kullanıcıdan “şu adımda kaldık” bilgisini beklemez; kendisi dokümanlardan
     çıkarır. Kullanıcı sadece yüksek seviye istek verebilir
     (örn. “STORY-0004 için kaldığımız yerden devam et”).

5. Komut üretimi
   - Gerekli shell komutlarını ve dosya değişikliklerini kendi belirler:
     - Örn. belirli dokümanları okumak için `sed`/`rg`,
     - Yeni doküman eklemek/güncellemek için uygun dosya yolu + isim.
   - Kullanıcının tek tek “şu komutu çalıştır” demesi beklenmez; önemli olan
     niyeti ifade etmesidir.

6. Meta alanları (ID ve Linkler)

- PB/PRD/STORY/AC/TP/ADR/RB gibi ID alan dokümanlarda:
  - H1 başlığının hemen altında `ID: <ID>` satırı bulunmalıdır.
  - Agent yeni doküman üretirken bu satırı **zorunlu** olarak ekler ve
    NUMARALANDIRMA-STANDARDI.md’de seçilen ID ile doldurur.
- Problem Brief ve PRD dokümanları için:
  - İlgili template’lerdeki “LİNKLER / SONRAKİ ADIMLAR” bölümü doldurulmalı;
    ilişkili PB/PRD/STORY/AC/TP/API dokümanları burada listelenmelidir.

Bu davranışın amacı, kullanıcının doküman ve süreç detaylarına hâkim olmasını
zorunlu kılmadan; sadece “ne istendiğini” söylemesiyle agent’ın doğru
dokümanları bulup, doğru sırada okuyup, adım adım ilerlemesini sağlamaktır.

## 7. Doc QA ve Script Çalıştırma Kuralları

Bu bölüm, özellikle doküman kalitesi ve zincir tutarlılığı ile ilgili
projelerde (QLTY-DOC-QA epic’i) hangi script setlerinin hangi sırayla
çalıştırılacağını tanımlar.

### 7.1 Doküman Zinciri Kontrolü (Tamlık)

“Doküman zinciri kontrolü” dendiğinde, agent aşağıdaki sırayı izler:

1. Format & ID kontrolleri (ön koşul)
   - `scripts/check_doc_templates.py`
   - `scripts/check_doc_ids.py`
   - `scripts/check_doc_locations.py` (dokümanların doğru klasörde olması)
   - `scripts/check_acceptance_evidence.py` (AC içindeki Kanıt/Evidence referansları)
2. Zincir & flow kontrolü (delivery tarafı)
   - `scripts/check_story_links.py`  
     - `docs/03-delivery/PROJECT-FLOW.md` ↔ STORY / AC / TP uyumu için.

Notlar:
- Şu anda **PB/PRD/TECH-DESIGN/ADR/RUNBOOK** gibi tam ürün zinciri
  kontrolleri için ayrı bir script (örn. `check_doc_chain.py` /
  `docflow_next.py`) tasarlanmıştır; bu fazlar STORY-0031 ve devamındaki
  işler kapsamında devreye alınacaktır.
- Şimdilik zincir kontrolü, ağırlıklı olarak delivery zincirine
  (STORY / AC / TP) odaklanır.

### 7.2 “Bu projeye başla” Akışı

Kullanıcı “Bu projeye başla: STORY-XXXX” dediğinde:

1. **STORY + AC + TP’yi aç**
   - Aktif STORY ID (örn. `STORY-0026`) bulunur.
   - İlgili `AC-XXXX` ve `TP-XXXX` dosyaları açılır.
2. **Format & ID ön koşul kontrolleri**
   - `check_doc_templates.py`  
   - `check_doc_ids.py`  
   - `check_doc_locations.py` (dokümanların doğru klasörde olması)  
   - `check_acceptance_evidence.py` (AC içindeki Kanıt/Evidence referansları)  
   - Eksik başlıklar, yanlış `ID:` satırları ve ID çakışmaları varsa
     uygun dokümanlara patch üretilir.
3. **Delivery zinciri kontrolü**
   - `check_story_links.py`  
   - PROJECT-FLOW tablosundaki satırlar ile STORY / AC / TP dosyaları
     arasındaki eksik veya hatalı bağlantılar raporlanır; gerekirse
     eksik dokümanlar şablona göre oluşturulur.
4. **Story’ye özel kontroller**
   - İhtiyaca göre:  
     - `check_api_docs.py` (STYLE-API-001 uyumu),  
     - `check_governance_migration.py`,  
     - `check_agent_docs_contract.py` vb.
5. **Özet ve iyileştirme fırsatları**
   - Hangi hataların düzeltildiği, hangi eksiklerin kaldığı ve sonraki
     mantıklı adımlar (yeni Story/AC/TP veya script genişletmeleri) kısa
     bir özet halinde raporlanır.

### 7.3 “Bu projeyi test et” Akışı

Kullanıcı “Bu projeyi test et: STORY-XXXX / TP-XXXX” dediğinde:

- Bağlam, ilgili **Test Plan** dosyasıdır (örn. `TP-0025` veya `TP-0030`).  
- Agent:
  - İlgili TP dosyasının **“ÇEVRE VE ARAÇLAR”** ve **“TEST SENARYOLARI ÖZETİ”**
    bölümlerini okur.
  - Yalnızca bu Test Plan’da açıkça tanımlanmış script ve senaryoları
    çalıştırır (örn. `check_doc_templates.py`, `check_story_links.py`,
    `check_doc_chain.py`).
  - Çıktıları TP içindeki senaryolarla ilişkilendirerek raporlar
    (hangi senaryo geçti/kaldı, hangi dokümanlara patch gerekti).

### 7.4 “Sadece Doc QA çalıştır” Akışı

Kullanıcı “Sadece Doc QA çalıştır” dediğinde:

- Bu, **global kalite turu** anlamına gelir; yeni feature/Story başlatılmaz.  
- Agent aşağıdaki seti çalıştırır:
  - `check_doc_templates.py`  
  - `check_doc_ids.py`  
  - Gerekirse, delivery zinciri görünümü için `check_story_links.py`
    tüm Story’ler üzerinde.  
- Amaç:
  - Mevcut dokümanların format, ID ve temel zincir tutarlılığını
    toparlamak;  
  - Yeni iş/feature yaratmak yerine, var olan borçları azaltmak.

### 7.5 Doğal Komutlar ve Script Setleri

Kullanıcıdan beklenen doğal komutlar:

- “Bu projeye başla: `STORY-XXXX`”
- “Bu projeyi test et: `STORY-XXXX` / `TP-XXXX`”
- “Sadece Doc QA çalıştır”

AGENT-RISK-CONTROL mantığı:

- “Bu projeye başla” komutu geldiğinde:
  - Önce format/ID script’leri (`check_doc_templates.py`, `check_doc_ids.py`),
  - Ardından zincir script’i (`check_story_links.py`),
  - Son olarak Story’ye özel script’ler (API/governance/agent-contract)
    sırasıyla çalıştırılır.
- “Bu projeyi test et” komutunda:
  - Yalnız ilgili Test Plan’da tanımlı script’ler devreye alınır; başka
    script eklenmez.
- “Sadece Doc QA çalıştır” komutunda:
  - Yeni Story/feature açılmaz; sadece doküman kalitesi ve zincir
    tutarlılığı iyileştirilir.

### 7.6 docflow_next (plan/run/autopilot)

- Plan: `python3 scripts/docflow_next.py STORY-XXXX` (legacy) veya `python3 scripts/docflow_next.py plan STORY-XXXX`
- Run: `python3 scripts/docflow_next.py run STORY-XXXX --level L1|L2|L3 [--dry-run]`
- Autopilot: `python3 scripts/docflow_next.py autopilot --max-run N [--force STORY-XXXX|--force-all] [--dry-run]`
  - Aday seçimi: `docs/03-delivery/PROJECT-FLOW.md` Öncelik DESC + Durum != Done
  - Olgunluk: Flow tablosundaki `M_STORY/M_AC/M_TP`; `maxAllowedM=min(...)` (M1→L1, M2→L2, M3→L3)
  - Kademeli ilerleme: `currentLevel=state.lastSuccessLevel` (yoksa L0), `nextLevel=current+1`; `nextLevel<=maxAllowedLevel` ise RUN, aksi SKIP; PASS’te Flow `L_LAST/L_NEXT` güncellenir; `--force` delta’yı bypass eder (maxAllowedLevel aşılmaz)
  - State/ledger/summary çıktıları `web/test-results/ops/` altındadır; repo’ya commit edilmez
  - `docflow_next` her koşumda `web/test-results/ops/timings.jsonl` üretir; trend için `python3 scripts/docflow_next.py stats --days 7` kullanılır.
  - Profiling opt-in: `--profile time` (default `none`).
  - L2 scope seçimi: `--impact all|auto|web|backend` (local default `all`, ci default `auto`; diff okunamazsa `all`).
  - Best-effort log capture: `--capture-logs on-fail|always|never` (default `on-fail`, çıktı: `web/test-results/ops/logs/**`).
  - Playwright (L3) env özet: `PW_AUTH_MODE=none|token_injection` (token: `PW_TEST_TOKEN` veya `KEYCLOAK_TOKEN_URL/CLIENT_ID/CLIENT_SECRET`), `PW_READONLY_ENFORCE=1` iken `/api/` write istekleri violation sayılır (allowlist/env ile istisna tanımlanabilir).

### 7.7 Faz 1 Kabul — Deterministik Güven (Kontrat)

- SSOT: Aday seçimi + olgunluk hedefi `docs/03-delivery/PROJECT-FLOW.md` tablosundan okunur (Öncelik DESC, Durum != Done, `M_STORY/M_AC/M_TP`); seviye ilerleme state’i `web/test-results/ops/autopilot_state.json` üzerinden yürür, PASS’te Flow `L_LAST/L_NEXT` aynalanır.
- Minimum kontrat (M1): PROJECT-FLOW satırı + ilgili `STORY-XXXX` dosyası + en az bir `AC-XXXX` dosyası (linkli).
- Zincir sabit: STORY/AC/TP; TP `maxAllowedM>=M2` iken zorunlu.
- SPEC/ADR/API/RUNBOOK zincire dahil değil; koşullu readiness gate olarak STOP/BLOCKED üretebilir.
- `maxAllowedM>=M2` iken TP zorunludur: `TP-XXXX` yoksa sistem RUN etmez; STOP/BLOCKED olarak raporlar.
- Sistem hedefe zıplamaz: her zaman kademeli ilerler (L1→L2→L3). State yalnızca PASS’te `lastSuccessLevel` olarak yükselir.
- Doküman eksikliği/kontrat eksikliği FAIL değildir: STOP/BLOCKED olarak sınıflandırılır; eksik tamamlanmadan ilgili `M_*` yükseltilmez (min M artmaz).
- Günlük işletim: önce `docflow_next autopilot --dry-run`, sonra gerekirse `autopilot` (summary: `web/test-results/ops/summary.md`).
- evidence-mode varsayılan `relaxed` olmalıdır; `strict` yalnız repo içi kanıt kuralı uygulanıyorsa seçilmelidir.
- ops doküman kontrolleri (`runbooks_links`, `release_docs`) yalnız `ops/release/nightly` modlarında koşar.
