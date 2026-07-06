# ADR-0035 — Faz 26 Permission Enforcement Contract (Read Gateway + Deny-Overrides)

> **Status**: ACCEPTED (2026-06-30) — Cross-AI: Codex `019f18f8` foundation review **kritik madde** ("izin-farkında graph iddiasını delmeye en yakın yer burası"; AGREE = bu kontrat acceptance test'lerine gömülürse). Scope: Faz 26 (ADR-0033). En kritik mimari kontrat.

---

## Context

Ürünün çekirdek iddiası: **izin-farkında graph** (herhangi düğümden gir, yalnız yetkili olduğunu gör, RAG/AI dahil). Codex'in tespiti: bu iddia mimari olarak **zorlanmazsa** ilk sızıntı vector search / full-text / cache / özet tablosu / async AI job / report-service bypass üzerinden doğar. "Her okuma can_view'den geçer" cümle olarak yetmez; **tek choke-point + deny-overrides** şart.

## Decision

1. **Tek Read Gateway choke-point (HARD)**: tüm okuma (UI / gp-ai / RAG / search / report / export / AI-context) **yalnız** `gp-core` Read Gateway üzerinden. gp-ai/report-service/search **doğrudan PG/MinIO/vector/Ollama-context'e erişemez** (read-only bile **YASAK**). OpenFGA = **data-plane policy enforcement point**, helper değil.

2. **Edge visibility policy**: edge görünür ⇔ `can_view(source) AND can_view(target) AND can_view(edge_scope)`. Gizli bağlı node **sayısı bile** default gösterilmez (count-leak). Traversal sırasında prune (post-filter değil); **depth-limit + query-budget + bounded neighborhood**.

3. **Deny-overrides (ABAC katmanı)**: OpenFGA allow **yeterli değil**. `classification` / `legal_hold` / `policy_tags` (KVKK/evidence policy) OpenFGA allow'un **üstüne deny** üretebilir. OpenFGA = "kim hangi nesneyle ilişkili"; policy katmanı = "bu bağlamda bu veri çıkarılabilir mi". **Deny her zaman partial-allow'u ezer.**

4. **RAG pattern**: vector index yalnız `object_id, chunk_id, org, scope, classification, policy_tags, embedding` (**metin YOK**) → retrieval aday ID → `can_view_context(user, object_id, action=rag_read)` filtre → **sonra** chunk text resolve. İlk RAG acceptance = "cevap veriyor" değil, **"yetkisiz chunk asla context'e girmiyor"**.

5. **AI özet cache**: cross-user/global **YASAK**; key ≥ `principal + scope + policy_version + source_hashes`; veya yalnız authorization-filtered kaynaktan yeniden üret.

6. **Bulk authorization**: bounded traversal + tek `AuthorizationDecisionService` + batched/cached OpenFGA; cache key = `principal + object + relation + policy_version + tuple_revision/snapshot`; **deny-by-default + kısa TTL**. Subject-visible projection sonra gelebilir → gelirse invalidation/rebuild contract şart (stale-projection leak).

7. **Tuple writer**: ad hoc değil — gp-core **domain transaction / outbox event** üzerinden. Fail-mode tanımlı (tuple write fail → object `pending-auth/unreadable` ya da rollback; görünürlük belirsiz KALMAZ). **Tuple drift detector** (DB scope ↔ FGA tuple).

8. **Acceptance gate (HARD)**: bulk-auth + scope-conflict + edge-visibility **Read Gateway acceptance test'lerine gömülmeden** hiçbir UI/report/AI **gerçek veriyle** çalıştırılmaz. (Yoksa doğru mimari pratikte "bypass kültürü"ne döner — Codex.)

## Consequences

- ✅ Tek PEP + deny-overrides → "izin-farkında graph" iddiası mimari olarak savunulabilir.
- ✅ RAG/cache pattern → AI sızıntısı (en yüksek risk) baştan kapalı.
- ⚠️ Bulk auth performans riski → bounded + batched + cache; UI/AI bağlanmadan önce perf+correctness test.
- ⚠️ Her okuma yolunun Gateway'den geçmesi = report-service/gp-ai entegrasyonu Gateway API'sine bağımlı (doğrudan DB join değil).

## References
- ADR-0033 (charter), ADR-0034 (KVKK/PII/classification besler), Ontology v2 §2/§3/§8, Build order `docs/faz-26-gp-core-build-order.md`
- Cross-AI: Codex `019f18f8` (foundation review — bu kontrat kritik madde)
