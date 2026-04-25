# ADR-0005: Ethics — SLA Calendar Semantics (Business Day Policy)

ID: ADR-0005  
Status: Draft  
Date: TBD  
Owner: TBD

## Context

`PRD-0004` ve `BM-0001-MET-KPI-004` kapsamında SLA ihlalleri ölçülür; ancak SLA hesaplaması
(iş günü/tatil/saat dilimi) net değilse raporlar ve eskalasyonlar hatalı olur.

## Decision

- SLA hesaplaması “iş günü takvimi”ne göre yapılır (lokasyon/ülke bazlı tatil takvimi desteklenir).
- SLA breach olduğunda otomatik eskalasyon kuralı uygulanır (risk seviyesine göre).

## Consequences

- Ölçüm doğruluğu artar.
- Operasyonel karmaşıklık artar (takvim yönetimi).

## Links

- PRD: `PRD-0004`
- BM: `BM-0001-MET-KPI-004`
- SPEC: `SPEC-0013`
