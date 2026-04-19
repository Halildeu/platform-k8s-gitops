# Changelog

Tüm önemli değişiklikler bu dosyada tutulur. Format: [Keep a Changelog](https://keepachangelog.com/) + [Semantic Versioning](https://semver.org/).

---

## [Unreleased] — 2026-04-17 → 2026-04-19

Faz 3/4 → Faz 11'e (Seviye 0-4) büyük delta — 53 commit K8s-6 session.

### Added

**Seviye 1 — Zanzibar runtime:**
- `kustomize/base/apps/permission-service/` tam manifest (ConfigMap, Deployment, Service, SecretStub, SA, ServiceMonitor, PDB, ExternalSecret) — D-003 TRANSFORMED Zanzibar authz hub (PR #502 platform-ssot uyumlu)
- OpenFGA enabled `ERP_OPENFGA_ENABLED=true`, 4 backend ConfigMap'inde `PERMISSION_SERVICE_BASE_URL`, `ERP_OPENFGA_*` env ekleme
- Gateway route `/api/v1/authz/**` eklendi

**Seviye 2 — Ops sertleşme repo-side paket:**
- `kustomize/overlays/{test,prod}/eso/` overlay split (base placeholder FQDN → overlay patch ile gerçek Vault FQDN) — Codex iter-5 Opsiyon B namespace fix
- `bootstrap/install-eso-helm.sh` — ESO Helm install + NEXT STEPS + cache-busting pull kanıt uyarısı
- `bootstrap/apply-eso-switch.sh` — 7 servis idempotent secret-stub → externalsecret swap
- `bootstrap/vault-policies/eso-runtime.hcl` — AppRole Vault policy HCL (9 path read)
- `bootstrap/vault-policies/README.md` — apply rehberi + test komutları
- `helm-values/external-secrets/values.yaml` — ESO Helm values (non-root, webhook + cert-controller)
- `kustomize/base/apps/*/externalsecret.yaml` — 7 backend + permission-service per-service ExternalSecret
- `kustomize/overlays/*/eso/externalsecret-ghcr-pull.yaml` — W1 workload ns ghcr-pull ES

**Seviye 3 — Stability soak monitoring:**
- `kustomize/base/monitoring/zanzibar-stability-rule.yaml` — 8 alert PrometheusRule (Hub/Pod/CNI + ZanzibarEdgeSyntheticFail + cluster_scope labels)
- `kustomize/base/monitoring/blackbox-exporter.yaml` — ConfigMap + Deployment + Service + 4 Probe CR (testai/prod deny/health external edge, Codex iter-2 C-1 REVISE)
- `kustomize/base/monitoring/backup-freshness-rule.yaml` — 5 alert (PGStale/Critical + Vault + KC + ExporterDown)
- `kustomize/base/monitoring/recording-rules.yaml` — 16 pre-compute recording rule (hub/gateway/edge/pods/jvm/hikari/probe)
- `kustomize/base/monitoring/grafana-dashboards/` — 4 dashboard ConfigMap (authz plane, platform pods, edge synthetic, JVM+DB+Hikari)
- `bootstrap/backup-freshness-exporter.sh` — node_exporter textfile collector

**Seviye 4 — D32 prod cutover:**
- `bootstrap/install-on-staging-sw-2.sh` — F1-F9 prod host bootstrap script (D32 staging-sw-2)
- `argocd/applications/` 6 Application (root + test + prod + system + eso-test + eso-prod) app-of-apps pattern
- `argocd/applicationsets/` multi-cluster ApplicationSet DRAFT (D32 sonrası)

**Runbook pack:**
- `docs/D32-bootstrap-runbook.md` — F1-F9 adım-adım + partial unwind
- `docs/prod-cutover-smoke-runbook.md` — S4-D atomic cutover smoke
- `docs/S4-rollback-runbook.md` — D30 72h warm rollback (5 dk trafik geri alma + teşhis)
- `docs/S1-S2-acceptance-smoke-runbook.md` — D29 3-katman (Up/Functional/Zanzibar-ready)
- `docs/S2-A1-shortname-apply-plan.md` — shortname selective apply + rolling restart
- `docs/S2-X2-nginx-edge-migration.md` — D18 edge migration (D32 öncesi/sonrası)
- `docs/S5-disaster-recovery-runbook.md` — backup + restore drill (PG/KC/Vault/K8s)
- `docs/S5-cert-renewal-runbook.md` — Sectigo wildcard yıllık yenileme
- `docs/S5-capacity-expansion-runbook.md` — disk LVM + JVM heap + PVC + Quota
- `docs/S5-vault-audit-retention.md` — file backend + logrotate + review
- `docs/S5-privileged-access-review.md` — AppRole + RBAC + SSH + PAT çeyreklik
- `docs/on-call-triage-playbook.md` — 14 alert karar matrisi (ROLLBACK/INVESTIGATE/OBSERVE + Kyverno + backup triggers) + 5 dk checklist + escalation tree
- `docs/S5-security-incident-response.md` — 6 incident tipi (credential compromise + container escape + suspicious edge + supply chain + DDoS + exfil) + forensics + post-mortem + preventive hardening
- `docs/README.md` — master index (24 doc envanteri + 🚨 on-call + 🚀 deploy + ✅ acceptance + 🔐 day-2 + 📋 plan + 📊 query pack + 🤝 handoff + quick start)

**Plan pack:**
- `docs/S2-B1-vault-property-matrix.md` — Vault path + property matrisi
- `docs/S2-B2-digest-pin-ci-template.md` — platform-ssot CI digest pin template
- `docs/S2-C-argocd-install-plan.md` — ArgoCD install + app-of-apps plan
- `docs/S2-X3-security-hygiene.md` — IP sanitize HARD RULE
- `docs/S3-stability-soak-pack.md` — 7 günlük stability soak

**Monitoring query pack:**
- `docs/promql-query-pack.md` — günlük ops + S3 soak PromQL + recording rule tablosu
- `docs/logql-query-pack.md` — Loki log analysis (authz + edge + pod + security + DB + CNI + Vault + S3 + tuning + alert mapping)
- `docs/traceql-query-pack.md` — Tempo trace analysis (OTel config + TraceQL + ops troubleshoot + sampling + Tempo tuning + metrics_generator)

**Admission Policy (Kyverno DRAFT):**
- `helm-values/kyverno/values.yaml` — Kyverno admission controller (audit + background + cleanup + reports)
- `kustomize/base/policies/require-sha-image-tag.yaml` — D30 immutable (latest/main-stable YASAK)
- `kustomize/base/policies/disallow-privileged-pods.yaml` — container escape önleme
- `kustomize/base/policies/require-non-root.yaml` — runAsNonRoot: true zorunlu
- `kustomize/base/policies/require-resource-limits.yaml` — D22 CPU + memory limit
- `kustomize/base/policies/require-image-pull-policy.yaml` — imagePullPolicy Always YASAK
- `bootstrap/install-kyverno.sh` — Helm install + policy apply + audit → enforce rehberi
- `argocd/applications/platform-policies.yaml` — GitOps sync Application (DRAFT)

**Cert-manager (DRAFT, PLAN D8 Aşama 2):**
- `helm-values/cert-manager/values.yaml` — Helm chart (installCRDs + webhook + cainjector + ServiceMonitor)
- `kustomize/base/cert-manager/clusterissuer-letsencrypt-staging.yaml` — ACME staging (rate limit testi)
- `kustomize/base/cert-manager/clusterissuer-letsencrypt-prod.yaml` — ACME prod
- `bootstrap/install-cert-manager.sh` — Helm install + ClusterIssuer apply + test Certificate CR rehberi
- `argocd/applications/platform-cert-manager.yaml` — GitOps sync (DRAFT)

Şu an Sectigo wildcard manuel aktif; cert-manager Faz 12'de devreye alınır.

**Handoff pack:**
- `docs/session-handoff-2026-04-19.md` — v4 5-alan (Bağlam/İddia/İspatlar/İspatlamaz/Bilinen boşluk), 38 commit özet
- `docs/dev-repo-handoff-bundle.md` — dev repo 3 PR konsolide prompt (smoke-client + NS fix + W1/W3)
- `docs/handoff-*.md` — 4 handoff doc (S2-B artifact + smoke-client + auth NS + S2-X3 security)

**Load test:**
- `tests/k6/zanzibar-load.js` — k6 profile (50 VU × 6dk steady, 5 threshold, 4 group)

**Repo hygiene:**
- `.github/workflows/ci.yml` — 5 CI job (kustomize-build + yaml-lint + shell-lint + closure-language-check + placeholder-leak-check)
- `.github/pull_request_template.md` — PR template (HARD RULE kontrol + Codex verdict)
- `.github/ISSUE_TEMPLATE/{bug,feature}.md` — issue template (D29 3-katman + HARD RULE etki + Codex istişare seviyesi)
- `.github/CODEOWNERS` — PR review otomatik atama (kritik alanlar: PLAN + CLAUDE + base + prod + ArgoCD + bootstrap)
- `.github/dependabot.yml` — github-actions haftalık bağımlılık güncelleme
- `kustomize/overlays/{test,prod}/namespace.yaml` — explicit Namespace manifest + labels (platform=true + env=test|prod, ApplicationSet prereq)
- `CLAUDE.md` — agent kılavuzu (6 HARD RULE + pattern + pitfall + session akış)
- `CONTRIBUTING.md` — repo workflow 9 adım + HARD RULE enforce + commit type
- `CHANGELOG.md` — Keep a Changelog format (41 commit özet + karar logu)
- `README.md` genişletme — 119 satır (dizin + runbook envanteri + hızlı kurulum + karar logu)

### Changed

- `kustomize/base/eso/clustersecretstore-vault.yaml`: FQDN → placeholder `OVERLAY_MUST_OVERRIDE` (fail-closed, Codex iter-5)
- `kustomize/base/eso/kustomization.yaml`: ghcr-pull ES resource kaldırıldı (overlay-specific taşındı)
- `kustomize/overlays/test/kustomization.yaml`: intra-ns shortname refactor (S2-A1) + yorum IP drift fix + ConfigMap DDL/FLYWAY test override
- `kustomize/overlays/prod/kustomization.yaml`: overlay cleanup (S2-A1 follow-up, redundant replace patches kaldırıldı)
- `bootstrap/install-on-staging-sw-2.sh` F6: `base/eso` apply YASAK → `overlays/prod/eso` (W1 fix)
- `bootstrap/install-on-staging-sw.sh`: ESO opsiyonel follow-up note eklendi
- `helm-values/ingress-nginx/values-prod.yaml`: metrics.serviceMonitor enabled + release label + server-tokens:false
- `helm-values/ingress-nginx/values-test.yaml`: server-tokens:false (güvenlik parity)
- `PLAN.md`: D28 handoff + D29 3-katman + D30 atomic cutover + D31 MSSQL opsiyonel + D32 staging-sw-2 + HARD RULE güncellemeleri
- `argocd/applications/platform-eso.yaml` → `platform-eso-test.yaml` (rename + overlay path) + yeni `platform-eso-prod.yaml`

### Fixed

- **Seviye 0 Calico CNI recovery (2026-04-17):** calico-typha scale=0 + calico-node recycle → TigeraStatus DEGRADED=False (5 pod crash 20h)
- **W1 ghcr-pull namespace drift:** ES base'de external-secrets ns'de yaratılıyordu, workload platform-*'ta bekliyordu → Opsiyon B overlay-specific
- **C monitoring cross-cluster target:** cluster-local FQDN (platform-test.svc) → external edge URL (testai.acik.com/ai.acik.com) Codex iter-2 REVISE
- **5 latent drift (iter-6):** bootstrap/README ESO adımı + install-sw.sh ESO note + S2-A1 rollback selective + S2-X2 D32 hizası + script closure kelime
- **Handoff v4 sayı drift:** 25/30/31/32/36 → 38 (iter-7/iter-8 absorb)
- **AR WARN 3 fix (51018da):** ESO FQDN + MSSQL opt + rule scope label
- **Tag drift runtime:** overlay sha-3923901 eşleşmeyen staging-sw tar → kubectl set image ile düzeltildi

### Codex Protocol

- Ana thread: `019d9a75-4299-7313-85bb-003a7de680eb` (Seviye 0/1 deploy + retrospektif ping-pong)
- Delta thread: `019da5f8-9087-73f0-899b-267fa608456e` (iter-2..iter-8 retrospective + absorb)
- 8 iterasyon: AGREE / PARTIAL / REVISE absorb pattern
- Kural: AGREE sonrası plan onayı kullanıcıya SORULMAZ → direkt impl

### User Feedback

- **"Kapanış kelime yasak"** (2026-04-19): `memory/feedback_no_closure_language.md` — "bugün kapandı/tamam bitti/gün sonu" YASAK
- **"IP dış'a sızmaz"** (2026-04-19): `docs/S2-X3-security-hygiene.md` — HARD RULE + repo scan PASS
- **"Seçenek listesi sorma"** (2026-04-19): `memory/feedback_no_option_lists.md` — (a)(b)(c) YASAK
- **"Pause yasak, yol haritası tamamla"** (2026-04-19): `memory/feedback_no_closure_language.md` update — "pause/bekle" YASAK listesi eklendi
- **"İstişare kesin komut değil, yol haritası tamamla"** (2026-04-19): her iş için Codex onay sormak gereksiz, repo-side iş zinciri devam

## [0.1.0] — 2026-04-14 → 2026-04-16 (Dilim 1+2+3)

- İlk PoC — Dilim 1 (auth-service + api-gateway) + Dilim 2 (5 backend) + Dilim 3 (OpenFGA + frontend)
- testai.acik.com edge çalışır (6/6 backend 401 JSON)
- Calico CNI + ingress-nginx + host compose (PG + KC + Vault)
- Hostname rename: test.acik.com → testai.acik.com
- GitHub remote aktif + SSH deploy key (port 443 alternatif)

## [0.0.1] — 2026-04-13 öncesi

- Repo başlangıç + temel Kustomize yapısı + host-compose bootstrap

---

## Karar Logu Özeti

- **D1/D16:** 2 k3d cluster (test + prod)
- **D17:** Test scale-to-zero
- **D18:** Host nginx SSL SNI (D32 iki-host split)
- **D20:** Host bridge (test 172.19.0.x, prod 10.9.10.53)
- **D22:** CPU bütçesi (dar request / cömert limit)
- **D23:** DR RPO 24h / RTO 4h
- **D24:** JVM `-Xmx` explicit
- **D28:** Handoff 5-alan
- **D29:** Up ≠ Functional ≠ Zanzibar-ready
- **D30:** Atomic cutover + 72h warm rollback + immutable artifact
- **D31:** PG primary, MSSQL secondary/opsiyonel
- **D32:** staging-sw-2 fiziksel sunucu (external cloud REDDEDILDI)

Tam liste: [PLAN.md](./PLAN.md) Karar Logu bölümü.
