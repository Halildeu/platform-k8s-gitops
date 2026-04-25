# Runtime Dependency Matrix

## Amaç

Bu matris, runtime bileşenlerinin birbirine olan boot ve çalışma bağımlılıklarını
gösterir.

## Matris

| Bileşen | Doğrudan Bağımlılıklar | Bağımlılık Tipi | Boot İçin Zorunlu | Etki |
| --- | --- | --- | --- | --- |
| `mfe-shell` | gateway, Keycloak, remote MFE'ler | HTTP + MF remote | Evet | shell açılmazsa kullanıcı akışı bozulur |
| `mfe-users` | `mfe-shell`, gateway, `user-service` | MF + HTTP | Evet | kullanıcı yönetimi açılamaz |
| `mfe-access` | `mfe-shell`, gateway, `permission-service` | MF + HTTP | Evet | rol/yetki ekranı açılamaz |
| `mfe-audit` | `mfe-shell`, gateway, `permission-service` | MF + HTTP | Evet | audit görünümü çalışmaz |
| `mfe-reporting` | `mfe-shell`, gateway, `variant-service` | MF + HTTP | Evet | variant/raporlama görünümü çalışmaz |
| `api-gateway` | discovery, auth/user/permission/variant/core-data, observability | route + registry | Evet | tek giriş hattı düşer |
| `auth-service` | discovery, Postgres, Vault/keys, user-service, permission-service | DB + registry + iç servis | Evet | login ve service token akışı durur |
| `user-service` | discovery, Postgres, permission-service, auth-service | DB + registry + iç servis | Evet | kullanıcı işlemleri durur |
| `permission-service` | discovery, Postgres, Keycloak/Vault | DB + registry + JWT | Evet | yetki ve audit akışı durur |
| `variant-service` | discovery, Postgres, permission-service | DB + registry + iç servis | Evet | theme/variant akışı durur |
| `core-data-service` | discovery, Postgres, Keycloak | DB + registry + JWT | Evet | company master data erişimi durur |
| `discovery-server` | yok | registry | Evet | service discovery zinciri bozulur |
| `postgres-db` | volume/storage | stateful DB | Evet | backend kalıcılığı durur |
| Keycloak | internal DB/storage | auth provider | Evet | kullanıcı JWT akışı durur |
| Vault | config + unseal | secret store | Hayır localde, Evet hedef mimaride | prod-grade secret modeli etkilenir |
| Prometheus | metrics targets | observability | Hayır | izleme kaybolur, iş mantığı sürer |
| Grafana | Prometheus | observability | Hayır | dashboard kaybolur, iş mantığı sürer |

## Gözlemler

- Discovery ve Postgres, backend için ortak kritik boğumlardır.
- Keycloak yoksa kullanıcı JWT doğrulama akışı kırılır.
- Vault localde zorunlu değildir; fakat hedef mimaride kritik bileşendir.
- `core-data-service` dependency olarak tanımlı olmasına rağmen compose zincirinde eksikti; bu patch ile ayağa kaldırma yolu eklenmiştir.

## Sonuç

Yeni runtime bileşeni eklenirken bağımlılık zinciri bu matriste görünmeden kabul edilmemelidir.
