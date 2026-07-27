Bir ağ teşhisi sırasında ölçüldü (VPN'siz, iç ağdan Mac'ten).

## Ölçüm

`.15` (aiserver — k3d-test + k3d-prod, Vault, Keycloak, Postgres barındıran host):

```
ufw                      : inactive
iptables INPUT DROP/REJECT: 0
tcp/22 kaynak kısıtı      : yok
```

Yani **host seviyesinde hiçbir paket filtresi yok**. Karşılaştırma: `.53` (legacy) → `ufw active`.

## Dış arayüzde (0.0.0.0) dinleyenler

| Port | Servis | Durum |
|---|---|---|
| 22 | sshd | beklenen |
| 80/443/5544/5545/8444 | nginx (edge) | beklenen |
| **5000** | `platform-prod-registry` | 🔴 **kimlik doğrulama YOK** |
| **5001** | `platform-test-registry` | 🔴 **kimlik doğrulama YOK** |
| 6379 | `platform-redis-streams-test` | ✅ `-NOAUTH Authentication required` |
| 9100/9101 | metrics exporter | 403 |

**İyi haber:** hassas olanların 16'sı yalnız `127.0.0.1`'e bağlı (Vault 8200/8201, Keycloak 8081/8082, Postgres…). Redis de auth istiyor. Yani ilk bakışta korktuğum "açık veri deposu" durumu **yok**.

## Asıl bulgu: kimliksiz registry'ler

```
curl http://10.9.10.15:5000/v2/          → 200      (401 + WWW-Authenticate DEĞİL)
curl http://10.9.10.15:5000/v2/_catalog  → {"repositories":[]}
curl http://10.9.10.15:5001/v2/_catalog  → {"repositories":["platform-backend-audio-gateway-service"]}
```

Kurumsal ağdaki **herhangi bir host** bu registry'lerin kataloğunu okuyabilir ve imaj çekebilir. Biri `platform-prod-registry` adını taşıyor.

**Yazma iznini TEST ETMEDİM** — push denemek mutasyon olurdu. Ama Docker Registry v2 varsayılanı auth'suz **read-write**'tır ve 401 dönmediğine göre yazmanın da açık olması kuvvetle muhtemel. Doğrulanması gerekiyor.

Eğer yazma açıksa: LAN'daki bir aktör cluster'ın çektiği bir etiketi **üzerine yazabilir** → tedarik zinciri riski. Bu, Faz 22'nin (güvenlik sertleştirme) doğrudan kapsamında.

## Neden şimdi görünür oldu

Bu host `.53`'ten yeni taşındı. `.53`'te `ufw` **aktifti**; `.15`'te hiç açılmamış. Yani taşımada **host güvenlik duvarı katmanı geride kaldı** — servisler taşındı, filtre taşınmadı.

## Öneri

1. **Registry'leri localhost'a bağla** — en az iş, en büyük kazanç. **YAPILDI** (aşağıya bkz.): kök neden repo desired-state'indeydi, orada düzeltildi + invariant testi eklendi.
2. ~~**ufw'yi `.53` profiline hizala**~~ — 🔴 **BU ÖNERİ TEHLİKELİDİR, GERİ ÇEKİLDİ.** Bkz. aşağıdaki "ufw tarafı" bölümü.
3. Yazma iznini doğrula (kontrollü, tek seferlik push denemesi) ve gerekirse `REGISTRY_STORAGE_DELETE_ENABLED=false` + auth ekle.

## Kapsam notu

Ben **hiçbir şeyi değiştirmedim** — tümü salt-okuma ölçümü. ufw'yi açmak ya da registry bağlamasını değiştirmek çalışan bir sistemde bağlantı kesebilir (cluster'lar bu registry'lere erişiyor olabilir), o yüzden owner kararına bırakıyorum.

---

## Ek ölçüm: LAN yayınını hiçbir şey kullanmıyor → kaldırmak güvenli

İlk yazımda "registry bağlamasını değiştirmek çalışan cluster'ların erişimini kesebilir, owner kararı" demiştim. **Ölçtüm; kesmiyor.**

```
tek tüketici (k3d-test):
  platform-test/audio-gateway → platform-test-registry:5000/platform-backend-audio-gateway-service@sha256:0bd85f41…

k3d node registries.yaml:
  platform-test-registry:5001:
    endpoint: [http://platform-test-registry:5000]

k3d-prod tüketici sayısı : 0
repo referansı           : 0   (ne 10.9.10.15:500x ne localhost:500x)
```

Cluster registry'ye **docker ağı içindeki hostname** (`platform-test-registry:5000`) ile ulaşıyor — host'un `-p 0.0.0.0:5000->5000` / `0.0.0.0:5001->5000` yayınıyla **hiç ilgisi yok**. Yani o iki yayın **ölü yüzey**: kimse kullanmıyor, ama LAN'daki herkese açık.

`platform-prod-registry` kataloğu ayrıca **boş** (`{"repositories":[]}`), yani orada korunacak veri de yok.

### Bu, riski ortadan kaldırıyor

