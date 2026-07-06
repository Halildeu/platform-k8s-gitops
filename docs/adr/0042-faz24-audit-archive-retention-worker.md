# ADR-0042 — Faz 24 Audit Archive 7-Year Retention Worker (WORM Cold-Storage Contract)

> **Status**: ACCEPTED (2026-06-17). Faz 24 KVKK audit pipeline'ının (`audit_event` immutable append-only + BE-016 hash-chain) **Katman-1 = 7 yıl değişmez (WORM) cold archive** akışının teknik kontratını tanımlar. Issue gitops`#1250` ("[PR-audit-01] Audit 7yr retention worker (cron)"). Bu ADR **tasarım kapısı (B dilimi)**; backend worker kodu (C) + deploy (D) ayrı, fresh backend session'a bırakılır (§7).
>
> **Bağlantı**: [ADR-0030](0030-kvkk-meeting-intelligence-boundary.md) (KVKK boundary — bu repo'da hâlâ **PLACEHOLDER**; KVKK retention **policy** kararı ayrı bir repo'da kapatıldı — §2 truth-closure), [ADR-0031](0031-two-server-meeting-intelligence-topology.md) (two-server topology / stateful-cold off-hot-cluster), [ADR-0002](0002-single-host-dual-cluster.md) (single-host dual-cluster), [ADR-0041](0041-faz24-openfga-tuple-governance.md) (Faz 24 governance disiplini). Cross-AI plan-time consult: Codex thread `019ed4f4-1d6b-7bd3-8cad-175487fa7a9b` (A+B `ready_for_impl: true`, 5 design-call REVISE absorbed).
>
> **AMENDED (2026-06-17, C-slice öncesi — Codex `019ed4f4` C-plan AGREE)**: İki kontrat düzeltmesi C kodlamasından önce mühürlendi: **(1) `CHAIN_SCOPE = PER_TENANT` PIN'lendi** (D4.4 hard gate **canlı consumer kodundan teyit** edilerek çözüldü — `AuditIntegrityVerifier.verifyTenant(tenantId)` + `findByTenantIdOrderBySeqAsc` + `prev_hash`="same tenant chain; NULL=tenant GENESIS"; provenance `platform-backend@74c9e1a9`/#677/#1249). V1 worker yalnız PER_TENANT derlenir, runtime scope-flip YOK; GLOBAL dalı **historik/ileride** referans olarak korunur ama V1'de aktif değildir. **(2) D4.7 idempotency `version_id` modeline düzeltildi**: S3 Object Lock COMPLIANCE + versioning aynı key'e yeni-version PUT'u **engellemez** (her *version*'ı değişmez kılar; "overwrite denied" iddiası YANLIŞ'tı). Doğru model: ledger `object_version_id`/`manifest_version_id` + version-specific HEAD/GET + checksum-sha256 doğrulama + **latest-version == kayıtlı version** assertion; sapma → fail-closed `audit_archive_anomaly_total`, cursor ilerlemez, re-put YOK. Cred Delete*/Bypass reddeder → tüm version'lar değişmez kalır.

---

## Context

Faz 24 KVKK audit pipeline canlı + E2E kanıtlı (gitops`#1648`): producer (`audio-gateway-service`, `@ConditionalOnProperty` audit sink) → Redis Streams (host-compose, stream `audit:events`, group `audit-persist-v1`) → `audit-event-consumer-service` (**pure** Redis-Streams consumer, `@RestController` yok) → Postgres `audit_event.audit_event` (append-only trigger + BE-016 SHA-256 hash-chain, tamper-detect). Durable smoke: 4/4 fire EMIT+persist, stream==DB, dlq=0, hash-chain dolu.

**Canlı `audit_event.audit_event` şeması** (sentetik değil; host PG `platform-pg-test` introspection):

