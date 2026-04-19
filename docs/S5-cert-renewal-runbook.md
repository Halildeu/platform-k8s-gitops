# S5 Cert Renewal Runbook — Sectigo Wildcard `*.acik.com`

> **Source:** K8s-6 S5 day-2 ops (Codex iter-7 tespit)
> **Kapsam:** ai.acik.com + testai.acik.com wildcard cert yenileme
> **Cert:** Sectigo wildcard `*.acik.com` (staging-sw + staging-sw-2 host nginx mount)
> **Frekans:** Yıllık (Sectigo 365 gün validity)

---

## 1. Renewal Takvim

| Kilometre | Gün öncesi expire |
|---|---|
| Uyarı e-posta (Sectigo otomatik) | T-90, T-60, T-30, T-7 |
| CSR + renewal talep (ops/sysadmin) | T-30 |
| Yeni cert obtain | T-14 |
| Host mount + nginx test | T-7 |
| Apply (renewal deploy) | T-3 |
| Doğrulama | T-0 ve T+1 |

**Monitoring alert** (opsiyonel ops):
```promql
# Blackbox probe ssl expire days (prod cluster prod edge + test edge)
probe_ssl_earliest_cert_expiry{job=~"blackbox-(testai|prod)-health"} - time()
# < 30 gün = WARN, < 7 gün = CRITICAL
```

---

## 2. CSR + Renewal (T-30)

```bash
# Host staging-sw veya staging-sw-2'de
openssl genrsa -out /tmp/acik-com-new.key 4096
openssl req -new -key /tmp/acik-com-new.key \
  -out /tmp/acik-com-new.csr \
  -subj "/C=TR/ST=Istanbul/L=Istanbul/O=<Org>/CN=*.acik.com" \
  -addext "subjectAltName=DNS:*.acik.com,DNS:acik.com"

# CSR'yi Sectigo portal'a yükle (sysadmin panel)
cat /tmp/acik-com-new.csr
```

Sectigo portal renewal akışı: CSR upload → domain validation (DNS TXT veya e-mail) → cert issued (ZIP: cert + intermediate chain).

---

## 3. Cert Dosyaları (T-14)

Sectigo ZIP'ten gelen dosyalar:

```
wildcard_acik_com.crt      # Server cert
SectigoRSADomainValidationSecureServerCA.crt   # Intermediate
USERTrustRSAAddTrustCA.crt  # Intermediate
AAACertificateServices.crt  # Root (opsiyonel, mount gerekmez)
```

Full chain birleştir:

```bash
cat wildcard_acik_com.crt \
    SectigoRSADomainValidationSecureServerCA.crt \
    USERTrustRSAAddTrustCA.crt \
    > /tmp/acik-com-fullchain.crt

# Private key yanında olsun
cp /tmp/acik-com-new.key /tmp/acik-com.key
```

---

## 4. Host nginx Mount (T-7)

### 4.1 Staging-sw (testai.acik.com)

```bash
# Eski cert yedek
sudo cp /home/halil/platform/web/nginx/ssl/acik.com.crt \
  /home/halil/platform/web/nginx/ssl/acik.com.crt.bak-$(date +%Y%m%d)
sudo cp /home/halil/platform/web/nginx/ssl/acik.com.key \
  /home/halil/platform/web/nginx/ssl/acik.com.key.bak-$(date +%Y%m%d)

# Yeni cert mount
sudo cp /tmp/acik-com-fullchain.crt /home/halil/platform/web/nginx/ssl/acik.com.crt
sudo cp /tmp/acik-com.key /home/halil/platform/web/nginx/ssl/acik.com.key
sudo chmod 600 /home/halil/platform/web/nginx/ssl/acik.com.key

# Nginx test
docker exec platform-web-nginx nginx -t
# Beklenen: "syntax is ok" + "test is successful"
```

### 4.2 Staging-sw-2 (D32 sonrası ai.acik.com)

Aynı pattern, `host-compose/proxy/tls/` mount konumuna göre yol değişir:

```bash
sudo cp /tmp/acik-com-fullchain.crt /home/halil/platform-k8s-gitops/host-compose/proxy/tls/fullchain.crt
sudo cp /tmp/acik-com.key /home/halil/platform-k8s-gitops/host-compose/proxy/tls/privkey.key

docker exec host-nginx-proxy nginx -t
```

### 4.3 K8s Ingress TLS Secret (opsiyonel — cluster TLS termination kullanılıyorsa)

```bash
# Test cluster
kubectl --context k3d-test -n platform-test create secret tls wildcard-acik-com-tls \
  --cert=/tmp/acik-com-fullchain.crt \
  --key=/tmp/acik-com.key \
  --dry-run=client -o yaml | kubectl --context k3d-test -n platform-test apply -f -

# Prod cluster
kubectl --context k3d-prod -n platform-prod create secret tls wildcard-acik-com-tls \
  --cert=/tmp/acik-com-fullchain.crt \
  --key=/tmp/acik-com.key \
  --dry-run=client -o yaml | kubectl --context k3d-prod -n platform-prod apply -f -
```

---

## 5. Apply (T-3) + Doğrulama (T-0)

### 5.1 Nginx reload (zero downtime)

```bash
# staging-sw
docker exec platform-web-nginx nginx -s reload

# staging-sw-2 (D32 sonrası)
docker exec host-nginx-proxy nginx -s reload
```

### 5.2 Edge doğrulama

```bash
# Expire date
echo | openssl s_client -servername testai.acik.com -connect testai.acik.com:443 2>/dev/null \
  | openssl x509 -noout -dates
# notBefore = renewal tarih, notAfter = +365 gün

# Certificate chain doğrulama
echo | openssl s_client -servername testai.acik.com -connect testai.acik.com:443 -showcerts 2>/dev/null \
  | grep -E "(subject|issuer)"
# Beklenen: subject = *.acik.com, issuer = Sectigo

# HTTPS smoke
curl -vk https://testai.acik.com/testai-healthz 2>&1 | grep -E "^(< |SSL)"
curl -vk https://ai.acik.com/auth/actuator/health 2>&1 | grep -E "^(< |SSL)"
```

### 5.3 Prometheus probe güncellemesi

```promql
# Probe başarılı?
probe_success{job=~"blackbox-(testai|prod)-(deny|health)"} == 1

# Yeni cert expire günü
(probe_ssl_earliest_cert_expiry{job=~"blackbox-(testai|prod)-health"} - time()) / 86400
# Beklenen: ~365 (renewal sonrası)
```

---

## 6. Rollback (cert hatası sonrası)

```bash
# Eski cert'i geri koy
sudo cp /home/halil/platform/web/nginx/ssl/acik.com.crt.bak-<DATE> \
  /home/halil/platform/web/nginx/ssl/acik.com.crt
sudo cp /home/halil/platform/web/nginx/ssl/acik.com.key.bak-<DATE> \
  /home/halil/platform/web/nginx/ssl/acik.com.key

docker exec platform-web-nginx nginx -s reload
```

Eski cert hâlâ geçerliyse (T-N günlük window), servis etkilenmez.

---

## 7. Referanslar

- Sectigo portal: <admin > account (ops)
- `/home/halil/platform/web/nginx/ssl/` — staging-sw mount
- `host-compose/proxy/tls/` — staging-sw-2 mount (D32 sonrası)
- `docs/S2-X2-nginx-edge-migration.md` — edge topoloji (D32 öncesi/sonrası)
- `kustomize/base/monitoring/blackbox-exporter.yaml` — probe SSL expire metric
