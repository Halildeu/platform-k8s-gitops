# Docs Index — platform-k8s-gitops

Tüm runbook, plan pack, handoff, query pack index — agent/ops session başlangıç noktası.

---

## 🚨 On-Call + Incident Response

| Doküman | Kullanım |
|---|---|
| [on-call-triage-playbook.md](./on-call-triage-playbook.md) | 14 alert karar matrisi (ROLLBACK/INVESTIGATE/OBSERVE) + 5 dk checklist + escalation tree |
| [S4-rollback-runbook.md](./S4-rollback-runbook.md) | D30 72h warm rollback (5 dk trafik geri alma + teşhis) |
| [S5-security-incident-response.md](./S5-security-incident-response.md) | 6 incident tipi (credential/escape/edge/supply-chain/DDoS/exfil) + forensics + Codex post-mortem |

---

## 🚀 Deploy + Cutover

| Doküman | Kullanım |
|---|---|
| [D32-bootstrap-runbook.md](./D32-bootstrap-runbook.md) | F1-F9 staging-sw-2 prod host bootstrap + partial unwind |
| [prod-cutover-smoke-runbook.md](./prod-cutover-smoke-runbook.md) | S4-D atomic cutover (dış proxy switch + T+5/T+30/T+60 smoke) |
| [S2-A1-shortname-apply-plan.md](./S2-A1-shortname-apply-plan.md) | Shortname refactor selective apply + rolling restart + rollback |
| [S2-X2-nginx-edge-migration.md](./S2-X2-nginx-edge-migration.md) | D18 host nginx edge migration (D32 öncesi/sonrası iki-host) |

---

## ✅ Acceptance + Smoke

| Doküman | Kullanım |
|---|---|
| [S1-S2-acceptance-smoke-runbook.md](./S1-S2-acceptance-smoke-runbook.md) | D29 3-katman (Up/Functional/Zanzibar-ready) + D30 immutable + No-Go gate mapping |

---

## 🔐 Day-2 Ops

| Doküman | Kullanım |
|---|---|
| [S5-cert-renewal-runbook.md](./S5-cert-renewal-runbook.md) | Sectigo wildcard yıllık yenileme (manuel; cert-manager Faz 12) |
| [S5-capacity-expansion-runbook.md](./S5-capacity-expansion-runbook.md) | Disk LVM + memory + CPU + PVC + ResourceQuota revize |
| [S5-disaster-recovery-runbook.md](./S5-disaster-recovery-runbook.md) | Backup + restore drill (PG/KC/Vault/K8s full) + RPO 24h / RTO 4h |
| [S5-vault-audit-retention.md](./S5-vault-audit-retention.md) | Vault file audit backend + logrotate + haftalık review + aylık archive |
| [S5-privileged-access-review.md](./S5-privileged-access-review.md) | Vault AppRole + K8s RBAC + SSH + GHCR PAT çeyreklik audit |

---

## 📋 Plan Pack

| Doküman | Kullanım |
|---|---|
| [S2-B1-vault-property-matrix.md](./S2-B1-vault-property-matrix.md) | ESO Vault path + property matrisi + preflight script |
| [S2-B2-digest-pin-ci-template.md](./S2-B2-digest-pin-ci-template.md) | Platform-ssot deploy-backend.yml digest pin CI snippet |
| [S2-C-argocd-install-plan.md](./S2-C-argocd-install-plan.md) | ArgoCD install + 6 Application app-of-apps plan |
| [S2-X3-security-hygiene.md](./S2-X3-security-hygiene.md) | IP sanitize HARD RULE + güvenlik best practice |
| [S3-stability-soak-pack.md](./S3-stability-soak-pack.md) | 7 günlük stability soak (Gün 1 baseline → Gün 7 No-Go gate) |

---

## 📊 Monitoring Query Pack

| Doküman | Kullanım |
|---|---|
| [promql-query-pack.md](./promql-query-pack.md) | PromQL — günlük ops + S3 soak + recording rule tablosu |
| [logql-query-pack.md](./logql-query-pack.md) | Loki LogQL — authz + edge + pod + security + DB + CNI + Vault + tuning |
| [traceql-query-pack.md](./traceql-query-pack.md) | Tempo TraceQL — OTel config + ops troubleshoot + sampling + tuning |

---

## 🤝 Handoff

| Doküman | Kullanım |
|---|---|
| [session-handoff-2026-04-19.md](./session-handoff-2026-04-19.md) | **v4 — 52 commit özet, D28 5-alan** (en güncel) |
| [session-handoff-2026-04-17.md](./session-handoff-2026-04-17.md) | v3 — Seviye 0 recovery başlangıç |
| [session-handoff-2026-04-16-v2.md](./session-handoff-2026-04-16-v2.md) | v2 — Dilim 1+2+3 canlı |
| [session-handoff-2026-04-16.md](./session-handoff-2026-04-16.md) | v1 — Dilim 3 başlangıç |
| [session-handoff-2026-04-15.md](./session-handoff-2026-04-15.md) | v0 — Dilim 2 başlangıç |
| [dev-repo-handoff-bundle.md](./dev-repo-handoff-bundle.md) | Platform-ssot 3 PR konsolide prompt (smoke-client + NS fix + W1/W3) |
| [handoff-S2-B-artifact-hardening.md](./handoff-S2-B-artifact-hardening.md) | W1 ghcr-pull ESO + W3 digest pin CI |
| [handoff-smoke-client-keycloak.md](./handoff-smoke-client-keycloak.md) | Keycloak smoke-client confidential client |
| [handoff-auth-hardcoded-ns-fix.md](./handoff-auth-hardcoded-ns-fix.md) | auth-service application-k8s.yml NS default |
| [handoff-S2-X3-security-hygiene.md](./handoff-S2-X3-security-hygiene.md) | IP sanitize HARD RULE paralel iş |

---

## 🗺️ Quick Start — Yeni Session

1. Bu dosya (docs/README.md) — genel bakış
2. [../PLAN.md](../PLAN.md) — son 5 entry + Güncel Seviye Durum
3. [../CLAUDE.md](../CLAUDE.md) — agent HARD RULE + pattern + pitfall
4. [session-handoff-2026-04-19.md](./session-handoff-2026-04-19.md) — son durum + pending iş
5. Codex thread: `019d9a75` (ana) + `019da5f8` (delta)

---

## 📚 Repo Dizin

- [../README.md](../README.md) — repo genel + kurulum + karar logu
- [../CONTRIBUTING.md](../CONTRIBUTING.md) — repo workflow 9 adım
- [../CHANGELOG.md](../CHANGELOG.md) — Keep a Changelog format, session delta
- [../CLAUDE.md](../CLAUDE.md) — agent kılavuzu
