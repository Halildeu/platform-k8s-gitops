# RB-compose-volume-ssot – Compose Volume SSOT & Drift Cleanup

ID: RB-compose-volume-ssot  
Service: compose-stack  
Status: Draft  
Owner: @team/platform

-------------------------------------------------------------------------------
1. AMAÇ
-------------------------------------------------------------------------------

- Staging + prod compose dosyaları arasındaki persistent volume adlandırma
  drift'ini kalıcı olarak çözmek.
- Fresh-volume incident'larını önlemek: deploy-backend.sh compose dosyaları
  arası switch yaptığında veri orphan kalmasın.

-------------------------------------------------------------------------------
2. KAPSAM
-------------------------------------------------------------------------------

- `backend/docker-compose.yml` (staging / local)
- `deploy/docker-compose.prod.yml` (prod)
- Staging sunucusundaki orphan Docker volumes (manuel cleanup)

Arka plan:

- 2026-04-14 incident: Vault ve Keycloak'ta staging↔prod compose arasında
  volume name drift tespit edildi. Örnek: staging `vault-data:` (tire),
  prod `vault_data:` (alt çizgi) → Docker seviyesinde iki ayrı volume.
- Tetikleyici: PR #372 öncesi staging yanlışlıkla prod compose'u seçiyordu
  (`platform_vault_data` yarattı). PR #372 fix staging'i doğru compose'a
  döndürdü → `platform_vault-data` yeni volume (boş) oluşturdu → "Vault
  data yok" semptomu. Her deploy compose switch'iyle sorun tekrar edebilir.

Canonical SSOT (2026-04-14 sonrası):

```
postgres_data    → platform_postgres_data
vault_data       → platform_vault_data
vault_logs       → platform_vault_logs
vault_snapshots  → platform_vault_snapshots   (yalnız prod mount eder)
loki_data        → platform_loki_data
tempo_data       → platform_tempo_data
```

Her volume'de `name: platform_*` explicit override vardır. Böylece compose
project name veya dosya kaynağı ne olursa olsun Docker-level volume adı sabit.

-------------------------------------------------------------------------------
3. BAŞLATMA / DURDURMA
-------------------------------------------------------------------------------

