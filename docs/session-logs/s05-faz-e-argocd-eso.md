# Session 05 — Faz E ArgoCD + ESO İlerleme

> Extracted 2026-04-23 from `docs/session-handoff-2026-04-20-k8s-migration-faz-b-c.md` (lines 654-731)
> Canonical truth: `docs/state/current-state.md`

---

## Session 5 — Faz E ArgoCD + ESO İlerleme (2026-04-20 ~11:00-12:00 UTC+3)

> Trigger: kullanıcı "yol haritasını tamamlayalım"

### AA. ArgoCD Hub Bootstrap (k3d-prod)

- ArgoCD deployed (revision 2) — argocd-server + controller + repo-server + dex 5 pod Running
- **GitHub repo secret**: `gh auth token` (Mac) → `gh-platform-k8s-gitops` K8s Secret (type=git + labels argocd.argoproj.io/secret-type=repository) → HTTPS + PAT auth
- **root.yaml apply**: app-of-apps pattern, targetRevision=main, auto-sync, self-heal, prune
- **Child app'ler auto-generate**:
  - `platform-system`: Synced + Healthy ✓
  - `platform-eso-prod`: OutOfSync (CR'lar cluster'a henüz apply edilmedi)
  - `platform-prod`: OutOfSync Missing (manual sync mode, ADR-0002 D30 atomic cutover gereği)
- **platform-prod destination fix** (PR #24): `name: prod-cluster` (eski D32 separate-host kalıntısı) → `server: https://kubernetes.default.svc` (ADR-0002 single-host-dual-cluster uyumu). Commit `7661127` squash merged.

### BB. ESO Helm Install Dual-Cluster

- `external-secrets/external-secrets@0.10.5` helm install:
  - k3d-prod: `external-secrets` ns, 3 pod Running (controller + webhook + cert-controller)
  - k3d-test: aynı 3 pod Running
- **ClusterSecretStore** apply (external-secrets.io/v1beta1 — v1 henüz ESO 0.10'da yok):
  - k3d-prod: vault-platform-gitops → http://vault.platform-prod.svc.cluster.local:8200 + AppRole role_id `0db7ba83...`
  - k3d-test: aynı → platform-test + `6e2e8407...`
- **K8s AppRole secret**: `vault-approle-secret` K8s Secret her cluster'da, data.secret-id bootstrap-drill'den okundu (Vault init sonrası)
- **Endpoints host-bridge IP update** (Faz D.prod/test sonrası yeni IP'ler):
  - k3d-test platform-test ns: postgres 172.19.0.7, keycloak 172.19.0.5, vault 172.19.0.4
  - k3d-prod platform-prod ns: postgres 172.21.0.4, keycloak 172.21.0.5, vault 172.21.0.6

### CC. ESO CSS BLOCKED: Pod Network → Stateful IP Routing

**Semptom**: ClusterSecretStore Ready=False ("unable to log in with app role auth: Put http://vault.platform-test.svc.cluster.local:8200/v1/auth/approle/login: dial tcp 10.45.59.158:8200: connect: connection refused")

**Teşhis**:
- Node (k3d-test-server-0 172.19.0.3) → platform-vault-test (172.19.0.4:8200) → **200 OK** (aynı docker network)
- Pod (10.44.x) → 172.19.0.4:8200 → **Connection refused**
- Pod → Service ClusterIP → Endpoints 172.19.0.4 route'da iptables FORWARD veya Calico policy block ediyor

**Çözüm yolları (bu oturum kapsamı dışı, handoff pending)**:
1. Vault pod'u k3d cluster içine al (StatefulSet, pod→pod routing)
2. NodePort Service + externalTrafficPolicy=Local (k3d node üzerinden)
3. Calico IPPool/FelixConfiguration'a platform-*-net subnet'lerini hostIP range olarak ekle
4. Kube-proxy iptables SNAT rule (host-network NAT)

Şu anki çözüm denemeleri (başarısız):
- v1beta1 CRD apiVersion (doğruydu, bağlantı sorun)
- AppRole secret-id K8s Secret (kuruldu, Vault ulaşamıyor ama)
- Endpoints IP güncelleme (IP'ler doğru)

### DD. Yol Haritası Final Durum (Bu Oturum Sonrası)

| Faz | Alt-Durum | Kanıt |
|---|---|---|
| **A** Decision Reset | ✅ DONE | ADR-0002 merged |
| **B** Test Authoritative Live | ✅ DONE + LIVE | testai login canlı |
| **C** Test Stability Gate | ✅ DONE + CANLI | 0 critical (BackupExporter scope fix canlı kanıtlı) |
| **D.test** Test Stateful | ✅ DONE + LIVE | 3 ayrı instance (pg+kc+vault) |
| **D.prod** Prod Stateful | ✅ DONE + LIVE | Soft cutover, 7 DB migrate, 9 backend healthy |
| **E.1** ArgoCD Hub | ✅ DONE | 5 pod, root.yaml Synced |
| **E.2** Cluster Register | 🟡 Partial | In-cluster only (external k3d-test register pending) |
| **E.3** Application Sync | 🟡 Partial | platform-system ✅, platform-prod ✅ config; overlay apply BLOCKED (ESO CRD needed first) |
| **E.4** ESO CSS Ready | ❌ BLOCKED | Pod network → stateful IP routing issue (handoff item) |
| **F** Prod Workload Preflight | ✅ Fiilen | Manuel cutover |
| **G** Atomic Cutover | ✅ Fiilen | Soft cutover |
| **H** Compose Decommission | ✅ Fiilen | 7 container rm |
| **I** Day-2 Hardening | 🟡 %10 | Doküman + rule scope fix; cron drill pending |

**Toplam k8s migration: ~%97** — ana chain (auth isolation + prod+test LIVE) tamamlandı. ESO GitOps tamamlanmadı.

### EE. Sonraki Oturum İçin Sıra

1. **ESO connection fix** (öncelikli): pod network → stateful IP routing sorunu (yukarıdaki 4 çözüm yolundan biri). Test ve prod aynı sorun.
2. **Frontend rebuild env-per-build** — sub_filter hack yerine Dockerfile ARG + 2 image (prod + testai)
3. **Vault PLACEHOLDER rotation** — backend client_secret'ları gerçek KC realm değerleriyle doldur
4. **Faz I cron drill** — backup-freshness-exporter.sh cron wiring; Sectigo cert renewal calendar (Sep 1 2026 hedef)
5. **Test cluster ArgoCD register** — prod hub'dan test cluster yönet; platform-eso-test + platform-test Application'lar sync
6. **Eski docker volumes rm** — `platform_postgres_data` vb. 7 gün sonra cleanup (rollback window)

---
