# Session Handoff — 2026-06-17 — audit-retention-worker Prometheus alerts (#1250 follow-up)

> Format: D28 5-alan + P0 aksiyon listesi. Bu, gitops `#1250` (audit-archive 7yr WORM retention worker) D-dilimi sonrası **Codex-onaylı out-of-scope follow-up** için handoff'tur (spawn_task `task_19335787`). Cross-AI thread `019ed4f4`.

---

## 1. Bağlam — neden bu session

`#1250` audit-retention-worker uçtan uca CANLI + kapalı (A `#1653` + B/amend `#1651`/`#1654` + C platform-backend `#687` + D `#1655 dc6ed103`). Worker k3d-test'te ArgoCD-reconciled CronJob olarak çalışıyor (`schedule: 0 3 * * *`). **Tek eksik = worker-specific Prometheus alert'leri** (ADR-0042 §4 observability). Codex (`019ed4f4` D-postimpl AGREE) bunu out-of-scope follow-up'a aldı + **explicit tasarım kısıtı** verdi:

> Worker run-once bir CronJob → in-process Micrometer counter'ları (`audit_archive_lag_seconds`, `audit_archive_chain_break_total`, `audit_archive_anomaly_total`, `audit_archive_errors_total`) **EPHEMERAL** — Prometheus 30sn'lik bir job'ı güvenilir scrape edemez. Alert'leri **DURABLE DB state** üzerinden tasarla, in-process counter'lara güvenme.

## 2. İddia — bu follow-up'ta ne yapılacak

Worker için **DB-cursor/ledger tabanlı** Prometheus alert kuralları (+ gerekiyorsa bir postgres-query exporter). 3 alert sınıfı:

1. **archive_lag** — en eski eligible-ama-arşivlenmemiş satır yaşı: `now - min(event_timestamp)` WHERE `seq > audit_archive.audit_archive_cursor.last_archived_seq` AND `event_timestamp < now() - 90 gün`. Eşik > ~26h (günlük schedule + margin) → alert.
2. **chain_break / anomaly** — fail-closed sinyalleri: `kube_job_status_failed{job_name=~"audit-retention-worker.*"}` (ChainBreakException/ArchiveAnomalyException failed Job bırakır + cursor donar) OR `audit_archive_ledger.verify_status != 'VERIFIED'` satırı.
3. **stale-cursor** — eligible satır varken `audit_archive_cursor.updated_at` ilerlemiyorsa → worker koşmuyor/takıldı.

## 3. İspatlar — canlı deployed state (truth)

- **CronJob**: `kubectl --context k3d-test -n platform-test get cronjob audit-retention-worker` → `schedule=0 3 * * * suspend=false`.
- **audit_archive schema** (host `platform-pg-test`, DB `audit_event`, worker-owned, dedicated role `audit_retention_worker`):
  - `audit_archive.audit_archive_cursor` (singleton id=1): `last_archived_seq bigint`, `updated_at timestamptz`. **Canlı**: `last_archived_seq=4`.
  - `audit_archive.audit_archive_ledger` (arşivlenen obje başına 1 satır): `object_key`, `min_seq`, `max_seq`, `row_count`, `min_event_timestamp`, `max_event_timestamp`, `object_sha256`, `object_version_id`, `manifest_sha256`, `manifest_version_id`, `retention_until`, `verify_status` (VERIFIED/…), `tenant_anchors jsonb`, `created_at`. **Canlı**: 1 row VERIFIED.
  - `audit_archive.audit_archive_tenant_anchor`: `tenant_id PK`, `last_entry_hash`, `last_archived_seq`, `updated_at`. **Canlı**: tenant 1, last_archived_seq=4.
- **Kaynak tablo** (read-only): `audit_event.audit_event` (`seq` bigint PK, `event_timestamp timestamptz` = eligibility ekseni, `tenant_id`). Worker'ın hot-window default 90d (ConfigMap `AUDIT_RETENTION_HOT_WINDOW_DAYS`).
- **DB erişim**: `ssh halil@staging-sw 'docker exec platform-pg-test psql -U postgres -d audit_event -c "<sql>"'` (peer-auth, şifresiz).

