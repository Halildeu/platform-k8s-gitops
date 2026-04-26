#!/usr/bin/env bash
# Faz 17.3 — Lokal dev fixtures yükle (KC realm + PG seed + OpenFGA tuples)
# Idempotent: ON CONFLICT DO NOTHING pattern kullanır.
#
# Kullanım:
#   ./scripts/dev-seed.sh                         # default profile = authn-min
#   ./scripts/dev-seed.sh --profile zanzibar-min  # + OpenFGA tuples
#   ./scripts/dev-seed.sh --profile full          # + all DB seed
#   ./scripts/dev-seed.sh --kc-only               # sadece KC realm import
#   ./scripts/dev-seed.sh --pg-only               # sadece PG seed
#   ./scripts/dev-seed.sh --openfga-only          # sadece OpenFGA tuple write

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
FIXTURES="${REPO_ROOT}/bootstrap/local-fixtures"

PROFILE="authn-min"
KC_ONLY=false
PG_ONLY=false
OPENFGA_ONLY=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile) PROFILE="$2"; shift 2 ;;
    --kc-only) KC_ONLY=true; shift ;;
    --pg-only) PG_ONLY=true; shift ;;
    --openfga-only) OPENFGA_ONLY=true; shift ;;
    -h|--help)
      grep -E '^#' "$0" | sed -E 's/^# ?//' | head -20
      exit 0
      ;;
    *) echo "bilinmeyen flag: $1"; exit 2 ;;
  esac
done

log()  { printf '\033[0;36m[dev-seed]\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[0;33m[dev-seed]\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[0;31m[dev-seed]\033[0m %s\n' "$*" >&2; exit 1; }

# Profile-aware bayraklar
DO_KC=true
DO_PG=true
DO_OPENFGA=false

case "${PROFILE}" in
  authn-min)     DO_OPENFGA=false ;;
  zanzibar-min)  DO_OPENFGA=true ;;
  full)          DO_OPENFGA=true ;;
  *) err "profile: authn-min | zanzibar-min | full bekleniyor" ;;
esac

# Override: --xxx-only flag'leri
if [[ "${KC_ONLY}" == "true" || "${PG_ONLY}" == "true" || "${OPENFGA_ONLY}" == "true" ]]; then
  DO_KC=false; DO_PG=false; DO_OPENFGA=false
  [[ "${KC_ONLY}" == "true" ]] && DO_KC=true
  [[ "${PG_ONLY}" == "true" ]] && DO_PG=true
  [[ "${OPENFGA_ONLY}" == "true" ]] && DO_OPENFGA=true
fi

KC_URL="${KC_URL:-http://localhost:8081}"
KC_ADMIN_USER="${KC_ADMIN_USER:-admin}"
KC_ADMIN_PASSWORD="${KC_ADMIN_PASSWORD:-admin}"
PG_HOST="${PG_HOST:-localhost}"
PG_PORT="${PG_PORT:-5432}"
PG_USER="${PG_USER:-platform}"
OPENFGA_URL="${OPENFGA_URL:-http://localhost:32080}"

# ----- KC realm import -----
if [[ "${DO_KC}" == "true" ]]; then
  log "Keycloak realm import: dev-local (target=${KC_URL})"
  KC_TOKEN=$(curl -s --max-time 10 -X POST \
    "${KC_URL}/realms/master/protocol/openid-connect/token" \
    -d "client_id=admin-cli" \
    -d "username=${KC_ADMIN_USER}" \
    -d "password=${KC_ADMIN_PASSWORD}" \
    -d "grant_type=password" | jq -r .access_token 2>/dev/null)

  if [[ -z "${KC_TOKEN}" || "${KC_TOKEN}" == "null" ]]; then
    warn "KC admin token alınamadı — KC çalışıyor mu? ${KC_URL}/realms/master"
  else
    HTTP=$(curl -s --max-time 10 -o /dev/null -w "%{http_code}" \
      -X POST "${KC_URL}/admin/realms" \
      -H "Authorization: Bearer ${KC_TOKEN}" \
      -H "Content-Type: application/json" \
      -d @"${FIXTURES}/keycloak/dev-local-realm.json" 2>/dev/null || echo "000")
    case "${HTTP}" in
      201) log "KC realm 'dev-local' created" ;;
      409) log "KC realm 'dev-local' zaten var (idempotent)" ;;
      *) warn "KC realm import beklenmedik HTTP=${HTTP}" ;;
    esac
  fi
