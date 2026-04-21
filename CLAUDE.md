# CLAUDE.md — platform-k8s-gitops Agent Kılavuzu

> Bu dosya Claude Code / agent session'larında otomatik yüklenir. Repo-specific kurallar, pattern'ler ve bağlam.

> Öncelik notu: Repo-geneli giriş yüzeyi [AGENTS.md](./AGENTS.md), canonical kural seti ise [docs/context-priority-rules.md](./docs/context-priority-rules.md) dosyasıdır. Bu dosya agent-özel tamamlayıcıdır; çelişki halinde `AGENTS.md` ve canonical kural seti üstün gelir.

---

## Proje Bağlamı

`autonomous-orchestrator` platformunun Docker Compose → Kubernetes geçişi için GitOps manifest repo. İki k3d cluster (test + prod), host nginx SSL edge, Vault + ESO secret flow, Zanzibar authz plane (permission-service + OpenFGA).

**Detay:** [README.md](./README.md) + [PLAN.md](./PLAN.md)

## Ana Kurallar (HARD RULE)

### 1. No Closure Language

"Kapandı/bitti/gün sonu/pause/bekle" kelimeleri **YASAK**. Kullanıcı "dur/yeter/bitti" demedikçe iş aktif devam eder. Her ara rapor sonunda **bir sonraki aksiyon** olmalı.

Memory referans: `~/.claude/projects/<slug>/memory/feedback_no_closure_language.md`

### 2. No Option-List Approval

Commit sonrası "(a)(b)(c) seçenek listesi" **sormak yasak**. Sıradaki mantıklı işi direkt uygula. Kullanıcı genel onay ("devam", "yol haritası tamamla") varsa onay soruları gereksiz.

Memory referans: `~/.claude/projects/<slug>/memory/feedback_no_option_lists.md`

### 3. IP Sanitize

Dış kullanıcı-facing response/doc'ta gerçek IP'ler görünmez. `10.9.10.53`, `127.0.0.1`, `172.19.0.x` gibi iç ağ IP'leri sadece repo içi teknik dokümanda (ops okur).

### 4. D30 Immutable Artifact

Overlay image tag `sha-<short>` (immutable). `main-stable` (moving) YASAK. Cutover sırasında pod `imageID` == GHCR digest eşleşmeli.

### 5. D29 Up ≠ Functional ≠ Zanzibar-ready

Her deploy/cutover 3 katman ayrı kanıt:
- **Up:** Pod Running + TCP reachable
- **Functional:** Endpoint response shape (401 JWT vs 500)
- **Zanzibar-ready:** Allow + Deny enforce authoritative synthetic

### 6. D30 Atomic Cutover + 72h Warm Rollback

Weighted DNS (%10/50/100) YASAK. Dış proxy L4 backend atomic switch. T+72h staging-sw compose frozen+ayakta (rollback pointer).

## Pattern'ler

### Kustomize Overlay

- Base manifest'ler namespace **tanımsız** (overlay set eder)
- Overlay kustomization `namespace: platform-<env>` → tüm resource'lar o ns'e gider
- **İstisna:** `kustomize/base/eso/` kustomization `namespace: external-secrets` (ClusterSecretStore için). ghcr-pull ExternalSecret overlay-specific (Codex iter-5 Opsiyon B).

### Selective Apply (D17 koruma)

`kubectl apply -k overlays/<env>` **D17 scale-to-zero patch'leri tekrar uygular** → mevcut Running pod outage riski. Selective:
```bash
# Tek dosya apply
kubectl --context k3d-<env> -n platform-<env> apply -f kustomize/base/apps/<svc>/configmap.yaml

# Rolling restart (envFrom ConfigMap pickup için)
kubectl --context k3d-<env> -n platform-<env> rollout restart deploy/<svc>
```

### Codex Adversarial Protokol

Her büyük delta (10+ commit) sonrası Codex MCP **retrospektif ping-pong** yeni thread'de:
- VERDICT: AGREE / PARTIAL / REVISE / RED
- AGREE → direkt impl, plan onayı sorma (CLAUDE.md global kural)
- PARTIAL → absorb et, yeni iter submit et
- REVISE → absorb + karşı-tez + iter devam
- RED → kullanıcıya rapor + yön sor

