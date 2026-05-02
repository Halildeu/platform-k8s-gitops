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

**Repo dağılımı (PR-8b user 2026-05-02 fill-in)**: endpoint-admin domain 4 component / 4 repo'ya yayılıyor; her guard ilgili repo CI'sında implement edilir.

| Guard | Hedef | Repo + Trigger | Implementasyon (post-sprint) |
|---|---|---|---|
| **DD-EA-1** | Manifest contract drift (kustomize render bytes) | `platform-k8s-gitops` `pull_request` paths `kustomize/base/apps/endpoint-admin-service/**` | `.github/workflows/gate-drift-endpoint-admin-manifest.yml` (planned, bu repo) |
| **DD-EA-2** | OpenFGA tuple writer YALNIZ permission-service (cross-service tuple discipline) | `platform-backend` `pull_request` paths `endpoint-admin-service/**/*.go` | platform-backend monorepo guard (mevcut DD-5 pattern reuse) |
| **DD-EA-3** | Image digest pin (deploy workflow strict mode) | `platform-k8s-gitops` `deploy-endpoint-admin-prod.yml` workflow | ADR-0011 D30 ile uyumlu, helper `verify-pod-digest.sh` reuse (PR #304) |
| **DD-EA-4** | Code signing verify (cosign verify on deploy + Authenticode 22.2+) | `platform-k8s-gitops` deploy workflow + `platform-agent` build pipeline | Azure Trusted Signing default; runtime cosign verify deploy workflow + ConfigMap `COSIGN_KEY_REF` public key (Azure KMS URI). 22.1 lab `lab-only-evidence` flag kabul. **Private key Vault/ESO DEĞİL** — supply-chain RoT, build-time CI pipeline |
| **DD-EA-5** | Vault secret path allowlist (`kv/platform/endpoint-admin/*` only) | `platform-k8s-gitops` ESO ExternalSecret CR PR check | `gate-drift-eso-endpoint-admin-secret-paths.yml` (planned). Allowlist: oidc-client-secret, audit-log-dsn, ad-bind-credentials, entra-app-credentials (22.3+), internal-api-key, agent-enrollment-secret. Code signing key NOT in allowlist (supply-chain pipeline) |
| **DD-EA-6** | Destructive command audit log immutable | `platform-backend` runtime integration test + `platform-k8s-gitops` audit log retention configmap | Cross-repo, audit retention 365d. backend integration test (Go test), gitops manifest config |
| **DD-EA-7** | Identity discovery PII boundary (no PII in logs) | `platform-backend` + `platform-agent` + `platform-web/apps/mfe-endpoint-admin/` (paralel guard her repo'da) | gitleaks + custom matcher (per-repo CI). 22.1 + 22.2 scope sadece acik.local discovery; future Entra/M365 (22.3+) |
| **BG-EA-1** | Per-PR boundary declaration (ADR-0011 BG-1 analog) | Both `platform-backend` + `platform-agent` + `platform-web` + `platform-k8s-gitops` (4 repo) | gitops mevcut `gate-pr-boundary-declaration.yml` reuse + diğer 3 repo'da paralel implementation |

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
