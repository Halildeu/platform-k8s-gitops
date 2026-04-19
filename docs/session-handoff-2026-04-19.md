# Session Handoff v4 — 2026-04-19 K8s-6

> **Format:** D28 HARD RULE 5-alan (Bağlam / İddia / İspatlar / İspatlamaz / Bilinen boşluk)
> **Scope:** 25 commit main..HEAD, Seviye 0 PASS + Seviye 1 deploy PASS + Seviye 2/3/4 repo-side paket
> **Codex thread referans:** `019d9a75-4299-7313-85bb-003a7de680eb` (K8s-6 ana), `019da5f8-9087-73f0-899b-267fa608456e` (iter-2..iter-6 delta retrospective)
> **No-closure uyarı:** Bu handoff "bugün kapandı/bitti" değil — sürekli ortak devam sürecinde ara rapor.

---

## 1. Bağlam

Bu session 2026-04-17'de Codex 4-tur re-baseline (D28-D31 + HARD RULES) ile başladı, 2026-04-19'da Seviye 1 deploy PASS + Seviye 2/3/4 repo-side paket haline evrildi. Ana hedef: Kubernetes yol haritasının 5 Seviye'sini (S0 Canlı dürüst → S1 Zanzibar runtime → S2 Ops sertleşme → S3 Stability soak → S4 Cutover) tamamlamak. Zanzibar-25 (paralel platform-ssot session) 14 PR merge + permission-service K8s-ready (PR #502) + OI-03 canary PASS gönderdi → K8s-6 ayağı başlattı.

**Çoklu iteration Codex adversarial istişare** (iter-2..iter-6) ile 25 commit Codex plan-consensus ile doğrulandı. İki thread: ana K8s-6 + retrospective delta. Kullanıcı HARD RULE'ları: (1) kapanış kelime yasak, (2) IP dışa sızmaz, (3) plan onayları Codex mutabıksa sorma — direkt impl, (4) paralel iş / sürekli devam.

---

## 2. İddia (bugün ne oldu — 25 commit)

### 2.1 Seviye 0 — Calico Recovery + testai Edge Fix (2026-04-17)

| Commit | İş |
|---|---|
| `50659d7` | PLAN 4-tur Codex re-baseline — D28-D31 HARD RULES + handoff v3 |
| `8e693d6` | Calico typha scale=0 + node recycle → TigeraStatus DEGRADED=False, 9/9 Running |

### 2.2 Seviye 1 — Zanzibar Runtime (2026-04-19)

| Commit | İş |
|---|---|
| `8cec273` | platform-ssot permission-service K8s-ready istek handoff |
| `ecc3935` | S1 permission-service manifest + Zanzibar runtime aktivasyonu (17 dosya, atomic) |
| `154b4a3` | S1 deploy-sonrası canlı sonuç — Hub smoke + deny enforce PASS |

### 2.3 Seviye 2 — Ops Sertleşme Repo-Side Paket

| Commit | İş |
|---|---|
| `eb13cb2` | S2-A1 shortname refactor (intra-ns svc URLs) |
| `85c7e2a` | S1 acceptance + S2/S3/S4 doc pack (6 doc) |
| `31ab635` | No-closure HARD RULE + nginx edge migration + shortname apply plan |
| `c5b9789` | S2-B1 ESO base — ghcr-pull ES + ClusterSecretStore |
| `5e13d45` | S2-B1 ESO permission-service pilot |
| `d349f04` | S2-B1 ESO 6 backend service ES |
| `51018da` | AR WARN 3 düzeltmesi — FQDN + MSSQL opt + rule scope |
| `4ff7c56` | S2-B2 digest pin CI template |
| `99bceec` | Overlay cleanup — redundant replace patches kaldırıldı |
| `0724ea8` | S2-B1 Vault property matrix preflight |
| `835a783` | dev-repo-handoff-bundle — 3 PR konsolide prompt |

