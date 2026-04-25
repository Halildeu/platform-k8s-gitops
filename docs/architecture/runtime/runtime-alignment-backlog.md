# Runtime Alignment Backlog

Bu dosya, aktif runtime topolojisinde halen açık duran mimari hizalama işlerini
tek yerde toplar. Amaç: feature geliştirmeye geçmeden önce hangi borcun
operasyonel, hangisinin mimari, hangisinin dokümantasyon kaynaklı olduğunu net
göstermektir.

Referans JSON artefact:
- `runtime-alignment-backlog.v1.json`

## 1. Kapalı Kalemler

- `permission-service` için compose healthcheck eklendi.
- `api-gateway` için compose healthcheck eklendi.
- Gateway bağımlılık zincirinde `permission-service` koşulu `service_healthy`
  seviyesine çıkarıldı.
- `core-data-service` compose build drift'i kapatıldı.
- `core-data-service` shared DB + Flyway baseline davranışı çalışır hale getirildi.
- `auth-service` için asgari TECH-DESIGN runtime overview eklendi.
- `variant-service` için asgari TECH-DESIGN runtime overview eklendi.
- `core-data-service` için asgari TECH-DESIGN runtime overview eklendi.
- `api-gateway` için asgari TECH-DESIGN runtime overview eklendi.
- `discovery-server` için asgari TECH-DESIGN runtime overview eklendi.
- `auth-service` iç istemcileri `WebClient` standardına taşındı.
- `user-service` iç istemcileri ve token mint hattı `WebClient` standardına taşındı.
- canlı database isolation cutover tamamlandı; runtime `service-owned schema`
  moduna geçti.

## 2. Açık Kalemler

Bu tur için açık runtime hizalama kalemi yok.

İzlenen ama runtime blocker olmayan konu:
- `user-service` içindeki tarihsel V6/V8 cross-service SQL coupling'i artık live
  cutover sonrası legacy migration debt olarak takip edilir.

## 3. Öncelik Sırası

1. Fresh bootstrap standardını `migration_schema_owned` zincirleriyle kalıcı kullanmak
2. Orta vadede ayrı database veya instance kararını backlog olarak ele almak

Sebep:
- Runtime servis özeti artık yazıya kilitlendi.
- Servisler arası HTTP istemcisi standardı kapatıldı.
- Fresh bootstrap, offline cutover, app-level rehearsal ve live cutover kanıtı üretildi.
- Geriye runtime blocker değil, orta vadeli veri topolojisi kararı kaldı.
