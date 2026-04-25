# RB-server-hardening-checklist – Production Server Security Hardening

ID: RB-server-hardening-checklist
Service: infrastructure
Status: Active
Owner: @team/platform

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

- Production sunucusunun guvenlik yapilandirmasini tekrarlanabilir sekilde belgelemek.
- Yeni kurulumda veya yeniden deploy'da ayni guvenlik seviyesini garantilemek.
- Docker UFW bypass sorununu 127.0.0.1 binding ile cozmek.

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

- UFW firewall yapılandırması (yalnizca 22/80/443 acik)
- Docker port binding (127.0.0.1 zorunlu)
- Keycloak ve Vault compose guvenlik ayarlari
- SSH sertlestirme (key-only oneri, fail2ban zorunlu)
- SSL sertifika kurulumu ve yonetimi
- Nginx guvenlik header'lari ve admin konsol engelleme
- Vault unseal proseduru
- OS guncelleme ve kernel sertlestirme
- SSH 5544 proxy kaldirilmasi (guvenlik acigi)

-------------------------------------------------------------------------------
3. BAŞLATMA / DURDURMA
-------------------------------------------------------------------------------

### 3.1 UFW Firewall

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp   comment 'SSH'
sudo ufw allow 80/tcp   comment 'HTTP redirect to HTTPS'
sudo ufw allow 443/tcp  comment 'HTTPS'
sudo ufw enable
sudo ufw reload
```

NOT: UFW kurallari Docker portlarina uygulanmaz. Docker portlarini kisitlamak icin docker-compose.prod.yml'de `127.0.0.1:` prefix kullanilir.

### 3.2 Docker Port Binding

docker-compose.prod.yml icindeki TUM port binding'ler `127.0.0.1:` ile baslamalidir:

```yaml
ports:
  - "127.0.0.1:8082:8080"   # API Gateway
  - "127.0.0.1:5432:5432"   # PostgreSQL
```

`0.0.0.0` ile baslayan port binding YASAKTIR.

Keycloak compose (`/opt/app/docker-compose.yml`):
```yaml
ports:
  - '127.0.0.1:8080:8080'
```

Vault container (docker run ile):
```bash
docker run -d \
  --name platform-stage-vault \
  --restart unless-stopped \
  --cap-add IPC_LOCK \
  -p 127.0.0.1:8200:8200 \
  -p 127.0.0.1:8201:8201 \
  --network platform_microservice-network \
  -v /home/halil/platform/state/vault/data:/vault/file \
  -v /home/halil/platform/repo/backend/devops/vault:/vault/config:ro \
  hashicorp/vault:1.21.4 vault server -config=/vault/config/vault.hcl
```

DIKKAT: Vault `platform_microservice-network`'e baglanmalidir, aksi halde backend servisleri Vault hostname'ini cozemez.

### 3.3 SSH Sertlestirme

/etc/ssh/sshd_config:
```
PermitRootLogin no
MaxAuthTries 3
PubkeyAuthentication yes
PasswordAuthentication yes   # key yedegi olarak acik, fail2ban zorunlu
```

### 3.4 Fail2ban

```bash
sudo apt install -y fail2ban
sudo systemctl enable fail2ban
sudo systemctl start fail2ban
```

### 3.5 SSL Sertifika

Dosyalar:
- `/home/halil/platform/tls/ai.acik.com/fullchain.pem` (644)
- `/home/halil/platform/tls/ai.acik.com/privkey.pem` (600)

```bash
chmod 644 /home/halil/platform/tls/ai.acik.com/fullchain.pem
chmod 600 /home/halil/platform/tls/ai.acik.com/privkey.pem
```

Mevcut: `*.acik.com` (Sectigo, gecerlilik: 1 Ekim 2026)

### 3.6 Nginx Guvenlik

`run-frontend-nginx-container.sh` tarafindan uretilen config icinde:
- `server_tokens off;` — versiyon gizli
- `Strict-Transport-Security` — HSTS
- `X-Frame-Options: SAMEORIGIN` — clickjacking koruması
- `X-Content-Type-Options: nosniff` — MIME sniffing koruması
- `X-XSS-Protection: 1; mode=block` — XSS koruması
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy: camera=(), microphone=(), geolocation=()`
- `/admin/` → 403 (Keycloak admin konsolu engellenmis)
- SSL: TLSv1.2 + TLSv1.3 only

### 3.7 Vault Unseal

Vault her restart'ta sealed baslar. Unseal icin 3 key gerekir:

```bash
KEY1=$(cat /home/halil/platform/state/vault/vault-unseal-key-1)
KEY2=$(cat /home/halil/platform/state/vault/vault-unseal-key-2)
KEY3=$(cat /home/halil/platform/state/vault/vault-unseal-key-3)
curl -s -X POST http://127.0.0.1:8200/v1/sys/unseal -d "{\"key\": \"$KEY1\"}"
curl -s -X POST http://127.0.0.1:8200/v1/sys/unseal -d "{\"key\": \"$KEY2\"}"
curl -s -X POST http://127.0.0.1:8200/v1/sys/unseal -d "{\"key\": \"$KEY3\"}"
```

