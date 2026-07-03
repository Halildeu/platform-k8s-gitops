# Observability/Audit GOP Skeleton — Meeting Intelligence (Faz 24)

> **Status**: SKELETON DRAFT (2026-06-02). 3-AI mutabakat Mavis MiniMax vurgu güçlendi: "observability GOP başı tasarlansın, sonraki PR'a ertelenmesin" (Codex AGREE).
>
> **Cross-AI mutabakat**: Codex `019e879c` AGREE + Mavis msg `74`/`78` AGREE.

---

## Bağlam

Faz 24 Meeting Intelligence için gözlemlenebilirlik (metric + log + trace + audit) sonraki PR'a ertelenmez. KVKK çerçevesinde **audit trail PR-stt-02'den itibaren işlemeli**. PII/transcript akışı kanıt zinciri olmadan production-ready sayılmaz.

## Tasarım Prensipleri

1. **Correlation ID baştan zorunlu** — `meetingId / sessionId / chunkIndex / requestId` her servis sınırında propagate edilir
2. **Structured log = JSON + redaction** — ses içeriği / transcript text **log'a yazılmaz**; yalnızca meta
3. **Audit event = ayrı stream** — KVKK Madde 12 hesap verebilirlik (kim, ne zaman, hangi veriye erişti)
4. **Metric naming canonical** — Prometheus standart isimler `meeting_*` / `stt_*` / `transcript_*` namespace
5. **Trace = OpenTelemetry** — Gateway → STT worker → DB latency dağılımı (sonraki faz; baseline span kontratı şimdi)
6. **PII guard** — log/metric/trace label'larında **email/phone/IBAN/full name YOK**; hash veya bucket

---

## Correlation ID Contract

Her HTTP/WebSocket request ve queue mesajında zorunlu header/field:

| Header/Field | Format | Anlam |
|---|---|---|
| `X-Correlation-Id` | UUID v4 | Request lifetime traversal (Gateway → STT → DB) |
| `X-Meeting-Id` | `MTG-<yyyy>-<seq>` | Toplantı kimliği (KVKK audit için kritik) |
| `X-Session-Id` | `SES-<uuid>` | WebSocket session (her connect yeni) |
| `X-Device-Id` | opaque token | Mobil cihaz (KVKK access audit için) |
| `X-Tenant-Id` | tenant slug | Multi-tenant readiness (ADR-0030 reserved) |
| `X-User-Id` | Keycloak `sub` | İşlem yapan kullanıcı (audit için kritik) |

**Generation**: Gateway tarafında oluşturulur; STT/Python servislerine **propagate** eder, **override etmez**.

---

## Structured Log Contract

```jsonc
{
  "timestamp": "2026-06-02T13:45:12.123Z",
  "level": "INFO",
  "service": "live-stt-service",
  "version": "0.1.0",
  "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
  "meeting_id": "MTG-2026-0042",
  "session_id": "SES-abc123",
  "user_id": "kc-sub-xyz",
  "event": "transcribe_success",
  "duration_sec": 2.5,
  "elapsed_ms": 187,
  "segments": 2,
  "language": "tr",
  "model": "medium",
  "compute_type": "int8",
  "device": "cpu"
  // YASAK: "text": "..."   (transcript içeriği log'a yazılmaz)
  // YASAK: "audio_path": "..."  (PII potansiyeli)
  // YASAK: "raw_audio_bytes": ...
}
```

**Redaction kuralları**:
- `text` / `transcript` / `audio_*` field'ları log'a **asla** koyulmaz
- `email` / `phone` / `iban` / `tc_kimlik` regex maskelenir
- Exception mesajlarında `_sanitize_error` (sadece class name) — live-stt-service zaten implement etti
- Username/email log'a girerse `hash_prefix(8)` (örn. `user_a1b2c3d4`)

---

## Audit Event Stream (KVKK Madde 12)

**Ayrı stream** — operational log'dan ayrı tutulur (DB veya Kafka topic), immutable, 7 yıl retention.

```jsonc
{
  "audit_id": "AUD-uuid",
  "timestamp": "...",
  "actor": {
    "user_id": "kc-sub-xyz",
    "user_email_hash": "8f7a1c..",
    "role": "meeting_owner"
  },
  "action": "transcript.read",
  "resource": {
    "meeting_id": "MTG-2026-0042",
    "transcript_segment_id": "SEG-001",
    "tenant_id": "tenant-main"
  },
  "result": "ok",
  "client_ip_hash": "...",  // raw IP YASAK
  "user_agent_class": "mobile_react_native"
}
```

