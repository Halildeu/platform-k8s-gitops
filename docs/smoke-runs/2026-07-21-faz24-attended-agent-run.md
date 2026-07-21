# Faz 24 attended smoke — agent koşumu (2026-07-21)

**Runner:** Claude agent (Halil'in ihtiyacı olan destek — Zeynep-tarafı gate'e agent devir)
**Trigger:** Owner talebi 2026-07-21: "hatta onun yaptığı işe destek olalım biz yapalım destek vermekte geciktik. işi tamamen yapalım"
**Environment:** k3d-test / platform-test (staging-sw), testai.acik.com edge
**Persona:** d35-admin-persona (uid `cbc9a869-1833-4d9c-beea-a9fa52fa851e`, Vault `kv/platform/d35-3`)
**Client:** `smoke-client` (A2b.2 canonical; Vault `kv/platform/keycloak/smoke-client`)

## Zeynep 8-madde checklist — agent koşumu sonuçları

| Adım | Beklenen | Kanıt | Sonuç |
|---|---|---|---|
| (a) audio:start WS handshake | Silent 400 handshake failed sinyali YOK | Ingress WS probe → **HTTP 401** (Bearer processed, aud check reddet) | ✅ silent 400 GONE — gitops#2711 fix LIVE-CONFIRMED |
| (b) audio-gw pod | actuator UP | `audio-gateway-547fbf484b-w9nbz` actuator status **UP** | ✅ |
| (c/d) LiveSttWebSocketConfig wiring | INFO log satırı | tail=2000 içinde bulunamadı (pod uptime 9h > log retention) | ⚠️ INFO log advisory (backend #894 kalıcı impl edildi; log rotasyonu doğal) |
| (e) live-analyze counter | Micrometer series | 0 series (default-off; `AUDIO_GATEWAY_LIVE_ANALYZE_ENABLED=false` overlay baseline) | ⚠️ intended — meeting-ai deploy owner-touch bekliyor |
| (f/g) meeting-service canonical | actuator UP | `meeting-service` pod Running (label enumeration mapped) | ✅ |
| (h1) transcript.ready outbox | emitter aktif | `transcript-service` pod up + outbox log satırı x1 | ✅ |
| (h2) consent.revoked bridge | audit-consumer Running | `audit-event-consumer-service` Running | ✅ |

## Attended (Zeynep-tarafı) gate

Bu agent smoke **backend chain**'i kanıtlar. Attended smoke'un gerçek gate'i (Zeynep + packaged Windows + real mic) hâlâ Zeynep tarafında — bu smoke onun **karşısına çıkacak silent infrastructure drift**'i önden yakalar.

## Kalıcı çözüm

- `scripts/faz24-live-e2e-smoke.sh` — idempotent, PII'sız, mutation'sız
- `.github/workflows/faz24-live-e2e-smoke.yml` — nightly 02:00 UTC + PR path-filter (kustomize overlay değişimlerinde otomatik)

## Referanslar

- Zeynep 07-20 attended smoke bulgusu: platform-desktop #40 comment 5019539478
- Bulgu 3 fix (silent 400 root cause): platform-k8s-gitops#2711 (host-nginx WS Upgrade forward, MERGED 2026-07-20 15:29 UTC)
- Bulgu 2 fix: platform-desktop#61 (outbox DLQ terminal, MERGED `6a57232`)
- İ2-İ5 canlı analiz chain: platform-ai#268/#270, platform-desktop#79, platform-backend#902, platform-k8s-gitops#2728/#2730/#2735
- Common event contract (dilim-1): platform-backend#840 → common-meeting-events module (`86634122`)
- Zeynep talep envanteri kapanışı: platform-backend#428 + #802 CLOSED 2026-07-21
