# S2-X2: Host Nginx Edge Migration (D18 Tam Aktivasyon) + Drift Root Cause

> **Source:** K8s-6 Seviye 2 (2026-04-19)
> **Codex Tur 3 uzlaşı:** "D18 resmi `host-compose/proxy/` tam aktivasyon S2'de" (S2-X2)
> **Drift kaynağı:** Mevcut `platform-web-nginx` (eski compose) default.conf'u kalıcı değil — periyodik override
> **Çözüm kategorisi:** Hedef mimari D18 proxy container aktivasyon

---

## 1. Mevcut Durum (2026-04-19)

**Hazır ama idle:** `host-compose/proxy/` dizini (15 Nisan yazıldı, 4 gün beklemede)

```
host-compose/proxy/
├── conf/nginx.conf       # D18 SNI proxy — ai.acik.com + testai.acik.com
├── docker-compose.yml    # Yeni proxy container tanımı
└── tls/                  # Sectigo cert mount
```

**`conf/nginx.conf` özelliği:**
- SSL termination (Sectigo wildcard)
- SNI routing: `ai.acik.com → 127.0.0.1:30080` (k3d-prod), `testai.acik.com → 127.0.0.1:31080` (k3d-test)
- `server_tokens off`, gzip, keepalive, max_fails
- upstream `prod_k3d_ingress` + `test_k3d_ingress`

