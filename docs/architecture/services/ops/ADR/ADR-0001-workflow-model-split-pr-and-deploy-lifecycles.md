# ADR-0001: Workflow Model — PR & Deploy Lifecycle Ayrımı

ID: ADR-0001  
Status: Draft  
Tarih: 2025-12-26  
Sahip: @team/platform

## Context

PR → CI → fix-loop → merge akışı ile, merge SHA sonrası deploy → validate → rollback akışı farklı tetiklere, farklı kill-switch’lere ve farklı edge-case’lere sahiptir.
Tek state machine altında birleştirmek:
- modelin şişmesine,
- “deploy disabled/skip” gibi sinyallerin PR state’ini kirletmesine,
- yanlış aksiyon önerilerine (NEXT_ACTION drift) yol açabilir.

Bu yüzden PR lifecycle ve deploy lifecycle ayrı modellenmeli; aralarındaki ilişki ise deterministik bir join key üzerinden raporlanmalıdır.

## Decision

- İki ayrı ama bağlı state machine kullanılacak:
  - PR Lifecycle
  - Release/Deploy Lifecycle
- Bağlantı noktası (join key): merge SHA (main commit).
- SSOT konumları:
  - PR Lifecycle SSOT: local `.autopilot-tmp/pr-tracker/PR-TRACKER.tsv` (gitignored).
  - Deploy Lifecycle SSOT: local `artifacts/ci-logs/main-<sha7>/` altında “deploy chain index + digest” dosyaları.

## Consequences

- Model daha deterministik olur; `DEPLOY_ENABLED` / `ROLLBACK_ENABLED` gibi policy’ler PR state’ini kirletmez.
- İki lifecycle arası ilişki merge SHA ile raporlanır.
- “deploy tracker TSV” şimdilik zorunlu değildir; zincir log index (chain digest) SSOT olarak yeterlidir.

## Links

- SPEC: `docs/03-delivery/SPECS/SPEC-0017-workflow-tracking-model-ssot-v0-1.md`
- Runbook: `docs/04-operations/RUNBOOKS/RB-insansiz-flow.md`
- Runbook: `docs/04-operations/RUNBOOKS/RB-local-merge-deploy-orchestrator.md`