fi

# ----- PG seed -----
if [[ "${DO_PG}" == "true" ]]; then
  log "PG seed (target=${PG_HOST}:${PG_PORT})"
  if command -v psql >/dev/null 2>&1; then
    PGPASSWORD="${PG_PASSWORD:-platform-dev-NOT_FOR_PROD}" psql -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" \
      -f "${FIXTURES}/postgres/seed-dev.sql" 2>&1 | tail -20 || warn "PG seed bazı satırlar fail (ON CONFLICT beklenen)"
  else
    warn "psql yok — docker exec denenebilir: docker exec -i <pg-container> psql ... < seed-dev.sql"
  fi
fi

# ----- OpenFGA model + tuple write (Faz 19.11 Step 3 + Faz 21.3 fixture activation) -----
# Order: discover/create store → write model.fga (capture model_id) → write tuples.
# Without the model-write step, tuples target whatever model was previously written
# to the store; Faz 21.3 explicit-scope semantic must be authoritative for dev/local.
if [[ "${DO_OPENFGA}" == "true" ]]; then
  log "OpenFGA model + tuples (target=${OPENFGA_URL})"

  # 1. Store discovery — env override > auto-discover > create
  STORE_ID="${OPENFGA_STORE_ID:-}"
  if [[ -z "${STORE_ID}" ]]; then
    STORE_ID=$(curl -s --max-time 5 "${OPENFGA_URL}/stores" | jq -r '.stores[0].id // empty' 2>/dev/null || true)
  fi
  if [[ -z "${STORE_ID}" ]]; then
    log "No OpenFGA store found — creating 'platform-dev'"
    CREATE_RESP=$(curl -s --max-time 10 -X POST "${OPENFGA_URL}/stores" \
      -H "Content-Type: application/json" \
      -d '{"name":"platform-dev"}' || echo "{}")
    STORE_ID=$(echo "${CREATE_RESP}" | jq -r '.id // empty' 2>/dev/null || true)
    if [[ -z "${STORE_ID}" ]]; then
      warn "OpenFGA store create failed — cluster'da openfga StatefulSet ayakta mı? Skip."
    else
      log "created store: ${STORE_ID}"
    fi
  else
    log "using OpenFGA store: ${STORE_ID}"
  fi

  if [[ -n "${STORE_ID}" ]]; then
    # 2. Render model.fga → JSON
    MODEL_FILE="${FIXTURES}/openfga/model.fga"
    RENDERER="${FIXTURES}/openfga/render_model_json.py"
    if ! command -v python3 >/dev/null 2>&1; then
      warn "python3 yok — model render edilemiyor; skip model write"
    elif [[ ! -f "${MODEL_FILE}" || ! -f "${RENDERER}" ]]; then
      warn "model.fga veya render_model_json.py eksik — skip model write"
    else
      MODEL_JSON=$(python3 "${RENDERER}" "${MODEL_FILE}" 2>&1) || {
        warn "model render başarısız: ${MODEL_JSON}"
        MODEL_JSON=""
      }
      if [[ -n "${MODEL_JSON}" ]]; then
        # 3. Write model — capture model_id for tuple writes
        MODEL_RESP_FILE=$(mktemp -t dev-seed-model.XXXXXX)
        HTTP=$(curl -s --max-time 10 -o "${MODEL_RESP_FILE}" -w "%{http_code}" \
          -X POST "${OPENFGA_URL}/stores/${STORE_ID}/authorization-models" \
          -H "Content-Type: application/json" \
          -d "${MODEL_JSON}" || echo "000")
        case "${HTTP}" in
          200|201)
            MODEL_ID=$(jq -r '.authorization_model_id // empty' "${MODEL_RESP_FILE}" 2>/dev/null || true)
            if [[ -n "${MODEL_ID}" ]]; then
              log "OpenFGA model written; model_id=${MODEL_ID}"
            else
              warn "OpenFGA model write HTTP=${HTTP} ama model_id parse edilemedi: $(head -c 200 "${MODEL_RESP_FILE}")"
              MODEL_ID=""
            fi
            ;;
          *)
            warn "OpenFGA model write HTTP=${HTTP}; body=$(head -c 300 "${MODEL_RESP_FILE}" 2>/dev/null)"
            MODEL_ID=""
            ;;
        esac
        rm -f "${MODEL_RESP_FILE}"
      fi
    fi

    # 4. Write tuples (idempotent — duplicate writes return 400, kabul ediyoruz)
    TUPLES=$(jq -c '.tuples' "${FIXTURES}/openfga/tuples.json")
    if [[ -n "${MODEL_ID:-}" ]]; then
      PAYLOAD=$(jq -nc --arg mid "${MODEL_ID}" --argjson tk "${TUPLES}" \
        '{authorization_model_id: $mid, writes: {tuple_keys: $tk}}')
    else
      PAYLOAD="{\"writes\": {\"tuple_keys\": ${TUPLES}}}"
    fi
    TUPLE_RESP_FILE=$(mktemp -t dev-seed-tuples.XXXXXX)
    HTTP=$(curl -s --max-time 10 -o "${TUPLE_RESP_FILE}" -w "%{http_code}" \
      -X POST "${OPENFGA_URL}/stores/${STORE_ID}/write" \
      -H "Content-Type: application/json" \
      -d "${PAYLOAD}" || echo "000")
    case "${HTTP}" in
      200) log "OpenFGA tuples written ($(echo "${TUPLES}" | jq 'length') tuples)" ;;
      400)
        # Codex retrospective WARNING #7: distinguish duplicate-write idempotency
        # vs model-mismatch / type-error in the response body so debug doesn't
        # have to re-run the script with manual curl.
        BODY=$(head -c 300 "${TUPLE_RESP_FILE}" 2>/dev/null)
        warn "OpenFGA write 400; body=${BODY}"
        ;;
      *) warn "OpenFGA write HTTP=${HTTP}; body=$(head -c 300 "${TUPLE_RESP_FILE}" 2>/dev/null)" ;;
    esac
    rm -f "${TUPLE_RESP_FILE}"
  fi
