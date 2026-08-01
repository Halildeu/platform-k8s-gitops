# ADR-0035 — Evidence Storage Contract v0 (Faz 22.8 owns; Faz 22.6 consumes)

> **Status**: PROPOSED / **BLOCKED** — runtime: #1388 + #1390 + ADR-0012-EA §0 (DD-EA-9 + DC-EA) + DPO/legal sign-off.
> **Tarih**: 2026-06-09 · **Owner faz**: 22.8 (Endpoint Data Protection/Forensic) · **Consumer**: 22.6 (Remote Access session recordings)
> **Cross-AI**: Implementer Claude (Opus 4.8) / Reviewer Codex (OpenAI) — thread `019ea961` AGREE.
> **İlişkili**: [22.8 plan](../faz-22-endpoint-data-protection-plan.md), [ADR-0033 broker](0033-faz-22-6-remote-access-bridge-broker.md), [ADR-0012-EA](0012-EA-endpoint-admin-governance-charter.md), [#1388 acceptance package](../faz-22-6-1388-acceptance-package.md), BE-016.

Bu ADR, hassas endpoint evidence'ı (forensic koleksiyon, offboarding copy, backup,
ve 22.6 session recording) için **tek, paylaşılan evidence-storage-contract**'ı
tanımlar. Amaç: 22.8 ve 22.6'nın **iki ayrı/çelişen storage tasarımı üretmesini
engellemek**; chain-of-custody, retention, immutability ve KVKK'yı tek yerde
mühürlemek. **22.8 contract owner'dır** (22.8C forensic en sıkı gereksinimi
getirir); 22.6 yalnız tüketir.

**Standartlar:** ISO/IEC 27037 (digital evidence handling), ISO/IEC 27040
(storage security), NIST SP 800-86 (forensic integration), S3 Object-Lock / WORM
(SEC 17a-4 benzeri immutability), NIST AU-9/AU-10 (audit protection / non-repudiation).

---

## Karar (PROPOSED)

### 1. Storage substrate — object storage + Object-Lock/WORM (default)

- **Default:** object storage (S3-compatible) with **Object-Lock (compliance mode) / WORM**.
- **Per-case object prefix:** `evidence/<opaque_case_uuid_or_job_uuid>/...` —
  **opaque UUID** (izolasyon + ACL boundary). **Human-readable `legal_case_id`,
  HR ticket, employee identifier, custodian name, hostname object key'de veya
  object-store listesinde GÖRÜNMEZ**; yalnız backend DB / signed manifest içinde
  RBAC altında tutulur.