| Kolon | Tip | Rol |
|---|---|---|
| `seq` | bigint **PK** (sequence) | **Monotonik arşiv cursor'u** (zaman değil) |
| `id` | uuid UNIQUE | Olay kimliği |
| `tenant_id` | bigint | İzolasyon |
| `event_type` | varchar(100) | Olay türü |
| `event_timestamp` | timestamptz | **Eligibility ekseni** (hot-window) |
| `ingested_at` | timestamptz | Tüketim zamanı |
| `dedup_key` | varchar(320) UNIQUE | İdempotency |
| `prev_hash` / `entry_hash` | varchar(64) | **Hash-chain** linkleri |
| `entry_hash_alg` / `entry_hash_version` | varchar(32) / int | Hash sürümleme |
| `session_id`, `user_id`, `chunk_seq`, `http_status`, `rejection_code`, `retry_after_seconds`, `correlation_id`, `stream_entry_id` | (çeşitli) | Olay metadata'sı |

Trigger'lar: `trg_audit_event_append_only` (BEFORE DELETE OR UPDATE → reddet) + `trg_audit_event_require_hash` (BEFORE INSERT). **Önemli: tabloda transcript/ses metni veya blob payload kolonu YOKTUR** — yani arşiv yalnız audit metadata taşır; transcript/ses içeriği yapısal olarak arşive giremez (schema-level KVKK guard).

**Cold-storage altyapısı**: `MinIO` staging-sw'da **host-compose** olarak zaten çalışıyor (`minio-minio-test-1`, `minio/minio:RELEASE.2025-09-07`, S3 API host `:9100`→container `:9000`, console `:9101`; root cred `_FILE`-mounted; health `live=200`). k3d cluster içinde MinIO **pod'u yok** — bilinçli: stateful/cold katman hot-cluster yaşam döngüsünden ayrı (ADR-0031 two-server, redis-streams/postgres host-bridge emsali).

`#1250` = bu metadata'yı 7 yıl değişmez cold archive'a yazan + hash-chain'i doğrulayan **cron worker**. Kaynak tablo append-only; 7 yıl içinde hiçbir satır silinmez.

## 2. Truth-Closure — ADR-0030 (bu repo) PLACEHOLDER'dır

