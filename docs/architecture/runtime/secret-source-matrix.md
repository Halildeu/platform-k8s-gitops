# Secret Source Matrix

## Amaç

Bu matris, hangi bileşenin hangi secret/config verisini hangi kaynaktan aldığı
konusunu görünür kılar.

## Matris

| Tüketici | Secret / Config | Kanonik Kaynak | Dev/Local Fallback | Teslim Mekanizması | Not |
| --- | --- | --- | --- | --- | --- |
| `user-service` | DB URL / user / password | Vault `vault.db.user-service.*` | `application-local/docker` + compose env | Spring property binding | prod hedefi Vault, local fallback env |
| `permission-service` | DB URL / user / password | Vault `vault.db.permission-service.*` | compose env (`PERMISSION_DB_*`) | Spring property binding | local profilde Vault kapalı |
| `variant-service` | DB URL / user / password | Vault `vault.db.variant-service.*` | env (`VARIANT_DB_*`) | Spring property binding | local/docker profilde Vault kapalı |
| `auth-service` | DB URL / user / password | Vault `vault.db.auth-service.*` | env (`AUTH_DB_*`) | Spring property binding | local/docker profilde Vault kapalı |
| `auth-service` | service JWT private/public key | Vault `vault.jwt.auth-service.*` | env (`SERVICE_JWT_*`) | Spring property binding | service token minting kaynağı |
| `api-gateway` | user JWT JWKS/issuer | env / runtime config | compose env default | Spring property binding | varsayılan Keycloak `serban` realm |
| `core-data-service` | DB URL / user / password | environment config | compose env | Spring property binding | mevcut kodda Vault entegrasyonu yok |
| Tüm resource server servisleri | JWT audience / issuer | environment config | application default | Spring property binding | user JWT doğrulama sınırı |
| `mfe-shell` | Keycloak URL / realm / clientId | runtime env (`VITE_*`) | kod default | `process.env` / `window.__env__` | varsayılan `serban` / `frontend` |
| `shared-http` | gateway base URL | `VITE_GATEWAY_URL` | `/api` | runtime env | same-origin proxy varsayılanı |
| Geliştirici iş akışı | GitHub auth pointer | Vault pointer dokümanı | lokal auth/session | insan + CLI | `docs/00-handbook/GH-AUTH-VAULT-POINTERS.md` referansı vardır |

## Gözlemler

- Kanonik hedef Vault olsa da, mevcut dev/local çalışma düzeni env fallback ağırlıklıdır.
- Frontend doğrudan Vault kullanmaz; yalnız runtime env tüketir.
- `core-data-service` secret modeli diğer servisler kadar olgun değildir; compose env ile ayağa kaldırılır.

## Sonuç

Her yeni servis için secret tasarımı eklenmeden önce bu matrise bir satır eklenmelidir.
