# DOC-ROUTING-SSOT (SSOT)

## Amaç
Aynı tip dokümanların tek kanonik konumda durmasını zorunlu kılmak.

## Routing Kuralları
- `PB-*.md` → `docs/01-product/PROBLEM-BRIEFS/`
- `PRD-*.md` → `docs/01-product/PRD/`
- `BM-*.md` → `docs/01-product/BUSINESS-MASTERS/<TOPIC>/`
- `BENCH-*.md` → `docs/01-product/BENCHMARKS/<TOPIC>/`
- `TRACE-*.tsv` → `docs/03-delivery/TRACES/`
- `SPEC-*.md` → `docs/03-delivery/SPECS/`
- `STORY-*.md` → `docs/03-delivery/STORIES/`
- `AC-*.md` → `docs/03-delivery/ACCEPTANCE/`
- `TP-*.md` → `docs/03-delivery/TEST-PLANS/`
- `GUIDE-*.md` → `docs/03-delivery/guides/`
- `RB-*.md` → `docs/04-operations/RUNBOOKS/`
- `ADR-*.md` → `docs/02-architecture/services/<SERVICE>/ADR/` (**service-local**)

## Kural
Yanlış konumdaki dosya **FAIL** sayılır (strict).
