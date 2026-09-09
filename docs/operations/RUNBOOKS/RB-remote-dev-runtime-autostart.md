# RB — Remote DEV runtime autostart (issue #3586)

Tetik: `/srv/platform-dev` uzak DEV ortamında runtime container'ları `Exited (128)`
durumunda ve `docker compose up -d` şu hatayı veriyor:
`runc create failed: container's cgroup is not empty: N process(es) found`.

## Tarihsel arıza ve güncel durum

İlk olayda live-restore ile yaşayan süreçler varken daemon runtime dizini
korunmuyordu. Yeni daemon konteynerleri Exited olarak görürken süreçler dolu
cgroup'larda kalıyor ve runc yeniden yaratmayı reddediyordu. Bu gözlem
`live-restore: true` ayarının tek başına her yeniden başlatmada arıza ürettiği
anlamına gelmez.

`RuntimeDirectoryPreserve=yes` sonrasında bu arıza tekrar üretilemedi.
Aşağıdaki unit'in güncel rolü otomatik compose başlangıcıdır; yetim temizliği
yalnız Docker'ın çalışmıyor bildirdiği, dolu cgroup'u olan konteynerler içindir.
Sağlıklı restart testi, gerçek yetim öldürme yolunun pozitif testi değildir.

## Kalıcı düzeltme

`bootstrap/host/platform-dev-runtime.service` kurulur ve etkinleştirilir:

```bash
sudo install -m 0755 -o root -g root \
  bootstrap/host/clear-orphan-cgroups.sh \
  /srv/platform-dev/ops/clear-orphan-cgroups.sh
sudo install -m 0644 -o root -g root \
  bootstrap/host/platform-dev-runtime.service \
  /etc/systemd/system/platform-dev-runtime.service
sudo mkdir -p /etc/systemd/system/platform-dev-docker.service.d
sudo install -m 0644 -o root -g root \
  bootstrap/host/platform-dev-docker.service.d/runtime-autostart.conf \
  /etc/systemd/system/platform-dev-docker.service.d/runtime-autostart.conf
sudo systemctl daemon-reload
sudo systemctl enable --now platform-dev-runtime.service
```

Unit root olarak çalışır (cgroup.kill root gerektirir), daemon soketini bekler,
yetim cgroup'ları temizler ve compose yığınını başlatır. Daemon'a eklenen
`Wants=` drop-in'i sayesinde daemon her başladığında bu unit de başlatılır.

## Yetim temizliği yalnız Docker'ın çalıştırmadığı container'a dokunur

İlk sürümde temizlik satır içi bir kabuk döngüsüydü ve iki ayrı kusuru vardı.

**Kusur 1 — sessiz ölü kod.** Boşluk kontrolü `[ -s "$cg/cgroup.procs" ]` idi.
cgroupfs altındaki dosyalar her zaman 0 boyut raporlar, bu yüzden test cgroup
dolu olsa bile daima yanlış döner. Canlı ölçüm: `stat -c %s cgroup.procs` = 0
iken gerçek süreç sayısı 1. Sonuç olarak temizlik hiçbir zaman çalışmadı;
unit'in kurtarma etkisi yalnız `docker compose up -d` adımından geliyordu.

**Kusur 2 — sağlıklı container'ı kesme riski.** Seçim `docker ps -aq` üzerindeydi
ve container'ın çalışıp çalışmadığına bakmıyordu. Boşluk kontrolü düzeltilseydi
seçim, PostgreSQL ve SQL Server dahil 18 sağlıklı container'ın tamamını
kapsayacaktı. Ölçülen değer: düzeltilmiş boşluk kontrolüyle aday sayısı 18.

`bootstrap/host/clear-orphan-cgroups.sh` ikisini birden kapatır. Bir baytlık
okuma ile gerçek boşluk kontrolü yapar ve yalnız `State.Running` değeri `false`
olan container'lara dokunur. `--dry-run` seçeneği hiçbir süreci durdurmadan neyi
seçeceğini yazar.

Kuru çalışmayı doğru izole daemon ortamıyla başlat:

```bash
sudo env DOCKER_HOST=unix:///run/platform-dev/docker.sock \
  /srv/platform-dev/ops/clear-orphan-cgroups.sh --dry-run
```

Ortam değişkeni olmadan sudo altında varsayılan Docker soketi seçilebilir;
0/0 sonucu 18 konteynerin kontrol edildiği anlamına gelmez.

Sağlıklı sistemde ölçülen sonuç:

```
orphan_cgroups=0 skipped_running_containers=18 dry_run=1
```

## Sonlandırma kolu doğrulaması

