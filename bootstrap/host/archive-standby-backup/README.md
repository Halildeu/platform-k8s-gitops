# Archive standby backup pull

`stagingsw` (`10.9.10.53`) aktif workload çalıştırmaz. Bu paket, yalnız
`aiserver` (`10.9.10.15`) yedeklerini saatlik olarak `.53` üzerindeki
`/srv/platform/archive/aiserver-backup` dizinine çeker.

Güven sınırı:

- Kaynak SSH kullanıcısı yalnız `/usr/bin/rrsync -ro /srv/platform/backup`
  forced-command'ını çalıştırabilir.
- `.53` kimliği `.15` üzerinde shell, port-forward, agent-forward veya yazma
  yetkisi alamaz.
- Aktarım `--ignore-existing` kullanır; arşiv dosyası silmez veya üzerine yazmaz.
- Yeni her dosya için boyut ve SHA-256, root-only append dizinindeki ayrı bir
  ledger dosyasına yazılır.
- Timer yalnız `/etc/aiserver-archive/ARCHIVE_STANDBY` sentinel'i varken çalışır.
- Bu akış `.53`te Docker, k3d, Vault, PostgreSQL veya Keycloak başlatmaz.

Kurulum `scripts/ops/install-aiserver-backup-replication.sh --apply` ile iki
host üzerinde idempotent yapılır. Ham private key veya backup içeriği stdout'a
yazılmaz.
