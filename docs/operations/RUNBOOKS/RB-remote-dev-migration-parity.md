# Remote DEV: mevcut gelistirme akisinin tasinmasi

12 Eylul 2026; takip: #3582, erisim #3710, registry #3712.

## Kapsam

Gelistirme makinesi Mac yerine `stagingsw` (`10.9.10.53`) olur.
Canonical kaynak repolar, GitHub CI/image build, GitOps TEST overlay ve
owner-gated PROD yayin akisi degismez. Yeni ekip izolasyonu veya branch
governance bu tasima icin yeni onkosul degildir.

Bu kayit bir production deploy veya tum urunlerin kabul testi degildir.
Sentetik DEV yolculugu ile TEST/PROD erisim kaniti ayri tutulur.

## DEV'den Normal Hostname Erisimi

Once: iki hostname public IP'ye cozuluyor, DEV'den HTTPS connect timeout
veriyordu. `--resolve` ile `10.9.10.15` uzerinden normal TLS dogrulamasi
geciyordu. DEV'in tanimli DNS sunucusu `10.9.10.1:53` de sorguya yanit vermedi.

Yalniz DEV `/etc/hosts` dosyasina eklenen kalici blok:

```text
# BEGIN platform-dev internal edge (GitOps #3710, 2026-09-12)
10.9.10.15 testai.acik.com ai.acik.com
# END platform-dev internal edge
```

Public DNS, NAT, `.15` servisleri veya cluster desired state degistirilmedi.
Bu DEV-local split resolution'dir; internetten public erisim testi degildir.
Hedef edge IP degisirse bu esleme de guncellenmelidir. `dig` hosts dosyasini
kullanmaz; uygulama cozumu `getent` ve normal URL ile kontrol edilir.

Kontrol (SSL bypass ve `--resolve` kullanilmaz):

```bash
getent ahostsv4 testai.acik.com ai.acik.com
curl --fail --silent --show-error --connect-timeout 5 --max-time 15 \
  --output /dev/null --write-out '%{http_code} %{remote_ip} %{ssl_verify_result}\n' \
  https://testai.acik.com
curl --fail --silent --show-error --connect-timeout 5 --max-time 15 \
  --output /dev/null --write-out '%{http_code} %{remote_ip} %{ssl_verify_result}\n' \
  https://ai.acik.com
```

Iki host: HTTP 200, remote IP `10.9.10.15`, TLS verify result 0.
TEST `platform-test` ve PROD `serban` realm OIDC discovery belgelerindeki
issuer ve auth/token endpoint'leri kendi HTTPS hostname'leriyle eslesti.
TEST `/api/users` anonim GET: 401 (fail-closed).
Headless Chromium iki normal URL'de Platform giris yuzeyini render etti ve
kurumsal giris komutuyla dogru realm'in parola formuna ulasti; hesaba girilmedi.
Ilk networkidle aninda SPA henuz bos oldugu icin render ayrica beklendi.
Bu sonuc kullanici hesabiyla TEST/PROD login veya urun kabul testi degildir.

Rollback: yalniz yukaridaki managed block'u kaldir. Orijinal yedek
`/etc/hosts.pre-platform-dev-20260912`; daha sonraki diger host kayitlarini
silmemek icin tum yedegi kosulsuz geri kopyalama. Rollback sonrasi eski
public-route kisitinin geri gelmesi beklenir. Host reboot gerekmiyor;
reboot/failover bu kontrolde uygulanmadi.

## GHCR Kimlik ve Artifact Kontrolu

Once: DEV Docker auth entry mevcuttu ama GitHub user API ile bu kimlik 401,
exact TEST meeting image manifesti denied donuyordu. Ayri `gh` oturumu kaynak
repo islemlerinde gecerliydi ancak package API icin `read:packages` eksikti.

Mevcut `k3d-test/platform-test/ghcr-pull` kimligi, owner eslesmesi ve
`read:packages` kapsami dogrulandiktan sonra DEV Docker'a aktarildi.
Kaynak ESO: `kv/gitops/ghcr-token`, `SecretSynced=True`.
Aktarim yalniz process memory ve `docker login --password-stdin` ile yapildi;
ham credential argv/chat/evidence/repo'ya yazilmadi.

Bu kimlik salt-okunur degildir. Mevcut OAuth yetkileri:
`gist`, `project`, `read:org`, `read:packages`, `repo`, `workflow`.
Yeni yetki verilmedi veya rotation yapilmadi; Vault/TEST/PROD kaynagi
degistirilmedi. Bu, DEV'e mevcut owner credential'inin
bir kopyasini ekler; bagimsiz read-only servis kimligi gibi sunulmaz.
Yerel Docker credential dosyasi sifreli vault degildir: base64 auth tutar.
`~/.docker/config.json` ve korunan orijinal yedegi
`~/.docker/config.pre-dev-parity-20260912.json` mode 0600'dur.
Diger Docker ayarlari ve registry kayitlari esitlik kontroluyle korundu.
`gh` CLI oturumu degistirilmedi; package API scope'u ayri kalir.