`RuntimeDirectoryPreserve=yes` sonrası gerçek yetim arızası yeniden üretilemediği
için, betiğin **fiilen süreç sonlandıran** kolu canlı yığın üzerinden
gözlemlenemez. O kolu test edilmemiş bırakmak, kurtarmanın kritik yarısını
doğrulanmamış bırakmak demektir.

`bootstrap/host/test-clear-orphan-cgroups.sh` bu boşluğu kapatır. Sahte bir
`docker` (betiğin `DOCKER` değişkeni üzerinden enjekte edilir) tek bir container
bildirir; gerçek bir cgroup içinde gerçek bir `sleep` süreci tutulur. Hiçbir
gerçek container'a dokunulmaz.

```bash
sudo bootstrap/host/test-clear-orphan-cgroups.sh
```

İki durum birlikte sınanır, çünkü yalnız öldüren bir kurtarma yolu hiç
öldürmeyen kadar yanlıştır:

| Durum | Beklenen | 2026-09-08 ölçümü |
|---|---|---|
| `State.Running=false` + dolu cgroup | süreç sonlandırılır | `orphan_cgroups=1`, süreç öldü |
| `State.Running=true` + dolu cgroup | dokunulmaz | `skipped_running_containers=1`, süreç yaşıyor |

Test çıktısı `reported_size=0` satırıyla cgroupfs boyut tuzağını da her koşuda
yeniden gösterir: dosya doludur ama bildirilen boyut sıfırdır.

Koşum sonrası canlı yığın etkilenmedi: 18 container `running`, artık test
cgroup'u yok, PostgreSQL süreç kimliği değişmedi, Keycloak realm 200.

## Arızanın kendisi ayrıca kapatıldı

`platform-dev-docker.service` üzerine `RuntimeDirectoryPreserve=yes` eklendikten
sonra daemon yeniden başlatması artık yetim süreç bırakmıyor. 2026-09-08 ölçümü:
yapılandırma yeniden üretilip daemon yeniden başlatıldıktan sonra 18 container
`running`, `exited` 0, yetim aday sayısı 0 ve PostgreSQL süreç kimliği
değişmedi. Bu unit'teki temizlik artık ikincil bir savunma katmanıdır; birincil
işlevi daemon açılışında yığının ayakta olmasını garanti etmektir.

## Kurtarma bir başlatma yolu olmalı, durdurma yolu değil

Bu unit'in ilk sürümünde `PartOf=platform-dev-docker.service` ve
`ExecStop=docker compose stop` vardı. Bu kombinasyon ters etki yaptı: daemon her
yeniden başladığında systemd durdurmayı yayıyor, unit tüm yığını kapatıyor ve
hiçbir şey geri başlatmıyordu. Bu ilişki kaldırıldı. Ancak 2026-09-08 20:38
kaydı Codex'in planlı soğuk testiyle örtüşür: stop 20:37:22–20:38:08,
compose up 20:38:18, doğrulama 20:40:34. O kaydı kendiliğinden oluşmuş bir
kesintinin tek başına kanıtı olarak kullanmayın.

Şimdiki tasarımda `PartOf=` ve `ExecStop=` yoktur. Kurtarma yalnız başlatma
yoluyla olur: daemon başlar, `Wants=` bu unit'i tetikler, unit yetim cgroup'ları
temizleyip compose yığınını ayağa kaldırır. `Wants=` (Requires değil) seçilmiştir,
böylece runtime hatası daemon'un kendisini bloke etmez.

## Doğrulama

Doğrulama elle compose çağrısı içermemelidir; aksi halde otomatik kurtarma değil,
elle toparlama ölçülmüş olur.

```bash
sudo systemctl restart platform-dev-runtime-config.service
sudo systemctl restart platform-dev-docker.service
sleep 150   # elle compose komutu yok
DOCKER_HOST=unix:///run/platform-dev/docker.sock docker ps --format '{{.Names}} {{.Status}}'
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:33081/realms/platform-dev
```

Ölçülen sonuç (2026-09-08): 18 container `Up`, `exited` 0, Keycloak realm `200`,
`platform-dev-runtime.service` `active`. Hiçbir elle adım atılmadı.
Uçtan uca giriş kanıtı: `node /srv/platform-dev/ops/verify-remote-dev-browser.cjs`.

## Rollback

```bash
sudo systemctl disable --now platform-dev-runtime.service
sudo rm /etc/systemd/system/platform-dev-runtime.service
sudo rm /etc/systemd/system/platform-dev-docker.service.d/runtime-autostart.conf
sudo systemctl daemon-reload
```

Referans: issue #3586, #3582.

