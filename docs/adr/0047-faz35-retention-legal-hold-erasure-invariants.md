# ADR-0047 — Faz 35 Etik Speak saklama, legal hold ve silme invaryantları

## Status

Proposed — 2026-07-29. Mühendislik invaryantları ölçüme dayalı ve uygulanmış
durumda; **§5'teki üç karar hukuk/DPO ve ürün sahibine aittir** ve bu ADR onları
karara bağlamaz. Production aktivasyonu bu ADR ile yetkilendirilmez.

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

## 5. Hukuk/DPO ve ürün sahibi kararına bırakılanlar

Aşağıdakiler mühendislik tercihi değildir ve bu ADR onları karara bağlamaz.

### K1 — Kripto-silme ne zaman meşru?

[ADR-0035](0035-evidence-storage-contract.md) anahtar imhasını **saklama süresi
ve legal-hold sonuna** bağlıyor. Saklama politikası kripto-silmeyi "şu an aktif
değil, gelecek dilim" diye tanımlıyor. İhbarcı talebiyle **daha erken** silme
yapılacaksa bu iki metin arasındaki çatışma açıkça çözülmelidir.

| seçenek | sonuç |
|---|---|
| Yalnız saklama sonu | ADR-0035 korunur; erken silme talebi karşılanamaz |
| Talep üzerine erken imha | ADR-0035 revize edilmeli; WORM attribution'ın ne kadarının korunacağı tanımlanmalı |
| Kategori bazlı | En esnek, en karmaşık; her kategori için ayrı gerekçe gerekir |

### K2 — Mevcut 430 satır için kripto-silme geçerli değil

Sonradan üretilen bir anahtar, değiştirilemez geçmiş gövdeyi geriye dönük
şifrelemez. Bugünkü defter için "anahtar imhası kapsamı yok etti" **denemez**.
Bu satırlar ya mevcut hâliyle saklanır ya da ayrı bir karar gerektirir.

### K3 — Kapsam tablosunun KVKK statüsü

İçinde kişisel veri yok — yalnız UUID ve tip. Ama bir ihbar vakasının
**varlığını** kanıtlıyor ve yaşayan kayıtlarla aynı kimlik uzayında. Bunun
dolaylı tanımlayıcı sayılıp sayılmayacağı, hangi saklama süresine tabi olacağı
ve silme talebinin kapsamına girip girmediği hukuk kararıdır.

Mühendislik tarafındaki güvenli sınır I4'te yazılı: kapsam kaydı içerikle aynı
anahtara bağlanmaz. Hukuk kararı kapsam kaydının da yok olmasını isterse, ham
UUID → makbuz eşlemesi imha edilir ve geriye yalnız doğrulama commitment'ı
kalır; bu, orijinal UUID ile sonradan doğrulama yapabilme yeteneğini azaltır.

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
