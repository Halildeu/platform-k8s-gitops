# remote-write-bridge — test→prod-hub Prometheus remote_write auth köprüsü

> gitops#1459 (Codex 019ebacc REVISE absorb). Test cluster metriklerinin prod-hub
> Grafana'da görünmesini sağlayan zincirin host-compose halkası.
> Mimari özet: compose dosyasının baş yorumunda.

## Neden bu şekil

- ADR-0002 §3.8: tek Grafana prod-hub'da; test → prod **remote_write** push modeli.
- k3d-test ve k3d-prod AYRI docker bridge'lerde (iptables isolation) — doğrudan
  erişim yok. Prod node'unu test ağına bağlamak REDDEDİLDİ (Codex: node'un tüm
  portları test yüzeyine açılır). Bu köprü yalnız `POST /api/v1/write` taşır.
- Receiver auth'suz (Prometheus native auth yok) → **basic auth bu katmanda**.
  Risk modeli veri okuma değil observability-integrity (label spoof,
  cardinality DoS) — bkz #1459 plan comment'i.

## Kurulum (staging-sw, ~5 dk)

```bash
cd /home/halil/platform-k8s-gitops/host-compose/remote-write-bridge

# 1. Parola üret + htpasswd yaz (apr1; alpine nginx destekler)
mkdir -p secrets && chmod 700 secrets
PW="$(openssl rand -base64 24 | tr -d '=+/' | head -c 32)"
printf 'rw-test:%s\n' "$(openssl passwd -apr1 "$PW")" > secrets/htpasswd
# Bind-mount uid tuzağı (canlı 2026-06-12): nginx worker uid 101 — host'ta
# 600/halil bırakılırsa container'da open() 13 Permission denied → her auth
# denemesi 500 döner. Sahipliği worker uid'ine ver:
sudo chown 101:101 secrets/htpasswd && sudo chmod 400 secrets/htpasswd

# 1b. Loki push AYRI parola + loki.htpasswd (gitops#1462 — Codex S1 izolasyon)
LPW="$(openssl rand -base64 24 | tr -d '=+/' | head -c 32)"
printf 'loki-test:%s\n' "$(openssl passwd -apr1 "$LPW")" > secrets/loki.htpasswd
sudo chown 101:101 secrets/loki.htpasswd && sudo chmod 400 secrets/loki.htpasswd

# 2. Vault'a seed — Prometheus (username/password) + Loki (loki_username/loki_password)
#    AYNI path, AYRI key (ESO promtail-loki-auth bu key'leri okur)
VT=$(jq -r .root_token /home/halil/bootstrap-drill/vault-init-test.json)
printf '%s' "$PW" | docker exec -i -e VAULT_TOKEN="$VT" platform-vault-test \
  vault kv put kv/platform/remote-write-bridge username=rw-test password=- >/dev/null
printf '%s' "$LPW" | docker exec -i -e VAULT_TOKEN="$VT" platform-vault-test \
  vault kv patch kv/platform/remote-write-bridge loki_username=loki-test loki_password=- >/dev/null
unset VT PW LPW

# 3. Başlat
docker compose up -d
docker compose ps   # healthy beklenir
```

## Loki ingestion (gitops#1462) — promtail + prod Loki NodePort

```bash
# prod Loki NodePort (bridge backend) + test promtail (STT-only dar scrape)
kubectl --context k3d-prod apply -k kustomize/base/monitoring-prod-hub        # loki-push-nodeport 30100
kubectl --context k3d-test  apply -k kustomize/base/monitoring-test-only      # promtail-loki-auth ESO
helm upgrade --install promtail grafana/promtail --version 6.16.6 \
  --kube-context k3d-test -n monitoring \
  -f helm-values/promtail/values-test-loki-bridge.yaml
# acceptance: prod Loki {cluster="test",app=~"audio-gateway"} + 01c Q1/Q3 LogQL +
# public ai.acik.com/loki/api/v1/push → 404 (Loki'ye ULAŞMAMALI)
```

## Doğrulama (acceptance negatif kanıtları dahil — #1459)

```bash
# healthz (auth'suz 200)
curl -s http://172.19.0.251:9091/healthz

# auth'suz POST → 401 (negatif kanıt 1)
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://172.19.0.251:9091/api/v1/write

# yanlış parola → 401 (negatif kanıt 2)
curl -s -o /dev/null -w '%{http_code}\n' -X POST -u rw-test:wrong http://172.19.0.251:9091/api/v1/write

# doğru auth + boş gövde → backend'e ulaşır (400/204 sınıfı; 401 DEĞİL)
curl -s -o /dev/null -w '%{http_code}\n' -X POST -u "rw-test:$PW" http://172.19.0.251:9091/api/v1/write

# kök path → 404 (yüzey daraltma)
curl -s -o /dev/null -w '%{http_code}\n' http://172.19.0.251:9091/
```

## Rotasyon

1. Yeni parola üret → `secrets/htpasswd` yeniden yaz → `docker compose exec remote-write-bridge nginx -s reload`
2. Vault `kv/platform/remote-write-bridge` güncelle → ESO refresh (1h; hızlandırma:
   `kubectl --context k3d-test -n monitoring annotate externalsecret remote-write-bridge-auth force-sync=$(date +%s) --overwrite`)
3. Test Prometheus yeni Secret'i otomatik okur (operator config-reloader).

## Kalıcılık notu

`docker network connect` YOK — iki bacak da compose network tanımıyla gelir;
`docker compose up -d` reboot/recreate sonrası aynı topolojiyi kurar
(restart: unless-stopped). Drift kontrolü: `docker inspect
platform-remote-write-bridge` iki network + .251 pin.

## Zincirin diğer halkaları

- Prod NodePort 30090: `kustomize/base/monitoring-prod-hub/prometheus-remote-write-nodeport.yaml`
- Prod receiver: `helm-values/kube-prometheus-stack/values-prod.yaml` `enableRemoteWriteReceiver: true`
- Test D19 Service+Endpoints + ESO: `kustomize/base/monitoring-test-only/`
- Test remoteWrite + basicAuth: `helm-values/kube-prometheus-stack/values-test.yaml`
