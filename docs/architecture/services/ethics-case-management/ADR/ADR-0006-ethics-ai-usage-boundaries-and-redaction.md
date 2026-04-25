# ADR-0006: Ethics — AI Usage Boundaries & Redaction Policy

ID: ADR-0006  
Status: Draft  
Date: TBD  
Owner: TBD

## Context

`BENCH-0001` AI risk kontrolleri ve `PRD-0004` AI governance maddeleri; uygulamada sınırları karar haline getirmek gerekir.

## Decision

- AI yalnız “asistan”tır: özetleme/triage önerisi/çeviri/redaksiyon gibi izinli alanlarda çalışır.
- Yasak: yaptırım önerisi, suçlama/niyet çıkarımı, insan onayı olmadan karar.
- Redaksiyon zorunludur: PII/özel nitelikli veriler model girdisine gitmez.

## Consequences

- Güven ve uyum artar.
- AI’den beklenen otomasyon sınırlandırılır.

## Links

- PRD: `PRD-0004`
- BENCH: `BENCH-0001` (AI Risk Kontrolleri)
- SPEC: `SPEC-0013`
