# Etik Speak — Aydınlatma Metni ve Gizlilik Bildirimi (KVKK + EU 2019/1937)

> **Yayın:** `https://ai.acik.com/privacy`
> **Sorumlu:** Acık A.Ş. (Veri Sorumlusu, KVKK Md.3(ç)) — VERBIS: [tescil no], adres, e-posta, telefon
> **Kabul tarihi:** [ES-311 imzalar sonrası; ES-313 real reporter open tarihi]
> **Sürüm:** v1.0 (`noticeVersion=v1` backend zorunlu alan — sürüm değişince eski receipt'ler yeniden gösterilir).

## 1. Kimler bu bildirimi okumalı?

Bu bildirim:

- **Bildirimde bulunanlar (whistleblower)** — Acık A.Ş.'ye etik ihlal, usulsüzlük, taciz, yolsuzluk veya diğer içsel/dışsal yasal-etik kural ihlalini bildiren gerçek kişiler.
- **Bildirimde adı geçen üçüncü şahıslar** — bildirim içeriğinde adı geçen çalışan, tedarikçi, müşteri veya diğer taraflar (KVKK Md.10 aydınlatma yükümlülüğü — bkz. §7 gecikme + istisna).

## 2. Hangi verilerinizi işleriz?

### 2.1 Anonim bildirim modu (default)

- **Bildirim içeriği** (özgür metin, kategori, tarih)
- **Ek dosyalar** (opsiyonel, malware tarama sonrası)
- **Access-secret** (256-bit rastgele; yalnız sizin cihazınızda saklanır — biz saklamaz, sadece hash'ini tutarız)
- **Bildirim zamanı** ve **kanal** (web/mobil)
- **Rate-limit için** IP hash (rate-limit süresi sonrası atılır)

**Kimlik verisi TALEP EDİLMEZ**. IP, cookie, e-mail, telefon, ad-soyad **toplanmaz**.

### 2.2 Gizli bildirim modu (opsiyonel, sonraki dilim)

- Anonim moddaki tüm veriler +
- **Sadece Reveal Officer + Legal counsel'ın erişebileceği** kimlik alanları (ad-soyad, iletişim, çalışan sicil no)
- Bu veriler **compartmentalized encryption** ile saklanır (KVKK Md.12 tedbir); staff/yönetici kimlik verilerini görmez, yalnız bildirim içeriğini görür.

### 2.3 İsimli bildirim modu (opsiyonel, sonraki dilim)

- Whistleblower kendi kimliğini staff'a açık olarak paylaşır.
- Yasal koruma tam olarak devam eder (EU 2019/1937 Art.19 retaliation yasağı).

## 3. Verilerinizi hangi hukuki gerekçeyle işleriz?

- **KVKK Md.5(2)(ç) hukuki yükümlülük** — İç Denetim Standartları, TİDE, Sarbanes-Oxley uyumlu whistleblowing kanalı bulundurma yükümlülüğü.
- **KVKK Md.5(2)(a) açık rıza** — İsimli bildirim modu tercihinde whistleblower'ın kendi rızası.
- **KVKK Md.5(2)(e) hukuki menfaat** — Etik ihlal soruşturması + delil koruma + hukuki takip.
- **EU 2019/1937 Art.9** — İç bildirim kanalı zorunluluğu (250+ çalışan işletmeler).

## 4. Verileriniz ne kadar saklanır?

| Veri türü | Saklama süresi | Yasal dayanak |
|---|---|---|
| Bildirim içeriği (anonim) | 5 yıl (case closure sonrası) | ISO 37002:2021 §8.6 + iç denetim standartları |
| Bildirim içeriği (gizli/isimli) | 5 yıl (case closure sonrası) — kimlik alanları ayrı silinebilir | KVKK Md.7 |
| WORM audit log | 10 yıl (immutable) | Sarbanes-Oxley Sec.802 + KVKK Md.7(2) |
| Ek dosyalar | Case ile aynı süre | (yukarı) |
| Access-secret hash | Case retention süresi + 1 yıl (fallback recovery) | Operasyonel |
| Basic-auth gate cookie | Session süresi (15 dk max) | Operasyonel |
| Rate-limit IP hash | 24 saat | Operasyonel |
| SLO/observability metrik | 90 gün | Operasyonel |
| Alertmanager log | 1 yıl | Operasyonel + audit |
| Legal reveal request log | 10 yıl (WORM) | KVKK Md.28 + hukuki takip |

Detay: `docs/legal/faz35-retention-policy.md`

## 5. Verileriniz kimlere aktarılır?

- **İç Denetim / Etik Kurulu** (yalnız case erişim yetkisi olan staff)
- **Hukuk müşavirliği** (yasal reveal veya soruşturma sürecinde)
- **Bağımsız denetim** (SOX/ISO/audit — anonimleştirilmiş)
- **Kolluk kuvvetleri / mahkeme** (yalnız yargı kararı ile, `RB-faz35-legal-reveal-request.md` prosedürü ile)

**Verileriniz ticari üçüncü şahıslara SATILMAZ.**
**Verileriniz reklamcılık, profilleme, otomatik karar için KULLANILMAZ.**

## 6. Whistleblower korunması (EU 2019/1937 Art.19)

Etik Speak üzerinden bildirim yapmanız nedeniyle karşı karşıya kalabileceğiniz misilleme (retaliation) — işten çıkarma, terfi engeli, ücret indirimi, disiplin cezası, sosyal dışlanma vb. — **yasal olarak yasaktır**. Böyle bir durumla karşılaşırsanız:

- Etik Speak `Bildirimi takip et` yoluyla ek bildirim yapabilirsiniz.
- Türkiye İş Kurumu (İŞKUR) + Türkiye İş Sağlığı Bakanlığı'na başvurabilirsiniz.
- Uluslararası düzeyde: EU Whistleblower Protection Directive'e dayalı Türkiye tarafındaki karşılık düzenlemeler.
- **Reveal Officer size retaliation koruması yazılı olarak hatırlatır.**

## 7. Haklarınız (KVKK Md.11 + GDPR Art.15-22)

- **Bilgi alma hakkı** — hangi verilerinizin işlendiğini öğrenebilirsiniz (`Bildirimi takip et`).
- **Düzeltme hakkı** — bildirim gövdesindeki hataları düzeltebilirsiniz (Reveal Officer koordinesinde).
- **Silme hakkı (unutulma hakkı)** — Case closure sonrası retention süresi bitiminde otomatik silme; öncesinde talep KVKK Md.7 istisna kuralları ile değerlendirilir.
- **İtiraz hakkı** — otomatik karar / profilleme yapılmıyor.
- **Şikayet hakkı** — KVKK: [kvkk.gov.tr/BasvuruIslemleri](https://www.kvkk.gov.tr) — Ombuds: [tbmm.gov.tr](https://www.tbmm.gov.tr).

**Anonimlik hakkı** — Bildirim modunda anonim kalırsanız, kimlik açığa çıkarma yalnız §8'de sayılan hukuki gerekçelerle mümkündür.

## 8. Anonimlik + reveal koşulları

**Anonimliğiniz** yalnız aşağıdaki hukuki-etik gerekçelerle geri alınabilir (bkz. `docs/runbooks/RB-faz35-legal-reveal-request.md`):

- **Yargı kararı** (mahkeme veya savcılık) — CMK Md.135 benzeri.
- **Bilinçli sahte bildirim** — iç soruşturma sonucu, kişilere iftira etmek amacıyla yapıldığı kanıtlanırsa.
- **Whistleblower'ın kendi yazılı rızası**.
- **Hayati tehlike** — whistleblower veya üçüncü şahıslar için.

Reveal ceremony:
- **3 imza gerekli**: Reveal Officer + Legal counsel + Business owner.
- **WORM audit log** (immutable) her reveal event'i tamperproof kayıt eder.
- **TTL max 60 dakika** — grant sonrası otomatik reseal.
- **Reveal edildikten sonra bile Art.19 retaliation koruması devam eder.**

## 9. Bildirim içeriği güvenliği

- **TLS 1.2+** her bağlantıda.
- **Sertifika**: `*.acik.com` wildcard, Sectigo (public CA).
- **Basic-auth gate** test döneminde sentetik veri koruması; production'da kaldırılır.
- **Session cookie**: `__Host-etik_mailbox` — Secure + HttpOnly + SameSite=Strict + 15 dakika TTL.
- **Backend erişim ayrımı** (compartmentalization): Reporter mailbox verileri + staff case yönetimi + Reveal Officer identity alanları ayrı schema + ayrı encryption key.
- **Vault-managed** DB parolaları + AppRole rotation.
- **NetworkPolicy** — servisler arası yalnız beklenen ingress/egress trafiği.
- **OpenFGA authz** — case erişim kararı fail-closed; explicit-deny + effective-deny testli.
- **Backup encryption** — off-site + retention pinning.

## 10. İletişim

Veri sorumlusu:

- **Kurum**: Acık A.Ş.
- **VERBIS tescil no**: [tescil no]
- **Adres**: [posta adresi]
- **E-posta (KVKK aydınlatma)**: [kvkk@acik.com]
- **KVKK / DPO**: [dpo@acik.com]
- **Reveal Officer** (Faz 35 whistleblowing): [reveal-officer@acik.com] — yalnız yasal reveal talepleri için.
- **Emergency contact** (7/24): [security-oncall@acik.com]

## 11. Sürüm ve değişiklikler

Bu aydınlatma metnini KVKK / EU 2019/1937 mevzuat güncellemeleri veya iç politika değişimleri gerektirdiğinde revize ederiz. Değişimler `noticeVersion` alanı arttırılır (backend). Eski `noticeVersion` ile açılan mailbox oturumlarında yeni sürüm gösterilir; kabul etmezseniz eski bildiriminizin yasal koruması **devam eder**.

**Değişiklik log**:
- v1.0 ([ES-313 real reporter open tarihi]) — İlk yayın; test-only phase sonrası.
