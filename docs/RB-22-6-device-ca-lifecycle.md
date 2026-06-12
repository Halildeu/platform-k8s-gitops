# RB-22-6 — Device-CA Lifecycle Runbook (D10-3 PKI lifecycle + D10-6 rotation/revoke drill)

> **Amaç:** remote-bridge mTLS'in **device-CA** tarafının tam yaşam döngüsü —
> issuance → CRL distribution → rotation → revocation drill. Pilot-flip runbook
> [§A1](RB-22-6-remote-bridge-pilot-flip.md) iki-ayrı-CA'yı **özetler**; bu runbook
> device-CA operasyon detayıdır (ADR-0034 §11/D10 #3 "PKI lifecycle" + #6 "key
> leak/rotation" drill'in CA tarafı).
> **Status:** operasyon runbook HAZIR; CANLI koşum **owner/operator-gated** (cert
> material + Vault custody — agent kendi başına koşamaz).
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

## 2. Device cert issuance (cihaz başına, ~5 dk)

```bash
# cihazda (veya operator host): CSR — device-id SAN'da authoritative (B1.4 CertIdentityGuard okur)
openssl req -new -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes \
  -keyout dev-<device-id>.key -out dev-<device-id>.csr \
  -subj "/CN=<device-id>" -addext "subjectAltName=URI:adcomputer:<objectGUID>"
# device-CA imza (sudoers-pinned wrapper) + EKU clientAuth + serial ledger
sudo /opt/rb-pki/bin/rb-issue-device-cert.sh dev-<device-id>.csr   # → dev-<device-id>.pem
# cihaza kurulum: PKCS#12 → DPAPI (Windows) veya TPM-bound (D10-3 non-exportable hedef)
openssl pkcs12 -export -inkey dev-<device-id>.key -in dev-<device-id>.pem \
  -certfile /opt/rb-pki/device-ca/device-ca.pem -out dev-<device-id>.p12
```

**Serial ledger zorunlu:** her issuance `serial,device-id,issued-at,operator` satırı append-only
log'a (revocation + audit için). **Fail sinyali:** SAN device-id beklenen değilse DUR
(B1.4 CertIdentityGuard SAN'ı authoritative okur — yanlış SAN = yanlış cihaz binding).

## 3. CRL generation + distribution (D10-3 revocation path)

```bash
# CRL üret (device-CA imzalı) — nextUpdate kısa (pilot 24h; stale CRL fail-closed)
sudo openssl ca -gencrl -config /opt/rb-pki/device-ca/openssl.cnf \
  -out /opt/rb-pki/device-ca/device-ca.crl -crldays 1
# broker'a dağıt: Vault seed (D43 stdin-pipe) → ExternalSecret → crl-pem property
ssh halil@staging-sw "vault kv patch kv/platform/endpoint-admin-service \
  RB_DEVICE_CA_CRL=@/opt/rb-pki/device-ca/device-ca.crl"
# ESO force-sync → broker B1.4 evaluator crl-pem reload
```

**Beklenen:** B1.4 `CertPathTrustEvaluator` CRL'i yükler; `aStaleCrlPastItsNextUpdateIsUnknownFailClosed`
testinin canlı karşılığı — `nextUpdate` geçmiş CRL = `UNKNOWN` fail-closed (revoke kaçmaz).
**Fail sinyali:** CRL `nextUpdate` geçmişse broker fail-closed olmalı (revoke edilmemiş cert bile
reddedilir — bu DOĞRU, stale-CRL grace YOK).

## 4. Rotation (CA + leaf, periyodik + key-leak sonrası)

| Rotasyon | Tetik | Adım | Broker etkisi |
|---|---|---|---|
| **Leaf rotation** | 90g ömür / pilot bitiş | yeni CSR → device-CA imza → cihaz reinstall; eski leaf CRL'e | kid değişmez (device-CA aynı); eski leaf CRL ile reddedilir |
| **Device-CA rotation** | 1y / key-leak şüphesi | yeni device-CA üret → broker `client-ca-pem-path` overlap window (eski+yeni trust) → tüm leaf reissue → eski device-CA retire | overlap window'da iki CA trusted; sonra eski kaldırılır |
| **Permit-signing key rotation** | key-leak / periyodik | broker `kid` bump (RemoteBridgePermitSigner) → eski kid'li permit `anExpiredOrWrongKidPermitIsRejected` ile reddedilir | agent eski-kid permit reddeder |

**Overlap window kuralı:** device-CA rotation'da **fail-open YASAK** — overlap yalnız trust
genişletir (iki CA kabul), asla daraltmaz; tüm leaf reissue tamamlanana kadar eski CA retire edilmez.

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
