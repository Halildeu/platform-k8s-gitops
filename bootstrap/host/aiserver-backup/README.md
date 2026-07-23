# aiserver host backup timers

Bu dizin `10.9.10.15` üzerindeki host-level PostgreSQL, Vault, Keycloak ve
backup-freshness görevlerinin canonical systemd tanımını taşır.

Kurulum hedefleri:

- `platform-backup-run` → `/usr/local/sbin/platform-backup-run`
- `platform-backup@.service` ve `platform-backup-*.timer` →
  `/etc/systemd/system/`
- Vault init dosyaları → `/srv/platform/secrets/backup-auth/` (`root:root`,
  `0600`; ham değerler loglanmaz)
- çıktı → `/srv/platform/backup/{pg,vault,keycloak,metrics}`

Kurulumdan sonra `systemd-analyze verify`, dört one-shot service çalıştırması,
üretilen dosyaların format/boyut kontrolü ve iki k3d node'unda
`backup_freshness.prom` varlığı doğrulanır. Timer'lar ancak bu kontrollerden
sonra `enable --now` yapılır.
