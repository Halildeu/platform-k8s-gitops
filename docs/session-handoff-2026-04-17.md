# Session Handoff — 2026-04-17 (Drift Teşhis + Metodoloji Sertleşmesi)

> Bu session **implementation yapmadı**. Kullanıcı talebi: "sistemi anlayıp planımızı
> mevcut durumu güncelleyeceğiz yalnızca". Odak: handoff v2'nin "testai tam yeşil"
> iddiasını doğrulamak — ve başarısız olduğunda metodolojik kök sebebini sertleştirmek.
>
> Codex MCP ile 3-tur plan istişaresi yapıldı (thread `019d9612-f2b7-7400-b025-8524ac1a2876`,
> kural gereği [feedback_codex_review_after_tasks.md](../../../../.claude/projects/-Users-halilkocoglu-Documents-platform-k8s-gitops/memory/feedback_codex_review_after_tasks.md)).

---

## 🎯 Yönetici Özeti (tek cümle)

**v2 handoff'un "testai 9/9 Ready, 7/7 smoke 200" iddiası gerçek değildi** — host nginx
edge'inde `testai.acik.com` server block YOK, tüm testai istekleri SNI fallback ile
`ai.acik.com` compose frontend'e düşüyordu. testai cluster'ı aslında sağlam; ama kimse
oraya gerçekten bağlanmadı. Faz 4 stabilite kapısı **başlamadı** (giriş kriteri bile yok).

---

## 📋 Bu Session Komitleri

**(yok)** — saf araştırma + istişare. Kod/manifest dokunulmadı. Repo `36b6876` (v2 handoff commit) durumunda.

---

## 🔴 Drift Bulguları (5 × 5-alan formatı)

> Format Codex Tur-2 önerisi: `Bağlam / İddia / İspatlar / İspatlamaz / Bilinen boşluk`.
> Gelecek handoff'ların zorunlu şablonu.

### Drift #1 — Host nginx `testai.acik.com` server block eksik (P0)

**Bağlam:**
- Tarih: 2026-04-17
- Host: staging-sw
- Container: `platform-web-nginx` (nginx:1.27-alpine, compose stack)
- İlgili: v2 handoff §🎯, PLAN D18, 2026-04-15 handoff §3 (append hack uyarısı)

**İddia:** Host nginx SNI proxy testai.acik.com için yapılandırılmış DEĞİL.

**İspatlar:**
```bash
docker exec platform-web-nginx nginx -T | grep server_name
  server_name ai.acik.com;
  server_name ai.acik.com;
  # testai.acik.com YOK

curl -sI -H "Host: testai.acik.com" http://127.0.0.1:9080/auth
  HTTP/1.1 308 Permanent Redirect
  Location: https://testai.acik.com/auth   # ingress-nginx ssl-redirect

curl -s -H "Host: testai.acik.com" -H "X-Forwarded-Proto: https" \
  http://127.0.0.1:9080/auth
  → HTTP 401, CT=application/json
  → {"error":"unauthorized","message":"JWT token zorunludur."}

curl -sk https://testai.acik.com/auth
  → HTTP 200, CT=text/html
  → <MFE shell, window.__env__.VITE_GATEWAY_URL="https://ai.acik.com/api"...>
```
Hop sınıfı: `cluster-bypass` (bypass ile cluster çalışıyor) vs `real-host` (edge kırık).

**İspatlamaz:** testai cluster'ın iç business davranışını (sadece edge→ingress→gateway
401 zincirini ispatlar). auth business port 8088 mantığını hiç ispatlamaz.

**Bilinen boşluk:** testai block'u 2026-04-15 handoff §3'te `cat >> default.conf` ile
eklenmişti (append hack). P2 #3 "compose restart dayanıklılığı" uyarısı vardı.
Muhtemelen compose restart'ında düştü. `/testai-healthz` bile 200 HTML dönüyordu
(catch-all) → status-code-only smoke bunu yakalayamadı.

