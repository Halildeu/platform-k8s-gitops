# ADR-0047 — Faz 35 Etik Speak saklama, legal hold ve silme invaryantları

## Status

Accepted — 2026-08-01. Mühendislik invaryantları (§3) 2026-07-29'da ölçüme dayalı
olarak yazıldı ve uygulandı. §5'te hukuk/DPO ve ürün sahibine bırakılan üç karar
**2026-08-01'de ürün sahibi tarafından verildi** ve aşağıya karar metni olarak
işlendi. Production aktivasyonu hâlâ bu ADR ile yetkilendirilmez — o ES-312'nin
kapısıdır.

**Owner issue:** ES-006 [#2652](https://github.com/Halildeu/platform-k8s-gitops/issues/2652)

**Açtığı işler:** ES-008 [#2654](https://github.com/Halildeu/platform-k8s-gitops/issues/2654),
ES-301 [#882](https://github.com/Halildeu/platform-backend/issues/882),
ES-302 [#884](https://github.com/Halildeu/platform-backend/issues/884),
ES-303 [#883](https://github.com/Halildeu/platform-backend/issues/883)

**İlgili:** [saklama politikası](../legal/faz35-retention-policy.md),
[ADR-0035 kanıt saklama sözleşmesi](0035-evidence-storage-contract.md),
[ADR-0046 ürün hücresi topolojisi](0046-faz35-etik-speak-product-cell-topology.md)

---

## 1. Bağlam

Bir ihbar sisteminde silme, sıradan bir veri yaşam döngüsü adımı değil. İki
yükümlülük aynı veriye ters yönde bakıyor:

- **Sil.** KVKK Md.7, GDPR Art.5(1)(e) — amaç ortadan kalkınca içerik durmaz.
- **Sakla.** EU 2019/1937 Art.18, SOX Sec.802, ISO 37002 §8.6 — ihbarın
  işlendiğine dair kayıt on yıl durur.

Saklama politikası bu ikisini şöyle ayırmış: **vaka içeriği** beş yıl sonra
satır düzeyinde silinir; **denetim defteri** on yıl saklanır ve silinmez.
Yani silme iddiası "her şey gitti" değil, "içerik gitti, işlendiğinin kaydı
attribution ile durdu".

Bu ayrımın çalışması, denetim satırının hangi vakaya ait olduğunun **içerik
silindikten sonra da** bilinebilmesine bağlı. 2026-07-29'da ölçtük: bilinemiyordu.

## 2. Ölçülen durum

Aşağıdakiler tahmin değil, k3d-test hücresinde ölçüldü.

| ölçüm | bulgu |
|---|---|
| `aggregate_id` ayırt edici kolonu | **yoktu**; vaka olayı vaka kimliğini, kanıt olayı ek dosya kimliğini taşıyor |
| tip türetilebilirliği | yalnız ebeveyn tablolara join ile — yani **silme, türetmeyi de yok ediyor** |
| WORM tablosunun sahibi | `ethics_app` — defteri **yazan** rol; PostgreSQL'de sahip kendi tetikleyicisini kapatabilir |
| tetikleyici kapsamı | `ORIGIN` — replica'da çalışmıyordu |
| defter büyüklüğü | 430 satır (368 vaka olayı, 62 kanıt olayı) |

Değiştirilemezliğin kapatılabilirliği deneyle doğrulandı: ayrı bir şemada
`ethics_app` kimliğiyle tetikleyici bir DELETE'i reddetti, ardından tek bir
`ALTER TABLE ... DISABLE TRIGGER` ile aynı DELETE geçti.

## 3. Karar — mühendislik invaryantları

Bunlar uygulandı ve canlıda doğrulandı.

### I1 — Değiştirilemezlik iki bağımsız kilide dayanır

```
ACL          çalışma zamanı rolü SELECT + INSERT; hiçbir şeyin sahibi değil
tetikleyici  append-only, ENABLE ALWAYS (replica dahil)
```

Göç rolü (`ethics_migrator`) şemayı sahiplenir ve Flyway'i koşar; uygulama rolü
yalnız okur ve ekler. Biri düşerse diğeri ayakta kalır. Tek kilit yeterli
değildir: sahiplik, kilidi kaldırma yetkisini de verir.

**Kanıt:** `scripts/faz35/harden-worm-ownership.sh --check` 10/10; negatif kanıt
üç saldırıyı (tetikleyici kapatma, TRUNCATE, DELETE) geri alınan bir transaction
içinde koşar ve üçü de reddedilir.

### I2 — Her denetim satırı, ebeveyni yaşarken sınıflandırılır

`ethics_audit_scope`: `worm_audit_id → (aggregate_type, root_case_id)`.

Salt bir tip kolonu yetmez. Bir satırın kanıt olayı olduğunu bilmek **hangi
vakaya** ait olduğunu söylemez; ebeveyn silindiğinde tip yaşar, aidiyet ölür.
Vaka kapsamlı bir silme iddiasının ihtiyacı aidiyettir.

Ebeveyni çoktan gitmiş satır `UNRESOLVED` yazılır, tahmin edilmez: bir silme
makbuzunda yanlış kök vaka, itiraf edilmiş bir boşluktan kötüdür.

**Kanıt:** canlıda 368 CASE + 62 ATTACHMENT = 430; kapsam dışı 0.

### I3 — Sınıflandırma da append-only

Sonradan düzenlenebilen bir sınıflandırma hiçbir şeyin kanıtı değildir: temiz
bir silme makbuzu uydurmanın en ucuz yolu, denetim satırlarını değil kapsam
satırlarını yeniden yazmak olurdu.

### I4 — Kapsam kaydı, içerikle aynı anahtara bağlanmaz

Kripto-silme devreye alındığında kapsam/manifest kayıtları vaka içeriğiyle
**aynı** anahtarla şifrelenmemelidir. Aksi halde anahtarın imhası, silmenin
kanıtını da yok eder ve geriye doğrulanamaz bir iddia kalır.

### I5 — Silme öncesi kapsam manifesti yazılır

Silme başlamadan önce beklenen kapsam (satır sayıları, digest'ler, anahtar
referansı, legal-hold sonucu) append edilir; kapsam kontrolü eksikse işlem
fail-closed durur. Sonuç ayrı bir olayla kaydedilir; yarım kalan durum
başarıdan ayrı bir olaydır.

*I5 tasarım kararıdır; orkestrasyon henüz yazılmadı (#884).*

## 4. Neden bu ayrım

Silme doğrulaması iki farklı soruyu karıştırmaya çok müsait:

1. **Erişilemez mi?** — kripto-silme buna cevap verir (anahtar imha edildi).
2. **Kapsam eksiksiz miydi?** — kripto-silme buna cevap **vermez**. Anahtarın
   hangi kayıtları kapsadığını ispatlamaz.

İkincisi için ayrı bir kapsam kaydı gerekir. Bu ADR ikisini ayrı invaryant
olarak tutar, çünkü tek mekanizma sanıp birini diğerinin yerine koymak, denetimde
"sildik" denip gösterilecek kanıtın olmaması demektir.

## 5. Ürün sahibi kararları (2026-08-01)

Aşağıdaki üç soru mühendislik tercihi değildi; 2026-07-29'da açık bırakıldı ve
2026-08-01'de ürün sahibi tarafından karara bağlandı. Sorular soruldukları hâliyle
korunuyor — bir kararın neyi kapattığı, ancak açık hâli okunabildiğinde denetlenir.

### K1 — Kripto-silme ne zaman meşru?

**Soru.** [ADR-0035](0035-evidence-storage-contract.md) anahtar imhasını **saklama
süresi ve legal-hold sonuna** bağlıyor. Saklama politikası kripto-silmeyi "şu an
aktif değil, gelecek dilim" diye tanımlıyor. İhbarcı talebiyle **daha erken** silme
yapılacaksa bu iki metin arasındaki çatışma açıkça çözülmelidir.

**Karar — "talep üzerine erken imha".** Kripto-silme yalnız **vaka içerik bölmesine**
uygulanır: bildirim gövdesi, ek dosyalar, kimlik kasası. Denetim defteri
(`ethics_worm_audit`) ve kapsam tablosu (`ethics_audit_scope`) hiçbir tetikte
imha edilmez; I4 bunu zaten ayrı anahtar şartıyla mümkün kılıyor.

İki tetik, ikisi de dört kapıdan geçer:

| tetik | ek koşul |
|---|---|
| **Normal** — vaka kapanışı + saklama süresi dolumu | saklama süresi default 5 yıl, **kiracı-parametrik** (yalnız uzatılabilir; [retention policy §1a](../legal/faz35-retention-policy.md)) |
| **Erken** — ihbarcının kendi bildirimi için onaylı silme talebi | talep sahibi = bildirim sahibi (access-secret eşleşmesi); kiracı profili bu tetiği kapatabilir (kamu Md.28) |

Her iki tetikte de dördü birden aranır: **legal-hold yok**, **aktif reveal grant
yok**, **kapsam manifesti yazıldı** (I5), **kapsam kontrolü eksiksiz**. Biri
sağlanmazsa işlem fail-closed durur; kısmi silme başarı sayılmaz.

**ADR-0035 ile çatışmanın çözümü.** ADR-0035 §5 iki farklı şeyi tek cümlede
tutuyordu: nesnenin silinmesi ve anahtarın imhası. Object-Lock compliance-mode
retention'ı **nesne silmeyi** engeller — anahtar imhasını değil. Erken talepte
şifreli nesne yerinde kalır (Object-Lock ihlali yok), yalnız erişilemez hale
gelir. Saklama yükümlülüğünün koruduğu şey de zaten içerik değil kayıttır:
2019/1937 Art.18 ihbarın *kaydını*, SOX Sec.802 *denetim kaydını* korur. İçeriğin
erken imhası bu kayıtların hiçbirini eksiltmez. **Legal-hold** tarafında istisna
yoktur ve mutlaktır: hold aktifken anahtar imhası delil karartmasıdır.

**Silmeden sonra defterde ne kalır** (K1'in "tanımlanmalı" dediği kısım):

| kalır | kalmaz |
|---|---|
| olay tipi, zaman damgası, aktör (staff subject / reporter) | bildirim gövdesi |
| `aggregate_id`, `aggregate_type` | ek dosya içeriği |
| `root_case_id` (kapsam tablosundan) | ihbarcı kimliği |
| silme makbuzu: manifest digest, kapsam sayıları, anahtar referansı, legal-hold sonucu | içeriğe çözülebilen hiçbir anahtar |

Yani silme sonrası cevaplanabilen soru şudur: *"bu vaka vardı, şu tarihte şu
aktörler şunu yaptı, içeriği şu kapsamla imha edildi"*. Cevaplanamayan: *"ne
yazıyordu"*. Ayrım kasıtlıdır.

### K2 — Mevcut 430 satır için kripto-silme geçerli değil

**Soru.** Sonradan üretilen bir anahtar, değiştirilemez geçmiş gövdeyi geriye
dönük şifrelemez. Bugünkü defter için "anahtar imhası kapsamı yok etti"
**denemez**. Bu satırlar ya mevcut hâliyle saklanır ya da ayrı bir karar gerektirir.

**Karar — mevcut hâliyle saklanır; geriye dönük imha yok.** Kripto-silme yalnız
anahtarın devreye alınmasından **sonra** oluşan içeriği kapsar. Anahtar öncesi
vakalar için silme makbuzu "kripto-silme" değil, **satır düzeyinde silme** iddia
eder ve makbuzda yöntem açıkça yazılır; iki yöntem tek kelimeye ("silindi")
katlanmaz.

Bu 430 satır zaten içerik değil, denetim satırıdır — silinmeleri gündemde
değildi. Karar, ileride bir denetimde "neden bu satırlar için anahtar yok"
sorusuna verilecek cevabı bugünden sabitliyor.

### K3 — Kapsam tablosunun KVKK statüsü

**Soru.** İçinde kişisel veri yok — yalnız UUID ve tip. Ama bir ihbar vakasının
**varlığını** kanıtlıyor ve yaşayan kayıtlarla aynı kimlik uzayında. Bunun
dolaylı tanımlayıcı sayılıp sayılmayacağı, hangi saklama süresine tabi olacağı
ve silme talebinin kapsamına girip girmediği hukuk kararıdır.

**Karar — bağımsız veri kategorisi değil; denetim kaydının teknik eki.**

- **Saklama süresi:** denetim defteriyle aynı — 10 yıl.
- **Silme talebinin kapsamı:** girmez.
- **VERBİS:** ayrı kayıt açılmaz; mevcut denetim kaydı kapsamında tanımlanır.

Gerekçe iki adımlı. Birincisi, vakanın *varlığını* zaten denetim defteri
kanıtlıyor; kapsam tablosu bir kişi hakkında yeni bir olgu eklemiyor, yalnız
mevcut satırın hangi köke ait olduğunu söylüyor. İkincisi ve daha önemlisi:
kapsam kaydını silmek veri sahibini **korumaz, korumasız bırakır**. I2'yi yok
eder, aidiyeti öldürür, ve geriye "sildik" denip kapsamı gösterilemeyen bir iddia
kalır. Silme talebinin amacı denetlenebilirliği azaltmak değildir.

Mühendislik tarafındaki güvenli sınır I4'te yazılı ve bu kararla korunuyor:
kapsam kaydı içerikle aynı anahtara bağlanmaz. Karar ileride değişir ve kapsam
kaydının da yok olması istenirse, ham UUID → makbuz eşlemesi imha edilir ve
geriye yalnız doğrulama commitment'ı kalır; bu, orijinal UUID ile sonradan
doğrulama yapabilme yeteneğini azaltır — bilerek ödenen bir bedel olmalıdır.

## 6. Sonuçlar

**Olumlu.** "Bu vakanın her kaydı silindi" iddiası artık silmeden sonra da
denetlenebilir. Değiştirilemezlik, onu ihlal edebilecek rolün iznine bağlı
değil. Silme ve kapsam ayrı invaryantlar olduğu için biri diğerinin yerine
konulamaz.

**Maliyet.** Ayrı bir göç rolü ve credential; kapsam tablosu her denetim satırı
için bir satır daha; silme akışı manifest yazmadan ilerleyemez.

**Riskler.** Kapsam kaydı yalnız yazıldığı andaki gerçeği taşır — yeni yazımlara
`root_case_id` kolonu eklenene kadar yeni satırlar hâlâ join ile
sınıflandırılıyor (bugün ebeveynleri yaşadığı için gerileme yok, ama ayrı dilim
olarak duruyor). `UNRESOLVED` satırlar bugün sıfır; ileride çıkarsa silme
makbuzu o vaka için eksiksiz olduğunu iddia edemez.

**Uygulanmayan.** Silme orkestrasyonu (#884), SLA saati (#882), reveal
containment (#883). Bu ADR onların dayanacağı invaryantları tanımlar.
