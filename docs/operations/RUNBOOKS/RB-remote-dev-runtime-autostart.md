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
