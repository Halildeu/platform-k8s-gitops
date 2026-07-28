# RB-faz35-tenant-onboarding — Etik Speak yeni müşteri (tenant) ekleme

> **Tetik**: Yeni bir firma Etik Speak whistleblowing kanalını kendi çalışanları için kullanmak istiyor (M2 ilk dış pilot ve sonrası).
> **Süre**: ~45-60 dk (ilk kez), ~20 dk (tekrarlayan).
> **Ön koşul**: ethics-service ≥ M2 multi-tenant resolver (backend PR #925) deploy'lu. ES-311 imza paketi + hedef firma için sözleşme/DPA imzalı.

---

## Mimari — neden bu kadar az adım

Multi-tenancy veri düzleminde **zaten mevcut**: her entity `org_id`-scoped, staff sorguları org-izole, staff org'u JWT `org_id` claim'inden çözülür. M2 (backend #925) public reporter path'ini de **host→org** çözecek şekilde tamamladı. Bu yüzden yeni müşteri = **veri-model değişikliği YOK**; sadece 3 eşleme:

1. Public host → org UUID (ethics-service config)
2. Ingress host → aynı backend (edge + K3s ingress)
3. Staff realm/client → `org_id` claim (Keycloak)

Firma verisi ilk bildirimle otomatik izole olur (case `org_id` = resolve edilen org).

---

## Adım 0 — Tenant kimliği belirle (5 dk)

```bash
# Yeni org için stabil UUID üret (bir kez; audit + config'de kalıcı)
TENANT_ORG=$(uuidgen | tr 'A-Z' 'a-z')
echo "TENANT_ORG=$TENANT_ORG"    # örn 7f3a...; bunu kaydet
```

Kararlaştır:
- **Firma adı** + kısa slug (örn `firma-x`)
- **Public host**: adanmış subdomain (`ihbar.firma-x.com` — firma DNS'i) VEYA paylaşımlı (`firma-x.speakup.acik.com` — bizim wildcard)
- **Staff erişimi**: firma İK'sı bizim Keycloak realm'inde mi (managed) yoksa kendi IdP'si federate mi (advanced, sonraki faz)

> **Karar vekili**: Host stratejisi (adanmış vs paylaşımlı subdomain) müşteri tercihi + DNS sahipliğine bağlı. Belirsizse Codex'e seçenekli sor (HARD RULE Kullanıcı-Kararı Vekili).

---

## Adım 1 — Keycloak: staff org_id claim (15 dk)

Firma İK personeli, bizim `platform-<env>` realm'inde `org_id` claim'i **firma org UUID'sine** eşlenmiş JWT almalı.

```bash
# Test cell örneği (aiserver, platform-test realm)
KC=https://testai.acik.com/auth   # prod: ai.acik.com
# 1. Firma için grup oluştur: /org/<slug>, attribute org_id=$TENANT_ORG
# 2. Group -> protocol mapper: org_id (User Attribute -> claim org_id)
#    (mevcut ethics-manager client zaten org_id mapper taşıyorsa grup attribute yeterli)
# 3. Firma İK kullanıcılarını bu gruba ekle + ethics-manager rolü/entitlement ver
```

Kontrol:
```bash
# İK personeli token'ı al, org_id claim doğru mu
# (LIVE smoke token pattern — Vault persona + smoke-client)
# Beklenen: jwt.org_id == $TENANT_ORG
```

> Detay KC hardening için: [project_faz22_sec_kc_hardening] + [reference_live_smoke_token_pattern].

---

## Adım 2 — ethics-service: host→org eşlemesi (10 dk)

Backend config'e tek entry. **ConfigMap-only değişiklik pod'a ulaşmaz** — env değişimi + rollout gerekir (bkz. CLAUDE.md Pitfall #3).

`kustomize/overlays/<env>/activation/etik-speak/` içinde ethics-service ConfigMap/env:

```yaml
# ethics.tenancy.public-hosts — bracket notation dotted host key'i korur
ETHICS_TENANCY_PUBLIC_HOSTS_0_HOST: "ihbar.firma-x.com"     # veya SPRING_APPLICATION_JSON
ETHICS_TENANCY_PUBLIC_HOSTS_0_ORG:  "<TENANT_ORG>"
```

Daha temiz: `SPRING_APPLICATION_JSON` ile map:
```json
{"ethics":{"tenancy":{"public-hosts":{"ihbar.firma-x.com":"<TENANT_ORG>"}}}}
```

Apply + rollout:
```bash
kubectl --context k3d-<env> -n platform-<env> apply -f <configmap>.yaml
kubectl --context k3d-<env> -n platform-<env> rollout restart deploy/ethics-service
kubectl --context k3d-<env> -n platform-<env> rollout status deploy/ethics-service --timeout=600s
```

> Not: unmapped host default `public-org-id`'ye düşer; yanlış/eksik entry **sessizce default org'a yazar** — bu yüzden Adım 4 doğrulaması zorunlu.

---

## Adım 3 — Ingress + edge: yeni host → aynı backend (10 dk)

**Adanmış subdomain** (`ihbar.firma-x.com`):
1. Firma DNS'i `ihbar.firma-x.com` → bizim edge IP (aiserver `10.9.10.15`, prod WAN)
2. TLS: firma sağlar (bize cert) VEYA ACME (Let's Encrypt) — edge nginx SNI
3. K3s ingress `etik-speak-public-api` + `-ui` host listesine ekle:

```yaml
# kustomize/overlays/<env>/activation/etik-speak/ingress-public-*.yaml
  rules:
    - host: ihbar.firma-x.com
      http: *publicApi   # mevcut anchor reuse
```
(TLS `hosts` listesine de ekle; wildcard `*.acik.com` değilse ayrı secret)

**Paylaşımlı subdomain** (`firma-x.speakup.acik.com`): wildcard `*.acik.com` cert zaten kapsar; sadece ingress host satırı + host→org entry yeterli.

Apply (selective, low blast-radius):
```bash
kubectl --context k3d-<env> -n platform-<env> apply -f kustomize/overlays/<env>/activation/etik-speak/ingress-public-api.yaml
kubectl --context k3d-<env> -n platform-<env> apply -f kustomize/overlays/<env>/activation/etik-speak/ingress-public-ui.yaml
```

---

## Adım 4 — Doğrulama: tenant izolasyonu (10 dk) — ZORUNLU

D29 3-proof + izolasyon kanıtı. **Bu adım atlanamaz** (yanlış org'a yazma sessiz hatadır).

### 4a. Reporter POST → firma org'una yazıyor mu

```bash
SECRET=$(LC_ALL=C tr -dc "A-Za-z0-9" </dev/urandom | head -c 43)
curl -sk -X POST "https://<edge-ip>/api/v1/public/ethics/reports" \
  -H "Host: ihbar.firma-x.com" \
  -H "Content-Type: application/json" -H "Idempotency-Key: $(uuidgen)" \
  -d "{\"mode\":\"ANONYMOUS\",\"category\":\"OTHER\",\"subject\":\"onboarding verify\",\"description\":\"tenant isolation check\",\"locale\":\"tr-TR\",\"accessSecret\":\"$SECRET\",\"noticeVersion\":\"v1.0.0\"}"
# Beklenen: 201 + receiptId
```

DB'de org doğrula (pod exec veya psql):
```sql
SELECT org_id FROM ethics_case ORDER BY created_at DESC LIMIT 1;
-- Beklenen: <TENANT_ORG>  (default 00000000-...-0035 DEĞİL)
```

### 4b. Firma İK staff SADECE kendi case'lerini görüyor mu

```bash
# Firma İK token'ı ile listCases → yeni case görünür
# Başka firma / default org token'ı ile → bu case GÖRÜNMEZ
# (cross-tenant leak = P0 blocker, deploy geri al)
```

### 4c. Browser smoke (HARD RULE — Tarayıcıdan Doğrulanmadan İş Bitmedi)

`ihbar.firma-x.com` → reporter formu 200 + POST 201 + firma İK manager UI'de case görünür.

---

## Adım 5 — Kayıt + kapanış

- `docs/faz-35-signatures/roster.md` firma-özel Reveal Officer / DPO ekle (firma kendi sorumlusunu atayabilir)
- VERBİS envanteri: firma ayrı veri sorumlusu mu, bizim veri işleyen mi — Legal Owner belirler
- Project #8 tenant tracker'a firma + org UUID + host + onboarding tarihi kaydet
- Evidence doc: `docs/faz-35-evidence/<tarih>-tenant-<slug>-onboarding.md` (4a/4b/4c kanıtları)

---

## Rollback

Yanlış eşleme / cross-tenant leak tespitinde:
```bash
# 1. host→org entry'yi kaldır (config revert + rollout)
# 2. ingress host satırını kaldır
# 3. Firma DNS'i geri al (adanmış subdomain ise)
# Veri KALICI: yanlış org'a yazılmış case'ler migration ister (org_id UPDATE),
#   silme YASAK (kanunî delil) — Legal Owner + DPO koordineli
```

---

## Referanslar

- Backend: ethics-service `PublicTenantResolver` + `PublicTenantProperties` (PR #925)
- [RB-faz35-real-reporter-open.md](RB-faz35-real-reporter-open.md) — kanal açma
- [RB-faz35-incident-response.md](RB-faz35-incident-response.md) — cross-tenant leak = SEV1
- [RB-faz35-legal-reveal-request.md](RB-faz35-legal-reveal-request.md) — firma-özel Reveal
- Staff org claim: `StaffContextResolver` (JWT `org_id`)
