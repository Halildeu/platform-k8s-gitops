# ADR-0034 — Faz 26 KVKK & Data Boundary (Governed Process & Work Platform)

> **Status**: ACCEPTED (2026-06-30) — Cross-AI: Codex `019f180a`/`019f18f8` AGREE + owner. Scope: Faz 26 (ADR-0033 charter). Faz 24 ADR-0030 (Meeting Intelligence KVKK) deseni reuse, supersede etmez.

---

## Context

İlk dikey = TR kamu/regüle holding iç-kontrol + KVKK + **kanıt yönetimi**. İşlenen veri: süreç/kontrol/risk + **doküman + kanıt (evidence)** + kişi/rol + denetim izi. Bir kısmı KVKK kapsamında (kişisel/özel kategori). Ürünün satış vaadi: **"verisi sunucudan çıkmaz"**.

## Decision

1. **On-prem only (HARD)**: doküman/süreç/kanıt içeriği + AI işleme (embedding/RAG/özet/IDP) **yerel** (ollama). Dış LLM/cloud'a içerik **gönderilmez**. (Satış vaadi + KVKK + güven.)

2. **PII tespit + redaksiyon**: Read Gateway + AI çıktısında PII (TC/IBAN/sağlık vb.) tespit/redaksiyon; izinsiz PII log'a/AI-çıktıya **sızmaz** (ADR-0035 deny-overrides ile birlikte).

3. **Evidence/records boundary**: `evidence_object` immutable + append-only `evidence_event` ledger + **WORM (ADR-0042 reuse, ayrı bucket)**; `retention_class` + `legal_hold` (stub-model Faz 26 → full retention/disposition/e-discovery Faz 28). Her evidence erişimi (view/export/download) audit-event üretir.

4. **Çerçeveler**: KVKK + Kamu İç Kontrol (COSO-temelli) + ISO 27001/9001/31000 + COSO; katalog org-visible, operasyonel uyum (status/gap/evidence) scoped (ADR-0035).

5. **Cross-server (varsa)**: gp-ai ayrı host'taysa içerik transit **mTLS/WireGuard** (ADR-0031); private LAN yetmez.

6. **Veri sınıflandırma**: node/evidence'ta `classification` + `policy_tags`; bu etiketler ADR-0035 deny-overrides ABAC katmanını besler (sınıflandırma OpenFGA allow'u **ezebilir**).

7. **Retention/silme**: retention-class bazlı; legal-hold varken disposition engellenir; silme = disposition workflow (Faz 28), evidence audit-chain **immutable** kalır.

## Consequences

- ✅ "Veri sunucudan çıkmaz" + WORM + audit → kamu/regüle satış için kredibilite.
- ✅ KVKK PII boundary + classification deny-overrides → leak/uyum riski azalır.
- ⚠️ On-prem AI = GPU host kapasite + model kalite sınırı (cloud LLM yok).
- ⚠️ Records full (retention/disposition/e-discovery) Faz 28'e ertelendi; MVP'de **model doğru** ama ürünleşmemiş — yanlış model kurmama disiplini (Codex).

## References
- ADR-0033 (charter), ADR-0035 (permission enforcement), ADR-0042 (WORM/audit reuse), ADR-0030 (Faz 24 KVKK deseni)
- Ontology v2 §6 (evidence event ledger) · Plan §6-§8