**Audit edilecek action'lar**:
- `meeting.create` / `meeting.delete`
- `audio.upload` / `audio.delete` / `audio.access`
- `transcript.create` / `transcript.update` / `transcript.read` / `transcript.export`
- `summary.read` / `decision.read` / `action.read`
- `consent.granted` / `consent.revoked`
- `share.granted` / `share.revoked`

---

## Metric Namespace

| Metric | Tip | Label | Anlam |
|---|---|---|---|
| `stt_transcribe_total` | Counter | `model`, `language`, `result` | Toplam transcribe çağrı |
| `stt_transcribe_duration_seconds` | Histogram | `model`, `language` | Whisper inference wall-clock |
| `stt_audio_bytes_total` | Counter | `format` | Toplam ses byte alındı (KVKK boyut izleme) |
| `stt_model_load_duration_seconds` | Histogram | `model`, `device` | Lazy-load süresi |
| `stt_threadpool_active_workers` | Gauge | — | Aktif Whisper worker thread |
| `stt_timeout_total` | Counter | `model` | 504 timeout sayısı |
| `stt_oom_total` | Counter | — | 503 memory error |
| `stt_pii_redaction_total` | Counter | `pattern_class` | Logging PII redaction tetik |
| `audio_gateway_session_active` | Gauge | — | Aktif WS session sayısı |
| `audio_gateway_chunk_total` | Counter | `meeting_id_hash` | Toplam audio chunk router |
| `audio_gateway_admission_rejected_total` | Counter | `reason` | Queue full / rate limit reject |
| `transcript_segment_total` | Counter | `status` (draft/final/revised) | Segment lifecycle |
| `meeting_active_total` | Gauge | — | Şu an aktif toplantı sayısı |
| `kvkk_audit_event_total` | Counter | `action`, `result` | KVKK audit event sayısı |
| `kvkk_consent_total` | Counter | `granted_revoked` | Consent event |

**Label disiplini**:
- `meeting_id` raw değil → `meeting_id_hash` (cardinality patlamasını engelle)
- `user_id` raw değil → `user_hash_prefix(8)`
- `tenant_id` slug OK (sınırlı kardinalitede)

---

## Distributed Trace (OpenTelemetry — sonraki faz, baseline kontrat şimdi)

Span hiyerarşisi:

```
[gateway.audio.stream]                    (root, WS connection)
  ├─ [gateway.auth.validate]             (JWT decode)
  ├─ [gateway.chunk.route]               (per chunk)
  │     └─ [stt.transcribe]              (Python service)
  │           ├─ [stt.model.load]        (ilk request)
  │           ├─ [stt.audio.decode]      (ffmpeg)
  │           └─ [stt.whisper.inference] (Whisper.transcribe)
  └─ [transcript.persist]                (DB save)
```

Span attribute'larında **transcript text YOK** — sadece meta (duration, language, segment count).

---

## Implementation Roadmap (Faz 24 alt-fazları)

| Adım | Scope | Repo |
|---|---|---|
| **0 (bu PR)** | Skeleton doc + ADR-0030 placeholder | platform-k8s-gitops |
| **PR-gw-01** | Gateway Contract 1.0 — header/JWT propagation + audit event publisher iskelet | platform-backend |
| **PR-stt-02** | live-stt-service structured log + correlation_id propagation + metric exporter (mevcut PoC'ye katman) | platform-ai |
| **PR-obs-01** | Grafana dashboard + Prometheus rule + Loki query + audit DB schema | platform-k8s-gitops |
| **PR-audit-01** | KVKK audit event consumer + retention worker (7 yıl) | platform-backend |

---

## Cross-AI Mutabakat Trail

| Karar | Cross-AI vote |
|---|---|
| Observability GOP başı (sona bırakma) | Mavis vurgu güçlendi → Codex AGREE → Claude AGREE |
| Correlation ID Gateway baştan zorunlu | Codex önerisi → Mavis AGREE → Claude AGREE |
| Structured log redaction (ses/transcript/PII) | Mavis "KVKK için" → Codex `_sanitize_error` zaten implement → Claude AGREE |
| Audit event ayrı stream + 7 yıl immutable | Claude önerisi (KVKK Madde 12) → Codex AGREE → Mavis AGREE |
| Metric namespace canonical baştan | Codex önerisi → Mavis AGREE → Claude AGREE |

## References

- ADR-0030 KVKK Meeting Intelligence Boundary (placeholder)
- `platform-ai` `live-stt-service` `_sanitize_error` PII guard
- Faz 23 notification-service event-contract (paralel pattern)
- Cross-AI threads: Codex `019e879c` + Mavis msg `74` / `78`