Yayını kaldırmak (ya da `127.0.0.1`'e bağlamak) **fonksiyonel olarak etkisiz**, yalnız saldırı yüzeyini kapatır. Tek dikkat: docker port bağlaması değişmez, container **yeniden oluşturulmalı** → mevcut volume/veri argümanları korunmalı.

```bash
# ÖNCE mevcut argümanları çıkar (veri kaybını önlemek için):
docker inspect platform-test-registry --format '{{json .Mounts}}{{"\n"}}{{json .Config.Env}}'
docker inspect platform-prod-registry --format '{{json .Mounts}}{{"\n"}}{{json .Config.Env}}'

# sonra aynı volume ile, yayın olmadan (ya da 127.0.0.1'e bağlı) yeniden oluştur.
# audio-gateway zaten imajı cache'lediği için kısa registry kesintisi onu etkilemez.
```

---

## 2026-07-27 — Kök neden bulundu: yüzey REPO'da beyan edilmişti

İlk yazımda bunu bir host konfigürasyon kazası sandım. Değil. `bootstrap/k3d-{test,prod,dev}.yaml`:

```yaml
registries:
  create:
    name: platform-test-registry
    host: "0.0.0.0"        # ← desired-state olarak beyan edilmiş
    hostPort: "5001"
```

Bu yüzden **her cluster recreate'inde yüzey geri geliyordu** (test cluster'ı #2306 Method A v2 ile yeniden kurulmuştu). Canlı host'u elle düzeltmek semptomu kapatır, bir sonraki recreate'te geri gelir.

### Uygulanan kalıcı çözüm (PR — issue #2974)

| Katman | Değişiklik |
|---|---|
| Desired state | üç dosyada `host: "0.0.0.0"` → `"127.0.0.1"` + gerekçe yorumu |
| Makine-zorunlu | `tests/operations/test_bootstrap_registry_binding_invariant.py` — glob ile keşif (yeni cluster dosyası otomatik kapsanır), `is_loopback` kontrolü, **eksik `host`** da ihlal, boş-glob/boş-kapsam durumunda vacuous geçmeyi engelleyen sayaç |
| CI gerçekten koşsun | `gate-drift-detection.yml` paths filtresine `bootstrap/k3d-*.yaml` + `tests/operations/**` — bu olmadan test var ama koruduğu PR'da hiç koşmuyordu |
| Canlı taşıma | `bootstrap/host/rebind-k3d-registry-loopback.sh` — idempotent, eski container'ı `-preloopback` olarak **silmeden** bırakır, katalog önce/sonra eşleşmezse kendi geri alır |

Negatif doğrulama: testi iki mutasyonla denedim — `host` `0.0.0.0`'a çevrilince ve `host` satırı tamamen silinince **ikisinde de FAIL**, düzeltilmiş halde 2 passed. Yani çapa gerçekten tutuyor.

### Canlı adım durumu

Repo tarafı tamam. Canlı container yeniden bağlama **harness izin sınıflandırıcısı tarafından reddedildi** (canlı host container topolojisi mutasyonu) — bu bir yargı değil, izin sınırı. Script host'ta `/tmp/rebind-registry.sh` olarak ve kalıcı olarak repoda duruyor; tek komut:

```bash
ssh aiserver-vpn 'bash /tmp/rebind-registry.sh platform-test-registry 5001 platform-test-net test'
```

Mutasyon öncesi son güvenlik ölçümü (temiz): 5000/5001'e **açık bağlantı yok**, nginx proxy **yok**, conntrack'te akan trafik **yok**, katalog referansları alındı (test 1 repo / prod boş).

### 🔴 ufw tarafı — ilk önerim TEHLİKELİYDİ

İlk yazımda "`.53` profiline hizala, orada çalışan bir profil var" dedim. **Bunu uygulamak `.15`'te SSH'ı keserdi.** `.53`'ün profili şu:

```
22/tcp ALLOW IN 10.9.0.0/16      # iç LAN
22/tcp DENY  IN Anywhere
```

FortiClient VPN havuzu `10.250.250.0/24` LAN dışıdır → DENY'e düşer. Bu tam olarak `.53`'te **~4 günlük SSH outage**'a yol açan konfigürasyondu (`reference_host_restart_argocd_ufw_drift`); düzeltmesi `ufw insert 1 allow from 10.250.250.0/24 to any port 22 proto tcp` idi. Yani "çalışan profil" diye kopyalayacağım şey, bilinen bir outage'ın kaynağıydı.

`.15`'te durum daha da kötü olurdu: FortiGate politikası `.15`'i hedef almadığı için (ayrı bulgu) tek uzak erişim yolu `.53` üzerinden jump — SSH'ı kesen bir kural onu da götürür.

Herhangi bir ufw ruleset'i **açıkça** şunları içermeli: `22/tcp` (LAN **ve** `10.250.250.0/24`), edge portları (80/443/5544/5545/8444), WireGuard UDP, k3d API. `enable`'dan **önce** eklenmeli. Ölçülen mevcut durum: `.15`'te `ufw inactive`, `iptables filter` INPUT policy ACCEPT, `raw` PREROUTING'deki 9 DROP'un tamamı Docker anti-spoof (container IP'leri + `127.0.0.1:5432/5433/8200`), nftables kuralı yok.

ufw'yi açmak host güvenlik-ayarı mutasyonudur ve `.15` **hem test hem prod** cluster'ını barındırır → ortam-kapsam kuralı gereği owner onayı gerekir. Doğru yaklaşım deadman switch'li: kuralları yaz → `systemd-run --on-active=10min ufw disable` planla → `enable` → **yeni** bir bağlantıdan SSH'ı doğrula → deadman'i iptal et.

Yan not: postgres (5432/5433) ve Vault (8200) zaten `127.0.0.1`'e bağlı ve raw-DROP ile korunuyor — yani registry'ler bu host'ta hijyen kuralının istisnasıydı.
