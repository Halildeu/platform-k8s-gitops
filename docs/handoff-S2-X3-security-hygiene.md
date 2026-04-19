# HAND-OFF: S2-X3 Security Hygiene — IP Sanitize + Kullanıcı-facing Gizlilik

> **Source:** K8s-6 S2 scope (2026-04-19, kullanıcı direktifi)
> **Target:** platform-ssot dev repo + ops docs audit
> **Priority:** P1 (preventive — mevcut durum tarama sonucu temiz ama kalıcı kural)
> **Kullanıcı direktifi:** "ai.acik.com testai.acik.com adresinde sayfada gezerken, login olurken IP'ler görünmemeli"

---

## 1. Mevcut Durum — Temiz ✅

K8s-6 güvenlik hijyen taraması sonucu:

| Kontrol | Sonuç |
|---|---|
| Response `Server:` header version | Gizli (`server_tokens off`) ✅ |
| Response `X-Real-IP` / `X-Forwarded-For` | Yok (sadece backend request header) ✅ |
| ai.acik.com / body IP regex | 0 match ✅ |
| /api/users, /auth/actuator/health 401 body | IP yok (`{"error":"unauthorized","message":"JWT token zorunludur."}`) ✅ |
| Actuator env/configprops endpoint | Kapalı (`MANAGEMENT_ENDPOINTS_WEB_EXPOSURE_INCLUDE: "health,info,prometheus"` + `show-details: never`) ✅ |

## 2. Kalıcı Kural (PLAN.md HARD RULE eklenecek)

### HARD RULE — Kullanıcı-facing Gizlilik

> **Hiçbir HTTP response (header veya body) dahili IP, hostname, cluster internal resource identifier içermez. Kullanıcı browser'ında ve login akışında yalnız public domain + user-facing error mesajı görünür. Actuator env/configprops/loggers/beans gibi operational endpoint'ler dış erişime kapalı; yalnız management port 8081 intra-cluster expose.**

Konsekvans:
- `X-Real-IP`, `X-Forwarded-For` request-only (proxy_hide_header ile response'ta sızmaz — zaten nginx default davranışı)
- Spring Boot `whitelabel error page` disabled (prod profile) — 500 response custom error handler
- Actuator exposure include **whitelist:** `health, info, prometheus, metrics` (env, configprops, loggers, beans, httptrace YASAK)
- Frontend build: `console.log` silinir, API_URL hardcoded değil (env-driven hostname)
- OIDC `issuer-uri`: `https://testai.acik.com/auth/realms/serban` (domain), IP değil

## 3. Preventive Audit Gerek (dev repo + docs)

### 3.1 Platform-ssot (dev repo) tarafı

- [ ] **Spring Boot GlobalExceptionHandler** — 500 response body IP/hostname/stack trace sızdırmıyor (prod profile'da detailed error off)
- [ ] **application-k8s.yml** tüm servisler — `management.endpoints.web.exposure.include` whitelist (env, configprops YASAK)
- [ ] **Actuator info endpoint** — build info, git commit OK; **IP/hostname yok**
- [ ] **Frontend webpack prod config** — `console.log` removal, API base URL env-driven
- [ ] **Keycloak realm** issuer-uri domain bazlı (staging-sw IP vs testai.acik.com — domain tercih)

### 3.2 Docs tarafı (platform-k8s-gitops)

- [ ] PLAN.md D karar tablosu — operasyonel IP referansları (D19 `10.9.10.53`, D20 ports) **internal doc, OK** ama paylaşılırsa sanitize
- [ ] session-handoff-*.md geçmiş — tarihsel kayıt, sanitize **gereksiz** (oluşan drift'i olduğu gibi belgele)
- [ ] Yeni yazılan docs (handoff-*.md) — **IP yerine semantic ad** (staging-sw intranet, kurumsal dış proxy, docker bridge)

**S1 hand-off'larında zaten uygulandı:** smoke-client handoff'ta `10.9.10.53` → `intranet host`.

## 4. Kabul Kriteri (preventive)

- [ ] Platform-ssot PR: Spring Boot prod profile whitelabel-error disabled
- [ ] Actuator exposure whitelist per-service audit
- [ ] Frontend prod build: console.log count 0
- [ ] PLAN.md HARD RULES'a yukarıdaki kural eklenmiş
- [ ] Gelecek handoff docs'ta IP yerine semantic ad kullanımı commit kuralı

## 5. Codex İstişare

Küçük scope doküman + preventive tarama. Plan istişaresi **opsiyonel** — kural zaten mevcut iyi-uygulama.

## 6. Prompt (platform-ssot'a)

```
TASK: Security Hygiene Audit (S2-X3)
From: K8s-6 kullanıcı direktifi 2026-04-19

Detay: platform-k8s-gitops/docs/handoff-S2-X3-security-hygiene.md

Özet: Dış response'larda IP/hostname/internal identifier sızmamalı. Preventive
audit + HARD RULE kalıcılık. Mevcut tarama temiz, kalıcılık için:
- Spring Boot prod profile whitelabel error disabled
- Actuator exposure whitelist (env/configprops YASAK)
- Frontend prod build console.log removal
- Keycloak issuer-uri domain bazlı

Kabul: Tüm servislerde include whitelist audit + 1 build test prod error page.
```