**Çözüm yönü (Codex Tur-3):** `host-compose/proxy/` altındaki D18 edge config
aktivasyonu + geçiş: `ai.acik.com` upstream mevcut compose'da kalsın, `testai.acik.com`
upstream test k3d'ye. Cutover günü ai upstream değişir. Mevcut `platform-web-nginx`
append hack'i kalıcı YER değil, acil hotfix.

---

### Drift #2 — Promtail CrashLoopBackOff root cause: host inotify limit (P1)

**Bağlam:**
- Cluster: k3d-prod (staging-sw)
- Pod: `promtail-m7ntj`, image `docker.io/grafana/promtail:3.0.0`
- 16m uptime, 8 restart

**İddia:** Host kernel `fs.inotify.max_user_instances=128` (default) limit aşılıyor.
2 k3d cluster aynı host'ta → kubelet/containerd/promtail instance quota'yı dolduruyor.

**İspatlar:**
```bash
kubectl --context k3d-prod -n monitoring logs -l app.kubernetes.io/name=promtail --tail=40
  level=error ... msg="error creating promtail"
  error="failed to make file target manager: too many open files"

ssh staging-sw sysctl fs.inotify.max_user_instances fs.inotify.max_user_watches
  fs.inotify.max_user_instances = 128
  fs.inotify.max_user_watches   = 186563
```

**İspatlamaz:** Log satırı teorik olarak `RLIMIT_NOFILE` ile de ilişkili olabilir.
Sysctl fix uygulandıktan sonra hâlâ crash ediyorsa file descriptor limiti ayrı
kontrol edilmeli (Codex Tur-2 uyarısı).

**Bilinen boşluk:** v2 handoff "sebep bilinmiyor" dedi. Teşhis edildi ama fix
uygulanmadı (kullanıcı: implementation yok).

**Çözüm yönü (Codex Tur-2):** `/etc/sysctl.d/*.conf` ile kalıcı
`fs.inotify.max_user_instances=512`. `max_user_watches` zaten yüksek — dokunma.
sysadmin bilgilendirilmeli (host-level değişiklik). `256` yetersiz olabilir, `1024`
gereksiz geniş; `512` denge.

---

### Drift #3 — "7/7 smoke 200" iddiası yanıltıcı — metodolojik (P1 metodolojik)

**Bağlam:** v2 handoff commit `36b6876`, §🎯 Şu Anki Durum.

**İddia:** v2 handoff "testai.acik.com 7/7 backend health 200" diyor. Gerçekte hiçbir
istek backend'e varmıyordu.

**İspatlar:** Drift #1 ile aynı — `curl -sk https://testai.acik.com/...` tüm
path'lerde `200 + text/html + <MFE shell HTML>` dönüyor. Status kodu "yeşil"
gözüküyor ama body compose frontend'i. `content-type` kontrolü olmayan smoke buradan
geçiyordu.