- **Encryption-at-rest:** per-case **KMS key** (crypto-erase'in temeli, §5).
- **Legal-hold flag:** retention dolsa bile silmeyi bloklar (forensic/dava).
- **SMB fallback** yalnız: per-case isolated write target + ACL + encryption +
  **write-once / WORM-equivalent control** + hash-manifest + immutable audit.
  **WORM-equivalent yoksa 22.8C forensic için KABUL EDİLMEZ** (en fazla
  non-forensic / lab / degraded backup fallback). **Genel share kabul edilmez.**

### 2. Per-object metadata — iki katman (sızıntı önleme)

Storage-list / read-metadata yetkisi olan biri fazla şey görmesin diye metadata
**ikiye ayrılır**:

- **Object-store metadata (minimal, düşük-sızıntı):**
  `{ manifest_entry_id, case_uuid, sha256, content_length_declared, dc_ea_tier }`.
  Device/tenant zorunluysa **opaque internal ID** (hostname / UPN / ticket-title YOK).
- **Signed manifest metadata (RBAC altında):**
  `{ source_device_id, tenant_id, collector_identity, path_class,
  acquisition_method+tool_version, chain-of-custody alanları, timestamp }`.
- `path_class` = normalize sınıf (raw path DEĞİL; data minimization).
- DC-EA-RED sınıfı object **hiçbir zaman** manifeste girmez (§ADR-0012-EA DC-EA).

### 3. Manifest = control-plane signed (yalnız agent değil)

- Agent object'leri yükler + agent-side hash bildirir; ama **manifest backend /
  control-plane tarafından imzalanır** (agent'a tek başına güvenilmez).
- **BE-016 hash-chain** pattern: `prev_entry_hash` (SHA256) → tamper-evident,
  append-only, non-repudiation (NIST AU-10).

### 4. Upload finalization (state gate)

- Object yüklenince, backend **object hash + size'ı manifest ile karşılaştırır**.
- **Eşleşmeden** object `collected` state'e GEÇMEZ (`uploaded → verifying →
  collected | rejected`).
- Mismatch → `rejected` + audit; partial/failed upload resume-safe.

### 5. Retention + crypto-erase (WORM-uyumlu)

- Per-substream retention (KVKK inventory ile hizalı; transcript/recording §22.8 plan).
- **Crypto-erase = per-case KMS key destruction.**
- **Object silme WORM-uyumlu:** Object-Lock retention / legal-hold **dolmadan**
  nesne **silinemez** — bu depolama katmanınca zorlanır, politika tercihi değildir.
- **Legal-hold aktifken KMS key destruction YAPILAMAZ**, istisnasız: hold altındaki
  içeriğin anahtarını imha etmek delil karartmasıdır.
- Retention sonu (yasalsa): KMS key destroy + object delete.

> **Revizyon — 2026-08-01 (ADR-0047 K1).** Bu bölümün ilk hâli iki farklı şeyi tek
> cümlede tutuyordu: *nesnenin silinmesi* ve *anahtarın imhası*. Object-Lock
> retention'ı yalnız birincisini engeller. Faz 35 ihbar akışında ihbarcının kendi
> bildirimi için **onaylı erken silme talebi**, legal-hold ve aktif reveal grant
> yokken KMS key destruction'ı tetikleyebilir; şifreli nesne yerinde kalır
> (Object-Lock ihlali yok) ve yalnız erişilemez hale gelir. Saklama yükümlülüğünün
> koruduğu şey içerik değil kayıttır (2019/1937 Art.18, SOX Sec.802) ve o kayıt
> denetim defterinde durmaya devam eder. Tam karar metni ve silme sonrası defterde
> neyin kaldığı: [ADR-0047 §5 K1](0047-faz35-retention-legal-hold-erasure-invariants.md).

### 6. Access control + quarantine

- **Quarantine state:** yüklenen evidence, **DPO/legal release öncesi** quarantine'de
  bekler (özellikle 22.8C forensic). Post-upload **DLP/secret-scan** quarantine'de
  koşar (denylist bypass / archive leakage yakalama).
- **Least-priv viewer** + **per-view immutable audit row** (read'ler write kadar
  önemli — NIST AU-9). İlgili kişi kendi verisine erişim **DPO/redaction-mediated**.
- Recording (22.6) için 3rd-party PII redaction-on-playback (ISO A.5.34).

### 7. Chain-of-custody (22.8C forensic + 22.6 recording)

`case_id · custodian · acquisition_method+tool_version · acquisition_hash ·
transfer_hash[] · storage_URI · object_lock_until · legal_hold · timestamp ·
access_log[]` — ISO 27037 + NIST 800-86 court-admissible. 6 custody point
(acquisition → upload → finalization → storage → access → disposal), her transferde
hash doğrulama.

### 8. Transport binding (agent → storage)

- Scoped **write-only** credential (no read/list/delete) — detay [ADR-0033 §... + 22.8 plan §9].
- Per-job + per-object-prefix, short-TTL, content-length + part cap, checksum header.
- Finalization (§4) olmadan evidence "collected" sayılmaz.

---

## Sonuçlar

**Olumlu:** tek contract → 22.6 + 22.8 storage drift yok; forensic court-admissibility;
KVKK retention/crypto-erase mühürlü; WORM ile manifest tampering + insider delete
engellenir.

**Maliyet:** object storage + Object-Lock + KMS altyapısı; quarantine/DLP pipeline;
runtime #1388 + DPO/legal olmadan açılamaz.

## Alternatifler (reddedildi)

- **Backend üzerinden büyük dosya transit:** ölçeklenmez → reddedildi (direct
  scoped upload).
- **Agent-only signed manifest:** agent compromise → tamper; control-plane co-sign
  zorunlu.
- **Mutable storage + soft-delete:** insider/tamper riski → WORM/Object-Lock.
- **22.6'nın kendi recording storage'ı:** drift → tek contract (22.8 owns).

## Cross-AI Consensus Log

| Tur | Reviewer | Verdict | Absorbe |
|---|---|---|---|
| iter-1/2 | Codex `019ea961` | REVISE→AGREE | 22.8 owns contract; object-lock/WORM + legal-hold; control-plane-signed manifest; finalization verify; crypto-erase WORM-uyumlu (retention/legal-hold sonrası); immutable access audit (reads); quarantine before release |