NOT: Vault unseal sonrasi backend servisleri restart gerekebilir.

### 3.8 SSH 5544 Proxy Kaldirma

`/home/halil/.local/bin/ssh_5544_proxy.py` guvenlik acigi olusturur:

```bash
kill $(pgrep -f ssh_5544_proxy)
crontab -l | grep -v ssh_5544_proxy | crontab -
```

### 3.9 OS Guncellemeleri

```bash
sudo apt update && sudo apt upgrade -y
```

### 3.10 Kernel Sertlestirme

/etc/sysctl.d/99-hardening.conf:
```
net.ipv4.conf.all.send_redirects = 0
net.ipv4.conf.default.send_redirects = 0
```

```bash
sudo sysctl -p /etc/sysctl.d/99-hardening.conf
```

-------------------------------------------------------------------------------
4. GÖZLEMLEME / LOG / METRİKLER
-------------------------------------------------------------------------------

- Dogrulama:
  - [ ] `docker ps --format '{{.Ports}}'` — hicbir satir `0.0.0.0` icermemeli
  - [ ] `curl http://<server-ip>:5432` — timeout/refused olmali (dis agdan)
  - [ ] `curl http://<server-ip>:8080` — timeout/refused olmali (dis agdan)
  - [ ] `curl -sI https://ai.acik.com | grep -i server` — versiyon gorunmemeli
  - [ ] `curl -sI https://ai.acik.com | grep Strict` — HSTS header mevcut
  - [ ] `curl -s https://ai.acik.com/admin/` — 403
  - [ ] `curl -s http://127.0.0.1:8200/v1/sys/health` — `sealed: false`
  - [ ] `systemctl is-active fail2ban` — `active`
  - [ ] `ss -tlnp | grep 5544` — bos olmali

- Network topoloji:
  ```
  Internet → 212.115.26.190 (DNS A kaydi)
           → Router/NAT (port forwarding 80/443)
           → 10.9.10.53 (host private IP)
           → Nginx :80/:443 (reverse proxy)
               ├─ /         → frontend (static)
               ├─ /api/*    → API Gateway :8082 (JWT zorunlu)
               ├─ /realms/* → Keycloak :8080
               ├─ /admin/*  → 403 BLOCKED
               └─ diger     → frontend SPA fallback

  Outbound NAT IP: 31.145.18.18
  Ic DNS: 10.9.10.10 (ai.acik.com → 10.9.10.53)
  Dis DNS: ai.acik.com → 212.115.26.190
  ```

-------------------------------------------------------------------------------
5. ARIZA DURUMLARI VE ADIMLAR
-------------------------------------------------------------------------------

- [ ] Arıza senaryosu 1 – Backend servisleri DOWN:
  - Given: Vault restart yapilmistir.
  - When: auth-service, user-service, permission-service, variant-service `503` doner.
  - Then: Vault sealed'dir; unseal proseduru uygulanir (bolum 3.7), ardindan servisler restart edilir.

- [ ] Arıza senaryosu 2 – Dis agdan backend portuna erisilebiliyor:
  - Given: docker-compose.prod.yml guncellenmistir.
  - When: `curl http://<server-ip>:5432` cevap doner.
  - Then: docker-compose.prod.yml'de ilgili port `127.0.0.1:` prefix'i kontrol edilir, container'lar yeniden olusturulur.

- [ ] Arıza senaryosu 3 – Keycloak admin konsolu disaridan erisilebiliyor:
  - Given: nginx config uretilmistir.
  - When: `curl https://ai.acik.com/admin/` 200 doner.
  - Then: nginx config'te `/admin/` block'u kontrol edilir, container restart edilir.

- [ ] Arıza senaryosu 4 – SSL sertifika suresi doluyor:
  - Given: Sectigo wildcard sertifika kullanilmaktadir.
  - When: `openssl s_client` ile `notAfter` 30 gun icinde.
  - Then: Yeni sertifika alinir, dosyalar guncellenir, nginx restart edilir.

-------------------------------------------------------------------------------
6. ÖZET
-------------------------------------------------------------------------------

- Production sunucu guvenlik zinciri:
  - [ ] UFW: yalnizca 22/80/443 ALLOW
  - [ ] Docker: tum portlar 127.0.0.1
  - [ ] SSH: root kapalı, fail2ban aktif
  - [ ] Nginx: guvenlik header'lari, admin block, versiyon gizli
  - [ ] Vault: unseal edilmis, microservice network'te
  - [ ] SSL: gecerli sertifika, key izni 600
  - [ ] SSH 5544 proxy: kaldirilmis
  - [ ] OS: guncellemeler uygulanmis

-------------------------------------------------------------------------------
7. LİNKLER (İSTEĞE BAĞLI)
-------------------------------------------------------------------------------

- `deploy/ubuntu/run-frontend-nginx-container.sh`
- `backend/docker-compose.prod.yml`
- `/opt/app/docker-compose.yml` (Keycloak)
- `docs/OPERATIONS/prod-public-edge-map.v1.json`
- `docs/04-operations/RUNBOOKS/RB-production-cutover-checklist.md`
- `docs/04-operations/RUNBOOKS/RB-ubuntu-web-nginx-deploy.md`