### Commit Message Pattern

```
<type>(<scope>): <kısa başlık>

<body — neden, ne, kanıt>

<Codex iter referansı varsa>
<Co-Authored-By: Claude ...>
```

Types: `feat` / `fix` / `refactor` / `docs` / `chore` / `test`

## Yaygın Pitfalls

1. **base/eso doğrudan apply:** FQDN placeholder (`OVERLAY_MUST_OVERRIDE`) → sessiz drift yerine fail-closed. Her zaman `overlays/<env>/eso`.

2. **Full `apply -k` canlı cluster'a:** D17 test overlay replicas=0 patch'leri aktif pod'u durdurur. Selective apply ZORUNLU.

3. **ConfigMap değişimi sonrası pod restart eksik:** `envFrom` otomatik pickup etmez. `kubectl rollout restart deploy` gerek.

4. **Tag drift runtime:** Overlay tag güncellensin ama pod imageID eski (staging-sw'de image import yapılmadıysa). Doğrulama:
   ```bash
   kubectl get pod -o jsonpath='{.items[0].status.containerStatuses[0].imageID}'
   ```

5. **Calico typha watch cache bozuk:** Bilinen pattern (2026-04-17 recovery). Fix:
   ```bash
   kubectl -n calico-system scale deploy calico-typha --replicas=0
   kubectl -n calico-system delete pod -l k8s-app=calico-node
   kubectl -n calico-system scale deploy calico-typha --replicas=1
   ```

## Repo İşleme

### Yeni Feature/Fix

1. `PLAN.md` ilgili Seviye/Faz altında karar var mı? yoksa D-karar ekle
2. Kustomize base/overlay değişim + build sanity (`kubectl kustomize ...`)
3. Codex plan-time istişare (yeni thread veya mevcut devam)
4. Commit + runbook referans güncelle (varsa)
5. Handoff doc update (büyük delta ise)

### Runbook Formatı

Her runbook: tetik → adımlar (süre + komut + beklenen + fail sinyali + devam eşiği) → rollback → referans. Örnek: `docs/D32-bootstrap-runbook.md`.

### Handoff D28 5-Alan

- **Bağlam:** Neden bu handoff?
- **İddia:** Ne yapıldı (commit özet)
- **İspatlar:** Canlı veya build sanity kanıt
- **İspatlamaz:** Henüz kanıtlanmamış (bekleyen functional)
- **Bilinen boşluk:** Pending iş + öncelik sırası

## Agent Session Akış

1. Oku: `AGENTS.md` → `docs/context-priority-rules.md`
2. Truth ayır: `docs/state/current-state.md` (canlı truth) + `docs/adr/0002-single-host-dual-cluster.md` (aktif mimari) + `PLAN.md` (roadmap/done kriteri)
3. Kontrol: `git log --oneline main..HEAD | head -10` + `git status`
4. Memory: `~/.claude/projects/<slug>/memory/MEMORY.md` → feedback kuralları
5. Codex thread: `PLAN.md` "Codex Thread" referanslar (ana + delta)
6. Historical gerekiyorsa: `docs/session-handoff-<latest>.md`
7. İş: kullanıcı explicit isteği varsa o, yoksa canonical truth + aktif blocker sırasındaki ilk iş

## Test Öncesi

```bash
# Kustomize build sanity (apply etmeden)
kubectl kustomize kustomize/overlays/test
kubectl kustomize kustomize/overlays/prod
kubectl kustomize kustomize/overlays/test/eso
kubectl kustomize kustomize/overlays/prod/eso
kubectl kustomize kustomize/base/monitoring

# YAML lint (opsiyonel, CI'da otomatik)
yamllint kustomize/ helm-values/ argocd/ docs/
```

## Kaynaklar

- PLAN.md D-kararlar logu
- docs/session-handoff-<YYYY-MM-DD>-v<N>.md (en son durum özeti)
- docs/D32-bootstrap-runbook.md (prod host F1-F9)
- Codex thread `019d9a75` (ana) + `019da5f8` (delta retrospective)
