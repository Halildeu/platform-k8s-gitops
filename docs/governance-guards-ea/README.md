# Endpoint-admin Governance Guard Inventory (DD-EA + BG-EA)

> Sprint "Prod post-cutover compliance" PR-9.
>
> **Status**: declared inventory; gerçek workflow implementasyonu post-sprint
> (kullanıcı 5 clarify cevabı + Faz 22.1 lab tier deploy sonrası).
>
> **Codex 019de00f öneri**: "DD-EA guard'ları için tüm 8 workflow'u bir anda
> gerçek guard gibi açma. Önce 'declared guard inventory' aç."

## 8 governance guard

ADR-0011 governance layer pattern (DD-1..DD-4 + BG-1) ile uyumlu, endpoint-admin domain için analog (DD-EA-1..7 + BG-EA-1).

| Guard | Hedef | Trigger | Implementasyon (post-sprint) |
|---|---|---|---|
| **DD-EA-1** | Manifest contract drift (kustomize render bytes) | `pull_request` paths `kustomize/base/apps/endpoint-admin-service/**` | `.github/workflows/gate-drift-endpoint-admin-manifest.yml` (planned) |
| **DD-EA-2** | OpenFGA tuple writer YALNIZ permission-service | `pull_request` paths Go source `*.go` (endpoint-admin repo) | Cross-repo guard, endpoint-admin repo CI'da; BG-EA-1 koordine |
| **DD-EA-3** | Image digest pin (deploy workflow strict mode) | deploy-endpoint-admin-prod.yml workflow | ADR-0011 D30 ile uyumlu, helper `verify-pod-digest.sh` reuse |
| **DD-EA-4** | Code signing verify (cosign verify on deploy) | deploy-endpoint-admin-prod.yml workflow step | Azure Trusted Signing default (ADR-0012-EA §Code signing) |
| **DD-EA-5** | Vault secret path allowlist (`kv/platform/endpoint-admin/*`) | ESO ExternalSecret CR PR check | `gate-drift-eso-endpoint-admin-secret-paths.yml` (planned) |
| **DD-EA-6** | Destructive command audit log immutable | endpoint-admin repo runtime test (Go integration) | Cross-repo, audit retention 365d |
| **DD-EA-7** | Identity discovery PII boundary (no PII in logs) | endpoint-admin repo unit/integration tests | Cross-repo, gitleaks + custom matcher |
| **BG-EA-1** | Per-PR boundary declaration (ADR-0011 BG-1 analog) | Both endpoint-admin repo + gitops repo PR'ları | gitops mevcut `gate-pr-boundary-declaration.yml` reuse + endpoint-admin repo'da paralel |

## Implementasyon sırası (post-sprint)

1. **Faz 22.0** (current sprint PR-8/PR-9): charter + skeleton + bu inventory
2. **Faz 22.1 Lab tier**:
   - User clarify cevapları (5 nokta) → ADR fill-in
   - DD-EA-1 + DD-EA-3 + BG-EA-1 implement (gitops-side guards)
   - Endpoint-admin repo skeleton (Go agent + REST API + admin portal)
3. **Faz 22.2 Pilot tier**:
   - DD-EA-2 + DD-EA-4 + DD-EA-5 implement
4. **Faz 22.3 Restricted tier**:
   - DD-EA-6 + DD-EA-7 implement
   - Production deploy approval + dual-control gate live

## Bu PR scope

Bu doküman **declared inventory** kapsamı. Gerçek workflow YAML dosyaları YOK; her guard'ın trigger + implementasyon planı tarif edildi.

Codex önerisinin sebebi: 8 workflow'u baştan placeholder olarak açmak "fake CI guard" yaratır (ADR-0011 BG-1 ile çakışır — boundary declaration enforcement gerçekten çalışmıyorsa governance signal sahte olur).

İmplementasyon Faz 22.1 sub-faz'da, kullanıcı clarify + lab tier deploy ile birlikte.

## Bağlantılı kararlar

- **ADR-0011** governance layer pattern (DD-1..4 + BG-1)
- **ADR-0012-EA** charter (`docs/adr/0012-EA-endpoint-admin-governance-charter.md`) — Faz 22 charter PR-8
- **ADR-0010 §2.5** boundary matrix — destructive command dual-control
- **Codex thread**:
  - `019dd895-17c1-79f0-b652-e316f64d4d79` (PR #270 mutabakat)
  - `019de00f-4b40-75c1-8ead-01b79c5819c1` (sprint review)