fi

# ----- 4. K8s Secret stub'ları (Faz 17.3 — local dev fixture) -----
# Test/prod ESO tarafından Vault'tan dolan secret'lar — lokal dev için fake değer
# Bu credentials sadece local-only stub; gerçek runtime için yeterli değil
# (KC realm fixture ile uyumlu ad-hoc dev secret).
#
# Skip when kubectl k3d-dev context yok (CI smoke runs, --openfga-only against
# bare openfga container, etc.). The stub is only useful when k3d-dev cluster
# is up; otherwise create-secret fails and aborts the script under set -e.
#
# Codex retrospective WARNING #6: bound the cluster-info probe with a
# request timeout so a configured-but-down k3d-dev cluster doesn't make
# the script hang for the kubectl default (~10s+).
if command -v kubectl >/dev/null 2>&1 \
    && kubectl config get-contexts k3d-dev >/dev/null 2>&1 \
    && kubectl --context k3d-dev --request-timeout=3s cluster-info >/dev/null 2>&1; then
  log "K8s secret stubs (auth-service-secrets — local dev only)"
  # Spring Boot convention env: SPRING_DATASOURCE_USERNAME + SPRING_DATASOURCE_PASSWORD
  # (DB_PASSWORD/USERNAME değil — Spring Boot relaxed binding uyumlu canonical adlar)
  # dev-pg container POSTGRES_USER=postgres + POSTGRES_PASSWORD=postgres ile başlatılır
  kubectl --context k3d-dev -n platform-dev create secret generic auth-service-secrets \
      --from-literal=SPRING_DATASOURCE_USERNAME=postgres \
      --from-literal=SPRING_DATASOURCE_PASSWORD=postgres \
      --from-literal=KEYCLOAK_CLIENT_SECRET=local-dev-stub \
      --dry-run=client -o yaml | kubectl --context k3d-dev apply -f - >/dev/null
else
  log "skip K8s secret stubs (no k3d-dev kubectl context)"
fi

log "=== seed tamamlandı (profile=${PROFILE}) ==="
