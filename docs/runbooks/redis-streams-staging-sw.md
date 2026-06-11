# RB — Redis Streams staging-sw Runtime (Faz 24 cross-server chunk transport)

> Faz 24 plan §6 TODO'sunun kapanışı (gitops PR #1289 satırı). Aşama-2 smoke
> ön şartı: platform-ai#151 → platform-ai#57 G8.
> Kontrat: platform-backend#534 (producer) + platform-ai#138 (consumer) +
> ADR-0031 D2 (topology) / D3 (resource pressure) / D8 (failure modes).

## Mimari (test plane)

```
web/mobile client ──HTTPS──▶ testai.acik.com /api/v1/audio-gateway (ingress)
                                   │
                          audio-gateway pod (k3d-test, platform-test ns)
                          JWT fail-closed → admit → XADD
                                   │ redis-streams:6379 (Service+Endpoints
                                   │  → 172.19.0.250 platform-test-net)
                          Redis Streams (host-compose, staging-sw)
                          audio:chunks:p00..p31 · group live-stt-v1
                                   │ staging-sw LAN IP :6379
                          live-stt consumer (GPU host, Windows)
                          STT_CHUNK_CONSUMER_ENABLED=true
```

- **Partition kontratı**: producer `hash(tenantId+sessionId) % 32` →
  `audio:chunks:p00..p31`; consumer XREADGROUP + `messageId`
  (`sessionId:chunkSeq`) dedup (Redis entry ID DEĞİL).
- **Init gerekmez**: stream'leri producer XADD yaratır; consumer group'u
  consumer `XGROUP CREATE mkstream` ile yaratır (BUSYGROUP tolere).
- **KVKK**: payload SHA-256 + routing metadata (raw audio/transcript YOK);
  persistence OFF — transport transient, kalıcılaşma ADR-0032 katmanında.
- **LAN-direct istisnası**: Aşama-2 smoke sabit test cümleleriyle koşar
  (synthetic fixture) → ADR-0031 D2 istisnası LAN-direct'e izin verir.
  **Gerçek meeting audio öncesi WireGuard + mTLS ZORUNLU** (operator gate).

## 1. Vault seed (bir kez)

```bash
# Parola üret (alphanumeric — Spring env interpolation safe) + Vault'a yaz
# D43 stdin-pipe: değer shell history/process list'e düşmez
ssh halil@staging-sw 'PW=$(tr -dc A-Za-z0-9 </dev/urandom | head -c 32); \
  printf "%s" "$PW" | VAULT_ADDR=http://127.0.0.1:8301 vault kv patch \
  kv/platform/audio-gateway-service redis_password=- && echo SEEDED'
```

Beklenen: `SEEDED`. ESO 1h refresh'le `audio-gateway-secrets` Secret'ını
oluşturur (anında zorlamak için: `kubectl --context k3d-test -n platform-test \
annotate externalsecret audio-gateway-secrets force-sync=$(date +%s) --overwrite`).

## 2. Redis compose up (staging-sw)

```bash
ssh halil@staging-sw
sudo mkdir -p /opt/platform/redis-streams
# compose dosyası: host-compose/redis-streams/docker-compose.yml (bu repo)
# .env: REDIS_PASSWORD=<adım 1'deki değer — Vault'tan oku, yeniden üretme:
#   VAULT_ADDR=http://127.0.0.1:8301 vault kv get -field=redis_password kv/platform/audio-gateway-service>
cd /opt/platform/redis-streams && docker compose up -d

# Doğrulama
docker exec platform-redis-streams-test sh -c 'redis-cli -a "$REDIS_PASSWORD" ping'   # PONG
docker inspect platform-redis-streams-test --format '{{.NetworkSettings.Networks.platform-test-net.IPAddress}}'  # 172.19.0.250
```

> IP `172.19.0.250` overlay Endpoints patch'iyle pin'li
> (`kustomize/overlays/test/kustomization.yaml` → `redis-streams`). Compose
> `ipv4_address` ile sabit — container recreate IP değiştirmez.

