# ADR-0001: Fleet — Vehicle Identity & Document Immutability

ID: ADR-0001  
Status: Draft  
Date: TBD  
Owner: TBD

## Context

`BM-0003` ve `PRD-0006`, filo operasyonunda:
- araç kimliğinin (VIN/plaka) kanonik yönetimini,
- kritik dokümanların (ruhsat/sigorta/muayene) silinmeden sürümlenmesini,
- ve tüm kritik değişikliklerin audit trail ile izlenmesini
zorunlu kılar.

## Decision

- Araç kimliği için kanonik `vehicle_id` zorunludur; `vin` ve `plate_history` ile desteklenir.
- Araç kaydı silinmez; status ile kapatılır (inactive/sold).
- Dokümanlar silinmez; yeni sürüm eklenir (immutability + versioning).
- Kritik alan değişiklikleri ve doküman görüntülemeleri audit’e düşer.

## Consequences

- Raporlama ve arama, “plaka değişimi” gibi durumlarda tutarlı kalır.
- Depolama ve retention politikası netleştirilmeden kapsam genişletilemez.
- Import/entegrasyonlarda idempotency ve dedup kuralı zorunlu hale gelir.

## Links

- BM: `BM-0003-CORE-DEC-001`, `BM-0003-CORE-GRD-001`, `BM-0003-CORE-GRD-002`, `BM-0003-CTRL-GRD-001`, `BM-0003-CTRL-GRD-002`
- PRD: `PRD-0006`
- SPEC: `SPEC-0016`

