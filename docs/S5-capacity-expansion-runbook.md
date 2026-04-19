# S5 Capacity Expansion Runbook — Disk/Memory/CPU Darboğaz

> **Source:** K8s-6 S5 day-2 ops (Codex iter-7 tespit)
> **Kapsam:** Disk baskısı + memory pressure + CPU throttling + K8s ResourceQuota
> **Trigger:** PrometheusRule alert (TBD capacity alerts) veya manuel tespit

---

## 1. Teşhis — Kaynak türü tespit

### 1.1 Disk baskısı

```bash
# Host disk kullanımı
df -h /
df -h /var/lib/docker
df -h /home/halil/platform

# Büyük tüketiciler (10GB+)
du -sh /var/lib/docker/volumes/* | sort -h | tail -10
du -sh /home/halil/platform/backup/* | sort -h | tail -5

# Docker reclaimable
docker system df
```

**Eşik:** `df -h /` > 85% → acil temizlik, > 90% → expand

### 1.2 Memory pressure

```promql
# Prometheus — pod memory / limit ratio
sum by (pod) (container_memory_working_set_bytes{namespace=~"platform-(test|prod)"})
  / sum by (pod) (container_spec_memory_limit_bytes{namespace=~"platform-(test|prod)"})

# Host RAM
free -h
```

**Eşik:** pod > 80% limit → JVM heap revize, host free < 2GB → RAM expand

### 1.3 CPU throttling

```promql
sum by (pod) (rate(container_cpu_cfs_throttled_periods_total{namespace=~"platform-(test|prod)"}[5m]))
  / sum by (pod) (rate(container_cpu_cfs_periods_total{namespace=~"platform-(test|prod)"}[5m]))
```

**Eşik:** > 5% → CPU limit arttır (D22)

---

## 2. Disk Genişletme (LVM expand)

### 2.1 Ön kontrol

```bash
sudo lvs
sudo vgs
sudo pvs

df -hT /   # dosya sistemi (ext4 veya xfs)
```

### 2.2 Yeni disk ekle (fiziksel veya sanal)

```bash
# Yeni disk: /dev/sdb (örn. 500GB)
sudo parted /dev/sdb mklabel gpt
sudo parted /dev/sdb mkpart primary 0% 100%

# PV create + VG extend
sudo pvcreate /dev/sdb1
sudo vgextend <VG_NAME> /dev/sdb1

# LV extend (tüm free space)
sudo lvextend -l +100%FREE /dev/<VG_NAME>/<LV_NAME>

# Dosya sistemi resize (ext4 için)
sudo resize2fs /dev/<VG_NAME>/<LV_NAME>
# XFS için: sudo xfs_growfs /
```

### 2.3 Doğrulama

```bash
df -h /
# Yeni boyut görünür

# Docker volume boş alan
docker system df
```

---

## 3. Memory Expansion

### 3.1 Host RAM ekleme (fiziksel)

Ops/sysadmin iş — staging-sw veya staging-sw-2 fiziksel RAM DIMM ekleme. Reboot gerekir.

Alternatif: workload tuning.

### 3.2 JVM Heap Revize (D24)

Pod memory pressure varsa JVM `-Xmx` revize:

```yaml
# kustomize/base/apps/<svc>/deployment.yaml env
- name: JAVA_TOOL_OPTIONS
  value: "-Xmx512m -XX:+UseG1GC -XX:MaxGCPauseMillis=100"
```

Test overlay'de tipik `-Xmx256m` (D17 scale-to-zero uyum), prod overlay'de `-Xmx512m`-`-Xmx1g`.

```bash
# Kustomize edit
sed -i 's|-Xmx256m|-Xmx512m|g' kustomize/overlays/prod/kustomization.yaml

# Selective apply (D17 korunarak)
kubectl --context k3d-prod apply -f kustomize/base/apps/<svc>/deployment.yaml
kubectl --context k3d-prod -n platform-prod rollout restart deploy/<svc>
```