### 2.4 Seviye 3 — Stability Soak Repo-Side Paket

| Commit | İş |
|---|---|
| `16ac951` | S3-A monitoring YAML (PrometheusRule + Blackbox probe) |

### 2.5 Seviye 4 — D32 Prod Cutover Repo-Side Paket

| Commit | İş |
|---|---|
| `4de25fb` | install-on-staging-sw-2.sh — D32 prod host F1-F9 bootstrap script |
| `881858e` | ArgoCD app-of-apps CR paketi (root + 4 Application) |

### 2.6 Codex Delta Retrospective İterasyon Absorb (iter-2..iter-6)

| Commit | İş |
|---|---|
| `0cdd116` | iter-2 AGREE — F+G metin closure drift 6 fix + test overlay yorum IP |
| `25b3b4a` | iter-2 D+C — ESO test/prod overlay split (placeholder + patch) + monitoring external edge probe (4 Probe CR testai/prod) |
| `a486c42` | iter-3 PARTIAL — install-eso-helm.sh + helm-values + F6 overlay fix |
| `41d17e9` | iter-5 AGREE — W1 ghcr-pull namespace fix (Opsiyon B overlay-specific) |
| `135a718` | iter-4/iter-5 scope — S4-rollback-runbook + D32-bootstrap-runbook + PLAN entry |
| `3b0cb50` | iter-6 PARTIAL — 5 latent drift temizliği (README + install-sw ESO + shortname rollback + nginx D32 + script closure) |

---

## 3. İspatlar (kanıtlanan — canlı veya build sanity)

### 3.1 Seviye 0 canlı PASS

- Calico CNI healthy: `TigeraStatus DEGRADED=False`, `calico-node + calico-typha + calico-kube-controllers` Running
- 9/9 backend pod Running (auth/gateway/user/variant/core-data/report/schema + pg/kc sidecars)
- testai.acik.com edge fix: `/testai-healthz → 200`, `/auth/actuator/health → 200`, `/reports + /schemas → 401 JSON`
- ai.acik.com compose (eski) DOKUNULMADI: 200+401 aynen

### 3.2 Seviye 1 canlı PASS (smoke partial)

- permission-service 1/1 Running, sha-3923901 immutable tag (D30 pilot)
- ImageID `sha256:24bc8d61e255686e677e910fe663e17b9221b8aa489d008a89958e5569936ddf` eşleşme
- **Smoke A (Hub cluster-direct):** `/actuator/health:8081 → 200`, `/api/v1/authz/version:8090 → 401 JWT required` (endpoint aktif), `/api/v1/authz/me → 401`
- **Smoke B (Enforcement partial):** caller auth-service → permission-service:8081 `{"status":"UP"}`, gateway `/variants + /auth/login (no token) → 401 deny`, testai edge `/auth/actuator/health → 200`
- Zanzibar-ready (D29) **partial**: Hub up + caller bağlantı + deny tarafı ✅

### 3.3 Seviye 2 repo-side build sanity PASS

- `kubectl kustomize overlays/test/eso` → ClusterSecretStore (external-secrets ns, platform-test.svc FQDN) + ExternalSecret ghcr-pull (platform-test ns) ✅
- `kubectl kustomize overlays/prod/eso` → prod eşdeğeri ✅
- `kubectl kustomize base/monitoring` → 4 Probe CR (testai-deny/health + prod-deny/health) + PrometheusRule ✅

### 3.4 Codex adversarial consensus

- 6 iterasyon ping-pong (iter-2 AGREE, iter-3/4/6 PARTIAL, iter-5 AGREE)
- Tüm REVISE feedback absorb edildi (W1 namespace fix, ESO overlay split, external edge probe, install-eso-helm.sh, 5 latent drift)
- "AGREE sonrası plan onayı sorma" kuralı uygulandı

---

## 4. İspatlamaz (henüz kanıtlanmamış)

### 4.1 Canlı functional (apply bekler)