**İspatlamaz:** v1 handoff "401 JWT token zorunludur" demişti (2026-04-15 canlı
kanıt). O zaman gerçekten cluster'a ulaşıyordu. Yarılma tam olarak ne zaman oluştu
(hangi compose restart'ında testai block düştü) — bu session'da tespit edilmedi.

**Bilinen boşluk:** Smoke scripts (`bootstrap/install-on-staging-sw.sh:298`,
`bootstrap/reconnect-compose-to-test-net.sh:96`) sadece status kodu görüyor.
Content-type ve body sentinel doğrulama yok. Negatif kontrol (bilinmeyen host default
server'a düşüyor mu) yok.

**Çözüm yönü (Codex 3-tur mutabık):** Smoke tuple'ı `(status, content-type,
body_sentinel)`. Negatif kontrol: bilinmeyen host → 200 HTML OLMAZ. Full body snapshot
overkill; sentinel yeter.

---

### Drift #4 — auth-service `:8088/actuator/health` INTERNAL_ERROR 500 (P2)

**Bağlam:** Intra-cluster curl (gateway pod'undan auth-service svc'ye).

**İddia:** auth-service business port 8088'de `/actuator/health` istendiğinde
`INTERNAL_ERROR 500` JSON dönüyor.

**İspatlar:**
```bash
kubectl --context k3d-test -n platform-test exec deploy/api-gateway -- \
  curl -s http://auth-service.platform-test.svc.cluster.local:8088/actuator/health
  {"error":"INTERNAL_ERROR","message":"Beklenmeyen bir hata oluştu.",...}

# Management port:
kubectl ... curl :8081/actuator/health → 200 UP

# Via gateway (doğru smoke kriteri):
kubectl ... curl http://api-gateway:8080/auth/actuator/health → 401 JWT
```

**İspatlamaz:** Bu "auth-service bozuk" demek değil.
Actuator sadece `MANAGEMENT_SERVER_PORT=8081`'de expose (D14 doğru). 8088'de path
open değil → `NoResourceFoundException` → `GlobalExceptionHandler.handleGeneric`
500'e wrap ediyor. 2026-04-16 v1 handoff #5 (PR #410) tam bu bug'ı 404'e çevirecekti —
image'a merge sonrası ulaşmadı görünüyor. Ama mimari ZATEN doğru:
- Pod readiness probe 8081 → 200 UP ✅
- Gateway route stripPrefix=1 → auth:8088 ama `/actuator/health` direkt dış smoke
  kriteri olmamalıydı

**Bilinen boşluk:** PR #410 merge/image rebuild zinciri doğrulanmadı. Ana repo
`autonomous-orchestrator` GHCR `main-stable` tag'inde PR #410 commit'inin var olup
olmadığı kontrol edilmedi.

**Çözüm yönü (Codex Tur-1):** Dış smoke'tan `/actuator/health` path'i çıkar. Dış
sağlık göstergesi: JWT E2E (business endpoint 2xx) veya edge `/healthz` sentinel.
Readiness check intra-cluster 8081'den.

---

### Drift #5 — v1 ↔ v2 handoff kanıt sınıfı yarılması (P1 metodolojik)

**Bağlam:**
- v1: [session-handoff-2026-04-16.md](./session-handoff-2026-04-16.md) (#5, #6, #7, #8
  follow-up'ları) "auth intentionally scaled to 0, 401 gateway fallback"
- v2: [session-handoff-2026-04-16-v2.md](./session-handoff-2026-04-16-v2.md) aynı
  günün ikinci session'ı: "7/7 backend 200 health"

**İddia:** v2 kanıt sınıfı yükseltmesi yaptı (v1 "tam valide değil" diyor, v2 "tam
yeşil" diyor) ama ikisi arasında yeni, v1'in şüphelerini kapatan bir kanıt mevcut
değil. v2, aynı günkü v1'in kendi uyarısını es geçti.

**İspatlar:**
- v1 L12: "Do NOT treat testai auth path as fully validated until #8 is fixed and
  auth replicas > 0"
- v2 L14-22: "9/9 pod Ready, 7/7 backend health 200" (auth replicas konusu net
  değil, "RSA key auto-generate" diyor ama fix'in tam testi yok)
- Drift #1 zaten gösteriyor: smoke aslında compose'a düşüyordu.

**İspatlamaz:** v2'nin kötü niyetli olduğunu; muhtemelen aynı smoke tuzağına
düşüldü (status=200=yeşil).

**Bilinen boşluk:** Handoff şablonu şu anda kanıt sınıfı zorunlu tutmuyor. "İspatlar"
alanı olmadan iddialar eşit ağırlıkta okunuyor.

**Çözüm yönü (Codex Tur-2):** Handoff şablonu 5 zorunlu alan:
`Bağlam / İddia / İspatlar / İspatlamaz / Bilinen boşluk`. Bu dosya ilk örnek.

---

## 🔑 Codex 3-Tur İstişare Mutabakatı

**Thread:** `019d9612-f2b7-7400-b025-8524ac1a2876` (plan-only, 3 tur).
**Sandbox:** read-only, approval-policy: never.

### Tur-1 çıktısı — drift teşhisi kritiği
- "Repo drift değil, live-state drift" hipotezi → Drift #1 ile kısmen doğrulandı (ingress
  sağlam, asıl sorun edge)
- `/actuator/health` dış smoke kriteri olmamalı (Drift #4 yorumu)
- Smoke status-code-only metodolojik zayıflık (Drift #3 yorumu)

### Tur-2 çıktısı — metodoloji sertleşmesi
**HARD RULE eklenecek:** "Yeşil/hazır/stabil iddiası, **authoritative entrypoint** ve
**hop sınıfı** açık değilse geçersizdir; cluster-bypass kanıtı gerçek kullanıcı yolunu
tek başına ispatlamaz."

**Faz 4 stabilite kapısı — 4 eksen (giriş kriteri):**
1. Host-edge reality (nginx -T + SNI fallback negatif)
2. Real-host smoke body-semantik (CT + sentinel)
3. Cluster-direct readiness (management port 8081)
4. JWT E2E success

**Handoff şablonu** — bu dosyadaki 5-alan.

**Promtail fix** — `fs.inotify.max_user_instances=512`, sysctl.d kalıcı.

**Host nginx** — D18 edge aktivasyonu + geçiş config (compose upstream'i bozma).

### Tur-3 çıktısı — prod cutover smoke runbook iskeleti
Final sıralama (Codex'in 12 düzeltmesi uygulanarak):

```
Adım -1  Preflight: DNS, TLS (no -k), artifact digest immutability (live imageID vs beklenen sha256)
Adım  0  Git/live reconcile (kubectl diff -k + argocd diff --exit-code; secret dump YOK)
Adım  1  Host-edge reality (nginx -T hedefli + SNI fallback negatif kontrol)
Adım  2  Deploy availability → cluster-direct readiness (tek kullanımlık smoke pod)
Adım  3  Intra-cluster gateway routing (svc DNS, localhost değil)
Adım  4  Real-host smoke: edge sentinel + bilinen-prefix 404 JSON + host-spesifik env sentinel
Adım  5  JWT E2E (smoke-client confidential, admin-cli değil)
Adım  6  Rolling restart continuity (0 unexpected 5xx/502/504, per deployment, xargs -P4)
Adım  7  NetworkPolicy reality (plain-TCP deny hedefi; kubernetes.default 403 "reached" olur)
Adım  8  Observability live (prod zorunlu port-forward; test N/A; synthetic-after log)
Gate yanı: Rollback pointer hazır mı? (smoke değil, cutover decision parçası)
```

**Chaos/RBAC/geniş NP kombinasyonu** ayrı `stability-abuse` runbook'una (MVP değil).

### Daha önceki thread'ler (bu session dışı, referans)
- `019d93fe-4745-7c10-a572-b865a44d30bb` — v2 session prod platform plan (Tur-5)
- `019d92c6-eff5-7351-ad56-d299269a40b1` — v1 session follow-up review (4 tur)

---

## 🚀 Sonraki Session Yapılacaklar (öncelik sırasıyla)

### 🔴 Zorunlu (önceki session'dan devir)

1. **`docs/prod-cutover-smoke-runbook.md` yaz** — Codex 3-tur iskeletini somut komutlara
   döknüş runbook. Adım -1'den 8'e `(komut, beklenen status/CT/body, İspatlar, İspatlamaz)`
   tuple formatında. testai Faz 4 girişi + prod cutover gate aynı runbook.
2. **PLAN.md güncellemesi**:
   - Bölüm 1 HARD RULES'a "authoritative entrypoint" kuralı
   - Faz 4 altına "Giriş / Gözlem / Çıkış" kriter tablosu
   - D28 karar numarası: "Handoff şablonu 5-alan zorunlu"
3. **Host nginx testai hotfix** (edge aktivasyonu şu aşamada büyük iş):
   - Geçici: `platform-web-nginx` default.conf'a testai block append + compose restart
     dayanıklılık (config mount pattern)
   - Kalıcı (ayrı session): `host-compose/proxy/` aktivasyonu + upstream geçiş config
4. **Promtail sysctl fix**: staging-sw'de
   `echo 'fs.inotify.max_user_instances=512' > /etc/sysctl.d/99-k8s.conf && sysctl -p`
   (sysadmin haberdar olsun).

### 🟡 Devam eden (v2'den gelen kalan iş)
5. ArgoCD install prod: `bash bootstrap/install-argocd.sh prod` (30dk)
6. ArgoCD Application CR'ları (app-of-apps) (45dk)
7. Prod overlay (platform-prod ns, prod host bridge) (1s)
8. Prod backend deploy (main-stable image import) (1s)
9. JWT E2E smoke — `smoke-client` Keycloak confidential client oluştur (Codex Tur-3:
   admin-cli kalıcı değil)
10. testai stabilite gözlemi — ancak Drift #1 fix + runbook passed sonrası başlar

### 🟢 Ertelenebilir
11. Ana repo PR #410 merge/image rebuild doğrulama (Drift #4)
12. Smoke script body-semantik sertleşmesi (Drift #3 fix)
13. Host nginx D18 edge tam aktivasyonu (cutover'a kadar)

---

## 📊 Gerçek Durum Tablosu (handoff v2'nin düzeltilmiş hali)

| Bileşen | v2 iddiası | **Gerçek (bu session)** |
|---|---|---|
| testai edge (user path) | "canlı 7/7 200" | **KIRIK** — compose frontend'e fallback |
| testai cluster (intra) | "Ready" | ✅ sağlam (bypass kanıtı: 401 JWT JSON) |
| testai NetworkPolicy | "8 policy aktif" | Manifest var, enforce reality test YAPILMADI |
| testai graceful rollout | "minReadySeconds/terminationGrace OK" | Manifest var, rolling restart 5xx testi YAPILMADI |
| k3d-prod cluster | "kurulu" | ✅ Running |
| k3d-prod monitoring | "9/10, Promtail crash" | ✅ 9/10 Running, Promtail **root cause bulundu** |
| k3d-prod ArgoCD | "yok" | ❌ yok (aynı) |
| k3d-prod backend | "deploy edilmedi" | ❌ yok (aynı) |
| ai.acik.com (compose) | "frontend 200, API 503" | frontend 200, **API 401** (iyileşti, diğer session Eureka fix merge'lenmiş) |
| Git | `36b6876` | `36b6876` (bu session komit yok) |

---

## 🛡️ Güvenlik / İzolasyon Durumu

- `ai.acik.com` (compose) dokunulmadı, 200 ✅ (gerçekten, test edildi)
- `testai.acik.com` edge kırık → pratikte ai.acik.com frontend'i serve ediyor,
  intranet-only niyeti korunuyor ama **gerçek testai deneyimi yok**
- Sectigo wildcard paylaşımı halen geçerli
- GHCR SSH deploy key read-only
- **Uyarı:** Handoff v2'ye güvenerek "testai kullanıcıya açık, smoke test edebilir"
  demek yanıltıcı. Drift #1 fix olana kadar testai user-path yok.

---

## 🌙 Son Söz

Bu session fiziksel ilerleme (deploy, fix, commit) yapmadı. Ama **v2'nin gerçekliğini
sarstı** ve gelecekteki aynı tuzağın metodolojisini tanımladı. Kullanıcının "sistemi
anlayıp planımızı güncelleyeceğiz" kararı doğruydu — fix yerine teşhisi önceleyerek
prod cutover'a yanlış güvenle gitmekten kurtuldu.

**Bir cümlede kalan iş:** Drift #1 (edge testai) + runbook yazımı + PLAN.md HARD RULE
güncellemesi → sonra v2'nin kalan listesi (ArgoCD + prod deploy + stabilite gözlemi
+ cutover).

Codex istişare kuralı aktif — gelecekteki her büyük iş yine plan istişaresi + tamamlanma
review'dan geçecek. Thread ID'leri session hafızasında.

Hayırlı çalışmalar. 🌙
