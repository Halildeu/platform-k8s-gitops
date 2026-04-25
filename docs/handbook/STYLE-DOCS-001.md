# STYLE-DOCS-001 – Doküman Yazım Stili (Compact)

Bu doküman, proje içindeki tüm yazılı dokümanların (PB, PRD, Tech-Design,
Story, Acceptance, Runbook, Data-Card, Model-Card vb.) tutarlı bir format ve
yazım stilinde üretilmesi için gereken kuralları tanımlar.

Amaç: Dokümanların okunabilir, taranabilir, sürdürülmesi kolay ve AI agent'lar
tarafından işlenebilir olmasını sağlamak.

-------------------------------------------------------------------------------
1. GENEL PRENSİPLER
-------------------------------------------------------------------------------

- Dokümanlar kısa, net ve doğrudan olmalıdır.
- Gereksiz süslü cümle, hikâye, yorum ve belirsiz ifadeler kullanılmaz.
- Her doküman başında 1–2 cümlelik “Amaç” bölümü bulunmalıdır.
- Doküman içeriği mümkün olduğunca madde madde yazılmalıdır.
- Terimler tutarlı kullanılmalıdır; tanımlar glossary içinde yer alabilir.
- Zorunlu bilgiler başlıklandırılmış bölüm halinde verilmelidir.

-------------------------------------------------------------------------------
2. BAŞLIK VE YAPI FORMATİ
-------------------------------------------------------------------------------

Tüm dokümanlar aşağıdaki yapısal ilkeleri takip eder:

- Ana başlık → H1 (#)
- Alt başlık → H2 (##)
- Alt seviye → H3 (###)
- Bölümler yatay çizgi (----) ile ayrılabilir.
- Uzun paragraflar 5 satırı geçmez; maddelemeye bölünür.

-------------------------------------------------------------------------------
3. DİL VE ÜSLUP
-------------------------------------------------------------------------------

- Dil sade, anlaşılır ve teknik doğruluğa uygun olmalıdır.
- Yorum, spekülasyon veya karmaşık anlatım kullanılmaz.
- Gereksiz sıfatlardan kaçınılır (mükemmel, harika, çok önemli vb.).
- Cümleler kısa ve net yazılır; pasif cümleler en aza indirgenir.
- Gereksiz İngilizce kelimeler kullanılmaz; teknik terimler istisna olabilir.
- Doküman gövdesi Türkçe yazılır:
  - Story “Tanım” bölümünde `As a / I want / so that` kalıbı kullanılmaz; yerine Türkçe rol/istek/fayda formatı yazılır.
  - Acceptance dokümanlarında “Given / When / Then” anahtar kelimeleri korunur; senaryo açıklamaları Türkçe yazılır.

-------------------------------------------------------------------------------
4. ZORUNLU BÖLÜMLER (HER DOKÜMAN TÜRÜ İÇİN)
-------------------------------------------------------------------------------

1) Amaç  
2) Kapsam  
3) Tanımlar (varsa)  
4) Yapı / Mimari / Akış  
5) Kararlar / Gereksinimler / Kurallar  
6) Riskler / Varsayımlar (PRD, Tech-Design vb. için)  
7) Uygulama Adımları (geliştirme dokümanlarında)  
8) Referanslar (varsa)

PRD, Story, Tech-Design, Acceptance gibi türlerin kendi template’leri bu yapı
üstüne oturur.

-------------------------------------------------------------------------------
5. DOKÜMAN TİPİNE GÖRE KISA REHBER
-------------------------------------------------------------------------------

PB (Problem Brief):
- Sorun, etkisi, hedef değer, başarı kriteri → 1 sayfa

PRD:
- Kullanıcı akışları
- Non-goals
- Acceptance kriterleri ile uyum

Tech-Design:
- Architecture diagram (sözel)
- Data flow
- Interface/contract
- Trade-off kararları (kısa)

Story:
- İş hedefi
- Kapsam dışı
- Success criteria

Acceptance:
- Given / When / Then formatı
- Net test edilebilir davranış tanımı

Runbook:
- Nasıl start edilir?
- Nasıl restart edilir?
- Hangi log’lara bakılır?
- Alarm gerçekleşirse ne yapılır?

Data-Card:
- Veri kaynağı, hacim, kalite, sınırlamalar

Model-Card:
- Model amacı, metrikler, riskler, bias, kullanım sınırları

-------------------------------------------------------------------------------
6. YAZIM KURALLARI
-------------------------------------------------------------------------------

- Kısaltmalar ilk geçtiği yerde açıklanır.
- Tarih formatı: YYYY-MM-DD
- Numara formatı: 1.234,56 (tr formatı) veya 1,234.56 (en formatı) → tutarlı olmalıdır.
- Kod parçaları mümkünse pseudo-code seviyesinde tutulur.
- Gereksiz tablo/şekil kullanılmaz.
- Her doküman bir “Özet” bölümü ile kapanmalıdır.

-------------------------------------------------------------------------------
7. AGENT DAVRANIŞI
-------------------------------------------------------------------------------

[DOC] iş tipi alındığında agent:

1. AGENT-CODEX.core.md  
2. AGENTS.md  
3. STYLE-DOCS-001.md (bu dosya)  
4. İlgili template (docs/99-templates/*)  
5. İlgili domain dokümanları  
okur ve aşağıdaki formatta yazım önerir:

- Örneklerden Öğrenilenler  
- Doküman Taslağı  
- Uygulama Adımları (dosya yolu + oluşturulacak dosya adı)

Agent’ın doküman üretirken:
- Belirsiz içerik yazmaması,
- Gereksiz uzun açıklamalardan kaçınması,
- Şablona uyması,
- Gereksiz başlık üretmemesi  
zorunludur.

-------------------------------------------------------------------------------
8. ÖZET
-------------------------------------------------------------------------------

Bu stil dokümanı tüm doküman tipleri için:
- dil,
- yapı,
- bölüm kuralları,
- template uyumu,
- agent davranış standartlarını  
tanımlar.

Doküman üretimi için tek doğruluk kaynağıdır.
