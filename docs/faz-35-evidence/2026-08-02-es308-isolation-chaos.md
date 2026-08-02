# ES-308 — İzolasyon kaos testi (2026-08-02)

> Kapsam: Etik Speak'in canlı **test hücresi**. Sorulan soru, ihbarcının bağlı olduğu
> vaattir: platformun geri kalanı kötü bir gün geçirirken ihbar **alınmaya ve
> saklanmaya** devam ediyor mu, ve personel erişimi bir bağımlılık düştüğünde
> **kapanarak mı** yoksa açılarak mı arızalanıyor?
>
> Koşum: `scripts/faz35/verify-test-isolation-chaos.sh` (aiserver üzerinde).
> Ham kanıt: `docs/faz-35-evidence/isolation-chaos-latest.json` (redakte —
> yalnız HTTP kodları ve toplam sayaçlar; hiçbir token, makbuz, dava kimliği
> veya ihbarcı değeri yok).

## Özet

| senaryo | ihbar alımı (public) | personel erişimi | karar |
|---|---|---|---|
| taban | `201` | `200` (198 dava) | — |
| **yetki servisi** (permission-service) düştü | `201` | **`403`** | fail-closed ✅ |
| **kimlik sağlayıcı** (Keycloak) düştü | `201` | geçerli token `200`; **sahte token `401`** | imza doğrulaması açılmadı ✅ |
| **yetki düzlemi** (OpenFGA) düştü | `201` | **`504`** — hiç dava dönmedi | veri sızmadı ✅ / yavaş ⚠️ |
| **bildirim** (notification-orchestrator) düştü | `201` + posta kutusu `200` | — | kayıp yok ✅ |
| diğer 18 ürün | — | — | **yapısal olarak ulaşılamaz** ✅ |

Tatbikat boyunca komşu ürünlerin tamamı `Ready` kaldı ve tatbikat sonrası hiçbir
kaos politikası geride kalmadı.

## Yöntem — bir NetworkPolicy tek başına kesinti *simüle etmez*

Bu, testin geçerliliğini belirleyen ve ölçümle bulunan noktadır.

İlk denemede Calico `Deny` uygulandı ve personel yolu **20 saniyeden uzun süre `200`
dönmeye devam etti**. Politika çalışmıyor değildi: JDK HTTP istemcisi sıcak bir
keep-alive bağlantısı tutuyordu ve conntrack kurulu akışın devam etmesine izin
veriyor. Kesinti ancak kurulu akışlar da temizlendiğinde gerçek oldu.

İkinci tuzak: conntrack kaydındaki hedef **Service ClusterIP'sidir** (kayıt DNAT
öncesi oluşur). Pod IP'siyle silmeye çalışmak **sıfır kayıt siler** — ve bu, çalışan
ama silecek bir şey bulamamış bir kesintiyle birebir aynı görünür.

Bu yüzden enjeksiyon **`Deny` + ClusterIP anahtarlı conntrack flush**'tır. Bu koşuda
her senaryoda 1-2 akış silindi; yani kesintilerin hepsi fiilen ısırdı.

## Yapısal bağımsızlık — kırmadan kanıtlamak

"Kapattık, bir şey olmadı" zayıf bir kanıttır: belki de o an trafik yoktu.
Daha güçlüsü **hiç ulaşılamaz olmasıdır**. `ethics-service` namespace default-deny
altında kapalı bir egress izin listesiyle çalışıyor:

```
auth-service · notification-orchestrator · openfga · permission-service · user-service
```

Aynı namespace'teki diğer **18 ürün** (Meeting, Endpoint, ATS, denetim köprüsü vb.)
bu listede yok — dolayısıyla bir Meeting veya Endpoint arızası Etik hücresini
tanım gereği etkileyemez. Doğrulayıcı bu listeyi manifest'ten değil **canlı
NetworkPolicy'den** okur, yani birisi ileride yeni bir egress kuralı eklerse test
düşer.

## Reddin şekli — durum kodu değil, gövde

Dava listesi yolunda **red, boş listedir**: politika motoru okunamadığında
`EthicsAuthorization.gateFor` `DENY_ALL` döndürür ve uç nokta `200` ile **boş liste**
verir, `403` değil. Yalnız durum koduna bakan bir test bunu "erişim açık kaldı"
diye okurdu — tam tersi doğruyken.

Doğrulayıcı bu yüzden gövdeyi sayar. Ve tabanın **boş olmadığını** ayrıca doğrular:
taban zaten 0 dava dönseydi, kesinti sırasındaki 0 hiçbir şey kanıtlamazdı.

Kaynaktaki gerekçe bunu açıkça söylüyor: *"nobody is recused" is what an outage
looks like* — bir kesinti, "kimse çekilmemiş" gibi görünür ve tam da çekilmenin
saklamak için var olduğu davaları açar.

## Dayanıklılık — ihbar neden kaybolmuyor

