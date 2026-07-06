# STT Pipeline — Loki Query Kontratı (transcript-free)

> **Status**: CONTRACT (PR-obs-01c, 2026-06-12). Faz 24 gitops#1248-A scope'u —
> **query kontratı bu doc ile teslim edilir; canlı Loki ingestion ayrı iş**
> (#1248-B: test cluster STT loglarının Loki'ye taşınması, remote_write
> onarımı #1459 ile aynı cross-cluster aileden).
>
> Cross-AI: Codex thread `019ebacc` iter-2 S4 — "#1248'i contract-doc'a
> daraltın, ingestion'ı ayrı issue'ya taşıyın; LogQL redaction negatif
> query'si tek başına KVKK kanıtı değildir" absorb edildi.

## Bağlam — neden kontrat şimdi, ingestion sonra

- Loki + promtail **yalnız prod-hub'da** canlı (k3d-prod monitoring, single-binary,
  7d retention — ADR-0002 §3.8 tek-Grafana modeli).
- audio-gateway **k3d-test'te** koşuyor; test cluster'da promtail YOK →
  STT logları bugün Loki'ye AKMIYOR. Cross-cluster push remote_write ile aynı
  altyapı sorununa bağlı (prod'a host-bridge expose) → #1459 / #1248-B.
- Kontratı şimdi mühürlemenin değeri: log şekli (alan adları, redaction
  sınırı, korelasyon anahtarları) **üretici taraflarda şimdi sabitlenir**;
  ingestion açıldığında query'ler değişmeden çalışır (skeleton doc'taki
  "correlation ID baştan zorunlu" prensibiyle aynı).

## Log shape sözleşmesi (üretici tarafları bağlar)

Kaynak: `docs/observability-skeleton-meeting-intelligence.md` §Structured Log
Contract. Loki query'lerinin varsaydığı minimal alan seti:

| Alan | Örnek | Not |
|---|---|---|
| `service` | `audio-gateway` \| `live-stt-service` | promtail label'ı `app` / `app_kubernetes_io_name` ile de gelir |
| `level` | `INFO` / `WARN` / `ERROR` | |
| `correlation_id` | UUID v4 | gateway üretir, consumer propagate eder — **log satırında düz alan** |
| `session_id` | `SES-<uuid>` | |
| `event` | `chunk_envelope_received`, `transcribe_success` | makine-okur event adı |
| YASAK | `text`, `transcript`, `audio_*`, raw `email/phone/iban/tc_kimlik` | S5 transcript-free kuralı — log'a hiç yazılmaz |

## Query kontratı (LogQL — ingestion açılınca birebir çalışır)

Label convention: promtail kube-sd default'ları (`namespace`, `app` veya
`pod`). Aşağıda `app` kullanıldı; ingestion PR'ı (#1248-B) gerçek label adını
doğrulayıp gerekirse bu doc'u günceller (tek satır değişiklik).

### Q1 — Correlation zinciri uçtan uca (asıl operasyon query'si)

Bir chunk'ın client→gateway→consumer yolculuğu (Aşama-2 G2 kanıtının
Loki karşılığı):

```logql
{namespace=~"platform-test|platform-prod"}
  |= "c54663af-9ada-4d3c-93f4-d6956a64f3da"
```

Beklenen: gateway admission satır(lar)ı + live-stt `chunk_envelope_received`
satırı AYNI correlation_id ile. (Bugünkü eşdeğeri: gateway minimal-log +
GPU host dosya logu + Redis envelope — bkz. "Test-side eşdeğer" bölümü.)

### Q2 — STT hata akışı (transcript-free triage)

```logql
{app=~"audio-gateway|live-stt-service"} | json
  | level=~"ERROR|WARN"
  | line_format "{{.service}} {{.event}} corr={{.correlation_id}} err={{.err_class}}"
```

`err_class` sadece exception SINIF adı taşır (`_sanitize_error` sözleşmesi) —
mesaj gövdesi değil.

