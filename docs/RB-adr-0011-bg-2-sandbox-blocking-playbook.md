# RB ADR-0011 BG-2 — Sandbox-Blocking Pattern Playbook

> **Tetikleyici**: Agent veya operator session'da yeni gray-area tespit edildiğinde + her PR review'unda referans olarak.
> **Authority**: ADR-0010 §2.5 + ADR-0011 §2.3 boundary taxonomy authoritative; sandbox infrastructure secondary check.
> **Codex consensus**: thread `019dd409` BG-2 PARTIAL/REVISE.

## Ana kural (en önemli cümle)

**Sandbox izin verdi diye işlem otomatik meşru olmaz.** Authority kaynağı ADR-0010 §2.5 + ADR-0011 §2.3 taxonomy. Sandbox secondary defense layer; primary authority belge tabanlı.

Aynı şekilde: sandbox blokladı diye işlem otomatik yasak değil. Codex consensus + ADR taxonomy'ye göre meşru ise pattern netleştirilmeden bypass yok; BG-2 bu açıklamayı yapan playbook.

## Pattern catalog (3 sınıf)

| Sınıf | Açıklama | Örnek |
|---|---|---|
| `blocked-as-expected` | Sandbox doğru blokladı; agent durur, user/operator runbook üretir | Production cluster destructive write, full Vault root regen |
| `sandbox-gap` | Sandbox bloklamadı ama ADR taxonomy'ye göre işlem agent için yasak | GA-001 Vault generate-root via container CLI; GA-002 ESO secret_id read |
| `over-blocked` | Sandbox blokladı ama taxonomy'ye göre işlem agent-actionable olabilir; pattern netleşmeden bypass yok | (henüz kanıtlanmış case yok — placeholder) |

## Gray-area karar kayıtları

Üç tanımlanmış gray-area, ayrı decision record dosyalarında:

- [GA-001](../adr/0011-gray-areas/GA-001-vault-generate-root-container-cli.md) — Vault generate-root via container CLI (`sandbox-gap`)
- [GA-002](../adr/0011-gray-areas/GA-002-eso-approle-reads.md) — ESO AppRole reads (split decision)
- [GA-003](../adr/0011-gray-areas/GA-003-direct-pg-alter-production-shared-schema.md) — Direct PG ALTER on production-shared schema (`blocked-as-expected`)

Her karar kaydı: class, sandbox behavior, decision, agent allowed/blocked operations, user path. Index: [docs/adr/0011-gray-areas/README.md](../adr/0011-gray-areas/README.md).

## Classification examples (Session 33 — non-resolution, için açıklama)

ADR-0011 §1'deki 3 gray-area dışında pattern'leri sınıflandırma için referans:

| İşlem | Class | Authority |
|---|---|---|
| Operator-provided JWT env ile runner çalıştırma | `credential-handling boundary` | Operator local shell (token değeri repo/log'a yazılmaz; agent transcript'inde literal görmez) |
| Test persona ephemeral password rotation | `credential-write (test)` | Operator/user authority gerekir; operator runs runbook |
| OpenFGA tuple seed on test | `state-mutation (test cluster)` | Codex consensus + Kural #7 (agent yapabilir) |
| Prod equivalent (tuple seed prod) | `state-mutation (production)` | User-approval + dual-clearance |

Bu tablo **resolution record değil**; sınıflandırma örneği. Bu pattern'ler için BG-1 zaten enforcement katmanı (boundary declaration block + label).

## Yeni gray-area discovery flow

Agent veya operator session'da yeni belirsiz pattern tespit ettiğinde:

1. **Stop** — sandbox bloklasa bile bloklamasa bile devam etme; gray-area ihtimalini kayda geçir
2. **Codex consensus** — Codex MCP'ye yeni thread veya devam thread'i ile soru: "Bu işlem agent için actionable mı?"
3. **PR aç** — `chore/adr-0011-ga-NNN-<short-name>` veya benzeri branch
4. **Pattern catalog'a ekle** — yeni `GA-NNN` decision record + playbook'taki tablo güncellenir
5. **Codex AGREE** post-impl review — pattern doğru mu

Codex AGREE alınmadan agent **işlemi denemez**.

## BG-1 + BG-2 ilişki

- **BG-1** (`gate-pr-boundary-declaration` CI gate): per-PR enforcement — boundary declaration block + 7 class checkbox + user-approval evidence + label
- **BG-2** (this playbook + 3 GA decision records): pattern catalog + decision history; reference layer

BG-1 hard gate (CI red); BG-2 reference (PR review + agent decision-making).

## Roadmap

- **AC-1b** (operator-driven, future): ilk gerçek drill execution post-merge
- **Yeni GA discovery**: gelecek session'larda gray-area tespitlerinde yeni `GA-NNN` PR'ları
- **Sandbox infrastructure update**: ADR taxonomy'de yeni class eklenirse sandbox rule update (ayrı PR)

## References

- ADR-0011 §1 (Context — 3 gray-area listesi)
- ADR-0011 §2.3 (Boundary declaration matrix)
- ADR-0010 §2.5 (Operator/agent authority)
- BG-1: `docs/RB-adr-0011-bg-1-pr-boundary-declaration.md`
- DD-1..DD-4: drift detection peers
- AC-1: drill evidence template
- Codex thread `019dd409` BG-2 PARTIAL/REVISE (multi-file structure + normative resolution + no CI gate)