`createReport` tek bir `@Transactional` içinde **yalnız kendi veritabanına** yazar;
bildirim ve denetim kayıtları senkron HTTP çağrısı değil, aynı işlem içinde yazılan
**outbox satırlarıdır**. Ölçüm bunu doğruluyor:

| ölçüm | kesinti öncesi | kesinti sırasında | sonra |
|---|---:|---:|---:|
| `ethics_notification_outbox_pending_entries` | 0 | 1 | **0** (boşaldı) |
| `ethics_notification_outbox_delivered_total` | 25 | — | 27 |
| `ethics_notification_outbox_dead_letter_entries` | 0 | — | **0** |

Ve asıl kanıt sayaç değil: bildirim servisi düşükken alınan ihbarın **makbuzu
kesintiden sonra posta kutusunu açtı** (`200`). Yani ihbar yalnız `201` almadı,
kalıcı oldu.

> Ölçüm notu: sabit 45 saniyelik pencere iki koşuda iki farklı sonuç verdi
> (yeniden deneme geri çekilmesi nerede olduğuna göre). Doğrulayıcı artık
> boşalana kadar sınırlı yoklama yapıyor — "kuyruğa alındı" ancak **boşalıyorsa**
> kabul edilebilir.

## Bulgu — OpenFGA istemcisinde okuma zaman aşımı yok (P2)

Yetki düzlemi kesintisinde personel isteği **hiç cevap vermedi**; kenar 90 saniyede
`504` üretti. Yeni bağlantı kurulması gereken durumda ise çağrı ~43 saniyede
bağlanma hatasıyla düşüyor ve yakalanıp fail-closed'a çevriliyor.

Kök sebep: `common-auth`'taki `OpenFgaProperties` **hiçbir zaman aşımı alanı
taşımıyor** ve `OpenFgaAuthzService` HTTP istemcisine zaman aşımı vermiyor —
yani kurulu bir soket üzerindeki istek süresiz bekler. Karşılaştırma:
`EthicsEntitlementVerifier` açık bir `PT3S` zaman aşımıyla çalışıyor ve
kesintide anında `403` döndü.

**Güvenlik etkisi yok** — hiçbir dava sızmadı, kapı kapalı kaldı. Etkisi
operasyonel: personel net bir "yetki servisi kullanılamıyor" yerine bir ağ geçidi
hatası görüyor, ve arıza 90 saniye sürüyor.

Kaskad riski ayrıca ölçüldü ve **doğrulanmadı**: kesinti sırasında 14 eşzamanlı
personel isteği asılıyken ihbar alımı `201` dönmeye devam etti (bir ölçümde 23 sn
gecikmeyle, sonra normale döndü); `hikaricp_connections_active` 10'luk havuzda 7'de
kaldı. Sanal iş parçacıkları açık ve public alım yolunun kendi bulkhead'i var
(`publicIntake`, eşzamanlı 8) — ikisi birlikte ihbarcı yolunu personel tarafındaki
yığılmadan ayırıyor.

Takip: **[platform-backend#1070](https://github.com/Halildeu/platform-backend/issues/1070)**.

## Yan bulgu — bayat `smoke-client` sırrı (giderildi)

Tatbikatın ilk koşumu token basamadı (`401 unauthorized_client`). Sebep ürün değil,
`/srv/platform/secrets/faz35-test/smoke-client.secret` önbelleğinin Vault'taki
kanonik değerin gerisinde kalmasıydı. Aynı dosyayı `verify-test-openfga-authz.sh`
de kullandığı için o doğrulayıcı da sessizce kırıktı. Dosya Vault'tan tazelendi
(eski sürüm `.stale-<tarih>` olarak yedeklendi).

## Neyi kanıtlamaz

- **Yalnız test hücresi.** Prod hücresi ayrı bir kapıdır (ES-310/312).
- Ölçülen kesintiler **ağ seviyesindedir**. Bozuk-cevap, yavaş-cevap veya
  yarı-bozuk bağımlılık sınıfı ayrıca ele alınmadı.
- Yük altında davranış tek bir eşzamanlılık noktasında (14) ölçüldü; gerçek pilot
  yükü için kapasite testi ayrı iştir.
- Diğer ürün arızası **yapısal olarak** dışlandı; bu ürünler fiilen düşürülüp
  gözlenmedi (paralel oturumların ortamını bozmamak için — ve ulaşılamazlık zaten
  daha güçlü kanıttır).

## Yeniden üretim

```bash
ssh aiserver 'bash /srv/platform/gitops/platform-k8s-gitops/scripts/faz35/verify-test-isolation-chaos.sh'
```

Script her çıkış yolunda (Ctrl-C dahil) kaos politikalarını **önek üzerinden**
siler; tutulan tek isim üzerinden değil — çünkü geride kalan bir `Deny` hücreyi
bir sonraki kişi için kapatır.
