# RB-22-6 — Remote-Bridge Pilot Flip Runbook (T-4 kickoff)

> **Tetik:** ADR-0034 §11/D10 expanded gate'in tüm maddeleri kanıtlı + §13 imzalı
> (engineering imzası 2026-06-11'de ATILDI; bu runbook İLK CANLI OTURUM flip'inin
> operasyonel sırasıdır). **Bu runbook'u koşmak = canlı pilot başlatmak — owner
> kararıdır; agent kendi başına koşamaz.**
> **Kod tarafı hazır:** T-2c (#583) sonrası flip **yalnız config + mounted secret
> dosyaları** — kod değişikliği sıfır. Enabled broker mutual-TLS-only fail-closed'tır;
> eksik/bozuk PEM ile pod hiç bind etmez (port kanıtlı kapalı kalır).
> **Referans:** [ADR-0033](adr/0033-faz-22-6-remote-access-bridge-broker.md) ·
> [ADR-0034](adr/0034-1388-sensitive-endpoint-ops-owner-decision.md) ·
> [ADR-0038](adr/0038-faz-22-6-remote-access-transport.md) ·
> [acceptance package §11.4 kanıt haritası](faz-22-6-1388-acceptance-package.md) ·
> wire contract: platform-backend `endpoint-admin-service/docs/remote-bridge-wire-contract.md`

---

## 0. Önkoşul çek-listesi (flip'ten ÖNCE — hepsi zorunlu)

- [ ] ADR-0034 §11.4 kanıt haritasında 11/11 madde ✅ (kalan 🔶/❌ işler kapandı)
- [ ] §11.2 DPO/Hukuk artifact'ları imzalı (aydınlatma metni + inventory edit + DPIA)
- [ ] D7 roster (aşağıda §6) doldurulmuş + maker≠checker doğrulanmış
- [ ] Red-team drill raporu (D10-11) yeşil
- [ ] Rollback path test edilmiş (§5 — flip'ten önce bir kez prova)

## 1. PKI — device-CA + broker sertifikaları (~30 dk)

İki AYRI CA (T-2c test mimarisiyle birebir; tek-CA-iki-amaç YASAK):

| CA | İmzaladığı | Trust'ı kim taşır |
|---|---|---|
| `rb-broker-ca` | broker server cert (SAN: broker FQDN + cluster IP) | agent'ın `trustManager`'ı |
| `rb-device-ca` | her pilot cihazın client cert'i | broker `client-ca-pem-path` (`clientAuth=REQUIRE`) |

AG-018 internal-OpenSSL-CA custody pattern'i reuse (host-fs custody + sudoers-pinned
wrapper). EC P-256 + SHA256; leaf ömrü pilot için ≤ 90 gün; CRL dağıtımı B1.4b
evaluator'a (`endpoint-admin.remote-access.cert-trust.crl-pem`).

```bash
# örnek (staging-sw, custody dizininde):
openssl ecparam -name prime256v1 -genkey -noout -out rb-device-ca.key
openssl req -new -x509 -key rb-device-ca.key -out rb-device-ca.pem -days 365 -subj "/CN=rb-device-ca"
# her pilot cihaz için: CSR → CA imza → PKCS#12 export → cihaza DPAPI/TPM korumalı kurulum
```

**Fail sinyali:** cihaz cert'inde SAN/CN beklenen device-id değilse DUR — B1.4
CertIdentityGuard SAN'ı authoritative okur.

## 2. K8s secret + deployment mount (~10 dk, gitops PR)

```bash
kubectl --context k3d-test -n platform-test create secret generic remote-bridge-tls \
  --from-file=server-chain.pem --from-file=server-key.pem --from-file=device-ca.pem
```

Deployment patch (gitops PR — endpoint-admin):
- volume `remote-bridge-tls` → mount `/etc/remote-bridge/tls` (readOnly)
- env/property:

```yaml
remote-bridge:
  enabled: "true"
  bind-host: "0.0.0.0"            # pod-içi; dış erişim YALNIZ L4 passthrough üzerinden
  port: "9444"
  tls:
    cert-chain-pem-path: /etc/remote-bridge/tls/server-chain.pem
    private-key-pem-path: /etc/remote-bridge/tls/server-key.pem
    client-ca-pem-path: /etc/remote-bridge/tls/device-ca.pem
  # allow-insecure-plaintext ASLA set edilmez (default false; loopback-dışında zaten reddedilir)
```

**Beklenen:** pod log `remote-bridge grpc server listening on 0.0.0.0:9444 (mutual TLS)`.
**Fail sinyali:** `TLS credentials failed to load` / `PARTIAL` → secret mount'u düzelt;
pod bind ETMEDEN fail eder (yarı-açık durum yoktur).

## 3. Ağ — NetworkPolicy + L4 TLS-passthrough edge (~20 dk, gitops PR)

- **NetworkPolicy (D10-8):** 9444'e ingress YALNIZ edge passthrough kaynağından;
  egress yalnız DB/recorder. Broker pod'una başka hiçbir yol yok.
- **Host nginx `stream` bloğu (TLS-passthrough — TERMINATE ETME, ADR-0038):**

```nginx
stream {
  server {
    listen 9444;                       # dış yüzey
    proxy_pass 127.0.0.1:31944;        # k3d nodePort → broker 9444
    # TLS passthrough: certificate BURADA SONLANMAZ — mTLS uçtan uca broker'da
  }
}
```

**Doğrulama:** `openssl s_client -connect <edge>:9444` → sertifika `rb-broker-ca`
zincirli broker leaf'i göstermeli (edge'in kendi cert'i DEĞİL → passthrough kanıtı).

## 4. D29-EA kabulü (Up ≠ Functional ≠ Secured — üçü AYRI kanıt)

| Katman | Komut/işlem | Beklenen |
|---|---|---|
| **Up** | pod Ready + `nc -z <edge> 9444` | TCP açık, restart=0 |
| **Functional** | pilot cihazdan T-3 harness `connect` (client cert'le) | AgentHello→seam; server-push heartbeat akar; KILL drill <1s |
| **Secured** | (a) cert'siz `openssl s_client` handshake FAIL; (b) yanlış-CA cert reject; (c) plaintext bağlantı reddi; (d) broker'a edge-dışı path'ten erişim YOK (NetPol) | dördü de fail-closed |

Ek negatifler (D10-1/2): canlı revoke→kill SLO ölçümü; recorder durdur→yeni oturum
`ACTIVE` olamıyor (fail-closed) kanıtı.

## 5. Rollback (≤5 dk, tek property)

1. `remote-bridge.enabled=false` → rollout restart (broker bean'leri tamamen yok olur)
2. Edge `stream` bloğunu kaldır/comment + nginx reload
3. Secret yerinde kalabilir (pasif); cihaz cert'leri iptal gerekiyorsa CRL'e ekle
4. Kanıt: 9444 kapalı + pod log'da remote-bridge satırı yok

## 6. D7 roster (pilot kickoff'ta doldurulur — ADR-0034 D7 gereği §11 gate parçası)

| Alan | Değer |
|---|---|
| Pilot cihazlar (2-5, IT-owned, BYOD yok) | `[ ]` örn. HALILKOOLUB735, MKR-A1 |
| Requester(lar) | `[ ]` |
| Operator(lar) | `[ ]` |
| Approver(lar) (≠ requester, insan) | `[ ]` |
| Pilot penceresi (başlangıç/bitiş) | `[ ]` |
| Kayıt saklama onayı (D3: 90g raw / 7y metadata) | `[ ]` |

## 7. İlk oturum sonrası (aynı gün)

- D29-EA kanıtlarını acceptance package §11.3-11.4'e işle
- Audit zincirinin (hash-chain) ilk oturum kayıtlarını bağımsız doğrula
- Gözlem: KILL SLO + heartbeat kayıpları + ErrorFrame oranı → board #510 comment
