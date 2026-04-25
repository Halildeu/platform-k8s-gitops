# ADR-0012: JWT Contains Identity Only (No Permission Claims)

ID: ADR-0012
Status: Accepted (implementation pending — Phase 3)
Date: 2026-03-29
Owner: @team/platform

## Context

Mevcut JWT'de Keycloak realm role'leri ve permission claim'leri gomulu.
Sorunlar:
- Permission degisiklikleri token expire'a kadar (5 dk) yansimaz
- SecurityConfig'de hardcoded admin role → 7+ permission mapping
- Token boyutu gereksiz buyuk
- Keycloak client role'leri authorization karari veriyor (olmamali)

## Decision

**JWT sadece identity bilgisi tasir. Tum permission check'ler OpenFGA'dan runtime'da yapilir.**

JWT'de kalacak claim'ler:
- `sub` — user ID
- `email` — email
- `preferred_username` — display name
- `realm_access.roles` — sadece `user` / `admin` (coarse identity, authz icin DEGIL)

JWT'den KALDIRILACAK:
- `permissions` claim
- `resource_access` client role'leri
- Custom permission mapper'lar

Permission check akisi:
```
Request → JWT'den userId cikart → OpenFGA check(userId, relation, object) → karar
```

## Consequences

**Positive:**
- Permission degisiklikleri aninda etkili (JWT refresh beklenmez)
- Token boyutu kucuk
- Keycloak = sadece authn, net govrev ayriligi

**Negative:**
- Her request'te OpenFGA cagrisi (cache ile mitigate: 30-60s TTL)
- OpenFGA SPOF riski → circuit breaker + cached fallback (her servis `OpenFgaAuthzService` SDK ile direct; D-008/C-008)
- Frontend hub hattı (permission-service:8090) için ayrı dayaniklilik: outbox + authzVersion caching
- Migration doneminde eski/yeni sistemler paralel calisacak

## Migration Plan

1. Phase 0-2: Tum servisler OpenFGA SDK entegre (tamamlandi)
2. Phase 3: @PreAuthorize → OpenFGA check ile degistir (feature flag)
3. Phase 3: Keycloak realm config'den permission mapper kaldir
4. Phase 3: JWT converter'lardan permission okuma kaldir
5. Phase 3: permission-service role'u donusturuldu — artik OpenFGA sync hub (D-003 DCP, 2026-04-11)

## Links

- Related: ADR-001-openfga-authorization.md
- Related: ADR-002-data-enforcement-rls-filter.md
