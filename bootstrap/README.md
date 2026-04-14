# Bootstrap — Cluster Kurulum Rehberi

İki k3d cluster (`prod` + `test`) ve host-level nginx SNI proxy kurulumu.
Lokal dev makinesi ve staging-sw için **aynı komutlar** çalışır.

## Ön koşullar

| Araç | Versiyon | Kurulum |
|---|---|---|
| Docker | 20+ | Lokal: Docker Desktop · Staging: `apt install docker-ce` (zaten var) |
| k3d | v5.7+ | `brew install k3d` ya da `curl -s https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh \| bash` |
| kubectl | v1.31+ | `brew install kubectl` ya da [resmi kurulum](https://kubernetes.io/docs/tasks/tools/) |
| helm | v3.14+ | `brew install helm` |
| argocd CLI | v2.13+ | `brew install argocd` |

## 1. Cluster'ları Kur

```bash
./bootstrap/setup-clusters.sh          # her iki cluster
./bootstrap/setup-clusters.sh prod     # sadece prod
```

Kubeconfig context'leri otomatik eklenir: `k3d-prod`, `k3d-test`.

```bash
kubectl config get-contexts | grep k3d-
kubectl --context k3d-prod get nodes
```

## 2. Calico CNI Kur

Flannel kapalı olduğu için CNI yok; pod'lar Pending kalır.

```bash
./bootstrap/install-calico.sh
# Kontrol:
kubectl --context k3d-prod -n calico-system get pods
kubectl --context k3d-test -n calico-system get pods
```

## 3. Host Nginx SNI Proxy (staging-sw üzerinde)

**Lokal geliştirici makinesinde ATLA** — lokalde `ai.acik.com`/`test.acik.com` DNS'i yok. Lokal dev için `kubectl port-forward` veya `/etc/hosts` ekle.

Staging-sw üzerinde:

```bash
# 1. Sectigo cert dosyalarını kopyala
mkdir -p host-compose/proxy/tls
cp /path/to/STAR_acik_com.crt host-compose/proxy/tls/wildcard-acik-com.crt
cp /path/to/STAR_acik_com.key host-compose/proxy/tls/wildcard-acik-com.key
chmod 600 host-compose/proxy/tls/wildcard-acik-com.key

# 2. Mevcut `platform-web-nginx`'i durdur (cutover anı)
docker stop platform-web-nginx

# 3. Yeni edge nginx'i başlat
docker compose -f host-compose/proxy/docker-compose.yml up -d

# 4. Sağlık kontrolü
curl -sk https://ai.acik.com/healthz
curl -sk https://test.acik.com/healthz  # test cluster up ise 200, değilse 503
```

## 4. Temizlik

```bash
./bootstrap/teardown-clusters.sh         # iki cluster'ı da sil
./bootstrap/teardown-clusters.sh test    # sadece test
```

## CIDR & Port Çakışma Önleme

| Kaynak | Prod | Test |
|---|---|---|
| API server (host port) | 6443 | 7443 |
| Ingress HTTP (host port) | 30080 | 31080 |
| Ingress HTTPS (host port) | 30443 | 31443 |
| Local registry | 5000 | 5001 |
| Pod CIDR | 10.42.0.0/16 | 10.44.0.0/16 |
| Service CIDR | 10.43.0.0/16 | 10.45.0.0/16 |
| Docker network | platform-prod-net | platform-test-net |

## Sorun Giderme

**Pod'lar Pending — CNI hatası:**
```bash
kubectl --context k3d-prod -n calico-system logs -l k8s-app=calico-node --tail=50
# tigera-operator deployment hazır mı?
kubectl --context k3d-prod -n tigera-operator get deploy
```

**Host nginx 502 Bad Gateway:**
```bash
# k3d cluster'ın ingress portları host'tan görünüyor mu?
ss -tln | grep -E "30080|31080"
# ingress-nginx pod'u var mı?
kubectl --context k3d-prod -n ingress-nginx get pods
```

**k3d cluster başlamıyor (Docker resource yetmiyor):**
```bash
docker system df          # image bloat kontrolü
docker system prune -a    # reclaimable silme (DİKKAT: kullanılan imajlar kalır)
```

## Sıradaki Adım

Cluster'lar ayakta, CNI hazır — sonra:
1. `helm-values/ingress-nginx/` — ingress controller (her iki cluster'a)
2. `helm-values/external-secrets/` — ESO + Vault ClusterSecretStore
3. `helm-values/argocd/` — prod cluster'a (tek instance, multi-cluster yönetir)
4. `helm-values/kube-prometheus-stack/` + `loki` + `tempo` — prod cluster monitoring

Her biri PLAN.md Faz 3'te listelenmiştir.
