"""Deployment contract drift detection library.

Codex 019e2319 iter-3 AGREE — Single contract motor consumed by both:
  * PR-time gate (check_pr_time.sh orchestrator)
  * Runtime drift detector (check_env_drift.sh orchestrator)

Source-of-truth: docs/operations/services.yaml (workload_kind + runtime_class
+ probe_contract + jvm_warmup_extra fields).
"""