- **Smoke-client allow synthetic** (D29 Zanzibar-ready full acceptance) — dev repo S2-B3 PR bekler (Keycloak confidential client)
- **ghcr-pull gerçek pull kanıtı** (W1 acceptance) — Codex iter-5 uyarısı: "secret var" ≠ "pull auth çalıştı"; cache-busting fresh tag veya node cache temizle gerek
- **Shortname apply canlı** — apply bekler (smoke-client merge sonrası selective apply + rolling restart)
- **S3 monitoring canlı** — PrometheusRule + 4 Probe apply bekler (prod cluster)
- **ArgoCD Running** — ArgoCD install bekler (test opsiyonel, prod D32)
- **D30 7 kalan servis digest pin** — dev repo S2-B W3 CI revize bekler

### 4.2 Ops bağımlı

- **Vault AppRole policy + secret seed** (kv/gitops/ghcr-token, kv/platform/<svc>) — ops iş
- **Dış proxy backend staging-sw-2 ekleme** (INACTIVE) — sysadmin iş
- **staging-sw-2 donanım** — D32 prod host, ops iş
- **Host nginx D18 migration kalıcı** — ayrı pencere, sysadmin

---

## 5. Bilinen Boşluk (ve öncelik sırası)

### 5.1 Aktif bekleyen iş (dev repo + ops koordineli)

| ID | İş | Bağımlılık | Öncelik |
|---|---|---|---|
| **S2-B3** | smoke-client Keycloak confidential client | dev repo `platform-ssot` PR | P1 (D29 blocker) |
| **S1-B2** | auth-service `application-k8s.yml` hardcoded NS default fix | dev repo PR (küçük) | P1 paralel |
| **S2-B W1** | Vault `kv/gitops/ghcr-token` seed + AppRole policy | ops iş | P1 |
| **S2-B W3** | platform-ssot `deploy-backend.yml` digest pin CI revize | dev repo CI PR | P1 |
| **ESO install test cluster** | Vault ops + dev repo S2-B3 paralel | S2-B W1 ön-bağımlı | P1 |

### 5.2 Apply pencere sırası (Codex iter-2 FR2 + iter-3 onayı)

1. Vault policy + path seed (ops)
2. `docs/S2-B1-vault-property-matrix.md` preflight script (exit 0)
3. `bash bootstrap/install-eso-helm.sh test` — ESO Helm install test cluster
4. `kubectl create secret generic vault-approle-secret -n external-secrets` (manuel ilk bootstrap)
5. `kubectl apply -k kustomize/overlays/test/eso` (W1 Opsiyon B — platform-test ns)
6. Doğrula: ClusterSecretStore Ready + ExternalSecret Synced + Secret ghcr-pull platform-test ns + **cache-busting pull kanıtı** (Codex iter-5)
7. (Smoke-client PR merge ise paralel) shortname selective apply + rolling restart (`docs/S2-A1-shortname-apply-plan.md`)
8. ArgoCD install test cluster (opsiyonel dev ergonomics) — S2-C1
9. S3 monitoring apply prod cluster (`kubectl --context k3d-prod apply -k kustomize/base/monitoring`) — S3-A
10. D32 staging-sw-2 donanım hazır → `bash bootstrap/install-on-staging-sw-2.sh` F1-F9 (`docs/D32-bootstrap-runbook.md`)
11. S4-D atomic cutover (`docs/prod-cutover-smoke-runbook.md`) + T+72h warm rollback window (`docs/S4-rollback-runbook.md`)

### 5.3 Repo-side yedek iş (dev/ops bekler iken)

- Smoke test runbook (S1 re-run + S2 acceptance template)
- Per-service ES switch automation helper (secret-stub → externalsecret exchange)
- Grafana dashboard JSON pack (authz plane + platform pods + edge)
- Load test k6 script K8s-6 Zanzibar profile (Zanzibar-25 k6 pattern taşıma)

---

## 6. Codex Adversarial Protokol Özeti

