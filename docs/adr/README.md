# Architecture Decision Records (ADR)

Büyük mimari kararların kayıt dizini. MADR (Markdown Architecture Decision Record) pattern.

**İlişki:** `PLAN.md` Karar Logu (D1-D32+) günlük karar akışı tek satır notlar. ADR detaylı, bağlam + alternatifler + sonuçlar.

## Format

Her ADR dosyası `NNNN-<kısa-başlık>.md`:

```markdown
# NNNN — Başlık

## Status
Accepted / Rejected / Proposed / Superseded by NNNN

## Context
Sorun tanımı, gerekçe.

## Decision
Seçilen yaklaşım.

## Consequences
Pozitif + negatif etkiler.

## Alternatives
Reddedilen alternatifler + red nedenleri.
```

## ADR Listesi

| # | Başlık | Status |
|---|---|---|
| 0001 | [Service Mesh Rejected](./0001-service-mesh-rejected.md) | Rejected |
| 0002 | [Single-Host Dual-Cluster Topology](./0002-single-host-dual-cluster.md) | **Accepted** (2026-04-19) |
| 0003 | [Inner-Loop Tooling Ownership Between platform-ssot and platform-k8s-gitops](./0003-inner-loop-tooling-ownership.md) | **Accepted** (2026-04-24) |
| 0004 | [Split-Repo Authority Transfer](./0004-split-repo-authority-transfer.md) | **Accepted** |
| 0005 | [Dual DataSource Reporting](./0005-dual-datasource-reporting.md) | **Accepted** |
| 0008 | [Multi-Org Explicit-Scope Zanzibar Contract](./0008-multi-org-explicit-scope-zanzibar.md) | **Accepted** (2026-04-26) |
| 0025 | [Enterprise Platform Charter — Process & Parameter Management Hub](./0025-enterprise-platform-charter.md) | **Proposed** (2026-05-20) |

Her yeni büyük karar için yeni ADR dosyası + PLAN.md D-karar satırı referansı.

> Not: README index 0008'den sonra eksik (ADR 0009-0024 dosyaları var ama listede yok). Pre-existing tech debt; ayrı PR'a bırakılabilir.

## Superseded Kararlar

ADR-0002 aşağıdaki kararları supersede etti:
- `PLAN.md D32` — staging-sw-2 ayrı fiziksel prod cluster
- `docs/D32-bootstrap-runbook.md` — D32 ayrı-host prod kurulum
- `bootstrap/install-on-staging-sw-2.sh` — ayrı sunucu prod bootstrap

Bu dosyalar **tarihi bağlam olarak korunur**; yeni kurulum ADR-0002 + `docs/prod-cutover-runbook-v2.md` izler.