### 3.3 Container Memory Limit Revize

```yaml
# kustomize/base/apps/<svc>/deployment.yaml
resources:
  limits:
    memory: "1Gi"    # 512Mi → 1Gi
  requests:
    memory: "512Mi"  # 256Mi → 512Mi
```

---

## 4. CPU Expansion

### 4.1 Host vCPU ekleme

Ops/sysadmin iş — VM CPU core sayısı arttırma veya fiziksel CPU upgrade.

### 4.2 Container CPU Limit Revize (D22)

```yaml
# kustomize/base/apps/<svc>/deployment.yaml
resources:
  limits:
    cpu: "1500m"   # 750m → 1500m
  requests:
    cpu: "300m"    # 150m → 300m
```

### 4.3 Active Processor Count Revize

G1GC ve JVM thread pool'ları `-XX:ActiveProcessorCount` ile kontrol edilir:

```yaml
# Overlay patch
- name: JAVA_TOOL_OPTIONS
  value: "-Xmx512m -XX:+UseG1GC -XX:MaxGCPauseMillis=100 -XX:ActiveProcessorCount=2"
```

Test overlay tipik 1 (dar), prod overlay 2-4.

---

## 5. K8s PVC Resize

Eğer K8s-6'da PVC kullanılıyorsa (şu an compose-based, PVC yok ama ileride olabilir):

```bash
# PVC mevcut boyut
kubectl -n platform-prod get pvc

# Resize (StorageClass allowVolumeExpansion: true gerek)
kubectl -n platform-prod patch pvc <pvc-name> \
  --type=json -p='[{"op": "replace", "path": "/spec/resources/requests/storage", "value": "20Gi"}]'

# Pod restart (filesystem expand)
kubectl -n platform-prod rollout restart deploy/<svc>
```

---

## 6. ResourceQuota Revize (namespace-level)

```bash
# Mevcut quota
kubectl --context k3d-prod -n platform-prod describe resourcequota platform-quota

# Revize (kustomize overlay)
```

```yaml
# kustomize/overlays/prod/kustomization.yaml patches
- target:
    kind: ResourceQuota
    name: platform-quota
  patch: |-
    - op: replace
      path: /spec/hard/requests.cpu
      value: "8"           # 4 → 8
    - op: replace
      path: /spec/hard/requests.memory
      value: 16Gi          # 8Gi → 16Gi
    - op: replace
      path: /spec/hard/limits.cpu
      value: "16"          # 8 → 16
    - op: replace
      path: /spec/hard/limits.memory
      value: 32Gi          # 16Gi → 32Gi
```

```bash
# Selective apply (D17 korunarak)
kubectl --context k3d-prod apply -f kustomize/base/apps/platform-quota.yaml  # veya namespace.yaml
```

---

## 7. Sıralı Aksiyonlar (hangi sırada ne yap)

| Öncelik | Senaryo | Aksiyon |
|---|---|---|
| P0 | Disk > 95% | Log/backup temizle + Docker prune → expand |
| P0 | Pod OOMKilled | JVM heap ↑ + memory limit ↑ + rolling restart |
| P1 | CPU throttle > 10% | CPU limit ↑ + ActiveProcessorCount ↑ |
| P1 | PVC > 85% | Resize PVC + pod restart |
| P2 | Host RAM free < 4GB | JVM heap tuning (TestDB'ler) + monitoring |
| P3 | Node disk IO yüksek | Hot pod tespit + scheduling revize |

---

## 8. Referanslar

- PLAN.md D22 CPU bütçesi
- PLAN.md D23 DR/RPO/RTO
- PLAN.md D24 JVM `-Xmx` explicit
- `docs/promql-query-pack.md` §2 Pod resource query'ler
- `kustomize/overlays/test/kustomization.yaml` — test ResourceQuota patch örneği
- `kustomize/overlays/prod/kustomization.yaml` — prod topoloji