### Q3 — Redaction ihlal nöbetçisi (negatif kontrol)

```logql
{app=~"audio-gateway|live-stt-service"}
  |~ "\"(text|transcript|audio_path|raw_audio_bytes)\"\\s*:"
```

Beklenen sonuç: **0 satır, her zaman**. >0 satır = S5 ihlali → P1 incident
(log üreticisinde redaction kaçağı).

> **KVKK sınırı (Codex S5 absorb)**: Bu negatif query *tek başına* KVKK
> kanıtı DEĞİLDİR — yalnız "bilinen alan adları log'a sızmadı" kontrolüdür.
> Tam kanıt seti: (1) üretici tarafı redaction birim testleri
> (platform-ai PII redaction suite — #97 ailesi), (2) log shape sözleşmesi
> code review gate'i, (3) bu nöbetçi query'nin periyodik koşumu. Üçü birlikte.

### Q4 — Gateway audit görünürlüğü (KVKK Madde 12 yardımcısı)

```logql
{app="audio-gateway"} | json
  | event=~"session_created|chunk_admitted|chunk_rejected"
  | line_format "{{.event}} sess={{.session_id}} corr={{.correlation_id}}"
```

Not: Asıl KVKK audit trail ayrı immutable stream'dir (PR-audit-01,
gitops#1249/#1250) — Loki operasyonel teşhis içindir, audit kaydı DEĞİLDİR
(7 yıl retention Loki'de yok; 7d).

### Q5 — Consumer sağlık nabzı

```logql
{app="live-stt-service"} | json | event="chunk_envelope_received"
```

`rate()` sargısıyla dashboard'a "consumer log nabzı" paneli eklenebilir
(ingestion sonrası; Prometheus tarafındaki `stt:consumer_present:bool` ile
çapraz kontrol).

## Test-side eşdeğerler (ingestion açılana KADAR geçerli yol)

Loki yokken aynı soruların bugünkü cevap yolları:

| Soru | Bugünkü komut |
|---|---|
| Correlation zinciri | Redis envelope: `docker exec platform-redis-streams-test redis-cli ... XRANGE audio:chunks:pNN - +` → `correlationId` alanı; GPU host: `live-stt` log dosyasında `chunk_envelope_received [<corr>]` |
| Gateway hata akışı | `kubectl --context k3d-test -n platform-test logs deploy/audio-gateway --since=1h \| grep -E "ERROR\|WARN"` (S5 gereği request-level log minimal — boş olması normaldir) |
| Redaction nöbetçisi | Aynı logs komutu + `grep -E '"(text\|transcript\|audio_path)"\s*:'` → 0 satır beklenir |
| Consumer nabzı | Prometheus: `stt:consumer_present:bool` + `redis_stream_group_consumer_idle_seconds` (PR-obs-01b) |

## Kabul / durum

- [x] Log shape sözleşmesi sabit (skeleton §Structured Log Contract'a bağlı)
- [x] 5 query kontratı (Q1-Q5) + redaction KVKK sınır notu
- [x] Test-side eşdeğer tablo (bugün çalışır komutlar)
- [ ] **#1248-B (ayrı issue)**: test cluster promtail → Loki ingestion
      (host-bridge expose; #1459 remote_write ile aynı altyapı ailesi) —
      açıldığında Q1-Q5 canlı koşulup bu doc'a kanıt eklenir; `app` label
      adı doğrulanır.

## Referanslar

- `docs/observability-skeleton-meeting-intelligence.md` (log shape + metric namespace)
- `kustomize/base/monitoring/stt-pipeline-rule.yaml` + `grafana-dashboards/stt-pipeline-dashboard.yaml` (PR-obs-01b)
- gitops#1459 (remote_write onarımı), gitops#1457 (exporter ACL ayrımı)
- Codex thread `019ebacc-12f9-7200-942d-81072b418ff2` (3-PR split + S4/S5 absorb)
