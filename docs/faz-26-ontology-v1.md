# Faz 26 — Ontology v2 (Bağlı-Veri / Graph Model)

> **Status**: DRAFT v2 (Faz 26A foundation) — Codex REVISE (thread `019f18f8`) absorbe edildi; AGREE-confirm pending.
> **Ref**: [`docs/faz-26-governed-process-platform-plan.md`](./faz-26-governed-process-platform-plan.md) · OpenFGA model: [`runtime-artifacts/faz26-gp/authorization-model-v1.fga`](../runtime-artifacts/faz26-gp/authorization-model-v1.fga)
> **Sahibi**: `gp-core-service` (impl platform-backend; bu doküman canonical spec).
> **v2 değişiklik (Codex absorb)**: Read Gateway choke-point · edge-visibility policy · definition/instance/binding ayrımı · reified coverage_mapping · evidence event ledger · katalog≠status.

---

## 1. Tasarım ilkeleri (v2)

1. **Tipli generic node + edge** — `(type, attrs)` node + `(type, from, to, scope)` edge. Any-entry pivot/karma-filtre bunun üstünde.
2. **Read Gateway = tek data-plane choke-point (Codex #1, HARD)** — UI / gp-ai / RAG / search / report / export **doğrudan PG/MinIO/vector/Ollama-context'e erişemez**; **hepsi `gp-core` Read Gateway'den** geçer. OpenFGA check helper değil, **data-plane policy enforcement point**. Bkz §8.
3. **Edge visibility policy (Codex #2)** — edge görünür ⇔ `can_view(source) AND can_view(target) AND can_view(edge_scope)`. Gizli bağlı node sayısı ("3 hidden control") default **gösterilmez** (count-leak).
4. **Definition / Instance / Binding ayrımı (Codex #3/#6)** — katalog (org-visible) ≠ operasyonel uygulama (scoped) ≠ kanıt bağlamı. Cross-unit = canonical object + scoped binding.
5. **Mutable node → change-history; evidence → immutable + append-only lifecycle event ledger (Codex #5)**. WORM/hash-chain ADR-0042 reuse.
6. **Crosswalk reified (Codex #4)** — `satisfies` düz edge değil; `coverage_mapping` ilişki-nesnesi.
7. **Reuse** — actor=Keycloak; evidence blob=WORM/MinIO; rapor=report-service; grid=AG-Grid. Ontology yalnız **ilişki/anlam + izin** katmanı.

## 2. Node tipleri (entity) — v2

### 2.1 Yapısal / scope
| Tip | Açıklama | Mutable |
|---|---|---|
| `organization` | Kurum/tenant | evet |
| `unit` | Birim/departman (parent) | evet |
| `actor` | Kişi/rol (Keycloak ref) | evet |
| `process` | Süreç | evet |
| `step` | Süreç adımı | evet |

### 2.2 Governance — katalog (org-visible) vs uygulama (scoped)
| Tip | Katman | Açıklama |
|---|---|---|
| `framework` | katalog | ISO/COSO/KVKK/Kamu İK |
| `requirement` | **katalog** | çerçeve maddesi/ilke (org-visible tanım) |
| `control_definition` | **katalog** | kontrolün ortak tanımı |
| `control_instance` | **scoped** | unit/process'teki uygulanışı (status/owner/freq) |
| `requirement_status` | **scoped** | bir requirement'ın unit/process'teki uyum durumu/gap |
| `coverage_mapping` | **reified ilişki** | control_definition↔requirement (coverage_level/rationale/status/source/approved_by/effective_from/version) |
| `risk` | scoped | risk (likelihood/impact/inherent/residual) |
| `kpi` | scoped | gösterge (target/threshold/value) |
| `policy` | org/scoped | politika (lifecycle) |
| `rule` | scoped | kural (expr) |
| `task` | scoped | görev/aksiyon (owner/due/status/sla) |
| `assessment` | scoped | değerlendirme/olgunluk (0-5) |

### 2.3 Evidence — immutable object + binding + event ledger (Codex #5)
| Tip | Açıklama |
|---|---|
| `evidence_object` | **immutable** içerik kimliği (immutable_id, hash_chain_ref, content_ref→WORM) |
| `evidence_binding` | bu kanıtın hangi control_instance/assessment/task/requirement_status için hangi scope'ta delil olduğu (N-N) |
| `evidence_event` (ledger) | **append-only**: `custody` / `binding` / `retention(legal_hold/disposition)` / `access(view/export/download)` — her olay hash-chain/WORM'a bağlı |

> `evidence_object` zorunlu alan: immutable_id · hash_chain_ref · content_ref · retention_class · record_vs_evidence. Mutable lifecycle (owner/custody/legal_hold/disposition) **event ledger** ile; array `custody_log[]` KULLANILMAZ.

## 3. Edge tipleri (ilişki) — v2

| İlişki | from → to | Kardinalite | Not |
|---|---|---|---|
| `contains` | process → step | 1-N | |
| `responsible` | step/task/control_instance → actor | N-1 | sahip |
| `has_risk` | step/process → risk | N-N | edge-scope taşır |
| `mitigated_by` | risk → control_instance | N-N | |
| `implements` | control_instance → control_definition | N-1 | katalog→uygulama |
| `(coverage_mapping)` | control_definition ↔ requirement | reified | **düz edge değil** |
| `status_of` | requirement_status → requirement | N-1 | scoped uyum |
| `belongs_to` | requirement → framework | N-1 | katalog |
| `measured_by` | control_instance/process → kpi | N-N | |
| `(evidence_binding)` | evidence_object ↔ control_instance/assessment/task/requirement_status | reified N-N | |
| `addresses` | task → risk/control_instance/requirement_status (gap) | N-N | |
| `governed_by` | control_instance/process → rule/policy | N-N | |
| `evaluates` | assessment → control_instance/requirement_status | N-1 | |
| `scoped_to` | * → organization/unit | **N-N** (multi-scope) | cross-unit için canonical+binding |

## 4. Pivot / karma-filtre kontratı (any-entry)

- Giriş: herhangi node. Traverse: `depth=1..k` (**limit + query budget zorunlu**), edge-tipi + node-tipi + attr filtresi, karma birleşim serbest.
- **Bounded permission-filtered traversal** — sınırsız graph exploration DEĞİL; her hop Read Gateway can_view + edge-visibility policy uygular (traversal sırasında prune, post-filter değil).
- Çıktı: `{nodes[], edges[]}` (yalnız görünür) + sayfalama (AG-Grid/çiçek).

## 5. İzin çapası (OpenFGA bağlama)

- Her node `scoped_to` org/unit (N-N) → OpenFGA viewer/editor/owner.
- `control_definition`/`requirement`/`framework` = katalog (org-visible); `control_instance`/`requirement_status`/`risk`/`evidence_binding` = scoped (izinli).
- **Tek can_view doğruluk kaynağı** Read Gateway'de; tüm okuma yolları (graph/search/RAG/report/AI) aynı policy path.

## 6. Evidence lifecycle (immutable + event ledger)

`evidence_object` immutable; **lifecycle = append-only `evidence_event`**: custody-transfer · binding-add/remove · legal-hold set/unset · disposition requested/approved/executed · access (view/export). Current-state (owner/custody/hold) = event'lerden **projection**. Ledger hash-chain → WORM kanıt zinciri. Relation'lar: `custodian` / `records_manager` / `legal_hold_manager` / `reviewer` (editor YOK).

## 7. Graph storage kararı (Codex #3)

**MVP = PostgreSQL**: typed `nodes` + `edges(source_id,target_id,edge_type,scope_id,valid_from/to,status)` adjacency + closure/recursive CTE + (gerekirse ltree/materialized path). İndeks: source/target/type/scope. **Sınırlar baştan**: depth limit, query budget, bounded neighborhood. **AGE/graph-DB baştan YASAK** (sprawl); ama AGE-göç-edilebilir tasarla (stable ID, edge metadata, no ORM magic). Deep analytics/centrality/impact ağırlaşırsa AGE değerlendir.

## 8. Read Gateway kontratı (Codex #1 — tek choke-point)

| Kural | |
|---|---|
| Tek erişim noktası | gp-ai/search/RAG/report/UI **yalnız** gp-core Read Gateway üzerinden; DB/vector/blob/Ollama-context **bypass YASAK** (read-only bile) |
| Karar noktaları | node okunabilir? edge okunabilir? edge'in iki ucu? evidence metadata? evidence blob/export? AI-context'e girebilir? özet cache güvenli? |
| RAG pattern | vector index yalnız `object_id, chunk_id, org, scope, classification, policy_tags, embedding` (metin YOK) → retrieval aday ID → `can_view_context(user,object_id,action=rag_read)` filtre → sonra chunk text resolve |
| AI özet cache | global/cross-user **YASAK**; key ≥ `principal + scope + policy_version + source_hashes`; veya yalnız authorization-filtered kaynaktan yeniden üret |

## 9. Açık noktalar (AGREE-confirm sonrası)

- Bulk authorization: her query'de N OpenFGA call mı, subject-visible projection mı (performans).
- Scope conflict resolution (multi-scope node, çelişen izin).
- Process template vs instance ayrımı gerekecek mi (v2'de defer).

## References
- Cross-AI: Codex `019f18f8` (foundation REVISE absorb)
- Plan: `docs/faz-26-governed-process-platform-plan.md` · Acceptance: `docs/faz-26-26b-27-acceptance.md`
- WORM/records: ADR-0042 · İzin: permission-service + OpenFGA (ayrı store)
