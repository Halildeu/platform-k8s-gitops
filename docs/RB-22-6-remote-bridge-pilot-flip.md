# RB-22-6 — Remote-Bridge Pilot Flip Runbook (T-4 kickoff)

> **İKİ AYRI FAZ — sınır bulanıklaştırılamaz (Codex 019ebbe4 P0):**
> - **Faz A — Transport exposure smoke:** bugünkü merged kodla (T-2c #583 sonrası)
>   yapılabilir; mTLS edge + fail-closed davranış kanıtlanır. Bu **canlı oturum
>   DEĞİLDİR** — T-2 transport'u kasıtlı inert'tir: `ControlPlaneHandler` INERT,
>   broker permit zinciri bağlı değil, heartbeat lease=0, DATA frame'leri semantiksiz.
> - **Faz B — İlk canlı oturum:** EK KOD ister (T-4 wiring) + D10 11/11 madde-seviyesi
>   yeşil + DPO/Hukuk artifact'ları. "Config-only flip" iddiası Faz B için GEÇERSİZ.
>
> **Bu runbook'u koşmak owner kararıdır; agent kendi başına koşamaz** (ADR-0034 §11).
> **Referans:** [ADR-0033](adr/0033-faz-22-6-remote-access-bridge-broker.md) ·
> [ADR-0034 §11/D10](adr/0034-1388-sensitive-endpoint-ops-owner-decision.md) ·
> [ADR-0038](adr/0038-faz-22-6-remote-access-transport.md) ·
> [acceptance package §11.4 kanıt haritası](faz-22-6-1388-acceptance-package.md) ·
> wire contract: platform-backend `endpoint-admin-service/docs/remote-bridge-wire-contract.md`
>
> **Kapsam — bu runbook yalnız ATTENDED VIEW_ONLY pilotudur (D8).** Unattended/break-glass
> **offline domain-auth recovery** ayrı bir capability düzlemidir → **[ADR-0040](adr/0040-faz-22-6-breakglass-domain-auth-recovery.md)**
> (PROPOSED, ayrı owner-sign-off §9; agent-mediated Kerberos AS-REQ relay). Bu runbook'la
> AÇILMAZ; kendi acceptance gate'i (ADR-0040 BG-D5) vardır.

---

## FAZ A — Transport exposure smoke (mevcut HEAD ile; canlı oturum değil)

**Amaç:** mTLS uçtan uca + fail-closed davranışın GERÇEK ağda kanıtı. Ekran/PTY/consent
YOK; sadece transport. Bu faz tamamlandığında elde edilen şey "broker'a güvenli
bağlanılabiliyor" kanıtıdır — oturum yetkisi değil.

### A0. Önkoşul

- [ ] Owner "transport smoke başlasın" kararı (bu da exposure'dır — agent başlatamaz)
- [ ] D10-8'in transport-smoke alt kümesi: NetworkPolicy + edge kuralı PR'ı merged
      → broker isolation manifest seti: scaffold `kustomize/base/apps/endpoint-admin-remote-bridge/`
      (inert, replicas:0) + owner-gated activation overlay
      `kustomize/overlays/test/activation/endpoint-admin-remote-bridge/` (Argo root dışı;
      11 izolasyon kontrolü + NetworkPolicy + ESO orada). Aktivasyon prosedürü:
      o overlay'in `OWNER-APPROVAL.md` dosyası.

### A1. PKI — iki AYRI CA (~30 dk)

T-2c test mimarisiyle birebir; tek-CA-iki-amaç YASAK:

| CA | İmzaladığı | Trust'ı kim taşır |
|---|---|---|
| `rb-broker-ca` | broker server cert (SAN: broker FQDN + edge IP) | agent `trustManager` |
| `rb-device-ca` | pilot cihaz client cert'leri | broker `client-ca-pem-path` (`clientAuth=REQUIRE`) |

AG-018 internal-OpenSSL-CA custody pattern reuse (host-fs custody + sudoers-pinned
wrapper). EC P-256 + SHA256; leaf ≤90 gün; CRL → B1.4 evaluator
(`endpoint-admin.remote-access.cert-trust.crl-pem`).

```bash
openssl ecparam -name prime256v1 -genkey -noout -out rb-device-ca.key
openssl req -new -x509 -key rb-device-ca.key -out rb-device-ca.pem -days 365 -subj "/CN=rb-device-ca"
# cihaz başına: CSR → CA imza → PKCS#12 → cihaza DPAPI/TPM korumalı kurulum
```

**Fail sinyali:** cihaz cert SAN/CN beklenen device-id değilse DUR (B1.4
CertIdentityGuard SAN'ı authoritative okur).

### A2. Secret delivery — ESO/Vault (GitOps truth; kubectl-imperative DEĞİL)

Repo'nun secret pattern'i ESO/Vault'tur (bkz. `kustomize/overlays/test/eso/endpoint-admin/`);
remote-bridge TLS de aynı yoldan gider — imperative `kubectl create secret` drift
yaratır ve YASAKTIR (Codex 019ebbe4 P2):

1. Vault seed (D43 stdin-pipe pattern — değerler shell history'ye düşmez):
   ```bash
   # SUPERSEDED 2026-06-12 (D10-8 broker isolation): broker SEPARATE Vault path
   # kv/platform/endpoint-admin-remote-bridge (control #3/#9 — broker secret'i
   # endpoint-admin-service-secrets ile ortak path'te durmaz). Seed komutu +
   # tam key listesi: activation overlay OWNER-APPROVAL.md.
   ssh halil@staging-sw "vault kv put kv/platform/endpoint-admin-remote-bridge \
     broker_tls_cert_chain_pem=@server-chain.pem broker_tls_private_key_pem=@server-key.pem device_ca_pem=@rb-device-ca.pem"
   ```
2. Gitops PR: `externalsecret.yaml`'a 3 key + Deployment'a secret-volume mount
   (`/etc/remote-bridge/tls`, readOnly) + aşağıdaki property'ler.
3. ESO force-sync → `kubectl get secret` ile render doğrula (hash-only, değer loglanmaz).

```yaml
remote-bridge:
  enabled: "true"
  bind-host: "0.0.0.0"            # TLS ile legal; loopback kısıtı yalnız plaintext içindir
  port: "9444"
  tls:
    cert-chain-pem-path: /etc/remote-bridge/tls/server-chain.pem
    private-key-pem-path: /etc/remote-bridge/tls/server-key.pem
    client-ca-pem-path: /etc/remote-bridge/tls/device-ca.pem
  # allow-insecure-plaintext ASLA set edilmez (default false)
```

**Beklenen:** pod log `remote-bridge grpc server listening on 0.0.0.0:9444 (mutual TLS)`.
**Fail sinyali:** `TLS credentials failed to load` / `PARTIAL` → secret render'ı düzelt;
pod bind ETMEDEN fail eder (yarı-açık durum yoktur — kod garantisi #583).

### A3. Ağ — NetworkPolicy + L4 TLS-passthrough edge

- **NetworkPolicy:** 9444'e ingress YALNIZ edge passthrough kaynağından; egress
  yalnız DB/recorder. Tam broker hardening (11 kontrol) artık manifest olarak
  mevcut: `kustomize/overlays/test/activation/endpoint-admin-remote-bridge/netpol.yaml`
  (ingress 9444 allowlist + egress default-deny scoped + per-session device ACL).
- **Host nginx `stream` (TERMINATE ETME — ADR-0038):**

```nginx
stream {
  server {
    listen 9444;
    proxy_pass 127.0.0.1:31944;   # k3d nodePort → broker 9444
  }
}
```

**Passthrough kanıtı:** `openssl s_client -connect <edge>:9444` çıktısındaki zincir
`rb-broker-ca` imzalı broker leaf'i olmalı (edge'in kendi cert'i görünüyorsa
terminate ediyor demektir → DUR, yanlış konfigürasyon).

### A4. Faz A kabulü (D29-EA — transport alt kümesi)

| Katman | Kanıt | Beklenen |
|---|---|---|
| **Up** | pod Ready + `nc -z <edge> 9444` | TCP açık, restart=0 |
| **Functional (transport)** | pilot cihazdan T-3 harness `connect` (client cert) | mTLS handshake OK; AgentHello→INERT seam; server-push heartbeat; registry'de peer; `killPeer` drill <1s |
| **Secured** | (a) cert'siz `openssl s_client` FAIL; (b) yanlış-CA cert reject; (c) plaintext reddi; (d) edge-dışı path'ten 9444'e erişim YOK | dördü fail-closed |

> **Bu tablo CANLI OTURUM kabulü DEĞİLDİR.** Faz B Functional kanıtı broker permit
> issuance/deny + consent lease + recording fail-closed + operation-level policy +
> revocation kill zincirini ister (aşağıda B2).

### A5. Faz A rollback (≤5 dk)

1. `remote-bridge.enabled=false` → rollout restart (broker bean'leri tamamen yok)
2. Edge `stream` bloğu kaldır + nginx reload
3. Kanıt: 9444 kapalı + pod log'da remote-bridge satırı yok
4. Cihaz cert iptali gerekiyorsa CRL'e ekle

---

## FAZ B — İlk canlı oturum (EK KOD + 11/11 D10 yeşil olmadan AÇILMAZ)

### B0. Ön-şartlar (hepsi zorunlu; biri eksikse pilot BLOCKED — ADR-0034 §11)

- [ ] **T-4 wiring MERGED + kanıtlı (kod işi, "config-only" DEĞİL):** broker
  SessionContext assembly (`ControlPlaneHandler` INERT'ten gerçek broker'a),
  attended-consent UI (endpoint'te görünür prompt + local abort), operator channel
  (FIDO2/WebAuthn step-up, D10-9), gerçek VIEW_ONLY capture + ConPTY (pilot
  kapsamına göre), recording aktivasyonu + broker-bağımsız WORM sink (D10-2),
  owner-signed pilot token akışı
- [ ] Acceptance package [§11.4 kanıt haritası](faz-22-6-1388-acceptance-package.md)
  **11/11 madde-seviyesi yeşil** (🔶/❌ kalmadı)
- [ ] §11.2 DPO/Hukuk artifact'ları imzalı (aydınlatma + inventory edit + DPIA)
- [ ] D7 roster (§B3) dolu + maker≠checker doğrulanmış
- [ ] Red-team drill raporu (D10-11) yeşil
- [ ] Faz A smoke kanıtları arşivli + Faz A rollback bir kez prova edilmiş

### B1. Canlı oturum açılışı

Faz A altyapısı üstüne: pilot operatörü → operator channel (step-up auth) →
SessionRequest → endpoint'te attended-consent prompt → consent lease → broker
permit → oturum `ACTIVE` (recording `RECORDING_READY` olmadan ACTIVE olamaz —
fail-closed, ADR-0034 D3).

### B2. Faz B kabulü (D29-EA — tam küme)

- **Functional:** uçtan uca oturum: permit issuance + capability enforcement
  (SCREEN_VIEW/PTY_COMMAND allowlist) + consent lease expiry/abort davranışı +
  recording chain'in bağımsız doğrulanması
- **Secured (negatifler):** self-approval deny · expired/replayed token deny ·
  capability-mismatch deny · recorder-unavailable deny · canlı revoke→kill SLO
  ölçümü · user local-abort <5s · approver-revocation kill <10s
- İlk oturum günü: audit hash-chain bağımsız doğrulama + KILL SLO + ErrorFrame
  oranı → board #510 comment + kanıtlar package §11.3-11.4'e işlenir

### B3. D7 roster (pilot kickoff'ta doldurulur — ADR-0034 D7)

| Alan | Değer |
|---|---|
| Pilot cihazlar (2-5, IT-owned, BYOD yok) | `[ ]` örn. HALILKOOLUB735, MKR-A1 |
| Requester(lar) | `[ ]` |
| Operator(lar) | `[ ]` |
| Approver(lar) (≠ requester, insan) | `[ ]` |
| Pilot penceresi | `[ ]` |
| Kayıt saklama onayı (D3: 90g raw / 7y metadata) | `[ ]` |
