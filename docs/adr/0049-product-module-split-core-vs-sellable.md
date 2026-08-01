# ADR-0049 — Ürün ayrık satış sınırı: ortak zorunlu çekirdek vs satılabilir modüller

## Status

Accepted — 2026-08-01. Owner kararı (2026-08-01 sohbet): *"birebir mevcut altyapı
kullanılsın; etik uygulaması tek başına satılabilsin; ortak zorunlu modüller
kalacak yalnızca — tüm modüller için geçerli; ATS tek başına satılabilir,
endpoint aynı şekilde."* Bu ADR o kararın kanonik modül kataloğuna işlenmiş
hâlidir. Fiyatlandırma/SKU adlandırması bu ADR'nin kapsamı dışındadır.

**Owner issue:** [#3178](https://github.com/Halildeu/platform-k8s-gitops/issues/3178)

**İlgili:** [ADR-0046 ürün hücresi topolojisi](0046-faz35-etik-speak-product-cell-topology.md),
platform-backend `PermissionCatalogService` (kanonik modül kataloğu),
platform-web `apps/etik-speak-manager` (ilk ayrık-satış hücresi — kabuk
birleşmesi 2026-08-01'de canlıda kabul edildi)

---

## 1. Bağlam

Platform çok ürünlü: Etik Speak, ATS, Endpoint Yönetimi, Raporlama, Toplantı
Zekâsı ve diğerleri aynı altyapı üzerinde yaşıyor. Owner kararı iki şeyi aynı
anda istiyor:

1. **Tek altyapı.** Ayrık satılan ürün ayrı bir uygulama değildir — aynı kabuk,
   aynı tasarım sistemi, aynı kimlik, aynı yetkilendirme düzlemi. (Bunun tersi
   denendi ve reddedildi: etik-speak-manager kendi kabuğunu çizmişti, "başka
   bir uygulama gibi" görünüyordu; 2026-08-01'de suite kabuğuna hizalandı.)
2. **Her ürün ayrı satılabilir.** Etik Speak'i tek başına alan müşteri ATS'yi
   görmez; ama denetim izini, kullanıcı yönetimini, temayı **her zaman** alır.

Bu ikisinin kesişimi bir sınıflandırma sorusudur: kanonik katalogdaki hangi
modül *çekirdek* (her kurulumda var, ayrı fiyatlanmaz), hangisi *satılabilir*
(SKU sınırı)? Bugüne kadar bu sınıflandırma hiçbir yerde yazılı değildi.

## 2. Kanonik katalog (ölçüm, 2026-08-01)

Modül anahtarlarının tek kaynağı `PermissionCatalogService.MODULES`
(platform-backend, origin/main). 15 anahtar:

```
USER_MANAGEMENT, ACCESS, AUDIT, IMPERSONATION_AUDIT, REPORT, WAREHOUSE,
PURCHASE, THEME, SUGGESTIONS, ETHIC, ENDPOINT_ADMIN, MEETING, TRANSCRIPT,
INTERVIEW_EVIDENCE, ATS
```

Kabuktaki `ATS_PRODUCT_HUB_ENTRY` / `RECRUITER_WORKSPACE_ENTRY` /
`INTERVIEW_EVIDENCE_ENTRY` gibi anahtarlar katalog modülü **değildir** — kabuk
giriş kapılarıdır ve bu ADR'nin konusu olan SKU sınırını tanımlamaz.

## 3. Karar

### 3.1 Ortak zorunlu çekirdek — her kurulumda var, ayrı fiyatlanmaz

| modül | neden çekirdek |
|---|---|
| `ACCESS` | Yetki vermeden hiçbir ürün açılamaz |
| `USER_MANAGEMENT` | Kiracının kendi kullanıcısını yönetememesi kurulum değildir |
| `AUDIT` | Uyumluluk delili opsiyonel olamaz — Etik Speak'in yasal değeri denetim izinden gelir; `AUDIT`'i satın alınabilir yapmak ürünü savunulamaz kılar |
| `IMPERSONATION_AUDIT` | `AUDIT` sınırının kendisini koruyan bölme (AUDIT görücüsü impersonation olaylarını göremez); denetim çekirdekse onu koruyan bölme de çekirdektir |
| `THEME` | Çekirdekte değilse "ayrı uygulama gibi görünüyor" sorunu her ayrık satışta geri gelir — bu tam olarak yaşandı ve düzeltildi |

**Katalog anahtarı olmayan çekirdek altyapı** (modül değil, kurulumun kendisi):
kimlik (Keycloak/OIDC), yetkilendirme düzlemi (permission-service + OpenFGA),
kabuk (mfe-shell veya ürün hücresi), bildirim, Vault/ESO secret akışı.
schema-service de buradadır: satılan modül değil, `REPORT`'un altyapısıdır.

### 3.2 Satılabilir ürünler — SKU sınırları

| SKU | katalog modülleri | not |
|---|---|---|
| **Etik Speak** | `ETHIC` | İlk ayrık-satış hücresi; canlıda kanıtlı |
| **ATS** | `ATS` + `INTERVIEW_EVIDENCE` | Tek SKU, iki modül: aday takibi ile hassas mülakat kanıtı **bilinçli olarak ayrı** modüllerdir (recruiter işi yürütür, kanıta otomatik erişmez); ikisi de explicit-grant-only kalır (`PermissionModulePolicy`) |
| **Endpoint Yönetimi** | `ENDPOINT_ADMIN` | |
| **Raporlama** | `REPORT` | schema-service dahil (altyapı olarak, ayrı kalem değil) |
| **Toplantı Zekâsı** | `MEETING` + `TRANSCRIPT` | Tek SKU, iki modül |
| **Öneri ve Fikir** | `SUGGESTIONS` | |
| **Satın Alma** | `PURCHASE` | |
| **Depo** | `WAREHOUSE` | |

### 3.3 Ayrık kurulumun şekli

Ayrık satılan ürün = **çekirdek (§3.1) + o SKU'nun modülleri**, aynı kabuk
deseniyle. Ürün hücresi kendi navigasyonunda yalnız kendi rotalarını taşır
(etik-speak-manager'daki `FOREIGN_PRODUCT_PREFIXES` testi bu sınırın zorlama
desenidir ve yeni ayrık hücreler için şablondur). Modül-kapılı build değil,
**entitlement-kapılı çalışma zamanı**: her kurulum aynı imajları alır, kiracının
almadığı SKU'nun modülleri entitlement'ta yoktur ve kabuk o yüzeyleri çizmez.

### 3.4 Sınıflandırma makine-zorlamalı olacak

Bu tablo dokümanda kalırsa çürür. Uygulama dilimi (platform-backend, #885
entitlement işiyle birlikte): katalogdaki **her** anahtar `CORE` veya
`SELLABLE(sku)` olarak sınıflandırılır; sınıflandırılmamış yeni anahtar testi
kırar. Böylece kataloğa modül ekleyen kişi satış sınırı kararını atlayamaz —
karar vermek zorunda kalır, varsayılan yoktur.

## 4. Sonuçlar

**Olumlu.** "Etik'i tek başına sat" artık tanımlı bir işlemdir: çekirdek +
`ETHIC`. Aynı işlem ATS ve Endpoint için de tanımlıdır; ürün başına yeniden
tartışılmaz. Denetim izi hiçbir satış konfigürasyonunda eksik olamaz.

**Maliyet.** Çekirdek beş modül her kurulumda kurulur ve işletilir — en küçük
müşteri için bile. Bu bilinçli: çekirdeği küçültmenin tasarrufu, uyumluluk
delilsiz kurulum riskinin yanında anlamsız.

**Riskler.** §3.4 uygulanana kadar sınıflandırma yalnız bu dosyada yaşar; yeni
katalog anahtarı sessizce sınıfsız kalabilir. Bu boşluk #885 dilimi kapanana
kadar açıktır ve orada kapanır.