---

# Ek — DEV hosttan k3d-test / k3d-prod erişimi (issue #3586)

aiserver üzerindeki k3d API sunucuları yalnız `127.0.0.1:6443` (prod) ve
`127.0.0.1:7443` (test) dinler; DEV host onlara doğrudan ulaşamaz.

## Kurulum

1. DEV hostta ayrılmış anahtar (`~/.ssh/id_ed25519_platform_dev`) üretilir ve
   açık anahtarı aiserver'da `aiadmin` kullanıcısının `authorized_keys` dosyasına
   eklenir. Ekleme öncesi dosyanın zaman damgalı yedeği alınır.
2. DEV hostun `~/.ssh/config` dosyasına `aiserver` girdisi eklenir.
3. `bootstrap/host/platform-dev-k8s-tunnel.service` kurulur:

```bash
sudo install -m 0644 -o root -g root \
  bootstrap/host/platform-dev-k8s-tunnel.service \
  /etc/systemd/system/platform-dev-k8s-tunnel.service
sudo systemctl daemon-reload
sudo systemctl enable --now platform-dev-k8s-tunnel.service
```

4. Güncel kubeconfig aiserver'dan alınır (DEV hostun eski kopyası farklı bir CA'ya
   aitti ve `x509: certificate signed by unknown authority` veriyordu):

```bash
cp ~/.kube/config ~/.kube/config.bak-$(date +%Y%m%d-%H%M%S)
ssh aiserver 'cat ~/.kube/config' > /tmp/kubeconfig.new
install -m 600 /tmp/kubeconfig.new ~/.kube/config && rm -f /tmp/kubeconfig.new
```

Yerel port numaraları kubeconfig'deki adreslerle aynı olduğu için dosyada
adres düzenlemesi gerekmez.

## Doğrulama

```bash
kubectl --context k3d-test -n platform-test get pod
kubectl --context k3d-prod -n platform-prod get pod
sudo systemctl kill platform-dev-k8s-tunnel.service && sleep 15
systemctl is-active platform-dev-k8s-tunnel.service
```

Ölçülen sonuç: k3d-test 29 Running + 4 Completed, k3d-prod 15 Running +
3 Completed, iki düğüm de `Ready`. Tünel öldürüldükten sonra `Restart=always`
ile 15 saniye içinde geri geldi ve kubectl yeniden çalıştı.

## Rollback

```bash
sudo systemctl disable --now platform-dev-k8s-tunnel.service
sudo rm /etc/systemd/system/platform-dev-k8s-tunnel.service
sudo systemctl daemon-reload
# aiserver'da:
cp ~/.ssh/authorized_keys.bak-<damga> ~/.ssh/authorized_keys
```

## Birleşik paket üzerinde bağımsız yeniden kontrol

2026-09-08 18:38:13Z: yalnız daemon restart, elle compose yok; runtime unit
InvocationID değişti. 18/18 konteyner kimliği, süreç kimliği ve image aynı;
PostgreSQL/MSSQL PID'leri korundu. Backend, frontend, OIDC, gerçek browser
login/reload, profil kalıcılığı ve varyant akışı yeniden geçti.
Kanıt: `/srv/platform-dev/evidence/recovery-20260908/pr3590-autostart-retest.json`.
Bu, gerçek yetim süreç arızasının yeniden üretildiği veya fiziksel makinenin
reboot edildiği iddiası değildir.

## Test düzeneği başarısızlığı başarı sayılmaz

İlk testte sudo/cgroup hazırlığı başarısız olduğunda iki case SKIP dönüyor,
ancak genel sonuç ALL PASS ve exit 0 oluyordu. Bu, sudo'yu hata döndüren bir
shim ile değiştirerek yeniden üretildi: iki SKIP, sıfır PASS, exit 0.
Düzeltilmiş sürüm iki case'in gerçekten çalışmasını zorunlu tutar; kurulum,
süreci taşıma ve helper hatası testi başarısız yapar. Cgroup kimlikleri her
koşumda benzersizdir ve cleanup yalnız o koşumun oluşturduğu grupları temizler.

Bağımsız tekrar: iki gerçek süreç/cgroup case'i PASS; eksik sudo case'i
nonzero ve ALL PASS yok. 18 canlı konteynerin PID'leri değişmedi, test cgroup'u
kalmadı. Bu sentetik Docker-state + gerçek kernel sonlandırma kanıtıdır;
doğal bir Docker orphan olayının yeniden oluştuğu iddiası değildir.
Özel kanıt: `/srv/platform-dev/evidence/killpath-review-20260908/fixed-result.json`.
