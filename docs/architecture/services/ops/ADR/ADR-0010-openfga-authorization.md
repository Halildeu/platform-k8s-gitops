# ADR-0010: OpenFGA for Authorization (Zanzibar Model)

ID: ADR-0010
Status: Accepted
Date: 2026-03-29
Owner: @team/platform

## Context

ERP sistemi Keycloak (authentication) + custom permission-service (authorization) kullaniyordu.
Sorunlar:
- JWT'ye gomulu permission → token expire'a kadar stale
- Hardcoded admin role → permission mapping (SecurityConfig icinde)
- Veri katmaninda zorlama yok → developer WHERE unutursa data leak
- inline isAdmin() check'ler, tutarsiz permission isimleri
- Permission-service'i bagimsiz SaaS urunu yapma hedefi vardi ama Codex istisaresi sonucu bu ertelendi

## Decision

**OpenFGA'yi kullan, kendi authorization engine'i yazma.**

- OpenFGA (Apache 2.0, Google Zanzibar implementasyonu) self-hosted deploy
- Mevcut permission-service OpenFGA hub'ina donusturuldu (TupleSyncService, AuthzVersionService, roles CRUD, /authz/me endpoint)
- Keycloak = authentication only (identity JWT)
- OpenFGA = authorization (ReBAC tuple store)
- Hibernate @Filter + PostgreSQL RLS = data enforcement

## Alternatives Considered

| Secenek | Karar | Neden |
|---------|-------|-------|
| Custom SaaS auth platform | Reddedildi | Solo developer icin 18-24 ay, market dolu (Auth0 FGA, Permit.io, Authzed) |
| Permit.io (SaaS) | Ertelendi | Vendor lock-in, maliyet; OpenFGA ayni temeli ucretsiz sunar |
| SpiceDB | Ertelendi | OpenFGA daha genis ekosistem, Keycloak connector mevcut |
| Cerbos | Reddedildi | ABAC-focused, ReBAC destegi sinirli |
| Mevcut permission-service'i genislet | Reddedildi | Legacy borc tasinir, Zanzibar modeli avantajlarindan yoksun |

## Consequences

**Positive:**
- Zanzibar modeli: resource hierarchy inheritance (company→project→warehouse)
- OSS, self-hosted, ucretsiz
- Java/JS/Python SDK mevcut
- Playground UI dahil
- Dev mode: openfga.enabled=false ile calismaya devam

**Negative:**
- Yeni teknoloji ogrenme egrisi
- Migration sureci (dual-write/shadow mode)
- OpenFGA performans izlenmeli (p99 <10ms hedefi)

**Risks:**
- OpenFGA SPOF → circuit breaker + cached fallback
- Model eksik senaryo → iteratif genisletme

## D-003 DCP: TRANSFORMED (2026-04-11)

Original D-003 "permission-service REMOVED" label was aspirational and changed to "TRANSFORMED":
- Permission-service IS the OpenFGA hub (TupleSyncService, AuthzVersionService, roles CRUD, /authz/me)
- Docker Compose: service remains active (not legacy profile)
- Gateway: /authz routes point TO permission-service
- Ref: CNS-20260411-001 Codex consensus, PR #325
- Note: D-002 governs Keycloak identity-only JWT (unrelated); permission-service transformation is D-003. See also ADR-0013 (D-008 formalization).

## Links

- [OpenFGA docs](https://openfga.dev)
- Related: ADR-0011-data-enforcement-rls-filter.md, ADR-0012-jwt-identity-only.md
- D-003 DCP: decisions/topics/zanzibar-openfga.v1.json
