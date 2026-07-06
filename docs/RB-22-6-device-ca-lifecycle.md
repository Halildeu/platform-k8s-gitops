# RB-22-6 — Device-CA Lifecycle Runbook (D10-3 PKI lifecycle + D10-6 rotation/revoke drill)

> **Amaç:** remote-bridge mTLS'in **device-CA** tarafının tam yaşam döngüsü —
> issuance → CRL distribution → rotation → revocation drill. Pilot-flip runbook
> [§A1](RB-22-6-remote-bridge-pilot-flip.md) iki-ayrı-CA'yı **özetler**; bu runbook
> device-CA operasyon detayıdır (ADR-0034 §11/D10 #3 "PKI lifecycle" + #6 "key
> leak/rotation" drill'in CA tarafı).
> **Status:** operasyon runbook HAZIR; CANLI koşum **owner/operator-gated** (cert
> material + Vault custody — agent kendi başına koşamaz).
> **KOD PRECONDITION (Codex 019ebc24):** bu runbook'un live path'i şu T-4/config
> ön-şartlarına bağlı (henüz default-off): (a) broker `cert-trust.evaluator=REAL_PKI`
> + `revocation-mode=CRL` + `trust-anchor-pem` + `crl-pem` (default IN_MEMORY/DISABLED);
> (b) device-CA **rotation overlap** için multi-issuer pin (mevcut B1.4 tek-issuer);
> (c) remote-bridge live mTLS **SAN→device binding** (mevcut `CertIdentityGuard` issuer/
> serial guard'dır, SAN parse etmez — SAN parse `MachineCertExtractor`'da, issuance/
> enrollment canonical). Bu ön-şartlar gelmeden runbook design-time-doğru ama live-path
> wiring'i eksiktir.
> **Custody pattern:** AG-018 internal-OpenSSL-CA (no paid CA, no AD CS) —
> host-fs custody + sudoers-pinned wrapper.
> **Referans:** [pilot-flip §A1](RB-22-6-remote-bridge-pilot-flip.md) ·
> [red-team drill §4/§6](RB-22-6-remote-bridge-redteam-drill.md) (token-theft + key-rotation) ·
> B1.4 evaluator (`endpoint-admin.remote-access.cert-trust.crl-pem`) ·
> [ADR-0038](adr/0038-faz-22-6-remote-access-transport.md)

---

## 0. CA hiyerarşisi (iki ayrı CA — tek-CA-iki-amaç YASAK)

| CA | İmzalar | Trust taşıyıcı | Custody |
|---|---|---|---|
| `rb-broker-ca` | broker server leaf (SAN: broker FQDN + edge IP) | agent `trustManager` | host-fs `/opt/rb-pki/broker-ca/` (sudoers-pinned) |
| `rb-device-ca` | her pilot cihaz client leaf | broker `client-ca-pem-path` (clientAuth=REQUIRE) | host-fs `/opt/rb-pki/device-ca/` (sudoers-pinned) |

EC P-256 + SHA256; CA ömrü 1y (pilot), leaf ≤90 gün. **Private key custody:** host-fs
`0600 root:root`, sudoers-pinned wrapper script erişir (operatör shell'den raw key okuyamaz);
asla Vault'a ham CA key konmaz (CA = root-of-trust, air-gap-benzeri custody).

## 1. Device-CA kurulumu (bir kez, ~15 dk operator)

> Tüm komut blokları **root shell / sudo wrapper** altında koşar (`/opt/rb-pki` 0700 root:root).

```bash
sudo install -d -m 0700 /opt/rb-pki/device-ca
cd /opt/rb-pki/device-ca
sudo openssl ecparam -name prime256v1 -genkey -noout -out device-ca.key
sudo chmod 0600 device-ca.key
sudo openssl req -new -x509 -key device-ca.key -out device-ca.pem -days 365 \
  -subj "/CN=rb-device-ca/O=acik" \
  -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
  -addext "keyUsage=critical,keyCertSign,cRLSign"
```

**Fail sinyali:** `basicConstraints CA:TRUE` veya `keyUsage cRLSign` eksikse DUR —
CRL imzalayamayan CA revocation drill'i (D10-6) çalıştıramaz.

## 1.5 CA database bootstrap (ZORUNLU — `openssl ca` bunsuz çalışmaz, Codex P1)

`openssl ca -gencrl/-revoke` gerçek bir CA DB ister; bu olmadan §3/§5 ilk adımda kırılır:

```bash
cd /opt/rb-pki/device-ca
sudo touch index.txt
sudo bash -c 'echo 1000 > serial'        # leaf serial counter
sudo bash -c 'echo 1000 > crlnumber'     # CRL number counter
sudo install -d newcerts
# openssl.cnf [ CA_default ]: dir, database=index.txt, serial, crlnumber, new_certs_dir=newcerts,
#   private_key=device-ca.key, certificate=device-ca.pem, default_md=sha256,
#   default_crl_days=1, policy + copy_extensions=copy + clientAuth EKU issuance profile
```

**Fail sinyali:** `index.txt`/`serial`/`crlnumber` yoksa `openssl ca` "unable to load CA
database" verir. `rb-issue-device-cert.sh` AYNI DB üzerinden imzalamalı — aksi halde CRL
verilen leaf serial'ını içermez (revoke drill sessizce başarısız olur).

## 2. Device cert issuance (cihaz başına, ~5 dk)

**Birincil yol (D10-3 non-exportable hedefi):** CSR'ı CİHAZDA TPM/DPAPI non-exportable key
ile üret (private key cihazdan asla çıkmaz). Aşağıdaki `-nodes` operator-host akışı yalnız
**geçici pilot bootstrap** — D10-3 closure DEĞİL, geçiş riski; raw key host'ta kalmamalı
(issuance sonrası `shred -u dev-<id>.key` + audit).

```bash
# GEÇİCİ pilot bootstrap (raw key — D10-3 final değil): CSR + SAN'lı leaf
openssl req -new -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes \
  -keyout dev-<device-id>.key -out dev-<device-id>.csr \
  -subj "/CN=<device-id>" -addext "subjectAltName=URI:adcomputer:<objectGUID>"
# NOT (Codex): SAN adcomputer:{objectGUID} = ISSUANCE/ENROLLMENT canonical identity
# (MachineCertExtractor doğrular). remote-bridge LIVE mTLS path'inde SAN→device binding
# henüz enforce edilmez — mevcut B1.4 CertIdentityGuard issuer/serial guard'dır. Live
# SAN-binding = T-4 evidence-required (PeerIdentityInterceptor certBoundDeviceId + broker).
# device-CA imza (sudoers-pinned wrapper) + EKU clientAuth + serial ledger
sudo /opt/rb-pki/bin/rb-issue-device-cert.sh dev-<device-id>.csr   # → dev-<device-id>.pem
# cihaza kurulum: PKCS#12 → DPAPI (Windows) veya TPM-bound (D10-3 non-exportable hedef)
openssl pkcs12 -export -inkey dev-<device-id>.key -in dev-<device-id>.pem \
  -certfile /opt/rb-pki/device-ca/device-ca.pem -out dev-<device-id>.p12
```

**Serial ledger zorunlu:** her issuance `serial,device-id,issued-at,operator` satırı append-only
log'a (revocation + audit için). Wrapper `rb-issue-device-cert.sh` `openssl ca` ile §1.5 CA-DB
üzerinden imzalar (aynı index.txt/serial → revoke/gencrl ile tutarlı), EKU `clientAuth` basar,
CSR SAN'ını kontrollü kopyalar (`copy_extensions = copy` + allowlist). **Fail sinyali:** issuance
SAN ile ledger device-id uyuşmazsa DUR (enrollment canonical; live binding T-4).

## 3. CRL generation + distribution (D10-3 revocation path)

**KOD PRECONDITION (Codex P1):** mevcut broker default `evaluator=IN_MEMORY` +
`revocation-mode=DISABLED` + boş `crl-pem`; CRL'i okuması için ÖNCE şu config aktif olmalı
(gitops PR — henüz yok):
- `ENDPOINT_ADMIN_REMOTE_ACCESS_CERT_TRUST_EVALUATOR=REAL_PKI`
- `ENDPOINT_ADMIN_REMOTE_ACCESS_CERT_TRUST_REVOCATION_MODE=CRL`
- `...TRUST_ANCHOR_PEM` (device-CA) + `...CRL_PEM` (CRL içeriği)
- ExternalSecret'a `RB_DEVICE_CA_CRL` + `RB_DEVICE_CA_TRUST_ANCHOR` key'leri + Deployment env mapping

**`crl-pem` startup-time okunur (hot-reload YOK):** `ScheduledRevocationDriver` CRL'i boot'ta
parse eder; yeni CRL = **rollout restart** (envFrom secret pickup + reparse). Canlı "reload" YOK.

```bash
# CRL üret (device-CA imzalı, §1.5 CA-DB üzerinden) — nextUpdate kısa (pilot 24h)
sudo openssl ca -gencrl -config /opt/rb-pki/device-ca/openssl.cnf \
  -out /opt/rb-pki/device-ca/device-ca.crl -crldays 1
# Vault seed (D43 stdin-pipe) → ExternalSecret → Deployment env → ROLLOUT RESTART (boot reparse)
ssh halil@staging-sw "vault kv patch kv/platform/endpoint-admin-service \
  RB_DEVICE_CA_CRL=@/opt/rb-pki/device-ca/device-ca.crl"
# ESO sync + kubectl rollout restart deploy/<broker> → yeni CRL boot'ta yüklenir
```

**Beklenen:** rollout sonrası `CertPathTrustEvaluator` yeni CRL'i parse eder;
`aStaleCrlPastItsNextUpdateIsUnknownFailClosed` testinin canlı karşılığı — `nextUpdate` geçmiş
CRL = `UNKNOWN` fail-closed. **Fail sinyali:** REAL_PKI config aktif değilken (default IN_MEMORY)
CRL hiç okunmaz — revoke etkisiz; ÖNCE config precondition.

## 4. Rotation (CA + leaf, periyodik + key-leak sonrası)

| Rotasyon | Tetik | Adım | Broker etkisi |
|---|---|---|---|
| **Leaf rotation** | 90g ömür / pilot bitiş | yeni CSR → device-CA imza → cihaz reinstall; eski leaf CRL'e | kid değişmez (device-CA aynı); eski leaf CRL ile reddedilir |
| **Device-CA rotation** | 1y / key-leak şüphesi | yeni device-CA üret → broker trust-anchor bundle (eski+yeni) → tüm leaf reissue → eski device-CA retire | overlap window'da iki CA trusted; sonra eski kaldırılır — **ama mevcut B1.4 tek-issuer pin (Codex P1), multi-issuer = T-4 precondition** |
| **Permit-signing key rotation** | key-leak / periyodik | broker `kid` bump (RemoteBridgePermitSigner) → eski kid'li permit `anExpiredOrWrongKidPermitIsRejected` ile reddedilir | agent eski-kid permit reddeder |

**Overlap window — güvenlik muhasebesi (Codex P1):** mevcut `CertIdentityGuard` + `ScheduledRevocationDriver`
**tek `expected-issuer-dn`** kullanır; iki-CA overlap için ya (a) multi-issuer pin desteği T-4 code
precondition'dır, ya da (b) overlap yalnız şu ek binding'lerle güvenli sayılır: **bounded trust-anchor
bundle** (yalnız eski+yeni device-CA, başka kök yok) + **per-device serial/thumbprint binding** (cert-bound
token, B1.1) + **CRL her iki CA'da** + **kısa TTL** + **audit + explicit rollback**. "fail-open YASAK"
iddiası bu muhasebe yapılmadan geçerli değildir — issuer-pin eski-CA'da kalırsa yeni-CA leaf'leri
fail-closed olur (DOĞRU yön), pin kapatılırsa trust iki-CA'ya genişler (yukarıdaki binding'ler şart).

## 5. Revocation drill (D10-6 key-leak/rotation — CANLI, owner-gated)

| Adım | Komut | Beklenen |
|---|---|---|
| 1. Bir pilot cihaz cert'ini revoke et | `sudo openssl ca -revoke dev-<id>.pem -config …` | serial CRL'e eklenir |
| 2. CRL regenerate + dağıt | §3 adımları | broker yeni CRL yükler |
| 3. Revoked cihazla bağlan | revoked cert ile mTLS handshake | **broker B1.4 REVOKED → reject/KILL** (handshake geçse bile device-trust=false) |
| 4. Permit-signing key rotate | broker kid bump | eski-kid permit reddedilir |
| 5. Eski-kid permit replay | yakalanmış eski permit sun | **agent verifier kid-mismatch reddeder** |

**Pass kriteri:** revoked cert + eski-kid permit'in ikisi de fail-closed reddedilir. Sonuç
red-team drill raporu §6'ya işlenir (acceptance package §11.4 D10-6).

## 6. Rollback / acil (key-leak müdahale)

1. **CA key sızdı şüphesi:** device-CA rotation (§4) — TÜM leaf reissue + eski CA retire (overlap window)
2. **Permit-signing key sızdı:** kid bump (§4) — eski kid tüm permit'leri geçersiz kılar (anında)
3. **Tek cihaz compromise:** o cihazın cert'ini revoke (§5) + CRL dağıt + cihaz re-enroll
4. Tüm acil işlemler serial ledger + audit'e; post-incident ADR

## 7. Custody guard (AG-018 pattern)

- CA private key: `0600 root:root`, sudoers-pinned wrapper (`rb-issue-device-cert.sh`,
  `rb-revoke.sh`) dışında erişim YOK; operatör shell'den raw key okuyamaz
- Wrapper script'ler: input CSR validation + serial ledger append + audit log
- Vault'a yalnız **CRL** (public) + **leaf** dağıtım materyali konur; **CA key asla**
- Custody host: staging-sw (pilot); prod cutover'da ayrı air-gap-benzeri host değerlendirilir
