# Notify ESO Prod Overlay (Faz 23 — Placeholder)

> **Status**: PENDING (Faz 23.9 prod cutover)
> **ADR**: [ADR-0013-notification-orchestration](../../../../docs/adr/0013-notification-orchestration.md)

Bu dizin Faz 23.9 prod cutover öncesi **placeholder**. ExternalSecret manifest'leri prod environment için Faz 23.9 sub-faz'ında activate edilir.

## Prereq (Faz 23.9 öncesi)

1. Faz 23.4-23.8 v1 stable (test overlay'da D29-NOTIFY 3 katman per channel PASS)
2. Provider config prod environment KVKK-compliant test çalışmaları tamam
3. D30-NOTIFY pod imageID == GHCR digest match
4. Atomic provider switch hazır (DB row update + cache invalidate)
5. 72h observation window planlandı
6. Rollback runbook test (RB-prod-deploy-rollback uyumlu)

## Activation Sequence

1. Vault populate prod (`kv/platform/notify/*` prod context)
2. ExternalSecret prod manifest'leri bu dizine eklenir
3. `kustomization.yaml` oluşturulur
4. `kustomize/overlays/prod/eso/kustomization.yaml`'a reference eklenir
5. PR boundary class: `state-mutation (production)` + `user-communication` + `user-approval-required` label
6. ArgoCD sync (selfHeal=false manual sync)
7. 72h observation window — DLQ count = 0, error rate < 0.1%

Detay: `docs/runbooks/RB-faz-23-charter.md` §Faz 23.9 Prod Cutover.
