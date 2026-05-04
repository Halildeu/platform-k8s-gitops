# Promotion scripts (Codex P0 #2 implementation)

This directory will host the PR-first promotion bot implementation. Currently
contains design only — see `docs/operations/promotion-ledger-design.md` for
the architecture spec.

Planned scripts (P0b implementation):

- `generate-ledger.sh` — invoked by platform-backend/platform-web CI after
  successful image build + GHCR push. Creates initial ledger entry
  `release-candidates/<repo>/<sha>.json`.

- `ledger-mark-verified.sh` — invoked by gitops smoke gate workflow after
  D29 Up + Functional + Zanzibar smoke pass on test cluster. Updates
  ledger entry's `promotion.test` block.

- `scan-promotion-candidates.sh` — invoked by daily scheduled workflow
  (Pazartesi-Cuma 08:00). Finds verified-in-test ledger entries without
  open prod-candidate PR, opens DRAFT PR for operator review.

- `ledger-close-prod.sh` — invoked by ArgoCD post-sync webhook (or scheduled
  poll). Updates ledger entry's `promotion.prod` block when prod cluster
  reaches the verified digest.

- `validate-ledger-schema.py` — JSON schema validation gate; runs in CI on
  any PR that touches `release-candidates/**`.

P0c (GitHub App registration) is operator manual; secret naming convention
documented in design doc.