## 3. Gitops apply (selective — blast radius küçük)

```bash
# ESO (ExternalSecret audio-gateway-secrets)
kubectl --context k3d-test apply -k kustomize/overlays/test/eso

# App + host-bridge + netpol + ingress (full test overlay; D17 deprecated,
# replicas=1 default güvenli). Selective istenirse:
kubectl --context k3d-test -n platform-test apply -k kustomize/base/apps/audio-gateway
# + overlay images/replicas/Endpoints patch'leri için full overlay önerilir:
kubectl --context k3d-test apply -k kustomize/overlays/test
```

## 4. D29 verify

| Katman | Komut | Beklenen |
|---|---|---|
| Up | `kubectl --context k3d-test -n platform-test get pod -l app.kubernetes.io/name=audio-gateway` | Running + Ready 1/1 |
| Up (digest) | `... -o jsonpath='{.items[0].status.containerStatuses[0].imageID}'` | overlay'deki digest ile aynı (D30) |
| Functional (health) | pod içinden `curl -s localhost:8210/actuator/health` | `"status":"UP"` (Redis indicator dahil — `AUDIO_GATEWAY_HEALTH_REDIS_ENABLED=true`) |
| Functional (auth) | `curl -s -o /dev/null -w '%{http_code}' -X POST https://testai.acik.com/api/v1/audio-gateway/sessions` | `401` (JWT'siz fail-closed) |
| Functional (token) | testai realm token ile aynı çağrı + `Idempotency-Key` | `201` + sessionId |
| Streams | `docker exec platform-redis-streams-test sh -c 'redis-cli -a "$REDIS_PASSWORD" XLEN audio:chunks:p00'` | chunk POST sonrası ≥ 0 artış (partition hash'e göre p00..p31 değişir: `--scan --pattern "audio:chunks:*"`) |

## 5. GPU host (koşu günü — Zeynep, stage2-smoke-runbook.md adım 3)

```powershell
# yalnız env ekle + task restart; kod değişikliği yok
STT_CHUNK_CONSUMER_ENABLED=true
STT_REDIS_URL=redis://:<password>@<staging-sw-LAN-IP>:6379/0
```

## Hata ayıklama

| Belirti | Sebep / fix |
|---|---|
| Pod `CreateContainerConfigError` | `audio-gateway-secrets` yok → ESO sync bekle/force-sync (adım 1) |
| Pod startup'ta `PlaceholderResolutionException: AUDIO_GATEWAY_JWT_*` | ConfigMap eksik env — bilinçli fail-fast (#556 kontratı); configmap'i doğrula |
| Health DOWN + `redis` component | Redis erişilemiyor: compose ayakta mı, Endpoints 172.19.0.250 mi, NetPol 6379 allow mu |
| Gateway 503 + Retry-After 30 | Redis down/auth fail (D8) — `docker logs platform-redis-streams-test` |
| Gateway 429 + Retry-After 10 | Consumer lag — GPU host consumer ayakta mı (`Get-ScheduledTask platform-ai-live-stt`) |
| GPU host bağlanamıyor | staging-sw firewall 6379 LAN; parola doğru mu (Vault'tan oku) |

## Rollback

```bash
# App'i durdur (test cluster'da replicas geçici 0 — 5 dk debug istisnası):
kubectl --context k3d-test -n platform-test scale deploy/audio-gateway --replicas=0
# Redis'i durdur (transient — veri kaybı yok by design):
ssh halil@staging-sw 'cd /opt/platform/redis-streams && docker compose down'
# Manifest geri alma: bu PR'ı revert + kubectl apply -k overlays/test
```

## Prod notu (D30 cutover'a defer)

Prod karşılığı AYRI iş: prod compose (ayrı parola + `platform-prod-net`) +
prod overlay resources + WireGuard/mTLS (ADR-0031 D2 zorunlu) + Gate A/B
ölçümleri (D3). Bu runbook test plane'i kapsar.
