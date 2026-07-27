# Faz 35 — personel ucunun açılması ve çift-host kapalı döngü

**Tarih:** 2026-07-27 · **Ortam:** k3d-test / `platform-test` · **Kapsam:** ES-203, ES-208, ES-210 (#2662)

Bu belge o gün çalışan hücreden alınan ölçümleri kaydeder. İddia edilen hiçbir şey ölçülmemiş değildir; ölçülmemiş olanlar açıkça "kanıtlanmadı" başlığı altındadır.

---

## 1. Çift-host kapalı döngü (#2662)

`speakup.acik.com` = TEST → org …0003 · `etik.acik.com` = CANLI → org …0001

```
1. ihbar (speakup.acik.com)
   HTTP 201, receiptId 8039576d-5af1-48e0-95e1-26c35ed1a14e

2. canlı kanal izolasyonu
   org …0001 dava sayısı: 138 -> 138   (değişmedi)

3. yönetici davayı görüyor (testai.acik.com)
   konu  : Cift-host kapali dongu dogrulamasi 20260726T223055Z
   durum : NEW | mod: ANONYMOUS | kategori: WORKPLACE_CONDUCT

4. yönetici yanıtı
   HTTP 201  {"authorType":"STAFF","visibility":"REPORTER_VISIBLE"}

5. ihbarcı posta kutusu (speakup.acik.com)
   oturum 200, posta kutusu 200
   - STAFF | REPORTER_VISIBLE | "Bildiriminiz alindi ve inceleniyor."
```

Yetki ayrımı:

```
kimliksiz çağrı                       -> 401
ETHIC=MANAGE olmayan persona (d35-3)  -> 401
case_viewer, kendi org'u  (…0003)     -> True
case_viewer, CANLI org    (…0001)     -> False
```

---

## 2. Personel ucunu tıkayan dört kusur

Her biri bir öncekini gizliyordu.

| kusur | belirti | düzeltme |
|---|---|---|
| Sağlama betiği verilmeyen rolü "atandı" diye raporluyordu; token iç adresten alınıyordu; `frontend` istemcisinde doğrudan erişim kapalıydı | 401, sebebi token'ı işaret ediyordu | gitops #2952 |
| user-service yetki-revizyonunu kimliksiz soruyordu | `/api/v1/users` **500**, iki pod da Ready | backend #940 |
| O düzeltme yanlış kimliği gönderdi | 500 aynen sürdü, testler yeşildi | backend #941 |
| Yönetici OpenFGA'da ürün üyeliği tutmuyordu | liste **200 `[]`** | gitops #2959 |

Ölçülmüş kimlik matrisi (`GET /api/v1/authz/version`):

```
kimliksiz                -> 401
X-Internal-Api-Key       -> 401
çağıranın bearer token'ı -> 200 {"authzVersion":234}
```

`X-Internal-Api-Key`'i okuyan filtre üç nedenle bu yolda hiç devreye girmiyor: `@Profile({"local","dev"})`, yalnız `/api/v1/internal/**` ile eşleşiyor, ve legacy bayrağı kapalıyken zinciri ilk satırda geçiyor.

**En sinsi olan sonuncusuydu:** org …0003'te 21 dava vardı, liste boştu, hiçbir log'da hata yoktu. Boş dizi "bu org'da dava yok" ile ayırt edilemez.

Not: `ethics-service` **kendi** OpenFGA store'unu kullanıyor (`01KXYKEB…`), paylaşımlı platform store'unu değil. Paylaşımlı store'da `ethics_product`/`ethics_case` tipleri hiç yok; oraya bakan biri "model kurulmamış" sonucuna varır.

---

## 3. ES-203 — çekilme beyanı

Yaptırım zaten canlıydı; eksik olan beyandı.

```
başlangıç              22 dava listeleniyor, hedef detay 200
recusal                21 dava listeleniyor, hedef detay 404
recusal kaldırıldı     22 dava listeleniyor, hedef detay 200
```

404 (403 değil): reddediş davanın varlığını doğrulamamalı.

`POST /api/v1/ethics/cases/{id}/recusal` → **204**, defterde tek kayıt:

```
ethics.case.recusal.declared
{"actorHash":"5c2c1b9a…","selfDeclared":true}
```

Tekrar davranışı, aralarında temizlik olmadan ölçüldü:

```
birinci POST  204
ikinci POST   404
defter        declared, sayı +1
```

İlk beyan davayı görüşten çıkardığı için ikinci çağrı 404 alıyor. İlk sürümdeki `recusal.repeated` olayı bu yüzden **erişilemezdi**; backend #943 ile kaldırıldı.

---

## 4. ES-208 — bildirim outbox / retry / DLQ

**Kesinti ihbarı bozmuyor.** Alıcı yetkisi düzeltilmeden önceki pencerede:

```
işlenen dava    : 154
bildirim durumu : DELIVERED 3 | DEAD_LETTER 18
```

**İçerik sızıntısı yapısal olarak imkânsız.** Etik outbox şemasında gövde/konu/dava-kimliği alanı yok:

```
id org_id event_type status created_at attempt_count next_attempt_at
claim_token locked_until delivered_at last_error_code
```

Metnin yaşadığı yer olan teslim edilmiş bildirimde:

```
konu  : "Etik bildirim kuyruğunda yeni işlem"
gövde : "…Ayrıntıları yalnızca Etik Speak yönetici ekranından görüntüleyin."

karşılaştırılan ihbar konusu    : 113
bildirim metninde bulunan       : 0
bildirim metnindeki UUID sayısı : 0
```

Sıfır UUID, "case-independent correlation" şartının doğrudan karşılığı.

**Kurtarma gerçek birikimle kanıtlandı.** 24 Temmuz'dan beri mahsur 20 bildirim:

```
GET  /dead-letters          -> {"count":20,"oldest":"2026-07-24T07:45:52Z"}
POST /dead-letters/requeue  -> {"requeued":20,"limit":50}

defterden okundu:
  outbox                 DEAD_LETTER 20 -> 0 | DELIVERED 8 -> 28
  notification_delivery  DELIVERED 20 (son 45 dk)
  notification_inbox     20 yeni satır  (son 45 dk)
```

Üç bağımsız tabloda tutuyor.

---

## 5. Bu belge neyi kanıtlamıyor

- **Üretim hazırlığı.** Hepsi test hücresi ölçümü.
- **ES-203'ün tamamı.** Kendi kendine çekilme çalışıyor; `subject_ref`, üçüncü-kişi çakışma beyanı ve reveal-approver dışlaması açık (backend #944/#945/#946).
- **#2662 kapısı.** Gövdesindeki altı bloktan biri (ES-208) kapandı; kapı hâlâ Blocked.
- **backend #943 ve #947'nin canlı ölçümü.** #943 istenen durumda ama iç ağ erişimi koptuğu için kümeye uygulanamadı; #947 henüz merge olmadı.

---

## 6. Kapsam dışı bulgular (düzeltilmedi, kaydedildi)

- **#2955** — board kanıt yazıcısı iki repoda iki aydır sessizce düşüyor (`ADD_TO_PROJECT_PAT` reddediliyor). Merge kapısı olmadığı için fark edilmeden birikti.
- **#2958** — `RemoteAuthzVersionProvider` dört serviste kimliksiz çağırıp 401'i `debug` seviyesinde yutuyor ve **bayat revizyon** döndürüyor; "revizyon bilinmiyor"u "değişmedi" saymak, geri alınmış bir yetkinin yaşamaya devam etmesi demek.
- **#2963** — `/api/v1/users` isteği user-service pod'unun tamamını ~5 s durduruyor, **farklı porttaki sağlık ucu dahil**: dairesel çağrı (user-service → permission-service → user-service) + `ActiveProcessorCount=1` ile tek sanal-iş-parçacığı taşıyıcısı.
