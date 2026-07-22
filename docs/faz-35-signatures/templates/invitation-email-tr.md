# Faz 35 ES-311 — İmza Davet Email Şablonu

**Kullanım**: Aşağıdaki metni owner her rol için ayrı ayrı ilgili kişiye email olarak gönderir. `<...>` yer tutucuları doldur.

---

## Şablon

**Konu**: [Faz 35 Etik Speak] Whistleblowing Kanal — `<ROL>` görevi için kabul talebi

---

Sayın `<Ad Soyad>`,

Şirketimizin whistleblowing (ihbar) kanalı **Etik Speak** 2026-07-22 itibarıyla anonim erişime açılmıştır (`speakup.acik.com` + `etik.acik.com`). Bu kanalın hukuki + operasyonel + teknik sorumluluğunu **7 rolde** paylaşan bir imza paketi hazırlıyoruz.

Sizi **`<ROL>`** görevi için öneriyorum. Rol yükümlülükleri aşağıdaki charter belgesinde detaylı:

**Charter linki**: https://github.com/Halildeu/platform-k8s-gitops/blob/main/docs/faz-35-signatures/charters/`<charter-file>`.md

### Özet yükümlülük

`<Charter'daki ilk 5-10 satırın özeti — owner rol'a göre doldurur>`

### Süre + yenileme

- 1 yıl geçerli (2026-07-22 → 2027-07-22)
- Yıllık yenileme + rol devir dokümante edilir

### Kabul yöntemleri (3 seçenek)

1. **Git commit** (teknik):
   - GitHub reposunda charter dosyasının sonuna kabul beyanı ekleyip commit
   - Instructions: charter dosyasının en altındaki "Kabul beyanı" bölümü
2. **PDF ıslak imza** (klasik):
   - Charter'ı PDF export edip ıslak imza atıp taranıp geri gönder
   - Ben (owner) PDF'i repo'ya commit ederim
3. **DocuSign / e-imza** (uzaktan):
   - Ben DocuSign linki hazırlayıp gönderim
   - Elektronik imza sonrası audit trail otomatik

### Kişisel mesuliyet uyarısı

Bu rol **kişisel taahhüttür**. İhmal veya kasıt sonucu doğacak zararlardan hukuken sorumlusunuz. Charter'daki tüm maddeleri okuyup anladığınızı beyan ederek imzalayın.

### Cevap süresi

Lütfen **7 gün içinde** (`<TARIH>`) charter'ı okuyup:
- **Kabul ediyorum** → yukarıdaki 3 yöntemden birini seçin
- **Kabul etmiyorum / açıklama istiyorum** → bu maile cevap yazın, konuşalım

### Sorular

Charter'daki herhangi bir madde net değilse veya değişiklik istiyorsanız iletişime geçin — legal counsel ile revizyon yapabiliriz.

Saygılarımla,

`<Owner adı>`
`<halildeu@gmail.com>`
Etik Speak — Platform Yönetimi

---

## Rol-özel varyasyonlar

### Legal Owner davet mailinde ek

Legal Owner rolüne özel bir vurgu: bu rol şirketin dış hukuk müşaviri olarak veya iç kadrolu avukat olarak alınabilir. Retainer sözleşmesi hazırlanabilir. Bu rolün kabul talebi + KVKK ihlal riski bilgilerine öncelik verilmelidir.

### DPO davet mailinde ek

100+ çalışan / 25M TL ciro / özel nitelikli veri işleyen şirketler için DPO ataması **kanunî zorunluluk** olduğunu belirt. Aday KVKK Kurul sertifikalı ise özellikle vurgula.

### Reveal Officer davet mailinde ek

Bu rol **kanunî ifşa süreç sahibi**. TCK Md.257 kapsamında görev suistimali suçu sorumluluğu vardır. Charter'daki 4-göz gate'i + muhbir kimlik gizliliği maddesini özellikle vurgula. Ayrıca:
- Reveal Officer #1 ve #2 aynı departmandan olamaz
- Kendi departmanıyla ilgili bildiriye erişim yasak (conflict of interest)

### On-Call Engineer davet mailinde ek

Vardiya bonusu / callout ödemesi / comp time konusunu net anlat. Business Owner ile koordine ol. Telefon 24×7 açık olmak zorunda.

---

## Follow-up template (7 gün sonra cevap gelmezse)

**Konu**: [HATIRLATMA] Faz 35 Etik Speak `<ROL>` kabul talebi — cevap bekleniyor

Sayın `<Ad>`,

`<TARIH>` gönderdiğim Etik Speak `<ROL>` kabul talebine henüz cevap alamadım. Kanal 2026-07-22'den beri LIVE ve kalıcı imzasız her geçen gün hukuki risk büyüyor.

Lütfen 3 gün içinde cevap verin:
- Kabul edecekseniz → 3 yöntemden birini seçin
- Reddedecekseniz → ret gerekçesi bildirin, alternatif adayı düşüneyim
- Ek zaman lazımsa → deadline'ı 7 gün daha uzatabilirim

Saygılarımla,
`<Owner>`

---

## Rejection response template

**Konu**: Faz 35 Etik Speak `<ROL>` kabul reddi — teşekkür + alternatif arayış

Sayın `<Ad>`,

`<ROL>` teklifimi reddettiğinizi bildirmişsiniz — anlıyorum, teşekkür ederim. Alternatif adayla süreç devam eder.

**Not**: Sizi başka rol için düşünmek isterim (`<farklı rol>`?). Uygun mu?

Saygılarımla,
`<Owner>`
