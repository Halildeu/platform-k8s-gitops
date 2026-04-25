# Service Communication Matrix

## Amaç

Bu matris, sistemdeki ana çağrı hatlarını ve bunların hangi auth/discovery modeli
ile çalıştığını görünür kılar.

## Matris

| Kaynak | Hedef | Kanal | Discovery | Auth Modeli | Not |
| --- | --- | --- | --- | --- | --- |
| Tarayıcı / MFE | `api-gateway` | HTTP REST (`/api`, `/api/v1`) | Hayır | Bearer JWT / permitAll dev modu | Frontend yalnız gateway ile konuşur |
| `mfe-shell` | remote MFE'ler | Module Federation | Hayır | shell auth state paylaşımı | `mfe-shell` host katmandır |
| `api-gateway` | `auth-service` | Spring Cloud Gateway route | `lb://auth-service` | kullanıcı JWT doğrulaması + forward | `/api/auth/**`, `/api/v1/auth/**` |
| `api-gateway` | `user-service` | Spring Cloud Gateway route | `lb://user-service` | kullanıcı JWT doğrulaması + forward | `/api/users/**`, `/api/v1/users/**` |
| `api-gateway` | `permission-service` | Spring Cloud Gateway route | `lb://permission-service` | kullanıcı JWT doğrulaması + forward | roles, permissions, audit |
| `api-gateway` | `variant-service` | Spring Cloud Gateway route | `lb://variant-service` | kullanıcı JWT doğrulaması + forward | variants, themes, registry |
| `api-gateway` | `core-data-service` | Spring Cloud Gateway route | `lb://core-data-service` | kullanıcı JWT doğrulaması + forward | `/api/v1/companies/**` |
| `auth-service` | `user-service` | REST client | Eureka + load balancer | service token / internal auth | `WebClient` + ortak timeout |
| `auth-service` | `permission-service` | REST client (legacy, TB-11) | Eureka + load balancer | service token / internal auth | `WebClient` — PR6a ile sökülecek (C-008) |
| `user-service` | `permission-service` | REST client (legacy, TB-11) | Eureka + load balancer | service token / internal auth | `WebClient` — PR6 ile sökülecek (C-008) |
| `user-service` | `auth-service` | REST client | direct/service URL | service token minting | `/oauth2/token` çağrısı `WebClient` ile yapılır |
| `variant-service` | `permission-service` | REST client (legacy, TB-11) | Eureka + load balancer | kullanıcı/scope authz doğrulama | `WebClient` — PR6 ile OpenFGA SDK'ya taşınacak (C-008) |
| Tüm backend servisleri | `OpenFGA` (port 4000) | OpenFGA SDK | Hayır | `OpenFgaAuthzService` (common-auth) | **Canonical check/listObjects yolu** (D-008/C-008). permission-service'e HTTP **YOK**. |
| `permission-service` | `OpenFGA` | OpenFGA SDK | Hayır | `OpenFgaAuthzService` + TupleSync | Tuple write/sync hub (D-003/D-008) |
| Backend servisleri | `discovery-server` | Eureka client | Hayır | servis kaydı | runtime ayağa kalkış bağımlılığı |
| Backend servisleri | `postgres-db` | JDBC | Hayır | DB credential | servis bazlı schema/table sahipliği |
| Backend servisleri | Keycloak | JWKS / issuer validation | Hayır | kullanıcı JWT doğrulama | resource server katmanı |
| `user-service` ve iç servisler | `auth-service` | `/oauth2/jwks`, `/oauth2/token` | Hayır / direct | service JWT doğrulama | iç auth hattı |

## Gözlemler

- Edge hattı net: frontend yalnız gateway ile konuşur.
- Uygulama kodu düzeyinde servisler arası iç çağrı standardı `WebClient` olarak birleşti.
- `user-service -> auth-service` token mint hattı mutlak URL ile, diğer iç çağrılar discovery/load-balanced akışla çalışır.
- **permission-service TRANSFORMED (D-003/D-008 FINAL):** OpenFGA Hub rolünü üstlenir
  (TupleSync + AuthzVersion + `/authz/me`/`/check`/`/explain` + rol CRUD). Kaldırılmaz (C-005).
- **C-008 canonical yol:** Backend servisleri `check`/`listObjects` için `OpenFgaAuthzService`
  (common-auth) kullanır — permission-service'e HTTP çağrısı YOK. Matriste "legacy, TB-11"
  işaretli satırlar PR6a/6b/6c ile sökülecek.

## Sonuç

Yeni servis veya yeni iç çağrı eklenirken bu matris genişletilmeden kod eklenmemelidir.
