# ci/ — Python check scripts (Faz 19.11.D port)

13 check script + 2 v1 JSON config + check_standards_lock_parts/ subdir.

## Scripts
- `check_enforcement_rules.py` — CI enforcement rules check
- `check_module_delivery_lanes.py` — per-module delivery lane uyumu
- `check_script_budget.py` — script complexity budget (script_budget.v1.json)
- `check_standards_lock.py` + 3 destek modülü — standards.lock vs gerçek state
- `check_test_quality.py` — test quality metrics
- `policy_dry_run.py` — policy enforcement dry-run (policies/ klasörünü okur)
- `run_module_delivery_lane.py` — per-module CI lane runner
- `validate_schemas.py` — JSON schema validation

## Config files
- `module_delivery_lanes.v1.json` — module delivery lane definitions
- `script_budget.v1.json` — script complexity limits

## CI gate'lerle bağlantı

Bu script'ler şu CI gate'leri (Faz 19.11.D bağımsız ama compatible):
- `gate-enforcement-check.yml` (henüz port edilmedi)
- `gate-policy-dry-run.yml` (henüz port edilmedi)
- `gate-schema.yml` (henüz port edilmedi)

Port: Aşama 2 sonrası gate workflow'lar adapt edilince aktive olur.