**Mevcut çalışan:** `platform-web-nginx` container (eski `backend/docker-compose.yml` compose) — default.conf host mount ile, testai server_block dün append ettim (drift #1 fix geçici).

## 2. Drift Root Cause Hipotez

- Gece 00:54 default.conf override → eski `platform-web-nginx` container'ına **bir deploy orchestration** yeniden default.conf yazıyor. Kaynak bilinmiyor (audit geniş, doğrudan process log yok).
- `install-on-staging-sw.sh` testai block idempotent append (grep-gate) — bu kaynak değil
- `backup.sh` (cron 03:00) nginx'e dokunmaz
- Olası: başka bir CI/CD pipeline veya manuel script default.conf'u "reset to known state" yapıyor

**Kalıcı çözüm:** Mevcut `platform-web-nginx`'ten çıkılıp D18 proxy container'ına geçilir. O zaman override süreci farklı bir dosyayı (D18 `nginx.conf`) etkilemez.

## 3. Migration Plan (apply: S2 session'da)

### 3.1 Pre-migration Check

- [ ] D18 `nginx.conf` içeriği testai + ai routes tamam
- [ ] Sectigo cert `/home/halil/platform/tls/` mount noktası D18 compose'da tanımlı
- [ ] k3d-prod :30080 + k3d-test :9080 (veya :31080, config'de ne yazıyor) accessible
- [ ] Compose ai.acik.com backend health OK (downtime öncesi baseline)

### 3.2 Migration Adımları

**ADIM 1 — Bacup + prova (T-10min):**
```bash
# Mevcut platform-web-nginx config backup
cp /home/halil/platform/web/nginx/default.conf /home/halil/platform/web/nginx/default.conf.bak-d18-migration

# D18 compose validate (dry-run)
docker compose -f /home/halil/platform-k8s-gitops/host-compose/proxy/docker-compose.yml config
```

**ADIM 2 — Atomic Swap (T-0, <60s downtime):**
```bash
# Eski platform-web-nginx stop
docker stop platform-web-nginx
# NOT: 80/443 portları serbest bırakılır

# D18 proxy up
cd /home/halil/platform-k8s-gitops/host-compose/proxy/
docker compose up -d

# nginx config reload (container başlangıcında zaten yüklenir)
docker ps | grep proxy  # yeni container running
```

**ADIM 3 — Smoke (T+5min):**
```bash
# Authoritative edge test (staging-sw localhost)
curl -sk -H "Host: ai.acik.com" https://127.0.0.1/ → 200 (compose backend)
curl -sk -H "Host: ai.acik.com" https://127.0.0.1/api/users → 401 JSON
curl -sk -H "Host: testai.acik.com" https://127.0.0.1/testai-healthz → 200
curl -sk -H "Host: testai.acik.com" https://127.0.0.1/variants → 401 JSON (K8s gateway)
```

**ADIM 4 — Rollback (gerekirse, <2min):**
```bash
# D18 proxy stop
cd /home/halil/platform-k8s-gitops/host-compose/proxy/
docker compose down

# Eski platform-web-nginx start (compose backend/docker-compose.yml)
cd /home/halil/platform/repo/backend
docker compose up -d platform-web-nginx
```

### 3.3 Post-migration Kalıcılık

D18 container aktif olduğunda:
- `host-compose/proxy/conf/nginx.conf` source-controlled (git tracked)
- Gece 00:54 override (eski `platform-web-nginx` config'e hedefli) **D18'i etkilemez** — farklı dosya
- Drift kategori çözümlendi: mevcut drift süreci artık idle container'a yazıyor (eski)

### 3.4 İleri İyileştirme

- Eski `platform-web-nginx` container tamamen decommission (compose tanımdan çıkar)
- LE HTTP-01 otomasyon (Faz 12+, opsiyonel Codex Tur 2)
- Prometheus nginx exporter D18 proxy scrape

## 4. Apply Zamanı

**Bugün apply YAPMA.** Gerekçeler:
- Canlı `ai.acik.com` edge swap → 30-60s downtime
- Rollback hazır olsa da atomic swap test cluster'da prova edilmemiş
- **Önerilen:** S2 session'da **staging pencere** (hafta sonu veya bakım saati)

**Bugünkü geçici fix (2026-04-19, Seviye 1):** Eski `platform-web-nginx` default.conf'a testai block append (commit `S0-D7` pattern + bugün restore). Drift gece 00:54 tekrar silerse install-on-staging-sw.sh idempotent restore'lar (grep-gate).

## 5. Kabul Kriteri (apply PASS)

- [ ] D18 proxy container Running
- [ ] Eski platform-web-nginx stopped (veya decommissioned)
- [ ] ai.acik.com + testai.acik.com smoke PASS (authoritative edge)
- [ ] nginx config source-controlled (host dosyası değil, git repo)
- [ ] Gece 00:54 override artık testai block'u etkilemiyor (48h izleme)

## 6. Root Cause Araştırma (ayrı paralel iş)

Override kaynağını bulmak için S2-X2.1:
- `/var/log/nginx/*` nginx stats
- systemd journal tam audit
- PostgreSQL backup script log
- Cron jobs + systemd timers full audit
- Jenkins/CI pipeline webhook receiver
- Manual deploy history (git log + /root/.bash_history eğer sudo erişim)

Root cause bulunursa **drift kaynağını durdurmak daha kalıcı** — ama D18 migration zaten drift kategori çözdüğü için acil değil.

## 7. Codex İstişare

- **Plan istişaresi:** Apply öncesi Codex ping-pong (cert mount + compose swap risk + rollback prova)
- **Tamamlanma review:** Migration sonrası smoke + 48h izleme raporu

## 8. Prompt (S2 apply session)

```
TASK: S2-X2 Host Nginx Edge Migration (D18 aktivasyon)
From: K8s-6 Seviye 2

Detay: platform-k8s-gitops/docs/S2-X2-nginx-edge-migration.md

Hazırlık: docker compose config (dry-run) + cert mount kontrol + smoke baseline.
Apply: eski platform-web-nginx stop → D18 proxy compose up → smoke PASS.
Rollback: D18 down → eski proxy up (<2min).

Zaman: Staging pencere (hafta sonu / bakım saati), canlı edge 30-60s
downtime kabul edilir.
Codex apply öncesi ping-pong + sonrası review zorunlu.
```