3.1 Drift check (her zaman PR'dan önce)

```bash
bash backend/scripts/doctor-infra.sh 2>&1 | grep -E "K[1-4]:"
# Beklenen: 4/4 PASS
#   K1: Compose volume keys identical across staging↔prod
#   K2: Every volume has explicit name: override (Docker-level pin)
#   K3: No stale volume declarations
#   K4: No dash-in-key naming drift (underscore-only)
```

3.2 Staging orphan cleanup (ilk migration, manuel)

SSOT PR merge edilip staging'e deploy edildikten sonra — eski drift volume'leri
sil.

```bash
ssh staging-sw

# Adım A — eski drift volume'lerini listele
docker volume ls --format '{{.Name}}' \
  | grep -E '^(platform_(vault-data|vault_file|backend_keycloak_data|keycloak_data|loki-data|tempo-data)|serban_.*)$'

# Adım B — içlerinde kullanılabilir veri var mı kontrol (güvenlik kontrolü)
for v in platform_vault-data platform_vault_file serban_postgres_data serban_vault-data; do
  sz=$(docker run --rm -v "$v:/d" alpine:3 du -sh /d 2>/dev/null | awk '{print $1}')
  echo "$v : $sz"
done

# Adım C — boş olanları sil (4K = praktik olarak boş)
for v in platform_vault-data platform_vault_file platform_loki-data platform_tempo-data \
         platform_backend_keycloak_data platform_keycloak_data \
         serban_postgres_data serban_vault-data; do
  if docker volume inspect "$v" >/dev/null 2>&1; then
    docker volume rm "$v" 2>&1 || echo "  $v: in-use, skip"
  fi
done

# Adım D — doğrula
docker volume ls --format '{{.Name}}' | grep -E 'platform|serban' | sort
# Beklenen (yalnız canonical):
#   platform_loki_data
#   platform_postgres_data
#   platform_tempo_data
#   platform_vault_data
#   platform_vault_logs
#   platform_vault_snapshots
```

3.3 Dolu orphan volume migration (eğer veri korunacaksa)

Eğer `platform_vault_data` (74MB eski prod vault data) veya benzeri dolu bir
orphan'da kurtarılmak istenen veri varsa, **canonical volume'e kopyala**:

```bash
# ÖRNEK: eski platform_vault_data → yeni platform_vault_data (rename kolay değil)
# Strategy: tmp container ile rsync
docker run --rm \
  -v platform_vault_data:/src \
  -v platform_vault_data_new:/dst \
  alpine:3 sh -c "apk add --no-cache rsync && rsync -a /src/ /dst/"

# SSOT canonical olmayan eski volume'u sil
docker volume rm platform_vault_data   # (eski)
# Yeni canonical'ı eski ismle rename (docker yoktur doğrudan rename):
# Workaround: new volume'u "platform_vault_data" olarak oluştur, data kopyala.
```

Bu migration SSOT PR merge'den ÖNCE yapılmalı (veri kaybolmasın). Staging'de
2026-04-14 itibarıyla volume'lerde anlamlı veri yok → migration atlanabilir.

3.4 Durdurma

- Compose drift fix'ini revert için: canonical `name:` override'ları kaldır
  ve top-level keys'i eski hallerine döndür. Ancak bu **incidentların tekrarlanmasına
  neden olur** — revert önerilmez. Rollback yerine düzeltme tercih et.

-------------------------------------------------------------------------------
4. GÖZLEMLEME / LOG / METRİKLER
-------------------------------------------------------------------------------

4.1 Doctor K section (CI + manuel)

```bash
bash backend/scripts/doctor-infra.sh | grep K
```

CI: `.github/workflows/ci-gate-infra.yml` (varsa) `doctor-infra.sh` çalıştırır;
K1-K4 fail → ci-gate red.

4.2 Canlı volume inventory

```bash
ssh staging-sw "docker volume ls --format '{{.Name}}\t{{.Mountpoint}}' | grep -E 'platform|serban'"
```

Beklenen yalnız 6 canonical volume. Ek isim drift işareti.

4.3 Compose parity (ad-hoc)

```bash
diff <(awk '/^volumes:/,/^[a-z]/' backend/docker-compose.yml | grep -E '^  [a-z]') \
     <(awk '/^volumes:/,/^[a-z]/' deploy/docker-compose.prod.yml | grep -E '^  [a-z]')
# Çıktı boş olmalı.
```

-------------------------------------------------------------------------------
5. ARIZA DURUMLARI VE ADIMLAR
-------------------------------------------------------------------------------

5.1 doctor K1 FAIL (volume keys divergence)

Tespit: staging ve prod compose top-level `volumes:` blokları farklı key set'i
tanımlıyor.

Çözüm adımları:

- Drift gör: `diff <(staging keys) <(prod keys)` komutu (§4.3)
- Canonical SSOT listesine (§2) uydur — eksik key'leri her iki dosyaya ekle
- Tekrar `doctor-infra.sh | grep K1` → PASS

5.2 doctor K2 FAIL (explicit name eksik)

Tespit: bir volume'un altında `name: platform_*` yok.

Çözüm: Her `volumes:` entry'sine `name:` satırı ekle:

```yaml
volumes:
  vault_data:
    name: platform_vault_data
```

5.3 doctor K3 FAIL (stale volume)

Tespit: top-level'de tanımlı ama hiçbir service mount etmiyor.

Çözüm: Ya kullanım ekle ya top-level'den kaldır. Kullanılmayan volume = ölü
kod; genellikle kaldır.

5.4 doctor K4 FAIL (dash in key)

Tespit: `vault-data` gibi tire içeren key.

Çözüm: `vault_data` gibi underscore'a çevir + mount reference'larını güncelle
+ SSOT eşlet.

5.5 Canlıda orphan volume (doctor pass ama staging'de drift volume var)

Tespit: `docker volume ls` canonical olmayan isimler gösteriyor.

Çözüm: §3.2 orphan cleanup adımlarını uygula.

-------------------------------------------------------------------------------
6. ÖZET
-------------------------------------------------------------------------------

- Staging ve prod compose dosyalarındaki persistent volume adları SSOT'a
  uymalı. Drift = fresh-volume incident'ı.
- Her volume'de explicit `name: platform_*` override vardır; compose project
  name veya dosya kaynağı drift olsa bile Docker-level volume adı sabit.
- doctor-infra.sh K1-K4 check'leri drift'i CI öncesi yakalar.
- 2026-04-14 sonrası canonical SSOT: 6 volume (postgres_data, vault_data,
  vault_logs, vault_snapshots, loki_data, tempo_data).

-------------------------------------------------------------------------------
7. LİNKLER (İSTEĞE BAĞLI)
-------------------------------------------------------------------------------

- `backend/docker-compose.yml` (staging — SSOT canonical volumes section)
- `deploy/docker-compose.prod.yml` (prod — SSOT canonical volumes section)
- `backend/scripts/doctor-infra.sh` (Section K: K1-K4 volume drift checks)
- `docs/04-operations/RUNBOOKS/RB-vault-dev-path-migration.md` (ilgili: vault state path migration)
- `.claude/plans/session-handoff-20260414-deploy.md` (incident tarihçesi)
