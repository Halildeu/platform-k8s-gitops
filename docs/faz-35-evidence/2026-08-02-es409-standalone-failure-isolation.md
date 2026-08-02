# ES-409 — Tek başına satış: arıza izolasyonu ve paylaşılan çekirdek artık riski (2026-08-02)

> Etik Speak tek başına satılabilir bir ürün (ADR-0049). O zaman alıcının soracağı soru
> şudur: **"Yalnız Etik Speak'i alırsam, ihbarcımın rapor bırakabilmesi için başka neyin
> ayakta olması gerekiyor?"**
>
> Bu belge o soruyu ölçülmüş cevaplarla yanıtlar. ES-308 (#2667) *diğer ürünlerin* Etik
> hücresini düşüremediğini kanıtladı; burada eksik kalan yarısı var: **paylaşılan çekirdek
> düşerse ne olur.**

## 1. Kısa cevap

| yol | dayandığı paylaşılan bileşen |
|---|---|
| **İhbarcı yolu** (rapor bırak, makbuz al, posta kutusunu aç) | **kenar (ingress) + kendi veritabanı**. Başka hiçbir şey. |
| **Personel yolu** (davaları gör, cevap yaz) | yukarıdakiler + Keycloak + permission-service + OpenFGA |
| **Ek dosya yolu** | yukarıdakiler + nesne deposu (MinIO) + tarayıcı |

İhbarcının rapor bırakabilmesi için gereken paylaşılan yüzey **iki bileşene** iniyor. Bu
tasarım gereğidir, ölçüldü, ve tek başına satışın çekirdek iddiası budur.

## 2. Hücre bağımsız dağıtılıp geri alınabiliyor (yapısal)

Her ürün üst overlay'de **ayrı bir satır**:

```
- activation/ats-interview-evidence
- activation/etik-speak
- activation/keycloak-sms-otp
- activation/cross-ai-deployment-protection-observe
```

Tek satırı kaldırmak tam olarak o ürün hücresini kaldırır; komşu ürünlerin render'ı
değişmez. Etik aktivasyonu ayrıca **7 iş yükünün 7'si için de** replica yaması taşıyor
(`ethics-service`, `etik-speak-public`, `etik-speak-manager`, `ethics-evidence-worker`,
`ethics-cdr-worker`, `clamav`, `heic-converter`) — yani hücrenin tamamı için kill-switch
mevcut, ve `heic-converter` bugün fiilen `0` replika ile bu mekanizmanın çalıştığını
gösteriyor (ES-306'da karantinaya alındı).

## 3. Ölçülmüş etki matrisi (ES-308, canlı TEST hücresi)

| paylaşılan bileşen düştüğünde | ihbar alımı | personel erişimi |
|---|---|---|
| **permission-service** (yetki) | `201` ✅ | `403` — fail-closed |
| **Keycloak** (kimlik) | `201` ✅ | geçerli token `200` (önbellekli JWK); **sahte token `401`** |
| **OpenFGA** (yetki düzlemi) | `201` ✅ | hiç dava dönmüyor |
| **notification-orchestrator** | `201` ✅ + kuyruğa alınır, iyileşince boşalır | — |
| **diğer 18 ürün** | etkisiz — **yapısal olarak ulaşılamaz** | etkisiz |

Kimlik sağlayıcı kesintisinde geçerli token'ın kabul edilmesi **açık değil dayanıklılıktır**
(JWK seti süreç içinde önbellekli); kritik olan sahte token'ın hâlâ reddedilmesidir.

## 4. Artık risk — dürüstçe

Yukarıdaki tabloda görünmeyen, **ihbarcı yolunu gerçekten düşürebilecek** paylaşılan
bileşenler şunlardır. Bunlar "sınırlandırıldı" değil, **kabul edilmiş** risklerdir:

| artık risk | etki | bugünkü azaltıcı |
|---|---|---|
| **Paylaşılan PostgreSQL örneği** | Etik kendi şemasına sahip ama sunucu paylaşımlı; örnek düşerse veya gürültülü komşu doyurursa **ihbar alımı durur** | ES-309 yedek/geri yükleme; ayrı şema + ayrı kimlik; kaynak kotası |
| **Tek kenar (ingress-nginx + host nginx)** | tüm ürünlerin tek giriş noktası; kenar düşerse ihbarcı ürüne hiç ulaşamaz | ES-309 SLO/alarm kapsamı |
| **Keycloak + permission-service + OpenFGA** | üçü de düşerse **personel** davalara erişemez; ihbar alınmaya devam eder ama **kimse okuyamaz** | fail-closed davranış ölçüldü; SLA ağı (#3271) süre uyarısı verir |
| **Nesne deposu (MinIO)** | ek dosyalı ihbar yolu durur; **metin ihbarı çalışmaya devam eder** | ek yolu ayrı arıza alanı (ES-104G) |
| **Tarayıcı tanım yaşı** | tanımlar imajla geliyor, yaşı ölçülmüyor | #3354 |

**En önemli cümle:** bir yetki/kimlik kesintisinde ihbar **alınmaya devam eder ama
okunamaz.** İhbarcı açısından bu sessiz bir arızadır — raporunu bıraktığını görür, kimsenin
bakamadığını görmez. EU 2019/1937'nin 7 günlük alındı teyidi süresi bu sırada işlemeye
devam eder. SLA ağı (`SLA_APPROACHING` / `SLA_BREACH`) bu boşluğun bugünkü karşılığıdır;
uzun bir yetki-düzlemi kesintisinde süre uyarıları birikir.

## 5. Bu belge neyi kanıtlamaz

- **Canlı browser/rollout matrisi çalıştırılmadı.** ES-409'un kabulü bunu da istiyor; burada
  yapılan yapısal bağımsızlık kanıtı + ES-308'in ölçülmüş arıza matrisi + artık risk
  dokümantasyonu. Ürün hücresinin fiilen bağımsız deploy/rollback edildiği bir tatbikat
  ayrı iştir.
- **Yalnız TEST hücresi.** Prod topolojisi ayrı kapı (ES-310/312) ve orada paylaşım
  sınırları farklı olabilir (dual-host cutover).
- Paylaşılan PostgreSQL'in gürültülü-komşu davranışı **ölçülmedi** — yalnız yapısal
  paylaşım tespit edildi.

## 6. Ticari okuma (özet)

Tek başına satın alan bir müşteri için dürüst cümle şudur:

> İhbarcının rapor bırakabilmesi kenara ve Etik'in kendi veritabanına bağlıdır. Kimlik ve
> yetki düzlemleri düştüğünde ihbar alınmaya devam eder; ekibin okuyabilmesi için o
> düzlemlerin ayakta olması gerekir. Diğer ürünlerin arızası Etik hücresine ulaşamaz —
> bu ağ katmanında yapısal olarak kapalıdır, tercihe bağlı değildir.
