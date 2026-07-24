# Faz 35 Etik Speak — aiserver canlı kapalı-döngü kabulü

> Tarih: 2026-07-23 16:12 Europe/Istanbul
>
> Kapsam: ES-1, yalnız `platform-test`, sentetik veri
>
> Runtime authority: `10.9.10.15` (`aiserver`)
>
> Tracked by: #2660
>
> Browser-driver düzeltmesi: `platform-web` commit
> `0cc6bbe92ed8a280b6c96a46f98cbff7cc9c1d7b`, PR #990

## Sonuç

`etik.acik.com`, `speakup.acik.com` ve `testai.acik.com/ethic` kullanılarak
kapalı-döngü müşteri yolculuğu aynı `.15` runtime üzerinde tamamlandı.

Canlı Playwright sonucu:

```text
2 passed (31.5s)
```

Trace, video ve screenshot kapalı tutuldu. Ham sentetik parola, bearer token,
receipt ID veya mailbox access secret evidence'a yazılmadı. Persona secret
dosyaları yalnız `.15` üzerinde
`/srv/platform/secrets/faz35-test/` altında invoking-user-owned mode `600`
olarak tutuldu ve ephemeral test container'ına read-only bağlandı.

## D29 kanıtı

### Up

`k3d-test/platform-test`:

| Deployment | Ready | Immutable image |
|---|---:|---|
| `ethics-service` | 1/1 | `sha256:f8fe0cd588c99ef78848bb4e0200d1268e0a4d6c6afc8599812dc7c18657db53` |
| `etik-speak-public` | 1/1 | `sha256:b9a9e8b1bc0e60bd63f8f469f418f2d9b227dbdb86d199ee38502b47298c7b2f` |
| `etik-speak-manager` | 1/1 | `sha256:ab9b55a52f1cca362d6d69c548e1e9f038e69c07ded468adfee28c1a43c133da` |

Pod `imageID` değerleri deployment digest'leriyle birebir eşleşti.

### Functional

İki public kanal için ayrı sentetik journey tamamlandı:

1. Public UI gerçek tarayıcıyla açıldı.
2. Anonim bildirim oluşturuldu ve kalıcı receipt/access-secret gösterildi.
3. Receipt diğer public hostta kullanılamadı; kanal bağlama fail-closed kaldı.
4. Ayrı `/ethic` manager UI'sine sentetik yetkili persona ile giriş yapıldı.
5. Yönetici aynı yeni vakayı UI listesinde açtı.
6. Atama ve `NEW -> IN_REVIEW` geçişi kaydedildi.
7. İç not ve reporter-visible staff yanıtı oluşturuldu.
8. Reporter mailbox staff yanıtını gördü; iç notu görmedi.
9. Reporter yanıt yazdı.
10. Sonraki yetkili manager aynı kalıcı reporter yanıtını okudu.
11. Mailbox logout tamamlandıktan sonra eski cookie ile okuma `404` oldu.

Ek protokol kontrolleri:

- public Basic Auth beklenmedi; gerçek açık reporter kontratı kullanıldı;
- eksik payload, geçerli `Idempotency-Key` ile `400`;
- aynı payload replay `200` ve `idempotentReplay=true`;
- aynı key + farklı payload `409`;
- suite-cookie credential confusion `400`;
- stale `If-Match` ikinci yazımı `412`;
- iki public host aynı artifact bytes ve güvenlik başlıklarını verdi;
- HSTS bir yıl, CSP default self, cache no-store ve yalnız `no-referrer`
  referrer policy değerleri doğrulandı.

### Zanzibar-ready

- Manager tokenında `aud=ethics-manager`,
  `scope=ethics:case:manage`, realm role `ethics-manager` ve beklenen test org
  birlikte doğrulandı.
- Yetkili persona yeni vakayı okuyup işledi.
- Wrong-org persona listeyi boş gördü.
- OpenFGA-denied persona aynı vaka için existence sinyali almadan `404` gördü.

## `.15` migration düzeltmeleri

Canlı kabul öncesi Faz 35 operasyon yüzeyinde iki eski-host drift'i bulundu:

- preflight SSH hedefi hâlâ `halil@staging-sw` idi;
- sentetik persona dosyaları artık var olmayan
  `/home/halil/bootstrap-drill/` yoluna sabitlenmişti.

Bu değişiklik preflight'i `aiserver` SSH aliasına, persona secret dosyalarını
`/srv/platform/secrets/faz35-test/` köküne taşır. Keycloak uzlaştırması
`.15` üzerinde yeniden çalıştırıldı; üç persona için audience/scope/org/role
kontratı geçti. Production realm, production secret veya `k3d-prod` Etik Speak
workload'u değiştirilmedi.

## Tekrarlanabilir doğrulama

- Faz 35 provisioning sözleşmesi: `43/43 PASS`
- Değişen Faz 35 kabuk programları: `shellcheck -x PASS`
- Browser driver exact source SHA-256:
  `8d25590f17cd302d688da395f4909e40c3c7a72ae7d68ef7c02debee02ac23f8`
- `.15` canlı ve salt-okunur aktivasyon preflight'i:
  - edge TLS/HTTP: iki public host için `PASS`
  - OpenFGA persona/tuple/allow/deny/recusal: `PASS`
  - Vault/ESO ve OpenFGA bağımlılıkları: `PASS`
  - kota ve bounded-repair kapasitesi: `PASS`
  - immutable render, root binding ve canlı kaynak sayımı: `PASS`

Preflight sonucu yalnız deployment hazırlık kanıtıdır; yukarıdaki gerçek
tarayıcı yolculuğunun veya production kabulünün yerine geçmez.

## Sınır

Bu kanıt ES-1 TEST kapalı-döngü kabulüdür. ES-3 production pilotu, gerçek PII,
production Etik Speak workload'u, Legal/DPO/secret-owner imzası veya production
go-live yetkisi üretmez. Cross-AI kullanıcı tarafından açıkça istenmediği için
otomatik istişare açılmadı; test, live evidence ve insan production kapıları
ayrı kalır.
