# aiserver — Faz 24 meeting-ai ready-consumer watchdog

## Neden

GPU host'taki meeting-ai, transcript-ready permit'i deploy edilen platform-ai
commit'iyle eşleşmediğinde açılışta reddedilir ve **8300 portu hiç açılmaz**.
Bunun tek izi bir log satırıdır (`[startup] Transcript-ready pre-enable permit
rejected`); ne alarm ne metrik vardır. 2026-08-04'te bu sessizlik saatlerce fark
edilmedi ve üç toplantı analizsiz kaldı (#3437, #3422).

Watchdog bu sessizliği duruma çevirir: mevcut WireGuard mTLS hop'u üzerinden
`/ready` okur, `ready_consumer` bayraklarını ve gecikmeyi kontrol eder,
**yalnız durum değiştiğinde** Teams Adaptive Card gönderir (her koşumda değil).

Salt-okunur: yalnız `kubectl get secret` (mTLS materyali) ve bir HTTPS GET.

## Kurulum (aiserver, root)

```bash
sudo install -m 0755 scripts/faz24/meeting-ai-consumer-watchdog.sh \
  /usr/local/sbin/meeting-ai-consumer-watchdog
sudo install -m 0644 bootstrap/host/aiserver-meeting-ai/meeting-ai-consumer-watchdog.service \
  /etc/systemd/system/
sudo install -m 0644 bootstrap/host/aiserver-meeting-ai/meeting-ai-consumer-watchdog.timer \
  /etc/systemd/system/
sudo mkdir -p /var/lib/platform
sudo systemctl daemon-reload
sudo systemctl enable --now meeting-ai-consumer-watchdog.timer
```

Doğrulama:

```bash
sudo systemctl start meeting-ai-consumer-watchdog.service
sudo journalctl -u meeting-ai-consumer-watchdog -n 20 --no-pager
systemctl list-timers meeting-ai-consumer-watchdog.timer
```

## Teams bildirimi (operatör ön koşulu)

Webhook dosyası yoksa watchdog **çalışmaya devam eder** ama bildirimi journal'a
yazar. Kartların gitmesi için Power Automate akış URL'i mode-0600 bir dosyaya
konur:

```bash
sudo install -d -m 0700 /srv/platform/secrets/alerting
# URL'i argv'ye YAZMA — stdin ile yaz:
sudo tee /srv/platform/secrets/alerting/teams-webhook.url >/dev/null
sudo chmod 0600 /srv/platform/secrets/alerting/teams-webhook.url
```

(Workspace kuralı gereği kanal Teams'tir; Slack yolu başka tenant'lar için
asset-preserved durur — ADR-0027/ADR-0029.)

## Ayarlar

Ortam değişkenleriyle geçersiz kılınabilir (service dosyasına `Environment=`
satırı eklenerek): `MAI_WATCHDOG_STATE`, `MAI_WATCHDOG_WEBHOOK_FILE`,
`MAI_WATCHDOG_CONTEXT`, `MAI_WATCHDOG_NAMESPACE`, `MAI_WATCHDOG_SECRET`,
`MAI_WATCHDOG_HOST`, `MAI_WATCHDOG_PORT`, `MAI_WATCHDOG_HOST_IP`,
`MAI_WATCHDOG_MAX_LAG`.

Alarm koştuğunda permit yenileme: `scripts/faz24/issue-transcript-ready-permit.sh`
(runbook: `docs/runbooks/RB-faz24-transcript-ready-legacy-pre-enable.md`).
