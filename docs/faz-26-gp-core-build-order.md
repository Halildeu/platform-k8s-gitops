# Faz 26 — gp-core Build Order (Enforcement Kernel First)

> **Status**: LOCKED — Cross-AI AGREE (Codex thread `019f18f8`, foundation review iter-2 AGREE).
> **Repo**: gp-core implementasyonu **platform-backend**'de (karar "A" — yeni servis mevcut repoda, izolasyon namespace/board/store).
> **Spec**: ontology v2 [`docs/faz-26-ontology-v1.md`](./faz-26-ontology-v1.md) + OpenFGA v2 [`runtime-artifacts/faz26-gp/authorization-model-v1.fga`](../runtime-artifacts/faz26-gp/authorization-model-v1.fga)
> **HARD ilke (Codex)**: İlk sprint çıktısı süreç ekranı / RAG demo / dashboard **DEĞİL**; **enforcement kernel** (izinli graph read/write + evidence ledger). UI/AI/report gerçek veriyle çalışmadan önce bulk-auth + scope-conflict testleri yazılmış olmalı.

---

## Build sırası (kilitli — bu sırayla)

### 1. Read Gateway contract + enforcement tests  ← İLK
Tüm okuma yolları tek policy path. Minimum API: `getNode` · `getEdges` · `traverse` · `search` · `resolveEvidence` · `resolveRagChunks` · `exportAuditBundle`.
**Acceptance test'leri (kanıtlamalı):**
- Source görünür / target gizli → edge YOK.
- Target görünür / source gizli → edge YOK.
- Edge scope gizli → edge YOK.
- Hidden-count default GÖSTERİLMEZ.
- RAG aday ID dönse bile chunk text **auth olmadan resolve edilemez**.
- Report/export **bypass olmadan** çalışır.
- Cross-user summary cache YOK.
- **Deny, partial-allow'u ezer** (deny-overrides).

### 2. Typed node/edge schema + reified relationship model
`node` · `edge` · `node_scope` · `edge_scope` · `control_definition` · `control_instance` · `requirement` · `requirement_status` · `coverage_mapping` · `evidence_object` · `evidence_binding`. Amaç: tüm ürünü modellemek değil, **v2 permission semantics'i taşıyan minimum iskelet**. PG (adjacency + recursive CTE + closure, index source/target/type/scope, depth/budget limit), AGE-göç-edilebilir.

### 3. OpenFGA model + tuple writer  (schema'dan SONRA)
- Tuple yazımı **ad hoc değil** — gp-core domain transaction / outbox event üzerinden.
- Fail-mode tanımlı: tuple write fail → object `unreadable/pending-auth` ya da transaction rollback (görünürlük belirsiz KALMAZ).
- **Tuple drift detector**: DB scope ↔ FGA tuple karşılaştırma.

### 4. Evidence event ledger  (erken — sonradan migration pahalı)
append-only `evidence_event` · event hash-chain · WORM object ref · current-state projection · event tipleri: legal-hold/disposition · access/export · binding/unbinding · custodian-transfer.

### 5. RAG/search integration  (yalnız Gateway kanıtlandıktan SONRA)
gp-ai erken bağlanır ama **yalnız Read Gateway üzerinden**. İlk RAG acceptance = "cevap veriyor" değil, **"yetkisiz chunk asla context'e girmiyor"**.

## Kalan açık maddeler — ilk impl dalgasında test-edilebilir karar olarak kapatılacak

| Madde | Karar (Codex önerisi) |
|---|---|
| **Bulk authorization** (en yüksek operasyonel risk) | Bounded traversal + tek `AuthorizationDecisionService` + batched/cached OpenFGA; **cache key = principal+object+relation+policy_version+tuple_revision/snapshot**; deny-by-default + kısa TTL. Subject-visible projection sonra (gelirse invalidation/rebuild contract şart). |
| **Scope-conflict resolution** | **deny-overrides**: classification / legal_hold / policy_tags ABAC katmanı OpenFGA allow'un üstüne **deny** üretebilir. OpenFGA = "kim ilişkili"; KVKK/evidence policy = "bu bağlamda bu veri çıkabilir mi". |
| **Process template/instance** | Defer OK (stable ID + definition/instance pattern + reified edge migration path açık). |

> **Codex son uyarı**: bulk-auth + scope-conflict Read Gateway acceptance testlerine **gömülmeden** hiçbir UI/report/AI gerçek veriyle çalıştırılmaz — yoksa doğru mimari pratikte "bypass kültürü"ne döner.

## References
- Cross-AI: Codex `019f18f8` (foundation REVISE→AGREE)
- Plan: `docs/faz-26-governed-process-platform-plan.md` · Acceptance: `docs/faz-26-26b-27-acceptance.md`
- Board: Project #7 "Epic 26A — Internal Foundation"
