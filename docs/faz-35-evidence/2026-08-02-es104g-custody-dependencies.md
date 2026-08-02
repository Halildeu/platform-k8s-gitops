# ES-104G — Ek dosya saklama bağımlılıkları ve değişmez promosyon (2026-08-02)

> Kapsam: Etik Speak canlı **test hücresinde** ek dosya saklama zincirinin bağımlılıkları.
> Sorulan: promosyon gerçekten değişmez mi, API ile işçi gerçekten ayrı kimlikler mi,
> tarayıcı gerçekten dış dünyadan kopuk mu, ve bunların hangisi **kaza eseri** doğru?

## Özet

| kabul maddesi | durum | kanıt |
|---|---|---|
| Tam, değişmez imaj digest'leri | ✅ | dört imaj digest-pinli; ES-306 kapısı her koşumda taze çeker |
| Ayrı API / işçi kimlikleri | ✅ **ama kırılgandı** | ayrı ServiceAccount + ayrı secret; sıraya bağımlılık invaryantla sabitlendi |
| Tarayıcı public ingress'siz | ✅ | `clamav` Service yalnız `clamd:3310`, ingress yalnız hücre içi |
| Tarayıcı internet egress'siz | ✅ | `clamav` NetworkPolicy egress kural sayısı **0** |
| Sabitlenmiş tarayıcı artefaktı/kuralları | ✅ | digest-pinli imaj + imajla gelen tanımlar |
| Sınırlı backlog metrikleri | ✅ | `ethics_evidence_pipeline_backlog_entries`, `..._pending_total` |
| Ayrı arıza alanları | ✅ | API / işçi / tarayıcı ayrı Deployment, ayrı SA, ayrı NetworkPolicy |

Bir de kapatılamayan bir görünürlük boşluğu çıktı: **tarayıcı tanım yaşı ölçülmüyor**
([#3354](https://github.com/Halildeu/platform-k8s-gitops/issues/3354)).

## Bulgu 1 — ayrım gerçekti, ama onu tutan şey bir liste sırasıydı

API ve işçi ayrı MinIO kimlikleri alıyor. Ama iki secret **aynı anahtar adlarını**
kullanıyor (`ETHICS_EVIDENCE_S3_ACCESS_KEY` / `_SECRET_KEY`) ve işçi ikisini birden
`envFrom` ile alıyor. `envFrom`'da çakışan anahtar **konuma göre** çözülür: son giren
kazanır.

Canlı ölçüm (değerler yazdırılmadan, yalnız sha256 ilk 12):

```
api-secret     = 9a79e5567b9a
worker-secret  = c9b33e0b1d19
worker-RUNTIME = c9b33e0b1d19   → işçi KENDİ kimliğini kullanıyor
```

Doğru — **ama yalnızca kendi secret'ı listede sonuncu olduğu için**. Sıra elle, bir
merge'le ya da bir biçimlendiriciyle değişse işçi sessizce API kimliğiyle koşardı:
hata yok, log satırı yok, düşen probe yok — ve "ayrı API/işçi kimlikleri" kabulü
hiçbir belirti vermeden yanlış olurdu.

Bu yüzden ayrım artık render üzerinden **invaryantla** tutuluyor
(`test_worker_object_store_identity_is_not_decided_by_list_order`). İddianın ısırdığı
ayrıca doğrulandı: sıra ters çevrildiğinde test düşüyor.

## Bulgu 2 — tarayıcı dış dünyadan kopuk; bunun görünmeyen bedeli var

`clamav` NetworkPolicy'si `policyTypes: [Ingress, Egress]` taşıyor ve **egress kural
sayısı sıfır** — yani tüm dışa çıkış kapalı. `freshclam` güncelleme yapamaz; tanımlar
imajla gelir (`daily.cvd` vb. hepsi 30 Tem 22:30 = imaj tarihi).

Bu bilinçli ve doğru: düşman girdisini ayrıştıran bileşenin dışa hattı olmamalı, ve
sabit tanım yeniden üretilebilir tarama demek. ES-104G'nin "pin scanner artifact/rules"
maddesiyle birebir.

Bedeli şu: **tanım yaşı sessizce büyür.** Altı ay eski tanımlarla çalışan ClamAV da
10 dakikada bir `SelfCheck: Database status OK` yazar ve taramaya devam eder — yalnızca
daha azını yakalar. Servis hiç metrik yayımlamıyor (`clamd:3310` dışında port yok,
Prometheus'ta `clamav*` serisi yok) ve etik-speak kurallarında tarayıcıya dair kural yok.

ES-306'da EICAR ile kanıtlanan şey tarayıcının **çalıştığıydı**; tanımlarının **güncel**
olduğu değil. İkisi farklı sorular ve ikincisi şu an ölçülmüyor → #3354.

## Bulgu 3 — arıza alanları fiilen ayrı

| iş yükü | ServiceAccount | ağ |
|---|---|---|
| `ethics-service` (API) | `ethics-service` | ingress: edge; egress: DB, KC, authz, notify, MinIO |
| `ethics-evidence-worker` | `ethics-evidence-worker` | ingress: **yalnız Prometheus scrape**; egress: DNS, DB, MinIO, clamav, dönüştürücü |
| `clamav` | `clamav` | ingress: hücre içi; egress: **yok** |
| `ethics-cdr-worker` | `ethics-cdr-worker` | ayrı |

İşçinin **istek yüzeyi yok**: namespace'e ulaşan bir saldırganın orada çalacağı bir uç
bulunmuyor. Tarayıcının ise dışarı çıkacak hattı yok.

## Bulgu 4 — provenance: üç birinci-taraf imajın üçünde de var

Hat cosign kullanmıyor; GitHub'ın yerel `actions/attest-build-provenance` adımını
kullanıyor. Doğru araçla sorgulandığında (attestation API — imaj çekmeye gerek yok):

| imaj | attestation |
|---|---|
| `platform-backend-ethics-service` | **1** |
| `platform-web-etik-speak-public` | **1** |
| `platform-web-etik-speak-manager` | **1** |
| `clamav` (üçüncü taraf) | **yok** (404 — beklenen) |

`ethics-service` attestation'ının içeriği:

```
predicateType : https://slsa.dev/provenance/v1
subject       : sha256:602df6a9affc8c3f...   (overlay'de pinli digest ile aynı)
buildType     : https://actions.github.io/buildtypes/workflow/v1
builder       : Halildeu/platform-backend/.github/workflows/ci-image-push.yml@refs/heads/main
repository    : https://github.com/Halildeu/platform-backend
```

Yani pinlenen digest'in **kanonik depodaki main dalından, kanonik iş akışıyla** üretildiği
kanıtlı. `platform-ssot` hattından gelen bir imaj bu kontrolü geçemezdi.

Üçüncü-taraf tarayıcı imajında attestation yok ve olması da beklenmiyor — oradaki güvence
digest sabitleme + ES-306 zafiyet kapısı.

## Neyi kanıtlamaz

- Yalnız **test hücresi**. Prod ayrı kapı (ES-310/312).
- Üçüncü-taraf `clamav` imajının **GitHub attestation'ı yok** (bizim hattımız üretmiyor);
  oradaki güvence digest sabitleme + ES-306 zafiyet kapısıyla sınırlı.
- Tanım tazeliği ölçülmedi ve şu an ölçülemiyor (#3354) — yalnız tanımların *sabit*
  olduğu ve *nereden geldiği* kanıtlandı.