## 4. İspatlamaz — henüz yok

- Worker için **HİÇ Prometheus rule yok** (sadece in-process Micrometer counter'lar var, ephemeral).
- Worker'ın bir **ServiceMonitor'ı yok** (CronJob, Service yok) — durable obs DB üzerinden olmalı.
- Bir **postgres-query exporter** gerekip gerekmediği karar verilecek (mevcut bir postgres-exporter varsa custom query eklenir; yoksa küçük exporter/scrape-CronJob).

## 5. Bilinen boşluk + P0 aksiyon listesi

**P0-1 — obs pattern keşfi** (≈20dk): `kustomize/base/monitoring/` PR-obs-01 Prometheus rules + scrape pattern'i oku (Faz 24 STT obs emsali: `project_faz24_obs01_observability` memory). Mevcut `postgres-exporter` / `redis-streams-exporter` scrape var mı? Varsa custom-query ekleme yolu; yoksa exporter tasarımı (Codex'e danış).

**P0-2 — alert metric kaynağı kararı** (Codex `019ed4f4` reply veya yeni thread):
- (a) **kube-state-metrics** zaten `kube_job_status_failed` veriyor mu? → chain_break/anomaly alert'i bununla (failed Job = fail-closed sinyal). En ucuz yol.
- (b) **archive_lag + stale-cursor** DB sorgusu gerektirir → postgres-exporter custom query (`pg_audit_archive_lag_seconds`, `pg_audit_archive_cursor_age_seconds`, `pg_audit_archive_unverified_ledger_total`).

**P0-3 — implement** (gitops): PrometheusRule manifest (`kustomize/base/monitoring/` veya prod-hub) + (gerekirse) postgres-exporter custom-query ConfigMap. ADR-0042 §4 metric isimleri ile hizala.

**P0-4 — cross-AI + gov-gate + merge**:
- Codex (`019ed4f4` veya yeni thread) post-impl review → AGREE (HARD RULE Cross-AI).
- PR body: `## Boundary declaration (ADR-0011 §2.3)` (alert manifest = state-mutation test cluster veya none-of-the-above eğer prod-hub config-only) + `## Cross-AI` bloğu (Implementer claude / Reviewer codex / thread UUID / Verdict). Local validator: `python3 scripts/governance/check_pr_boundary_declaration.py --body-file <body>`.
- CI yeşil (CI-red merge YASAK) → normal squash (admin YOK).

**Önemli gotcha'lar** (memory `project_faz24_audit_archive_minio_infra` D-DONE bölümünde):
- in-process Micrometer counter ephemeral — alert tasarımı DB-durable olmalı (Codex kısıtı).
- prod-hub mimarisi: Grafana/Prometheus prod-only (ADR-0002 §3.8); test→prod remote_write (`project_faz24_obs01_observability`); `absent()` yasağı, recording-only ConsumerAbsent emsali.
- DB sorgusu host `platform-pg-test` üzerinde; exporter'ın DB erişimi (read-only) + NetPol gerekir.

### Yeni session ilk komut
```
cd /Users/halilkocoglu/Documents/platform-k8s-gitops && git fetch origin && git log --oneline origin/main -3
# memory: project_faz24_audit_archive_minio_infra (D-DONE + alert follow-up tasarımı) + project_faz24_obs01_observability (PR-obs-01 pattern)
# ADR-0042 §4 observability + kustomize/base/monitoring/ oku → P0-1 obs pattern keşfi
```

**Referanslar**: `docs/adr/0042-faz24-audit-archive-retention-worker.md` §4 · `kustomize/base/monitoring/` (PR-obs-01) · memory `project_faz24_audit_archive_minio_infra` (D-DONE) + `project_faz24_obs01_observability` · spawn_task `task_19335787` · Codex thread `019ed4f4-1d6b-7bd3-8cad-175487fa7a9b`.
