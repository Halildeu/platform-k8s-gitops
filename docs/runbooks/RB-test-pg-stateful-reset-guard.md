# RB — Test PostgreSQL Stateful Reset Guard

## Amaç

2026-05-11 test ortamında görülen sınıfı tek kök neden altında ele alır:

> `platform-pg-test` data dizini fresh initialize olur; init script role/database
> oluşturur ama ürün şemaları geri dönmez. Üst servisler farklı semptomlarla
> düşer: `permission-service` schema eksikliği, `variant-service` theme tablosu
> eksikliği, `openfga` datastore drift'i ve endpoint-admin NetworkPolicy/DNS
> etkisi.

Bu runbook restore başlatmaz. Önce kanıt, sonra kontrollü restore kararını
zorunlu kılar.

## RCA sınıflandırması

| Katman | Bulgulanacak sinyal | Kabul edilmeyen durum |
|---|---|---|
| Stateful data-dir | `/srv/platform/stateful/test/postgres/PG_VERSION` | `PG_VERSION` yokken sessiz `initdb` |
| Backup semantiği | dump içinde kritik DB/schema/table marker'ları | sadece role/database içeren dump |
| Product schema | `variant_service.themes`, `data_access.scope` | pod Ready olsa bile tablo eksikliği |
| Authz datastore | OpenFGA `tuple` + `authorization_model` tabloları | OpenFGA pod up ama datastore boş |
| NetworkPolicy selection | endpoint-admin pod template `part-of=platform` | DNS/JDBC egress'in default-deny ile kesilmesi |

## Read-only guard komutları

### 1. Data-dir guard

```bash
python3 scripts/operations/check_test_pg_stateful_guard.py \
  --data-dir /srv/platform/stateful/test/postgres
```

`PG_VERSION` yoksa komut fail eder. Bilinçli boş bootstrap için explicit override
gerekir:

```bash
python3 scripts/operations/check_test_pg_stateful_guard.py \
  --data-dir /srv/platform/stateful/test/postgres \
  --allow-empty-init
```

`--allow-empty-init` normal recovery sırasında kullanılmaz; sadece operatör
tarafından açıkça kabul edilmiş boş test PG bootstrap'ında kullanılır.

### 2. Backup semantic guard

```bash
python3 scripts/operations/check_test_pg_stateful_guard.py \
  --dump /home/halil/platform/backup/pg/test/pg_dumpall_YYYYMMDD-HHMM.sql.gz
```

Aranan minimum marker'lar:

- `CREATE DATABASE variants_db`
- `CREATE SCHEMA variant_service`
- `CREATE TABLE variant_service.themes`
- `CREATE DATABASE reports_db`
- `CREATE SCHEMA data_access`
- `CREATE TABLE data_access.scope`
- `CREATE DATABASE openfga`
- `CREATE TABLE public.tuple`
- `CREATE TABLE public.authorization_model`

### 3. Endpoint-admin rendered label guard

```bash
python3 scripts/governance/check_endpoint_admin_template_labels.py \
  --kustomize-path kustomize/base/apps/endpoint-admin-service \
  --kustomize-path kustomize/overlays/test
```

Zorunlu pod-template label'ları:

- `app.kubernetes.io/name=endpoint-admin-service`
- `app.kubernetes.io/part-of=platform`

Not: `kustomize/overlays/prod` şu an endpoint-admin deployment render etmiyor.
Prod overlay bu servisi sahiplenirse aynı guard prod path'i için de
genişletilir.

## Kontrollü restore karar kapısı

Restore'a geçmeden önce:

1. Mevcut kırık durum dump alınır.
2. Aday backup `check_test_pg_stateful_guard.py --dump` ile geçer.
3. Aday backup scratch PostgreSQL'e restore edilir.
4. Scratch DB'de kritik tablo varlığı doğrulanır.
5. Dependent pod sırası netleşir: OpenFGA → permission-service → variant-service → endpoint-admin-service.
6. Rollback etkisi yazılır: eski data dir rename ile korunur, silinmez.
7. `docs/state/current-state.md` içine canlı drift notu düşülür.

## Recovery sonrası D29 kanıt zinciri

Tek kelimelik "green" kullanılmaz. Kanıt üç seviyede yazılır:

| Seviye | Minimum kanıt |
|---|---|
| Up | pod `Ready`, endpoint dolu, restart sayısı stabil |
| Functional | public/root smoke + servis health + kritik tablo varlığı |
| Zanzibar-ready | OpenFGA store/model/tuple + allow/deny sentetikleri |

## CI kapsamı

`.github/workflows/tpg-reset-guardrails.yml` şu regressionları yakalar:

- Semantik backup marker'ları eksilirse.
- Empty PG data dir explicit override olmadan sağlıklı sayılırsa.
- endpoint-admin rendered pod template NetworkPolicy label'larını kaybederse.
