# ADR-0012 — `@RequireModule` Interceptor + Phase 3 WebMvcTest Verification

> **Status**: Phase 1+2 ACTIVE (production-deployed) — Phase 3 **DEFERRED** (re-evaluate post-iter-49)
> **Date**: 2026-04-30
> **Related**: iter-49 series (Codex thread `019ddf43`), backend repo
> `permission-service/src/main/java/com/example/permission/config/RequireModuleInterceptor.java`,
> `common-auth/src/main/java/com/example/commonauth/openfga/RequireModule.java`,
> `permission-service/src/test/java/com/example/permission/config/RequireModuleInterceptorTest.java`,
> `permission-service/src/test/java/com/example/permission/controller/AccessControllerV1ScopeSecurityTest.java`

## Bağlam

`@RequireModule` annotation `permission-service` controller'larında module-level
authorization gate olarak kullanılır:

```java
@RequireModule(module = "users", relation = "can_view")
@GetMapping("/api/users/all")
public List<UserDto> listUsers(...) { ... }
```

`RequireModuleInterceptor` HandlerInterceptor JWT subject'inden numeric userId
çıkarır, OpenFGA'ya `(user, mappedRelation, "module", moduleName)` check
gönderir; denied → 403 Forbidden.

## Phase 1+2 — ACTIVE

| Phase | Kapsam | Status | Test |
|---|---|---|---|
| Phase 1 | Annotation tanımı + interceptor implementation | ✅ Production | unit |
| Phase 2 | Relation alias mapping (legacy `viewer`/`manager`/`admin` → canonical `can_view`/`can_manage`/`can_edit`) | ✅ Production | unit + integration |

**Test coverage (mevcut)**:
- `RequireModuleInterceptorTest` — unit test, mock OpenFgaAuthzService + AuthenticatedUserLookupService
- `AccessControllerV1ScopeSecurityTest` — security integration test (real Spring context)
- D35-3 ladder closure (2026-04-29) — relation alias mapping production fix

## Phase 3 — DEFERRED

**Hedef**: `@WebMvcTest` slice test ile `@RequireModule` annotation davranışının
controller-level doğrulanması. Mevcut testler full Spring context ile çalışır;
WebMvcTest slice (web layer + controller only) hem hızlı hem encapsulated.

**Codex tavsiyesi (`019ddf43`)**:
> "ADR-0012 Phase 3 ile A/B birleştirme. `@RequireModule WebMvcTest` ayrı
> spike/PR olarak defer devam etmeli. Bu matrix WebFlux `@SpringBootTest` ile
> daha doğru temsil ediliyor."

> "Bu iter'de sadece yeniden değerlendirme notu. A'yı bloke etmemeli."

## Karar

**Phase 3 WebMvcTest verification → DEFER continue**.

Rasyonel:
1. **Production functionality kanıtı yeterli**: `RequireModuleInterceptorTest`
   (unit) + `AccessControllerV1ScopeSecurityTest` (integration) ile interceptor
   davranışı kanıtlandı. D35-3 production fix sonrası canlı doğrulama mevcut.
2. **WebMvcTest scope'u hibrit gerekiyor**: Spring Cloud Gateway WebFlux
   reactive + permission-service Spring MVC servlet — iki farklı stack.
   Interceptor yalnız servlet path'inde tetikleniyor (`HandlerInterceptor`,
   not `WebFilter`). WebMvcTest doğru slice ama spike effort orta-yüksek
   (mock ApplicationContext + servlet handler chain).
3. **iter-49 ana scope tamamlandı**: A (status code matrix) + A.1
   (production fix bad-token 401) + A.2 (test infrastructure baseline) + B
   (Grafana SLO dashboard) ile iter-49 majör hedefler shipped.

## Defer takip kriterleri

Phase 3 WebMvcTest spike yeniden değerlendirilmeli **eğer**:

- D35 Zanzibar ladder closure'da yeni regression bulunursa (interceptor
  davranış kontratı net testle gerekli olur)
- `@RequireModule` annotation farklı semantik gelişimi (örn. wildcard
  relations, time-based gates) eklenirse
- WebMvcTest infrastructure başka bir ihtiyaç için zaten mevcutsa
  (sunk-cost ile hızlı eklenir)

Pre-prod'da bu kriterler aktif değil → defer continue.

## Sonuçlar

- iter-49 sıralaması A → A.1 → A.2 → B → C ile tamamlandı.
- ADR-0012 Phase 3 takip dokümanı (bu ADR) referans olarak kullanılır.
- Geri dönülürse: yeni ADR-0012-A (Phase 3 WebMvcTest impl) ile bu defer'e
  güncelleme bağlanır.

## Referanslar

- iter-49 A PR: [platform-backend#50](https://github.com/Halildeu/platform-backend/pull/50)
- iter-49 A.1 PR (production fix LIVE): [platform-backend#51](https://github.com/Halildeu/platform-backend/pull/51)
- iter-49 A.2 PR (test infrastructure baseline): [platform-backend#52](https://github.com/Halildeu/platform-backend/pull/52)
- iter-49 B PR (Grafana SLO dashboard): [platform-k8s-gitops#289](https://github.com/Halildeu/platform-k8s-gitops/pull/289)
- Codex thread: `019ddf43-e6eb-7dd0-9c30-d6c9b867e5dd`
- D35-3 ladder closure (2026-04-29 production fix): RequireModuleInterceptor.java +
  AccessControllerV1.java + canonical relations migration
