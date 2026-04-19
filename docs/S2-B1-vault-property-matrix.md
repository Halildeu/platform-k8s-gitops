# S2-B1 Vault Property Matrix — ESO Apply Preflight

> **Source:** K8s-6 Codex FR4 son öneri (2026-04-19)
> **Usage:** ESO apply öncesi Vault path + property varlık doğrulama
> **Prereq:** Vault AppRole `eso-runtime` aktif + `eso-runtime-kv-read` policy

---

## 1. Tek Tabloda — Her Servis × Vault Path × Property

### 1.1 ghcr-pull (base)

| Secret Key | Vault Path | Property | Zorunlu |
|---|---|---|---|
| username | `kv/gitops/ghcr-token` | `username` | ✅ |
| password | `kv/gitops/ghcr-token` | `password` | ✅ (GitHub PAT `read:packages`) |

### 1.2 permission-service (authz hub)

| Secret Key | Vault Path | Property | Zorunlu |
|---|---|---|---|
| SPRING_DATASOURCE_USERNAME | `kv/platform/permission-service` | `db_username` | ✅ |
| SPRING_DATASOURCE_PASSWORD | `kv/platform/permission-service` | `db_password` | ✅ |
| PERMISSION_SERVICE_INTERNAL_API_KEY | `kv/platform/permission-service` | `internal_api_key` | ✅ (shared caller'lar için) |
| KEYCLOAK_CLIENT_SECRET | `kv/platform/permission-service` | `keycloak_client_secret` | ✅ |
| ERP_OPENFGA_STORE_ID | `kv/platform/openfga` | `store_id` | ✅ (D-008 runtime kontrat) |
| ERP_OPENFGA_MODEL_ID | `kv/platform/openfga` | `model_id` | ✅ |

### 1.3 auth-service

| Secret Key | Vault Path | Property | Zorunlu |
|---|---|---|---|
| SPRING_DATASOURCE_USERNAME | `kv/platform/auth-service` | `db_username` | ✅ |
| SPRING_DATASOURCE_PASSWORD | `kv/platform/auth-service` | `db_password` | ✅ |
| SECURITY_SERVICE_JWT_PRIVATE_KEY | `kv/platform/auth-service` | `jwt_private_key` | ✅ |
| SECURITY_SERVICE_JWT_PUBLIC_KEY | `kv/platform/auth-service` | `jwt_public_key` | ✅ |
| KEYCLOAK_CLIENT_SECRET | `kv/platform/auth-service` | `keycloak_client_secret` | ✅ |
| PERMISSION_SERVICE_INTERNAL_API_KEY | `kv/platform/permission-service` | `internal_api_key` | ✅ (shared) |

### 1.4 user-service / variant-service / core-data-service

**Aynı property seti:**

| Secret Key | Vault Path | Property | Zorunlu |
|---|---|---|---|
| SPRING_DATASOURCE_USERNAME | `kv/platform/<svc>` | `db_username` | ✅ |
| SPRING_DATASOURCE_PASSWORD | `kv/platform/<svc>` | `db_password` | ✅ |
| KEYCLOAK_CLIENT_SECRET | `kv/platform/<svc>` | `keycloak_client_secret` | ✅ |
| PERMISSION_SERVICE_INTERNAL_API_KEY | `kv/platform/permission-service` | `internal_api_key` | ✅ (shared) |
| ERP_OPENFGA_STORE_ID | `kv/platform/openfga` | `store_id` | ✅ (direct engine) |
| ERP_OPENFGA_MODEL_ID | `kv/platform/openfga` | `model_id` | ✅ |

### 1.5 report-service / schema-service

| Secret Key | Vault Path | Property | Zorunlu |
|---|---|---|---|
| SPRING_DATASOURCE_USERNAME | `kv/platform/<svc>` | `db_username` | ✅ |
| SPRING_DATASOURCE_PASSWORD | `kv/platform/<svc>` | `db_password` | ✅ |
| KEYCLOAK_CLIENT_SECRET | `kv/platform/<svc>` | `keycloak_client_secret` | ✅ |
| PERMISSION_SERVICE_INTERNAL_API_KEY | `kv/platform/permission-service` | `internal_api_key` | ✅ |
| REPORT_MSSQL_USERNAME / SCHEMA_MSSQL_USERNAME | `kv/platform/mssql-external` | `username` | ⚠ **Opsiyonel** (D31, yorumlu ES) |
| REPORT_MSSQL_PASSWORD / SCHEMA_MSSQL_PASSWORD | `kv/platform/mssql-external` | `password` | ⚠ **Opsiyonel** |

## 2. Özet Vault KV Path Listesi

### 2.1 Zorunlu Path'ler (ESO apply için)

```
kv/gitops/ghcr-token           (username + password=PAT)
kv/platform/permission-service (db_username, db_password, internal_api_key, keycloak_client_secret)
kv/platform/auth-service       (db_username, db_password, jwt_private_key, jwt_public_key, keycloak_client_secret)
kv/platform/user-service       (db_username, db_password, keycloak_client_secret)
kv/platform/variant-service    (db_username, db_password, keycloak_client_secret)
kv/platform/core-data-service  (db_username, db_password, keycloak_client_secret)
kv/platform/report-service     (db_username, db_password, keycloak_client_secret)
kv/platform/schema-service     (db_username, db_password, keycloak_client_secret)
kv/platform/openfga            (store_id, model_id)
```

### 2.2 Opsiyonel (D31 feature flag)

```
kv/platform/mssql-external     (username, password — Workcube ERP read-only)
```

### 2.3 Test vs Prod İzolasyonu

Codex AR2 WARN: "Tek Vault paylaşılırsa env-prefix zorunlu olur (`kv/platform/test/<svc>`, `kv/platform/prod/<svc>`)."

**Mevcut mimari (D6 + D20):** Test ve prod **AYRI Vault instance** (staging-sw test Vault + staging-sw-2 D32 prod Vault). Path konvansiyonu **aynı** (`kv/platform/<svc>`), iki ayrı Vault'ta yaşar. Env-prefix gereksiz.

**Eğer ileride tek Vault paylaşılır ise:** Path'ler `kv/platform/test/<svc>` + `kv/platform/prod/<svc>` olarak bölünür, ES overlay'de key path override edilir.

## 3. Apply Preflight Script

```bash
#!/usr/bin/env bash
# Vault property matrix doğrulama
# Usage: vault login + VAULT_ADDR set + bu script

set -euo pipefail

PATHS=(
  "kv/gitops/ghcr-token:username,password"
  "kv/platform/permission-service:db_username,db_password,internal_api_key,keycloak_client_secret"
  "kv/platform/auth-service:db_username,db_password,jwt_private_key,jwt_public_key,keycloak_client_secret"
  "kv/platform/user-service:db_username,db_password,keycloak_client_secret"
  "kv/platform/variant-service:db_username,db_password,keycloak_client_secret"
  "kv/platform/core-data-service:db_username,db_password,keycloak_client_secret"
  "kv/platform/report-service:db_username,db_password,keycloak_client_secret"
  "kv/platform/schema-service:db_username,db_password,keycloak_client_secret"
  "kv/platform/openfga:store_id,model_id"
)

MISSING=0
for entry in "${PATHS[@]}"; do
  IFS=':' read -r path props <<< "$entry"
  IFS=',' read -ra keys <<< "$props"
  data=$(vault kv get -format=json "$path" 2>/dev/null | jq -r '.data.data // empty')
  if [[ -z "$data" ]]; then
    echo "❌ MISSING: $path"
    MISSING=$((MISSING + 1))
    continue
  fi
  for key in "${keys[@]}"; do
    val=$(echo "$data" | jq -r ".$key // empty")
    if [[ -z "$val" ]]; then
      echo "⚠ $path MISSING property: $key"
      MISSING=$((MISSING + 1))
    fi
  done
done

if [[ $MISSING -eq 0 ]]; then
  echo "✅ Tüm Vault property'ler hazır. ESO apply OK."
  exit 0
else
  echo "❌ $MISSING eksik — ESO apply'dan önce ops yaratmalı."
  exit 1
fi
```

## 4. Kabul Kriteri

- [ ] Tüm **zorunlu** 9 Vault path mevcut (KV v2)
- [ ] Her path'te beklenen property'ler dolu
- [ ] AppRole `eso-runtime` bu path'leri `read` yetkisine sahip
- [ ] Preflight script `exit 0` döner

## 5. ESO Apply Sırası (Codex FR2 uzlaşı)

1. **Preflight script** çalıştır (Vault doğrulama)
2. ESO Helm chart install (`helm-values/external-secrets/`)
3. ClusterSecretStore + ghcr-pull ExternalSecret apply — **OVERLAY ZORUNLU** (Codex iter-2 AGREE D-1):
   - Test cluster: `kubectl apply -k kustomize/overlays/test/eso`
   - Prod cluster: `kubectl apply -k kustomize/overlays/prod/eso`
   - **YASAK:** `kubectl apply -k kustomize/base/eso` (ClusterSecretStore FQDN placeholder, Ready=False)
4. Doğrula: `kubectl get externalsecret -A` + `kubectl get secret ghcr-pull` + `kubectl get clustersecretstore` (Status=Ready)
5. Per-service ES switch (her svc kustomization.yaml'da `secret-stub.yaml` kaldır + `externalsecret.yaml` ekle)
6. Apply overlay (`kubectl apply -k overlays/test`)
7. Doğrula: 7 ExternalSecret Synced + pod env effective

## 6. Prompt (ops/SRE session)

```
TASK: S2-B1 Vault Property Matrix Preflight
From: K8s-6 Codex FR4

Detay: platform-k8s-gitops/docs/S2-B1-vault-property-matrix.md

Ops: Vault path'leri (9 zorunlu + 1 opsiyonel) yarat, property'leri doldur,
AppRole eso-runtime read yetkisi ver. Preflight script exit 0 alınınca
ESO apply açılır.
```
