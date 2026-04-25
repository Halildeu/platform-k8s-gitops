# DOC-ID-SCOPE-POLICY (SSOT)

## Amaç
Doküman ID çakışmalarının hangi durumlarda hata sayılacağını netleştirmek.

## ID Scope Kuralları
- `ADR-XXXX`: **service-local**
  - Aynı `ADR-0001` birden fazla service altında olabilir (örn. `docs/02-architecture/services/<svc>/ADR/`).
- `BM-XXXX`: **pack-local**
  - `BM-0001` bir “BM Pack”tir (core/controls/metrics) ve aynı numara bu pack dosyalarında tekrar edebilir.
- `BENCH-XXXX`: **pack-local**
  - `BENCH-0002` bir “BENCH Pack”tir (matrix + gaps/trends) ve aynı numara bu pack dosyalarında tekrar edebilir.
- `SPEC-XXXX`: **global unique** (delivery spec)
- `STORY/AC/TP-XXXX`: **global unique** + NUM hizalı (aynı `XXXX` ile zincir)
- `PB/PRD-XXXX`: **global unique**
- `RB-*`: **global unique** (`docs/04-operations/RUNBOOKS/`)

## Not
Bu politika, `check_*` scriptleri ve CI gate’leri için tek doğru kaynaktır.