Bu repo'daki [`0030-kvkk-meeting-intelligence-boundary.md`](0030-kvkk-meeting-intelligence-boundary.md) hâlâ **`PLACEHOLDER (2026-06-02)`** statüsündedir (Adım-0 kapısı; pilot ses/transcript öncesi tam ADR doldurulacak). KVKK **retention policy** kararı (audit-archive 7yr değişmez + KVKK m.12 erişim-logu 2yr **ayrı**) ise **ayrı bir repo'da** (`platform-ai` PR#159, 3-AI mutabakatı: Claude + Codex + MiniMax; issue #52/#60 CLOSED) ACCEPTED'a çekildi. Bu iki "ADR-0030" **aynı belge değildir**; gitops ADR-0030 bir boundary placeholder'ı, policy kararı ise platform-ai tarafındadır.

**Bu ADR-0042, gitops ADR-0030 placeholder'ını "accepted" saymaz**; onu **extend** eder: ADR-0042 yalnız Katman-1 audit-archive'ın **teknik worker kontratıdır**; KVKK policy gerekçesi platform-ai#159'a dayanır. gitops ADR-0030'un tam-ACCEPTED'a çekilmesi (consent/deletion/access-boundary tam metni) ayrı bir governance işidir ve bu ADR'nin önkoşulu değildir.

## 3. Decision

### D1 — Decomposition + ordering (Codex call-1 REVISE absorbed)
`#1250` dört dilime ayrılır: **[A]** object-store infra (host-bridge + bucket WORM + ESO + NetPol + D29) · **[B]** bu ADR (worker kontratı) · **[C]** backend worker kodu (CronJob image + ledger/cursor Flyway + S3 client + hash-verify + Testcontainers) · **[D]** worker deploy. **A + B bu oturumda** (infra canlı + kontrat mühürlü). **C + D fresh backend session'a** (`platform-backend` checkout stale; audit-event-consumer-service lokal yok; MinIO Testcontainer + büyük cross-AI gerekiyor → `ready_for_impl: false` bu oturum için). Object-store, `#1250`'nin **ayrı linkli prerequisite**'idir (A onu karşılar).

### D2 — Worker placement (Codex call-4 REVISE absorbed)
Arşiv işi `audit-event-consumer-service`'e `@Scheduled` olarak **EKLENMEZ**. Ayrı, tek-amaçlı **`audit-retention-worker`** (tercihen Kubernetes **CronJob**, ya da tek-purpose image/profile). Gerekçe: consumer'ın sorumluluğu stream→persist; arşiv işi PG-scan + hash-verify + S3-write + ledger/cursor yaşam döngüsüdür — **ayrı failure domain, ayrı credential set, ayrı rollout cadence**. Ortak repository/entity kodu paylaşılabilir; **runtime servis ayrıdır**.

### D3 — Storage placement + immutability (Codex call-2 REVISE + call-3 AGREE absorbed)
Cold-store = **host-compose MinIO** (in-cluster StatefulSet+PVC **değil**; PVC hot-cluster yaşam döngüsüne bağlanırdı). Bucket `audit-archive`: **object-lock ENABLED (oluştururken)** + **versioning ON** + default **COMPLIANCE** mode retention **7 yıl (2557 gün)**.

Değişmezlik **üç katman**: (i) DB append-only trigger + BE-016 hash-chain (kaynak), (ii) S3 **Object Lock COMPLIANCE / WORM** per-**object-version** 7yr (arşiv), (iii) manifest+object SHA-256 digest (içerik bütünlüğü).

> **Object Lock semantiği (AMENDED)**: COMPLIANCE her *object version*'ı 7yr boyunca silinemez/kısaltılamaz kılar — ama bir key'i **tek-atamalı yapmaz**: aynı key'e ikinci bir `PutObject` yeni bir version yaratır (orijinal version değişmez kalır, "latest" pointer kayar). Yani "latest taşındı" tamper'ına karşı değişmezlik **overwrite-reddinden değil**, ledger'a pin'lenen `object_version_id` + version-specific SHA-256 doğrulamasından gelir (§D4.7). Worker hiçbir zaman kör re-PUT yapmaz; her zaman HEAD-first + kayıtlı-version doğrular.

> **PROD CAVEAT (legal-grade WORM ≠ test)**: Tek-host MinIO, root/fiziksel erişime karşı **legal-grade WORM değildir**. Production audit-archive ADR'si şunları **şart** koşar: off-host immutable replication/backup, provider-seviyesi S3 Object Lock (ya da dedicated WORM appliance), ve MinIO admin işlemlerinin ayrı audit'i. Test ortamı kanıtı (D29) prod legal-WORM iddiası **değildir**.

### D4 — Worker contract (Codex call-5 REVISE absorbed)
1. **Eligibility**: bir satır `event_timestamp < now() - HOT_WINDOW` ise "soğumuş" sayılır (`HOT_WINDOW` configurable, default **90 gün**). Hot satırlar DB'de kalır.
2. **İlerleme cursor'u = monotonik `seq`, YALNIZ no-gap contiguous prefix üzerinde ilerler** (zaman değil; asla satır atlamaz). Batch taraması: `SELECT ... WHERE seq > :cursor ORDER BY seq ASC LIMIT :batch`; eligibility filtresi **WHERE'de değil tarama sırasında** uygulanır — ilk **hot/ineligible** satırda batch **DURUR**, o satırın ötesindeki eligible satırlara **zıplanmaz**; cursor yalnız kesintisiz-eligible prefix'in son `seq`'ine ilerler. (Aksi halde `seq=100` hot iken `seq=101` geç-gelen eski `event_timestamp` ile eligible olursa cursor 101'e zıplar ve `seq=100` sonradan soğuduğunda kalıcı **arşiv-dışı** kalırdı. Out-of-order geç-gelen event'ler `seq` > insert-order taşıdığından, contiguous-prefix kuralı her satırın eninde sonunda arşivlenmesini garanti eder.)
3. **State tabloları** (worker'a ait — **ayrı schema `audit_archive`** + **izole Flyway history** `audit_archive.audit_retention_flyway_history`; worker yalnız `audit_event.audit_event`'e `SELECT`, `audit_archive.*`'e owner — consumer'ın schema'sı yazma yüzeyine açılmaz; Codex C(b) AGREE):
   - `audit_archive_cursor` (singleton): `last_archived_seq bigint`, `updated_at`.
   - `audit_archive_ledger` (arşivlenen her obje için bir satır): `object_key`, `chain_scope`, `min_seq`, `max_seq`, `row_count`, `min_event_timestamp`, `max_event_timestamp`, `entry_hash_alg`, `entry_hash_version`, `object_sha256`, **`object_version_id`**, `manifest_sha256`, **`manifest_version_id`**, `retention_until`, `worker_image_digest`, `verify_status`, `created_at`, ve anchor temsili — **PER_TENANT (V1)** → `tenant_anchors` (JSONB; her satırın **değişmez per-object chain proof snapshot'ı**, §D4.6); (GLOBAL dalı: `first_prev_hash`+`last_entry_hash` — V1'de aktif değil).
   - **`audit_archive_tenant_anchor`** (tenant başına bir satır — **authoritative mutable watermark**; Codex C(c) AGREE): `tenant_id bigint PK`, `last_entry_hash varchar(64)`, `last_archived_seq bigint`, `updated_at`. Per-tenant chain sürekliliği batch-sınırları arasında **bu tablodan** O(1) okunur (ledger JSONB taranmaz); cursor + ledger + anchor **aynı DB transaction'ında atomik** ilerler (singleton cursor row + etkilenen anchor row'ları `FOR UPDATE` kilitlenir, S3 version/checksum/retention doğrulaması **commit'ten önce** yapılır).
4. **Verify-before-archive (fail-closed)** — **`CHAIN_SCOPE ∈ {GLOBAL, PER_TENANT}`** parametresine göre:
   - **GLOBAL** (chain global `seq` sırasıyla linkli): (a) segment-içi süreklilik — sıralı her satırın `prev_hash`'i bir önceki satırın `entry_hash`'ine eşit; (b) **anchor continuity** — segmentin ilk satırının `prev_hash`'i bir önceki arşiv objesinin `last_entry_hash`'ine eşit (ledger). Ledger/manifest tek `first_prev_hash`/`last_entry_hash` taşır.
   - **PER_TENANT** (chain `tenant_id` başına linkli): bir segment birden çok tenant kapsayabileceğinden ardışık global-`seq` satırları birbirinin predecessor'ı **olmayabilir** → doğrulama **tenant bazlı** yapılır; manifest/ledger `tenant_anchors[]` (`{tenant_id, first_prev_hash, last_entry_hash}`) taşır; anchor continuity bir önceki segmentin **per-tenant** anchor'larına karşı tenant bazlı doğrulanır.
   - Her iki modda kırık varsa: **arşivleme YOK, cursor ilerlemez, alert** (`audit_archive_chain_break_total` + DLQ/alert).
   - **HARD GATE (C-slice) — RESOLVED = `PER_TENANT`** (2026-06-17): `CHAIN_SCOPE` canlı consumer kodundan teyit edildi (`AuditIntegrityVerifier.verifyTenant` tenant-local walk + `AuditChainSupport` tenant-GENESIS semantiği + V1 SQL `prev_hash` COMMENT "same tenant chain" + `(tenant_id, seq DESC)` index + `findTop1ByTenantIdOrderBySeqDesc`; provenance `platform-backend@74c9e1a9`). **V1 worker yalnız PER_TENANT derlenir; runtime'da scope flip etmez.** Global `seq` yalnız batch/cursor özelliğidir (no-gap ilerleme), chain semantiği değil. Sentetik varsayım yapılmadı; teyit kod-kanıtına dayanır.
5. **Format (V1)**: **NDJSON.gz** (satır başına bir JSON, tam kolon seti) + **manifest JSON**. (Parquet sonra, yalnız analytics mirror olarak — arşiv truth NDJSON.gz.)
6. **Manifest alanları**: `schema_version`, `artifact_kind="audit-archive-segment"`, `chain_scope` (`GLOBAL`|`PER_TENANT`), `row_count`, `min_seq`, `max_seq`, `min_event_timestamp`, `max_event_timestamp`, `entry_hash_alg`, `entry_hash_version`, `object_sha256` (NDJSON.gz digest), `retention_until`, `source_watermark` (cursor before→after), `worker_image_digest`, `created_at`, + chain anchor'ları: **GLOBAL** → `first_prev_hash` + `last_entry_hash`; **PER_TENANT** → `tenant_anchors[]` (`{tenant_id, first_prev_hash, last_entry_hash}`). **`manifest_sha256` (self-digest) manifest gövdesinde TUTULMAZ**: değer, `manifest_sha256` alanı **omit/null** iken canonical JSON (sorted keys, UTF-8, anlamsız-boşluk yok) üzerinden SHA-256 ile hesaplanır ve **ledger'a** (+ istenirse `<key>.sha256` sidecar'a) yazılır — gövdeye geri yazılıp kendi hash'ini geçersizleştirmez.
7. **Yazım sırası + idempotency = `version_id` modeli (AMENDED — Codex C-plan AGREE)** — object key `min_seq–max_seq`'ten deterministik türetilir. Önemli düzeltme: Object Lock+versioning aynı key'e re-PUT'u **engellemez** (yeni version yaratır); bu yüzden idempotency "overwrite-reddine" değil, **ledger'a pin'lenen version_id + version-specific SHA-256 doğrulamasına** dayanır. Re-run davranışı (sıralı):
   1. Ledger/cursor'u oku (bu segment daha önce işlendi mi?).
   2. `HEAD` **latest** key.
   3. Ledger kaydı varsa → kayıtlı `versionId` ile **version-specific** `GET`/`HEAD`.
   4. `object_sha256`'yı **checksum header `x-amz-checksum-sha256` veya immutable user-metadata** ile doğrula (**salt ETag YASAK**).
   5. Retention / object-lock header'ını doğrula: mode=COMPLIANCE **ve `retention_until == ledger.retention_until`** (veya `>= ledger.expected_min_retention_until`). Re-run aylar sonra olabileceğinden `now+7yr` ile **DEĞİL**, ilk yazımda ledger'a **pin'lenen** retention değeriyle karşılaştırılır (aksi halde her geç re-run false-mismatch verirdi).
   6. **latest version == ledger'daki kayıtlı version** assertion'ını yap.
   7. **latest farklıysa** (beklenmeyen ekstra version) → **fail-closed**: `audit_archive_anomaly_total`, **re-put YOK, cursor ilerlemez**, alert.

   **Ledger kaydı YOK + HEAD 200 (key zaten var)** — fail-closed: worker **kör PutObject YAPMAZ**; `audit_archive_anomaly_total` + alert, **cursor ilerlemez** (crash-after-PUT-before-DB-commit veya dış müdahale senaryosu; V1 güvenli davranış = fail-closed; bilinçli "adoption" prosedürü ayrı/manuel iştir, otomatik değil).

   **İlk yazım (ledger kaydı YOK + HEAD 404)**: `retention_until = write_time + 7yr` **hesaplanır ve ledger'a pin'lenir** (re-run karşılaştırma ekseni budur, §step-5) → `PutObject(NDJSON.gz, retention=COMPLIANCE retain-until=<pinned>, checksum-sha256)` → dönen **`x-amz-version-id`** yakalanır → version-specific HEAD verify (size + checksum + retention) → `PutObject(manifest.json, checksum-sha256)` → version-id yakala + HEAD verify → **tek DB transaction'ında atomik**: `audit_archive_ledger` insert (`object_version_id`/`manifest_version_id`/`object_sha256`/`manifest_sha256`/`retention_until`/`tenant_anchors`) + `audit_archive_tenant_anchor` upsert + `audit_archive_cursor` advance (S3 doğrulaması **commit'ten önce**). Worker cred (§D5) Delete*/Bypass'i reddeder → her version değişmez kalır. **Bucket-policy create-only deny V1 blocker DEĞİL** (Codex AGREE); **AWS SDK v2 (S3-compatible client)** `If-None-Match: *` create-only PUT destekliyorsa **defense-in-depth** olarak kullanılır, ama portable correctness sınırı worker-side HEAD-first + kayıtlı-version + latest-anomaly + no-delete-cred'dir (non-portable bucket-policy koşuluna güvenlik için bağımlı OLUNMAZ).
8. **Kaynak silme YOK**: worker hiçbir satırı silmez (append-only trigger zaten engeller). 7yr **sonrası** silme = ayrı **legal-hold / dual-control** ADR konusu, bu worker'ın kapsamı dışında.
9. **Katman-2 (KVKK m.12 erişim-logu, 2yr) explicit EXCLUDE**: farklı tablo/path; bu worker'a dahil değil.
10. **Payload guard**: arşiv yalnız `audit_event` kolonlarını taşır (transcript/ses payload kolonu schema'da yok); worker hiçbir transcript/ses içeriği serialize etmez.

### D5 — Worker credential least-privilege (Codex call-3 absorbed)
Worker MinIO service-account'u **yalnız**: `s3:PutObject`, `s3:GetObject`, `s3:GetObjectRetention`, `s3:PutObjectRetention` (yalnız set — COMPLIANCE altında kısaltma imkânsız), `s3:ListBucket`. **YASAK**: `s3:DeleteObject`, `s3:DeleteObjectVersion`, `s3:BypassGovernanceRetention`, admin/key-yönetimi. (COMPLIANCE mode'da root bile süre dolmadan silemez/kısaltamaz.)

## 4. Acceptance (C + D fresh session için exit kriteri)

- **D29 (A — bu oturum)**: MinIO Up; `audit-archive` bucket object-lock + versioning + COMPLIANCE 7yr default retention configured; in-cluster pod'dan **put/get/head OK**; **locked-version DELETE / retention-shorten / bypass DENIED** (same-key yeni-version PUT cred/storage seviyesinde denied DEĞİL — version-retention semantiği §D4.7; "latest taşındı" anomaly'si C-worker'da fail-closed yakalanır); retention header doğru; ESO/Vault path + NetPol yalnız gerekli trafiğe izin.
- **C worker**: Testcontainers (MinIO + PG); `CHAIN_SCOPE`=PER_TENANT (D4.4 RESOLVED, kod-teyit); no-gap contiguous-prefix cursor (atlanan satır yok); **per-tenant** verify-before-archive fail-closed (kırık tenant-chain → no-archive + alert); idempotent re-run (`version_id` HEAD-reuse + **latest-version anomaly fail-closed**, kör re-put YOK); deterministic NDJSON.gz byte-identical + manifest digest round-trip; least-privilege cred (Delete*/Bypass denied → version'lar değişmez; not: yeni-version PUT cred-seviyesinde "denied" değil, worker HEAD-first ile asla kör re-put yapmaz).
- **Observability**: Prometheus alert'leri — `audit_archive_lag_seconds` (soğumuş ama arşivlenmemiş en eski satır yaşı), `audit_archive_chain_break_total`, `audit_archive_errors_total`, DLQ/skip sayacı.
- **NetPol**: worker egress yalnız MinIO host-bridge (`:9000`) + PG.

## 5. Production-Promotion Gate

- Off-host immutable replication + provider/legal-grade WORM (D3 caveat) **prod-cutover prerequisite**'i.
- Worker cred prod realm'de Vault'tan; direct root cred YASAK.
- KVKK retention policy referansı platform-ai#159; gitops ADR-0030 placeholder'ının tam-ACCEPTED'a çekilmesi prod öncesi tamamlanır (ayrı governance işi).

## 6. Consequences

**Artı**: tamper-evident 7yr WORM archive (3-katman değişmezlik); arşiv failure domain'i consumer'dan ayrı; monotonik-`seq` cursor → deterministik, resumable, idempotent; transcript/ses arşive yapısal olarak giremez (schema guard).

**Eksi / risk**: tek-host MinIO legal-grade WORM değil (prod caveat, §5); worker kendi Flyway'ını taşır (cursor/ledger); hash-chain canonical sırası C başında consumer'dan teyit gerektirir (sentetik varsayım reddi).

## 7. Out-of-Scope (bu ADR / bu oturum)

- **C** backend `audit-retention-worker` kodu (fresh backend session; `platform-backend` checkout reconcile + worktree).
- **D** worker CronJob deploy + observability wiring.
- 7yr-sonrası legal-hold/dual-control silme ADR'si.
- gitops ADR-0030 placeholder'ın tam-ACCEPTED metni.

## References

- Issue gitops`#1250` (worker) + object-store prerequisite issue (A).
- Canlı pipeline: gitops`#1648` (audit E2E activation), `#1645` (enforce seed).
- Codex plan-time thread `019ed4f4-1d6b-7bd3-8cad-175487fa7a9b` (A+B AGREE).
- KVKK policy: platform-ai **KVKK policy ADR (PR#159)** ACCEPTED (3-AI mutabakat) + issue #52/#60. *(Bu policy ADR ile bu repo'daki gitops ADR-0030 placeholder'ı ayrı belgelerdir — §2.)*
- BE-016 hash-chain + `audit_event` append-only trigger (platform-backend #677/#1249).