Dogrulanan exact artifact:

```text
ghcr.io/halildeu/platform-backend-meeting-service@sha256:45245558cec7e7c2801fdd6515932af7df5787cd5099e52433522758913d2fc1
```

Canli TEST Deployment image referansi, Docker manifest descriptor digest,
gercek `docker pull` sonucu ve lokal `RepoDigests` eslesti. Image indirildi;
DEV veya TEST workload'una bu image deploy edilmedi.
Rollback icin korunan yedekten yalniz `auths["ghcr.io"]` girdisi yapisal
olarak geri alinir; sonradan eklenen diger registry ayarlari korunur.
Bu rollback eski gecersiz kimligi geri getirir. Token revoke/rotation ayridir.

## Aktarim Disindaki 12 Dosya

Kaynak liste: `/srv/platform-dev/migration/evidence/exclusions-reviewed.json`.
Eski dosyalarin degerleri okunmadi; birebir secret parity iddiasi yoktur.

| Adet | Kaynak grubu | Gereken karsilik / mevcut sinir |
| --- | --- | --- |
| 2 | `platform-desktop/.env` ve eski Desktop worktree `.env` | Canonical Desktop `build/config/public-runtime-config.json` TEST public client/PKCE ve servis URL'lerini sagliyor; dev loader bunu cwd altindan okuyor. Public config/auth/meeting config testleri 55/55 gecti. Eski ozel override'lar birebir bilinmiyor; Electron native audio/GUI yolculugu burada test edilmedi. |
| 5 | `ao-kernel/.opencode/tmp/pytest-14` altinda 4 `.env`, 1 `id_rsa` | Test kodu yeniden uretir: chunker fixture dummy TOKEN; sanitizer fixture mock private-key marker. Gercek provider/private key tasima ihtiyaci degil. |
| 3 | Eski `autonomous-orchestrator/.env`, tarihli `.env.bak`, `.cache/ws_api_demo/.env` | Ornek schema OpenAI/Google/DeepSeek/Qwen API ve Kernel auth/HMAC ayarlarini tanimliyor. Bunlarin gercek degerleri veya yeni secret-store eslemesi unverified. Normal Platform web/backend build/yayin icin gerekli olduklari saptanmadi. Eski live-provider/demo akisini yeniden kullanirken ilgili secret kaynagi gerekir; CLI abonelik auth'u bu API key'lerin yerine gecmez. |
| 1 | `platform-agent-faz22-local-ci/tmp/actions-runner-parallels-w11/.env` | Mac/Parallels Windows pilot runner'ina ait. Linux DEV'e dosya kopyalamak bu runner'i tasimaz; workflow macOS/parallels/windows11 label'lari ister. GitHub runner listesinde bu runner yok. Normal hosted web/backend CI'den ayri, native pilot siniri. |
| 1 | Eski GitOps `host-compose/proxy/tls/wildcard-acik-com.key` | Eski edge'in TLS private key'i; DEV HTTPS istemcisine gerekmez, kopyalanmadi. Aktif `.15` edge iki hostname icin normal TLS dogrulamasini geciyor. Sertifika yenileme/rotation kabul testi yapilmadi. |

Runner eslemesinde ek gozlem: `platform-agent` kaydinda `aiserver-signing`
Linux signing runner'i offline gorundu. Imzali Windows yayin yolu ayri
triage gerektirir; bu turda runner veya signing credential'i degistirilmedi.

## Duzeltme Sonrasi DEV Kaniti

- 18 konteyner: running, sahiplik, image ve mount kontrolleri gecti.
- 25 HTTP kontrolu: 11 frontend, 13 backend health, 1 OIDC discovery gecti.
- Gercek sentetik DEV girisi + reload: user API 200/200, grid 16 satir,
  128 hucre, page error yok. Bu production verisi veya kullanici kabul testi degil.
- Desktop config testleri: 3 dosya / 55 test; kaynak repo temiz kaldi.
- Kanit dizini: `/srv/platform-dev/evidence/dev-delivery-audit-20260912/`.
  `post-fix-runtime.json` ve `platform-dev-audit-browser-20260912.json`.
- Ayni gun onceki backend/frontend test ve build kanitlari
  `REPORT.md` ve `MIGRATION-PARITY.md` icinde exact kapsamiyla korunur.

Mevcut Platform web/backend gelistirme, test ve GitHub'a gonderme akisinin
DEV-local erisim/registry farklari giderildi. Yeni TEST veya PROD dispatch
yapilmadi; production yayin kabul/onay kapilari mevcut mimaride kalir.
Tum Mac secret'lari, live-provider akislari, native uygulamalar veya eski
lokal Docker verileri birebir tasinmis gibi raporlanmaz.
