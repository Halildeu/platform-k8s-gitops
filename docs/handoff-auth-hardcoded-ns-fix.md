# HAND-OFF: auth-service K8s Profile Hardcoded Namespace Default Fix

> **Source:** K8s-6 (platform-k8s-gitops) Seviye 1 — 2026-04-19
> **Target:** platform-ssot (Zanzibar-25 sonrası, yeni session veya ardıl)
> **Priority:** P1 paralel (K8s-6 Seviye 1'i bloke ETMEZ — ConfigMap override ile maskeleniyor; follow-up temiz drift kapanışı için)
> **Codex ping-pong Madde 1 uzlaşı:** "Bugün için test deploy ConfigMap override yeterli. Yalnız bunu Seviye 1'i bloklayan koşul değil, aynı gün paralel kapanacak drift olarak görüyorum."

---

## 1. Bağlam

K8s-6 Seviye 1 planının **retrospektif ping-pong** sırasında (thread `019d9a75`) şu drift tespit edildi:

`backend/auth-service/src/main/resources/application-k8s.yml:99` içeriği:

```yaml
permission:
  service:
    base-url: ${PERMISSION_SERVICE_BASE_URL:http://permission-service.platform-prod.svc.cluster.local:8090}
  audit-mirror:
    base-url: ${PERMISSION_AUDIT_MIRROR_BASE_URL:${PERMISSION_SERVICE_BASE_URL:http://permission-service.platform-prod.svc.cluster.local:8090}}

user:
  service:
    base-url: ${USER_SERVICE_BASE_URL:http://user-service.platform-prod.svc.cluster.local:8089}
```

**Sorun:** Env-driven pattern doğru ama **default değer `platform-prod.svc.cluster.local`** hardcoded. Test namespace'te (platform-test) env override olmadığında bu default devreye girer → NXDOMAIN veya yanlış namespace'e çağrı.

K8s-6 geçici override: `kustomize/base/apps/auth-service/configmap.yaml`'a `PERMISSION_SERVICE_BASE_URL`, `PERMISSION_AUDIT_MIRROR_BASE_URL`, `USER_SERVICE_BASE_URL` env'leri eklendi (shortname + PLACEHOLDER_NS replacement pattern).

**Codex Tur 1 (2026-04-19) hükmü:** "Burada doğru default **`platform-prod.svc.cluster.local`** değil. Doğru default **aynı namespace içi kısa DNS** olmalı: `http://permission-service:8090` ve `http://user-service:8089`. `platform-prod.svc.cluster.local` fallback'i bırakmak kötü default. Çalıştırılabilir ama doğru tasarım değil."

---

## 2. İstenen PR Kapsamı (küçük, tek dosya)

### `backend/auth-service/src/main/resources/application-k8s.yml:99` revizyonu

**ÖNCE:**
```yaml
permission:
  service:
    base-url: ${PERMISSION_SERVICE_BASE_URL:http://permission-service.platform-prod.svc.cluster.local:8090}
  audit-mirror:
    base-url: ${PERMISSION_AUDIT_MIRROR_BASE_URL:${PERMISSION_SERVICE_BASE_URL:http://permission-service.platform-prod.svc.cluster.local:8090}}
    enabled: ${PERMISSION_AUDIT_MIRROR_ENABLED:true}
    internal-api-key: ${PERMISSION_SERVICE_INTERNAL_API_KEY:}

user:
  service:
    base-url: ${USER_SERVICE_BASE_URL:http://user-service.platform-prod.svc.cluster.local:8089}
```

**SONRA:**
```yaml
permission:
  service:
    # Default: namespace-local shortname (Codex K8s-6 Tur 1 uzlaşı — aynı namespace
    # içi kısa DNS, ConfigMap override ile namespace'e çözülür)
    base-url: ${PERMISSION_SERVICE_BASE_URL:http://permission-service:8090}
  audit-mirror:
    base-url: ${PERMISSION_AUDIT_MIRROR_BASE_URL:${PERMISSION_SERVICE_BASE_URL:http://permission-service:8090}}
    enabled: ${PERMISSION_AUDIT_MIRROR_ENABLED:true}
    internal-api-key: ${PERMISSION_SERVICE_INTERNAL_API_KEY:}

user:
  service:
    base-url: ${USER_SERVICE_BASE_URL:http://user-service:8089}
```

**Değişiklik:** 2 default URL revize — `.platform-prod.svc.cluster.local` → shortname (intra-ns resolve).

### Eğer user-service, variant-service, core-data-service, report-service `application-k8s.yml` dosyalarında da aynı pattern varsa:

```bash
grep -rn "platform-prod.svc.cluster.local" backend/*/src/main/resources/application-k8s.yml
```

**K8s-6 tespit:** Sadece auth-service'te var. Ama teyit için yukarıdaki grep çalıştırılmalı. Eğer başka servislerde de varsa aynı pattern'e çevir.

---

## 3. Kabul Kriteri

- [ ] auth-service `application-k8s.yml` default URL shortname (`permission-service:8090`, `user-service:8089`)
- [ ] grep sonucu sıfır hardcoded `platform-prod.svc.cluster.local` fallback
- [ ] `mvn test -pl auth-service` yeşil
- [ ] CI build + GHCR push (yeni image tag, örn. `sha-<new_commit>`)
- [ ] K8s-6 tarafı bilgi verilir: yeni image tag overlay test+prod'a işlenebilir (ama zorunlu değil — ConfigMap override zaten doğru davranışı sağlıyor)

---

## 4. Codex İstişare Önerisi (feedback memory gereği)

Bu PR küçük scope (2 default URL), plan istişaresi iterate yerine **tek turlu consult** yeterli olabilir:

1. Plan önerisi Codex'e sun (PR taslağı)
2. Codex onay/revize
3. Commit + PR + CI + merge

Büyük refactor değil — pattern değişikliği yok, sadece default değer düzeltmesi.

---

## 5. K8s-6 ile Bağlantı

- **Seviye 1'i bloke ETMEZ.** Bu PR `S1-B2` todo olarak K8s-6 tarafında bekliyor (paralel iş).
- K8s-6 Seviye 1 commit `S1-D6` atomic commit'te ConfigMap override zaten mevcut — pod yeni image çekmeden de doğru davranır.
- Bu PR merge olduktan sonra yeni image tag (örn. `sha-<new_commit>`) K8s-6 overlay'e işlenebilir, ama **paralel** — Seviye 1 smoke bunu beklemez.
- Ana fayda: **drift kapanır**, yeni deploy'larda yanlış default sessizce pick-up edilmez.

---

## 6. Referanslar

- K8s-6 thread: `019d9a75-4299-7313-85bb-003a7de680eb`
- K8s-6 PLAN.md D32 + Seviye 1: `PLAN.md` 2026-04-19 entry
- K8s-6 permission-service manifest commit (bekleyen): `kustomize/base/apps/permission-service/*`
- Codex ping-pong Madde 1 detay: thread 019d9a75 son 2 mesaj (retrospektif pekiştirme + Codex geri adım)
- K8s-6 ConfigMap override pattern: `kustomize/base/apps/auth-service/configmap.yaml:56-61` (PERMISSION_SERVICE_BASE_URL, PERMISSION_AUDIT_MIRROR_BASE_URL, USER_SERVICE_BASE_URL eklemeleri)

---

## 7. Prompt (Zanzibar Session'a Kopyala-Yapıştır)

```
TASK: auth-service application-k8s.yml hardcoded NS default fix
From: K8s-6 session, retrospektif ping-pong Madde 1 uzlaşı
Priority: P1 paralel (küçük PR, K8s-6 Seviye 1 bloke etmez)

Referans dokümanı:
platform-k8s-gitops/docs/handoff-auth-hardcoded-ns-fix.md

Özet: backend/auth-service/src/main/resources/application-k8s.yml
satır 99 civarı permission.service.base-url ve user.service.base-url default
değerleri hardcoded "http://permission-service.platform-prod.svc.cluster.local:8090"
(ve user eşdeğeri) var. Namespace-local shortname default'a çevrilmeli:
"http://permission-service:8090", "http://user-service:8089".

Drift gerekçesi: test namespace override olmazsa prod default devreye girer →
NXDOMAIN. Çift doğruluk kaynağı (dev repo default ≠ K8s ConfigMap override).

Kabul: grep sıfır "platform-prod.svc.cluster.local" fallback + mvn test PASS +
CI build + GHCR push yeni tag.

Codex istişaresi: küçük scope, tek turlu consult yeterli.
```
