# RB — Remote DEV runtime autostart (issue #3586)

Tetik: `/srv/platform-dev` uzak DEV ortamında runtime container'ları `Exited (128)`
durumunda ve `docker compose up -d` şu hatayı veriyor:
`runc create failed: container's cgroup is not empty: N process(es) found`.

## Kök neden

`/etc/platform-dev/docker.json` içinde `live-restore: true` var.
`platform-dev-runtime-config.service` tmpfs yapılandırmasını yeniden ürettiğinde
`platform-dev-docker.service` yeniden başlar. Live-restore container süreçlerini
öldürmez, ancak yeni daemon durumu onları `Exited` sayar. Süreçler cgroup'larda
yetim kalır; cgroup boş olmadığı için `unless-stopped` yeniden başlatma politikası
container'ı yeniden yaratamaz. Runtime, kimse elle müdahale edene kadar kapalı kalır
(2026-09-06 → 2026-09-08 arası 46 saat kapalı kaldı).

## Kalıcı düzeltme

`bootstrap/host/platform-dev-runtime.service` kurulur ve etkinleştirilir:

```bash
sudo install -m 0644 -o root -g root \
  bootstrap/host/platform-dev-runtime.service \
  /etc/systemd/system/platform-dev-runtime.service
sudo systemctl daemon-reload
sudo systemctl enable --now platform-dev-runtime.service
```

Unit root olarak çalışır (cgroup.kill root gerektirir), daemon soketini bekler,
yetim cgroup'ları temizler ve compose yığınını başlatır. `PartOf=` sayesinde
daemon her yeniden başladığında birlikte hareket eder.

## Doğrulama

```bash
sudo systemctl restart platform-dev-runtime-config.service
sudo systemctl restart platform-dev-docker.service
sudo systemctl restart platform-dev-runtime.service
sleep 120
DOCKER_HOST=unix:///run/platform-dev/docker.sock docker ps --format '{{.Names}} {{.Status}}'
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:33081/realms/platform-dev
```

Beklenen: 14 container `Up`, `exited` sayısı 0, Keycloak realm `200`.
Uçtan uca giriş kanıtı: `node /srv/platform-dev/ops/verify-remote-dev-browser.cjs`.

## Rollback

```bash
sudo systemctl disable --now platform-dev-runtime.service
sudo rm /etc/systemd/system/platform-dev-runtime.service
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
