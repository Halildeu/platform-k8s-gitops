# Etik Speak — Aydınlatma Metni ve Gizlilik Bildirimi TASLAĞI

> **Durum:** YAYINLANAMAZ TASLAK. Named Legal + DPO kabulü, versioned retention
> parametreleri ve production gate tamamlanmadan kullanıcıya sunulmaz.
>
> **Hedef yayın:** `https://ai.acik.com/privacy`
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

**Kimlik verisi TALEP EDİLMEZ**. IP, tracking/suite cookie, e-mail, telefon ve
ad-soyad **toplanmaz**. Reporter mailbox açıldığında yalnız host-only,
HttpOnly ve kısa ömürlü mailbox session cookie kullanılabilir; bu cookie
identity veya cross-subdomain tracking alanı değildir.
Kaynak IP yalnız edge'in volatile rate-limit durumunda anlık olarak kullanılabilir;
hash'lenmez, durable storage'a veya log/trace/metric label'a yazılmaz ve
case/receipt ile ilişkilendirilmez.

### 2.2 Gizli bildirim modu (opsiyonel, sonraki dilim)

- Anonim moddaki tüm veriler +
- **Sadece Reveal Officer + Legal counsel'ın erişebileceği** kimlik alanları (ad-soyad, iletişim, çalışan sicil no)
- Bu veriler **compartmentalized encryption** ile saklanır (KVKK Md.12 tedbir); staff/yönetici kimlik verilerini görmez, yalnız bildirim içeriğini görür.

### 2.3 İsimli bildirim modu (opsiyonel, sonraki dilim)

- Whistleblower kendi kimliğini staff'a açık olarak paylaşır.
- Yasal koruma tam olarak devam eder (EU 2019/1937 Art.19 retaliation yasağı).

## 3. Hukuki dayanak — Legal/DPO tarafından seçilecek

Bu ürün veya mühendislik belgesi müşteri adına hukuki dayanak seçmez. KVKK,
GDPR, EU 2019/1937, SOX veya başka bir düzenlemenin kuruma uygulanabilirliği;
veri sorumlusu, Legal ve DPO tarafından versioned policy içinde belirlenir.
Seçim yapılmadan production durable storage fail-closed kalır.

## 4. Verileriniz ne kadar saklanır?

| Veri türü | Saklama süresi | Yasal dayanak |
|---|---|---|
| Bildirim içeriği (anonim) | Named Legal/DPO versioned policy parametresi | Owner-supplied |
| Bildirim içeriği (gizli/isimli) | Named Legal/DPO versioned policy; identity ayrı parametre | Owner-supplied |
| WORM audit log | Named Legal/Audit versioned policy parametresi | Owner-supplied |
| Ek dosyalar | Ayrı attachment policy; varsayılan fail-closed | Owner-supplied |
| Access-secret verifier | Case policy sınırı içinde; ek fallback yılı yok | Operasyonel + owner policy |
| Public auth cookie | Yok | No-collect |
| Rate-limit IP/hash | Saklanmaz; yalnız volatile edge state | No-collect |
| SLO/observability metrik | Yalnız aggregate allowlist; owner-supplied kısa pencere | Operasyonel |
| Alert/incident kaydı | Narrative/identity/secret içermez; owner-supplied süre | Operasyonel + owner policy |
| Legal reveal request log | Yalnız confidential/named mod etkinse owner-supplied policy | Owner-supplied |

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

## 8. Anonimlik ve ayrı kimlik compartment'ı

Gerçek anonim modda reporter identity toplanmaz; bu nedenle ürün içinde sonradan
“reveal” edilebilecek bir kimlik kaydı yoktur. IP/UA/referrer/TLS metadata'sı da
kimlik yerine kullanılacak correlation alanı olarak tutulmaz.

Gelecekte confidential veya named mod açılırsa identity; narrative'dan ayrı
compartment, ayrı anahtar, ayrı OpenFGA ilişkileri ve named Legal/DPO owner
kararı gerektirir. Bu taslak herhangi bir reveal gerekçesi, imza sayısı, TTL
veya hukuki yetki üretmez; ilgili production policy ve runbook ayrıca accepted
olmadan identity storage refuse-to-store kalır.

## 9. Bildirim içeriği güvenliği

- **TLS 1.2+** her bağlantıda.
- **Sertifika**: `*.acik.com` wildcard, Sectigo (public CA).
- **Public erişim** hesap ve suite oturumu istemez; Basic Auth veya suite cookie
  public reporter credential'ı değildir.
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
