#!/usr/bin/env bash
# k3d managed registry: LAN yayınından (0.0.0.0) loopback'e (127.0.0.1) taşı.
# Faz 22 güvenlik sertleştirme — gitops #2974.
#
# NEDEN
#   registry:2 kimlik doğrulaması OLMADAN koşuyor ve Registry v2 varsayılanı
#   auth'suz READ-WRITE'tır. `host: "0.0.0.0"` bu registry'yi kurum LAN'ının
#   tamamına açar; cluster ondan imaj çektiği için LAN'daki bir aktör cluster'ın
#   kullandığı bir etiketi üzerine yazabilir (tedarik zinciri yolu).
#
# NEDEN LOOPBACK KIRMAZ
#   Cluster node'ları registry'ye HOST yayını üzerinden değil, docker ağı
#   içindeki container hostname'i ile ulaşır:
#     node registries.yaml: platform-test-registry:5001 -> http://platform-test-registry:5000
#   Host'tan `docker push localhost:<port>/...` da çalışmaya devam eder. Yalnız
#   LAN'daki UZAK makinelerin erişimi kapanır — ölçümde böyle bir tüketici yok.
#
# DESIRED STATE
#   Kalıcı kaynak bootstrap/k3d-{test,prod,dev}.yaml içindeki
#   `registries.create.host: "127.0.0.1"`. Bu script yalnız HÂLİHAZIRDA 0.0.0.0
#   ile oluşturulmuş container'ları o desired-state'e getirir; cluster yeniden
#   kurulduğunda gerek kalmaz. Invariant testi:
#   tests/operations/test_bootstrap_registry_binding_invariant.py
#
# GERİ ALINABİLİRLİK
#   Eski container SİLİNMEZ — "<name>-preloopback" adıyla stopped durur.
#   Katalog mutasyondan sonra birebir aynı değilse script KENDİ geri alır.
#   Manuel geri alma:
#     docker rm -f <name> && docker rename <name>-preloopback <name> && docker start <name>
#   Doğrulandıktan sonra temizlik:  docker rm <name>-preloopback
#
# KULLANIM (host üzerinde, aiserver)
#   bash rebind-k3d-registry-loopback.sh platform-test-registry 5001 platform-test-net test
#   bash rebind-k3d-registry-loopback.sh platform-prod-registry 5000 platform-prod-net prod
#
# Idempotent: bind zaten 127.0.0.1 ise no-op döner.
set -euo pipefail

NAME="${1:?container adı (örn. platform-test-registry)}"
PORT="${2:?host port (örn. 5001)}"
NET="${3:?docker network (örn. platform-test-net)}"
CLUSTER="${4:?k3d cluster adı (örn. test)}"
OLD="${NAME}-preloopback"

BIND="$(docker inspect "$NAME" --format '{{json .HostConfig.PortBindings}}')"
VOL="$(docker inspect "$NAME" --format '{{range .Mounts}}{{if eq .Destination "/var/lib/registry"}}{{.Name}}{{end}}{{end}}')"
IMG="$(docker inspect "$NAME" --format '{{.Config.Image}}')"

# Volume adı çözülemezse DOKUNMA — yanlış/eksik -v argümanı registry verisini
# yeni boş bir anonim volume'e kaydırır ve repo'lar "kaybolmuş" görünür.
[ -n "$VOL" ] || { echo "FATAL: /var/lib/registry volume bulunamadı — dokunmuyorum"; exit 1; }

echo "before: bind=$BIND volume=$VOL image=$IMG"
case "$BIND" in *'"HostIp":"127.0.0.1"'*) echo "ZATEN loopback — no-op"; exit 0 ;; esac

BEFORE="$(curl -s --max-time 5 "http://127.0.0.1:${PORT}/v2/_catalog" || echo FAIL)"
echo "katalog(önce): $BEFORE"

docker stop "$NAME" >/dev/null
docker rename "$NAME" "$OLD"

if ! docker run -d --name "$NAME" \
      --restart unless-stopped \
      -p "127.0.0.1:${PORT}:5000" \
      -v "${VOL}:/var/lib/registry" \
      --network "$NET" \
      -e K3S_KUBECONFIG_OUTPUT=/output/kubeconfig.yaml \
      --label app=k3d --label "k3d.cluster=${CLUSTER}" \
      --label k3d.registry.host=127.0.0.1 --label k3d.registry.hostIP=127.0.0.1 \
      --label k3d.role=registry --label k3d.version=v5.7.5 \
      --label "k3s.registry.port.external=${PORT}" --label k3s.registry.port.internal=5000 \
      "$IMG" >/dev/null; then
  echo "CREATE FAIL -> geri alıyorum"
  docker rm -f "$NAME" 2>/dev/null || true
  docker rename "$OLD" "$NAME"; docker start "$NAME" >/dev/null
  echo "ROLLBACK OK"; exit 1
fi

# Eski topolojiyi koru: k3d registry'yi hem cluster ağına hem default bridge'e bağlar.
docker network connect bridge "$NAME" 2>/dev/null || true

AFTER=""
for _ in $(seq 1 10); do
  AFTER="$(curl -s --max-time 3 "http://127.0.0.1:${PORT}/v2/_catalog" 2>/dev/null || true)"
  [ -n "$AFTER" ] && break
  sleep 1
done
echo "katalog(sonra): ${AFTER:-BOS}"

if [ "$AFTER" != "$BEFORE" ]; then
  echo "KATALOG UYUŞMUYOR -> geri alıyorum"
  docker rm -f "$NAME"
  docker rename "$OLD" "$NAME"; docker start "$NAME" >/dev/null
  echo "ROLLBACK OK (veri eski container'da güvende)"; exit 1
fi

echo "after: bind=$(docker inspect "$NAME" --format '{{json .HostConfig.PortBindings}}')"
echo "OK — eski container '$OLD' (stopped) geri alma için duruyor"
