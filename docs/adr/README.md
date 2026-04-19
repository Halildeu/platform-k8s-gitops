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

Her yeni büyük karar için yeni ADR dosyası + PLAN.md D-karar satırı referansı.