**Thread 1 (`019d9a75`)** — K8s-6 ana: 4-tur re-baseline → Seviye 0 recovery → Seviye 1 deploy-öncesi karar → Seviye 1 deploy-sonrası retrospektif ping-pong (Madde 1-4 auth NS / variant ConfigMap / immutable tag / D32)

**Thread 2 (`019da5f8`)** — Delta retrospective (iter-2..iter-6):
- **iter-2 AGREE:** F+G metin closure + D ESO overlay split + C monitoring external edge
- **iter-3 PARTIAL:** helm-values/ yoktu + install-on-sw.sh ESO yoktu + sw-2.sh F6 base/eso yanlıştı
- **iter-4 REVISE:** W1 ghcr-pull namespace drift
- **iter-5 AGREE:** Opsiyon B overlay-specific ES (base/eso yalnız ClusterSecretStore)
- **iter-6 PARTIAL:** 5 latent drift (README ESO apply sırası + install-sw ESO note + shortname rollback selective + nginx D32 hizası + script closure kelime)

**Kural:** Codex AGREE sonrası plan onayı kullanıcıya SORULMAZ → direkt impl (CLAUDE.md 2026-04-17 kural).

---

## 7. Yeni Session Başlangıç Rehberi

### 7.1 Okuma sırası (yeni session veya sen-dönerse)

1. Bu dosya (session-handoff-2026-04-19.md) — hızlı bağlam
2. `PLAN.md` — son 3-5 entry (Güncel Seviye Durum + 2026-04-19 entries)
3. `docs/dev-repo-handoff-bundle.md` — dev repo bekleyen 3 PR
4. `docs/S2-B1-vault-property-matrix.md` — ESO preflight
5. `docs/D32-bootstrap-runbook.md` — F1-F9 adım-adım
6. `docs/S4-rollback-runbook.md` — D30 72h warm

### 7.2 Kontrol komutları

```bash
# Repo sanity
cd /Users/halilkocoglu/Documents/platform-k8s-gitops
git status                                          # clean main'den 25 commit ahead
git log --oneline main..HEAD | head -5              # son 5 commit

# Kustomize build sanity
kubectl kustomize kustomize/overlays/test/eso       # ClusterSecretStore + ES
kubectl kustomize kustomize/overlays/prod/eso       # prod eşdeğeri
kubectl kustomize kustomize/base/monitoring         # 4 Probe + PrometheusRule

# Staging-sw canlı durum
ssh halil@staging-sw 'kubectl --context k3d-test -n platform-test get pods'   # 9/9 Running + 1 permission-service
ssh halil@staging-sw 'curl -sk https://testai.acik.com/testai-healthz'         # 200
```

### 7.3 İlk karar sorusu

- **Dev repo karşı session durumu?** smoke-client + auth NS + W3 CI PR'lar açıldı mı?
- **Vault ops?** kv/gitops/ghcr-token + kv/platform/<svc> seed + AppRole policy hazır mı?
- **Apply pencere açık mı?** Hem bağımlılık hazır hem operatör müsait mi?

Cevaba göre apply hattı (5.2) başlat veya repo-side yedek iş (5.3) devam.

---

## 8. Referanslar

- **Handoff v3:** `docs/session-handoff-2026-04-17.md` (Seviye 0 recovery başlangıç)
- **PLAN.md:** Güncel Seviye Durum + Bölüm 1.5 D32 Kontrat + 2026-04-17/19 entries
- **Dev repo handoff bundle:** `docs/dev-repo-handoff-bundle.md` (3 PR konsolide prompt)
- **S4 rollback runbook:** `docs/S4-rollback-runbook.md`
- **D32 bootstrap runbook:** `docs/D32-bootstrap-runbook.md`
- **Prod cutover smoke runbook:** `docs/prod-cutover-smoke-runbook.md`
- **Codex thread ID'leri:** `019d9a75` ana + `019da5f8` delta retrospective
