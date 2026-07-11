# RB — k3d-test node max-pods 50→80 recreate (Method B, coordinated window)

> **Amaç**: k3d-test-server-0 kubelet `max-pods` tavanını **50→80** canlıya geçirmek. Desired source (`bootstrap/k3d-test.yaml`) zaten 80 (gitops #2315); live kubelet hâlâ 50. Bu runbook o farkı **kontrollü clean rebuild** ile kapatır.
>
> **Karar (Codex `019f533d`)**: Yöntem **B** (`k3d cluster delete/create --config`, k3d'nin desteklenen lifecycle yolu). **A** (elle `docker run` replikasyonu) = unsupported metadata drift → NO-GO. **C** (docker daemon restart) = prod-adjacent host-wide blast (k3d-prod + host data-plane) → HARD NO-GO. Yeni-agent = topology drift → NO-GO.
>
> **Tetik (ne zaman)**: Bir sonraki net-new Deployment'tan **ÖNCE**, incident baskısı olmadan, Mavis/aktif-session kontrolüyle bulunan ilk çakışmasız bakım penceresinde. Agent kullanıcıya tekrar dönmeden yürütür (Codex GO gate karşılanınca). Acute rollout-stuck pain zaten gitops #2315 (maxSurge:0 terminate-first) ile çözüldü — bu rebuild SADECE net-new pod headroom ekler.

## Neden clean rebuild güvenli (stateless-ish cluster)

- **Data-plane HOST docker**: `platform-pg-test` / `platform-vault-test` / `platform-kc-test` k3d **dışında** host container. In-cluster PG/Vault/KC yok. DB + auth + secret-source rebuild'den **etkilenmez**.
- Cluster in-cluster state (Deployment/ConfigMap/ESO-synced Secret/ArgoCD app) **git + ArgoCD + ESO**'dan reconstructable.
- Bu nedenle B'nin failure-mode'u tanımlı: clean rebuild + reconciliation (A'nın sessiz metadata drift'inden denetlenebilir).

⚠️ "Stateless" varsayımı **inventory ile kanıtlanmalı** (aşağıdaki preflight). "1-2 dk bounce" **taahhüt edilmez** — bootstrap/reconciliation süresi daha uzun olabilir.

## Backup (blocking precondition — TAMAMLANDI 2026-07-12)

- **Off-volume + integrity-checked**: `staging-sw:/home/halil/k3d-test-backups/20260712/` (k3d docker volume DIŞI, host home).
  - `state.db` (48MB) + `state.db-wal` + `state.db-shm` (WAL-mode tutarlılık için birlikte).
  - `PRAGMA integrity_check` = **ok**; `kine` tablosu **2663 row** (k3s KV state doğrulandı).
  - SHA256 `e8d19ad89ff5163867363884349431c00f769293921f51a99aee0ae05fb94f81`.
- ⚠️ Düz `cp` çalışan SQLite'tan alınırsa WAL/SHM nedeniyle tutarsız olabilirdi — bu yüzden 3 dosya birlikte kopyalandı + integrity-check yapıldı. Restore **zorunlu yol değil** (B clean reconstruction esas); backup break-glass içindir.
- Rebuild öncesi **taze backup tekrar alınır** (aynı reçete, tarihli yeni dizin).

## Reconstructability preflight (rebuild ÖNCESİ — hepsi ✅ olmadan GO yok)

1. [ ] **Non-GitOps obje envanteri**: `kubectl --context k3d-test get all,cm,secret,externalsecret,ingress -A` → git manifesti OLMAYAN (manuel apply / imperative) objeler tespit. Faz 24 activation overlay'leri + device-key broker + artifact-host manuel digest pin'leri özellikle kontrol.
2. [ ] **Runtime-artifact ledger envanteri**: sadece git'te olmayan runtime artifact'ler (örn. imperative `kubectl set image` repository_dispatch executor pin'leri — ADR-0023) → rebuild sonrası geri yükleme listesi.
3. [ ] **ArgoCD test-cluster re-registration**: prod-hub ArgoCD'de yeni test cluster credential/CA kaydı (yeni cluster CA + token). `argocd cluster add` veya manifest.
4. [ ] **Vault Kubernetes auth rebootstrap**: yeni cluster SA token-reviewer + CA → Vault `auth/kubernetes` config güncelleme (ESO'nun Vault'a auth olabilmesi için).
5. [ ] **ESO ClusterSecretStore doğrulama**: rebuild sonrası `Ready=True` + kritik ExternalSecret'ler `SecretSynced=True`.
6. [ ] **GHCR pull-secret bootstrap**: chicken-and-egg (ghcr-pull ExternalSecret ESO'dan gelir ama ESO pod'u da image ister) — bootstrap sırası çöz.
7. [ ] **CRD/controller sırası**: ArgoCD + ESO CRD'leri + operator'lar app workload'lardan önce.
8. [ ] **Ingress/serverlb + edge**: `k3d-test-serverlb` + host-nginx stream + `testai.acik.com` public edge reachability.
9. [ ] **D29 kanıt planı**: Up + Functional + Zanzibar-ready ayrı ayrı toplanacak (tek "GREEN" değil).

## GO gate (Codex — hepsi ✅ olunca agent yürütür, user'a dönmez)

- [ ] Mavis: çakışan aktif test session / acceptance çalışması YOK
- [ ] Aktif Job/migration/rollout YOK
- [ ] Pending pod nedeni + mevcut ReplicaSet durumu kaydedildi
- [ ] Off-volume + integrity-checked SQLite backup TAZE (rebuild günü)
- [ ] Non-GitOps obje + artifact-ledger envanteri alındı (preflight 1-2)
- [ ] ArgoCD re-registration + Vault/ESO rebootstrap + GHCR bootstrap adımları doğrulandı (preflight 3-6)
- [ ] Rollback/reconstruct komutları kuru kontrol edildi
- [ ] Public test maintenance başlangıcı Mavis üzerinden bildirildi

## Execution (Method B)

```bash
# 0. TAZE off-volume backup (yukarıdaki reçete, yeni tarihli dizin) + integrity_check=ok doğrula
# 1. Bakım bildirimi (Mavis peers)
# 2. Cluster sil (k3d volume + serverlb + network temizlenir)
ssh halil@staging-sw 'k3d cluster delete test'
# 3. Cluster yeniden yarat — bootstrap/k3d-test.yaml zaten max-pods=80 (gitops #2315)
ssh halil@staging-sw 'cd <gitops-path> && k3d cluster create --config bootstrap/k3d-test.yaml'
# 4. Reconstructability zinciri (preflight 3-7 sırasına göre): CRD/operator → ArgoCD re-reg →
#    Vault k8s auth → ESO store → GHCR bootstrap → ArgoCD test overlay sync → artifact-ledger restore
# 5. Post-rebuild acceptance (aşağıda) — hepsi geçmeden "capacity raised" DENMEZ
```

## Post-rebuild acceptance (Codex — hepsi kanıtlanmadan Done YASAK)

- [ ] Kubelet process argümanı `max-pods=80` (`docker inspect k3d-test-server-0 ... Cmd` veya `ps`)
- [ ] `kubectl get node k3d-test-server-0 -o jsonpath='{.status.allocatable.pods}'` == **80**
- [ ] Node `Ready=True`; `MemoryPressure=False`, `DiskPressure=False`, `PIDPressure=False`
- [ ] `Too many pods` / unschedulable Pending kalmadı
- [ ] ArgoCD test application'ları `Synced/Healthy`
- [ ] ESO store `Ready=True` + kritik ExternalSecret'ler `SecretSynced=True`
- [ ] Kritik Deployment/StatefulSet'ler beklenen replica'da (özellikle device-key broker + endpoint-admin + Faz 24 pipeline)
- [ ] `testai.acik.com` public edge ulaşılabilir
- [ ] D29 Up + Functional + Zanzibar-ready ayrı kanıtlandı
- [ ] `docs/state/current-state.md` live truth `50 → 80` **ancak bu aşamada** güncellendi

## Rollback

- Rebuild reconciliation başarısızsa: git + ArgoCD + ESO ile ileri-düzelt (clean reconstruction esas yol).
- Break-glass (kine restore gerekirse): off-volume backup'tan `state.db` + wal + shm yeni cluster datastore'una restore — ama bu **fragile** (k3s sqlite restore into fresh cluster); tercih edilmez. Öncelik forward-reconcile.
- Host data-plane (pg/vault/kc) rebuild'den etkilenmez → onlar rollback gerektirmez.

## İlişkili

- Karar: Codex thread `019f533d` "Controlled D"
- Part 1 (rollout-safety + max-pods source): gitops #2315 (MERGED)
- Umbrella issue: #2306 (acceptance criteria) + #2308 (net-new tavan bu rebuild ile kapanır)
- Guard (kapasite alert): ayrı — host systemd collector → node_exporter textfile → prod-hub PrometheusRule (Codex D)
- Observability drift (ADR-0002/0026 test lightweight scrape + remote_write): ayrı issue
