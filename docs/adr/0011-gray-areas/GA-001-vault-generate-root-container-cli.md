# GA-001 — Vault generate-root via container CLI

## Class

`credential-write`

## Sandbox behavior

`sandbox-gap` — Session 32'de sandbox bu pattern'i bloklamadı; agent denedi (`docker exec ... vault operator generate-root`); key drift evident kaldı (Codex `019dd333` Session 32 retrospective).

## Decision

**Agent için yasak.** Container CLI veya `docker exec ... vault operator generate-root` olması sonucu değiştirmez. Bypass kabul edilmez:

- Container içinden `docker exec`
- `kubectl exec` ile pod-internal
- Vault HTTP API direct
- Sidecar/init-container ile gizleme

Hepsi aynı sınıfta — `credential-write` ve agent yetkisi dışında.

## Agent allowed

- Runbook yazmak (`docs/RB-vault-*.md` örnek pattern)
- Komutları **dry-doc** olarak göstermek (operator için reference)
- Operator output'unu **redacted evidence** olarak işlemek (token literal'ları transcript'e girmesin)
- Vault status read-only check (`vault status` output parsing — sadece public state)

## Agent blocked

- `vault operator generate-root -init`
- `vault operator generate-root -nonce=... -otp=...` progress
- `vault operator generate-root -decode=...`
- Root token üretimi/handling
- Unseal key material (`vault operator unseal`, `vault operator rekey`)

## User path

1. Operator opens Codex consensus discussion (gerekçe: "neden generate-root gerekli, alternatif var mı?")
2. User explicit approval (chat, PR review, veya issue)
3. Operator execution local terminal'de (transcript-redacted)
4. Evidence: BG-1 `credential-write` + `state-mutation (production)` (vault prod ise) class işaretli + `user-approval-required` label + User-approval evidence link
5. Optional: drill evidence (AC-1 template) ile audit trail

## BG-1 mapping

- `[x] credential-write` (zorunlu)
- `[x] state-mutation (production)` (Vault prod ise)
- `user-approval-required` label zorunlu
- `User-approval evidence: <link>` zorunlu (`N/A` reddedilir)

## References

- ADR-0011 §1 Context (gray-area #1: "Vault `generate-root` via container CLI (sandbox didn't block, agent attempted, key drift evident)")
- ADR-0011 §2.3 (boundary class taxonomy)
- ADR-0010 §2.5 (Operator/agent authority — Vault credential operations user-approval required)
- BG-1: `docs/RB-adr-0011-bg-1-pr-boundary-declaration.md`
- Vault DR runbook: `docs/RB-vault-test-dr-rekey.md` (PR #202), `docs/RB-vault-prod-dr-inventory.md` (PR #203)
- Codex thread `019dd409` BG-2 PARTIAL/REVISE
- Codex thread `019dd333` Session 32 retrospective (drill discipline)
