# Faz 24 İ2-T — Live transcript SSE broadcast (desktop→web anlık)

**Owner request (2026-07-21)**: "masaüstü uygulaması girişi konuşanların anlık webe yansıması sorununu çöz"

Bu runbook, desktop'ta konuşulanların **başka bir web viewer'a** anlık aktarılmasını sağlayan İ2-T zincirinin enable + operate + rollback kılavuzudur.

## Mimari

```
Desktop (recorder)         audio-gateway                        Web viewer(s)
    ↓ audio chunks              ↓                                    ↓
  WS proxy → live-stt           ↓                                    ↓
       ↓ TranscriptResult       ↓                                    ↓
              → durable Redis (persistent) ─ İ4 live-analyze (meeting-ai)
              → LiveTranscriptBroadcastSink  →  LiveTranscriptStreamHub
                                                    ↓
                                         GET /api/v1/audio-gateway/
                                              meetings/{id}/live-transcript/stream
                                                    ↓
                                         mfe-meeting EventSource + UI
```

**Ephemeral** — no persistence at this hop. Canonical transcript persistence remains `meeting-service` (mfe-meeting canonical intelligence result endpoint via [platform-web#948](https://github.com/Halildeu/platform-web/pull/948)).

## Bileşenler (LIVE)

| Layer | Bileşen | Kaynak PR |
|---|---|---|
| Backend | `LiveTranscriptStreamHub` (in-memory pub/sub) | [platform-backend#914](https://github.com/Halildeu/platform-backend/pull/914) |
| Backend | `LiveTranscriptBroadcastSink` (decorator, outer chain) | Aynı |
| Backend | `LiveTranscriptStreamController` (SSE + `meeting:can_view` gate) | Aynı |
| Frontend | `meeting-live-transcript-sse.ts` (EventSource client) | [platform-web#976](https://github.com/Halildeu/platform-web/pull/976) |
| Overlay | `AUDIO_GATEWAY_DIRECT_STT_LIVE_TRANSCRIPT_BROADCAST_ENABLED` baseline | [platform-k8s-gitops#2754](https://github.com/Halildeu/platform-k8s-gitops/pull/2754) |

## Enable (owner-touch)

### 1. Backend enable (audio-gateway)

Overlay patch (`kustomize/overlays/test/kustomization.yaml`):

```yaml
patches:
  - target:
      kind: ConfigMap
      name: audio-gateway-config
    patch: |-
      - op: replace
        path: /data/AUDIO_GATEWAY_DIRECT_STT_LIVE_TRANSCRIPT_BROADCAST_ENABLED
        value: "true"
```

Apply + rollout:
```bash
kubectl --context k3d-test apply -k kustomize/overlays/test
kubectl --context k3d-test -n platform-test rollout restart deploy/audio-gateway
kubectl --context k3d-test -n platform-test rollout status deploy/audio-gateway --timeout=180s
```

### 2. Backend verify (agent, staging-sw)

```bash
POD=$(kubectl --context k3d-test -n platform-test get pod -l app.kubernetes.io/name=audio-gateway -o jsonpath='{.items[0].metadata.name}')
kubectl --context k3d-test -n platform-test exec "$POD" -- env | grep -E 'AUDIO_GATEWAY_DIRECT_STT_LIVE_TRANSCRIPT_BROADCAST_ENABLED'
# Expected: AUDIO_GATEWAY_DIRECT_STT_LIVE_TRANSCRIPT_BROADCAST_ENABLED=true

# SSE endpoint smoke (bearer required)
BEARER=$(bash /path/to/get-smoke-token.sh)
curl -s -N -H "Authorization: Bearer $BEARER" \
  "https://testai.acik.com/api/v1/audio-gateway/meetings/<meetingId>/live-transcript/stream" \
  | head -5
# Expected: :heartbeat  (SSE comment) veya event: transcript-chunk / data: {...}
```

### 3. Web enable (mfe-meeting)

Overlay env (`kustomize/base/apps/platform-web-nginx-stage/configmap.yaml` veya mfe-meeting bundle env injection):

```
VITE_MEETING_LIVE_TRANSCRIPT_SSE_URL=https://testai.acik.com/api/v1/audio-gateway/meetings/{meetingId}/live-transcript/stream
```

Rebuild mfe-meeting bundle + overlay digest bump PR.

### 4. Web integration (App.tsx wire — follow-up PR)

`apps/mfe-meeting/src/App.tsx` içinde selectedMeeting değiştiğinde:

```typescript
useEffect(() => {
  if (!selectedMeeting) return;
  const controller = connectLiveTranscriptSse(
    selectedMeeting.id,
    {
      onSnapshot: (snapshot) => setLiveSseSnapshot(snapshot),
      onError: (msg) => setStreamStatusMessage(msg),
    },
  );
  return () => controller.close();
}, [selectedMeeting?.id]);
```

TranscriptSegment[] `chunks` mevcut `transcript` array'e prepend edilebilir (draft state, "Kayıtçı" speaker).

## Verify (attended smoke — Zeynep pattern)

1. **Desktop recorder** — win-unpacked ile audio:start
2. **Web viewer** (başka user'ın browser'ı, aynı meetingId) — mfe-meeting Meetings sayfasında meeting'i aç
3. Beklenen: 3-5 saniye içinde web viewer'da draft transcript chunk'lar akmaya başlar
4. Desktop `audio:stop` → hub subscriber sayısı azaldıkça sink temizlenir; canonical readback web'de meeting-service üzerinden gelir (persistence path)

## Metrics

Prometheus:
- `audio_gw_live_transcript_broadcast_publish_total` (planlı — sonraki iterasyonda counter eklenecek)
- `audio_gw_live_transcript_hub_active_meetings` (gauge — planlı)

Grafana dashboard update ileriki polish PR'ında.

## Rollback

```bash
# Overlay flip back
sed -i 's/AUDIO_GATEWAY_DIRECT_STT_LIVE_TRANSCRIPT_BROADCAST_ENABLED: "true"/AUDIO_GATEWAY_DIRECT_STT_LIVE_TRANSCRIPT_BROADCAST_ENABLED: "false"/' \
    kustomize/base/apps/audio-gateway/configmap.yaml
kubectl --context k3d-test apply -k kustomize/overlays/test
kubectl --context k3d-test -n platform-test rollout restart deploy/audio-gateway
```

Broadcast off → `LiveTranscriptStreamHub` bean absent → SSE endpoint `@ConditionalOnBean` nedeniyle Spring context'e girmez → 404. Frontend `connectLiveTranscriptSse` `EventSource` open sonrası 404 alır → `error` state; mevcut UI transkript kaynağı (WS live-stream veya API) etkilenmez.

## Known-good defaults

- `HEARTBEAT_INTERVAL = 15s` (proxy tear-down protection)
- `BUFFER_CAPACITY = 128` (drop-oldest; ~4dk stall coverage @ 500ms cadence)
- `withCredentials: true` (bearer cookie/header forward)
- Auth policy: `MeetingAccessValidator` — `meeting:{id}#can_view` (not `can_record`; viewer scope)

## Guarantees

- **Ephemeral** — no persistence, no replay, sink map bounded across long uptimes
- **Best-effort broadcast** — publish failure never masks durable Redis emission
- **Owner-gated** — SSE preflight 401/403/404 without existence leak, 5xx fail-closed 503
- **PII discipline** — text passes as-is (already payload-audited via [platform-backend#819](https://github.com/Halildeu/platform-backend/issues/819)); no raw audio, no bearer in logs

## Referanslar

- [platform-backend#914](https://github.com/Halildeu/platform-backend/pull/914) — backend hub + decorator + controller + 11 test
- [platform-web#976](https://github.com/Halildeu/platform-web/pull/976) — frontend EventSource client + 6 test
- [platform-k8s-gitops#2754](https://github.com/Halildeu/platform-k8s-gitops/pull/2754) — overlay env baseline
- ADR-0031 (audio-gateway bounds) — max chunk / buffered / session
- ADR-0011 §2.3 (boundary declaration) — user-communication class
- Faz 24 İ4 pattern (`LiveAnalyzeTriggerSink`) — decorator chain reference
