# ADR-0051 — Anonim alımda kötüye kullanım, yasadışı içerik ve zorunlu bildirim

## Status

**Proposed** — 2026-08-02. ES-009 ([#2655](https://github.com/Halildeu/platform-k8s-gitops/issues/2655)).

Bu ADR'nin **teknik** bölümleri (§3, §4, §6) ölçülmüş mevcut davranışı kayda geçirir ve
karara bağlanmıştır. **Hukuki** bölümü (§5) bilinçli olarak **açık bırakılmıştır**: saklama
süresi, teslim yolu ve zorunlu bildirim yükümlülüğü isimli bir insan kararıdır ve bu
belge onu üretmez. ES-1 alım/ek dondurmasından **önce** o kararın sahibi belirlenmelidir.

**İlgili:** [ADR-0050 ihbarcı erişimi kurtarılamaz](0050-faz35-reporter-access-non-recoverable.md),
[ADR-0048 kanıt çift-artefakt saklama](0048-faz35-evidence-dual-artifact-custody.md),
[ADR-0047 dava–kimlik bağı bölmeleri](0047-faz35-case-identity-link-compartments.md)

---

## 1. Bağlam — aynı anda sağlanamayan dört şey

Anonim bir ihbar kanalı dört şeyi birden ister ve bunlar birbirini keser:

1. **Anonimlik.** İhbarcı kimliği tutulmaz; kaybolan erişim geri verilemez (ADR-0050).
2. **Kötüye kullanım kontrolü.** Kanal spam, taşkın ve kasıtlı yükle boğulmamalı.
3. **Yasadışı içerik.** Anonim bir yükleme yolu, er ya da geç taşınması bile suç olan
   materyalin geleceği bir yoldur.
4. **Zorunlu bildirim.** Bazı içerikler için bildirim yükümlülüğü doğabilir.

Gerilim şurada: **(1), (2) ve (4)'ün olağan çözümlerini elinden alır.** Kötüye kullananı
kimlikle engelleyemeyiz — kimlik yok. Bir yükümlülük doğduğunda "kim yükledi" sorusuna
cevap veremeyiz — cevap saklanmıyor. Ve (3), (1) ile birleştiğinde ürünü, sahibini
bilmediği yasadışı materyali **elinde tutan** taraf hâline getirir.

Bu ADR bu gerilimi çözdüğünü iddia etmiyor. Yaptığı şey, **ürünün ne yapıp ne
yapmayacağını** kesinleştirmek ve hukuki kararın nerede başladığını işaretlemek.

## 2. Neden ürün hukuki hüküm üretmemeli

Bir tarayıcı "bu dosya kötü amaçlı" diyebilir. Bir tarayıcı **"bu suçtur"** diyemez.
Aradaki fark teknik değil, hukukidir: suç niteliği yargı yetkisine, bağlama ve niyete
bağlıdır; imza eşleşmesine değil.

Ürün otomatik bir hüküm üretirse iki yönde de zarar verir. **Yanlış pozitifte** masum bir
ihbarcı, kanalın var olma sebebi olan korumayı kaybeder — ve bunu asla öğrenemez, çünkü
anonimdir. **Yanlış negatifte** ise "sistem temiz dedi" cümlesi, olması gereken insan
incelemesinin yerine geçer. İkisi de sessizdir; sessiz hatalar bu üründe en pahalı olanlardır.

Bu yüzden karar nettir: **ürün tespit eder ve yüzeye çıkarır; hüküm vermez.**

## 3. Ölçülen mevcut davranış (2026-08-02, TEST hücresi)

### Kötüye kullanım kontrolü — kimliğe değil hacme dayalı

| katman | kontrol |
|---|---|
| ingress-nginx | IP bazlı istek sınırı |
| uygulama (rate limiter) | `publicIntake` 5 istek/sn, `publicMailbox` 10 istek/sn |
| uygulama (bulkhead) | `publicIntake` 8 eşzamanlı, `publicMailbox` 12 eşzamanlı, bekleme yok → anında `429` |
| erişim denemesi | `failedAttempts` + `lockedUntil` (kaba kuvvet kilidi) |
| yükleme boyutu | `ETHICS_EVIDENCE_MAX_BYTES` (25 MiB), sayfa/piksel üst sınırları |

Bu katmanların hiçbiri kimlik kullanmaz — kullanamaz. Kanalın savunması **şekil ve hacim**
üzerindedir.

### Yasadışı/kötü amaçlı içerik — tespit, karantina, mühür

Ek dosya boru hattının terminal durumları:

`INTEGRITY_VERIFIED` · `ORIGINAL_SEALED` · `SCAN_PENDING` · `REJECTED_INTEGRITY` ·
`REJECTED_POLICY` · `MALICIOUS_QUARANTINED` · `SANITIZE_FAILED`

Kötü amaçlı bulguda ürün: **durumu `MALICIOUS_QUARANTINED` yapar**, karantina kovasına
alır, denetim zincirine `ethics.evidence.rejected` olayı yazar. **Silmez. Sınıflandırmaz.
Hiçbir yere bildirmez.**

Tarayıcının fiilen çalıştığı ES-306'da kanıtlandı (EICAR → `Eicar-Test-Signature FOUND`);
"ayakta = çalışıyor" varsayımıyla geçilmedi.

### Otomatik hukuki eylem — yok

Terminal durum kümesinde ve bildirim hedeflerinde makam/kolluk/hukuk anlamı taşıyan
hiçbir değer yoktur. Bildirim outbox'ının tüm sözlüğü dört olaydır — `NEW_REPORT`,
`REPORTER_MESSAGE`, `SLA_APPROACHING`, `SLA_BREACH` — ve **dördü de kurum içine** gider.
Son ikisi alındı teyidi ağının personele kurduğu süre uyarılarıdır (#3271); dışarıya
giden bir hat yoktur.

## 4. Karar — ürünün yapacakları ve asla yapmayacakları

### Yapar

1. Hacim/şekil temelli kötüye kullanım sınırlaması (kimliksiz).
2. Her eki tarar; kötü amaçlı bulguyu **karantinaya alır ve mühürler**.
3. Kararı ve gerekçe kodunu **denetim zincirine** yazar (WORM).
4. Etik ekibe **durumu** gösterir: "bu ek karantinada, sebep kodu X".
5. Asıl dosyayı, incelenebilir kalması için **mühürlü** saklar (ADR-0048).

### Asla yapmaz

| Yasak | Gerekçe |
|---|---|
| İçeriği hukuken sınıflandırmak ("bu suçtur") | Suç niteliği yargı yetkisi + bağlam işidir; imza eşleşmesi değildir |
| Kolluğa/makama otomatik bildirim | Bildirim bir insan kararıdır; otomatikleşirse yanlış pozitif geri alınamaz |
| Karantinaya alınan aslı otomatik silmek | Delil bütünlüğünü yok eder; ayrıca kararı geri alınamaz kılar |
| İhbarcıyı kimliklendirmeye çalışmak | Kimlik zaten yok (ADR-0050); denemek kanalın vaadini bozar |
| Karantina durumundan ihbarcıya suçlayıcı mesaj üretmek | Ürün hüküm vermez; yanlış pozitif masum ihbarcıyı susturur |
| "Temiz" sonucunu insan incelemesinin yerine koymak | Yanlış negatif sessizdir; tarama bir kolaylıktır, teminat değil |

## 5. İnsan hukuk kapısı — bu ADR'nin **karara bağlamadığı** kısım

Aşağıdakiler isimli bir insan kararıdır (Legal/DPO + ürün sahibi). Bu belge onları
üretmez; **açık bırakır ve sahibini bekler**:

| açık karar | neden insan gerekir |
|---|---|
| Karantinadaki materyalin **saklama süresi** | Elde tutmanın kendisi yükümlülük doğurabilir; süre yargı yetkisine bağlı |
| **Teslim yolu**: yasal talep geldiğinde kim, neyi, hangi kanıtla verir | Zincir-of-custody + yetkilendirme; ürün kendi başına karar veremez |
| **Zorunlu bildirim** yükümlülüğünün kapsamı ve tetikleyicisi | Yükümlülük ülkeye ve içerik sınıfına göre değişir |
| Karantinadaki içeriğe **kimin bakabileceği** | Bakmanın kendisi risk taşır; en dar yetki tanımlanmalı |
| Yanlış pozitif itiraz yolu | Anonim ihbarcı itiraz edemez; telafi mekanizması tasarım kararıdır |

**Ara dönem duruşu (karar gelene kadar geçerli):** materyal mühürlü karantinada kalır,
silinmez, dışarı verilmez, ve yalnız mevcut en dar rol (ES-206 ile zorlanan) erişebilir.
Bu, karar verilmiş gibi davranmamak için bilinçli olarak **en az taahhüt** eden duruştur.

## 6. Sonuçlar

**Kabul edilen boşluk.** Kötüye kullanan biri, hacim sınırlarına uyduğu sürece kanalı
kullanmaya devam edebilir — kimliksiz bir kanalda bunun tam çözümü yoktur. Ölçüt "hiç
kötüye kullanım olmasın" değil, "kötüye kullanım kanalı çökertmesin"dir.

**Taşıma riski.** Ürün, sahibini bilmediği materyali elinde tutar. Bu bilinen ve kabul
edilen bir maruziyettir; azaltıcı unsurlar mühürlü saklama, en dar erişim ve WORM denetim
kaydıdır. Ortadan kaldırılması §5'teki kararlara bağlıdır.

**ES-1 bağı.** Alım/ek dondurması **öncesinde** §5'in sahibi belirlenmiş olmalıdır;
aksi hâlde ürün, cevabı olmayan bir soruyla canlıya çıkar.

## 7. Uygulama (makine-zorunlu)

§4'ün "asla yapmaz" satırlarından otomatikleştirilebilir olanı bir invaryantla sabitlenir:
ek dosya boru hattının terminal durumları ve bildirim olay kümesi taranır; hukuki hüküm
veya makam bildirimi anlamı taşıyan bir değer eklenirse derleme düşer. Kalanı (saklama
süresi, teslim yolu) insan kararıdır ve testle zorlanamaz — bu belge onları **açık** olarak
işaretler ki unutulmasınlar.

## 8. Kapsam dışı

- Yasal ifşa (reveal) akışı — ADR-0047 + ES-303; ihbarcı **kimliği** değil, dava içeriği içindir.
- Saklama/silme genel politikası — ADR-0047 (retention/legal-hold/crypto-erasure).
- Ülke-özel zorunlu bildirim listesi — §5 sahibinin çıktısı olur, bu ADR'nin değil.
