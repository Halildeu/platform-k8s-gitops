# Redis Streams (test plane) — Faz 24 cross-server chunk transport

Audio-gateway (k3d-test) → Redis Streams (bu compose) → live-stt (GPU host)
hattının orta bacağı. Kontrat + profil detayları `docker-compose.yml` üst
yorumunda; kurulum/işletme adımları canonical runbook'ta:

→ **`docs/runbooks/redis-streams-staging-sw.md`**

## Hızlı başlatma (staging-sw)

```bash
sudo mkdir -p /opt/platform/redis-streams
# .env: REDIS_PASSWORD=<Vault kv/platform/audio-gateway-service redis_password ile aynı>
sudo cp docker-compose.yml /opt/platform/redis-streams/
cd /opt/platform/redis-streams && docker compose up -d
docker exec platform-redis-streams-test redis-cli -a "$REDIS_PASSWORD" ping  # PONG
```

## Sınırlar

- **Test plane**: prod karşılığı D30 cutover planıyla gelir (ayrı compose +
  ayrı Vault path + WireGuard zorunlu).
- **KVKK**: stream payload'ı SHA-256 + routing metadata taşır (raw audio /
  transcript YOK — #534 PII guard); persistence OFF.
- LAN-publish yalnız Aşama-2 synthetic smoke içindir (ADR-0031 D2 istisnası);
  gerçek meeting audio öncesi WireGuard+mTLS şart.
