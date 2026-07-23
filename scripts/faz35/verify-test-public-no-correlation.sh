#!/usr/bin/env bash
set -euo pipefail

# ES-106 read-only runtime verifier. It emits only booleans/counts; raw request
# or workload logs are never copied to stdout, evidence, GitHub, or chat.
readonly SSH_TARGET="${SSH_TARGET:-staging-sw}"
readonly KUBE_CONTEXT="k3d-test"
readonly KUBE_NS="platform-test"
readonly INGRESS_NS="ingress-nginx"
readonly EXPECTED_HOSTS=("etik.acik.com" "speakup.acik.com")
readonly EXPECTED_HEADER_CONFIG="platform-test/etik-speak-public-upstream-headers"

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
ROOT_DIR=$(CDPATH='' cd -- "$SCRIPT_DIR/../.." && pwd)
ACTIVATION_DIR="$ROOT_DIR/kustomize/overlays/test/activation/etik-speak"

for command_name in ssh kubectl grep awk sed mktemp date openssl; do
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "FATAL: required command is unavailable: $command_name" >&2
    exit 2
  }
done

rendered_file=$(mktemp)
trap 'rm -f "$rendered_file"' EXIT
chmod 600 "$rendered_file"
kubectl kustomize "$ACTIVATION_DIR" >"$rendered_file"

for ingress_name in etik-speak-public-ui etik-speak-public-api; do
  ingress_block=$(
    awk -v name="$ingress_name" '
      /^kind: Ingress$/ {block=$0 ORS; capture=1; next}
      capture {block=block $0 ORS}
      capture && /^  name: / {
        if ($1 == "name:" && $2 == name) matched=1
      }
      capture && /^---$/ {
        if (matched) {printf "%s", block; exit}
        capture=0; matched=0; block=""
      }
      END {if (capture && matched) printf "%s", block}
    ' "$rendered_file"
  )
  [ -n "$ingress_block" ] || {
    echo "FATAL: rendered ingress is missing: $ingress_name" >&2
    exit 3
  }
  for exact_annotation in \
    'nginx.ingress.kubernetes.io/enable-access-log: "false"' \
    'nginx.ingress.kubernetes.io/enable-opentelemetry: "false"' \
    "nginx.ingress.kubernetes.io/proxy-set-headers: $EXPECTED_HEADER_CONFIG" \
    'nginx.ingress.kubernetes.io/proxy-hide-headers: Set-Cookie'
  do
    grep -Fq "$exact_annotation" <<<"$ingress_block" || {
      echo "FATAL: rendered $ingress_name misses privacy annotation" >&2
      exit 4
    }
  done
done

sentinel_suffix=$(openssl rand -hex 12)
sentinel_ua="ES106-SYNTHETIC-UA-${sentinel_suffix}"
sentinel_referrer="https://synthetic.invalid/es106-${sentinel_suffix}"
sentinel_forwarded="198.51.100.42"
sentinel_cookie="suite_session=ES106-SYNTHETIC-${sentinel_suffix}"
started_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

ssh "$SSH_TARGET" bash -s -- \
  "$KUBE_CONTEXT" "$KUBE_NS" "$INGRESS_NS" "$EXPECTED_HEADER_CONFIG" \
  "$started_at" "$sentinel_ua" "$sentinel_referrer" "$sentinel_forwarded" \
  "$sentinel_cookie" "${EXPECTED_HOSTS[@]}" <<'REMOTE'
set -euo pipefail

readonly kube_context=$1
readonly kube_ns=$2
readonly ingress_ns=$3
readonly expected_header_config=$4
readonly started_at=$5
readonly sentinel_ua=$6
readonly sentinel_referrer=$7
readonly sentinel_forwarded=$8
readonly sentinel_cookie=$9
shift 9
readonly hosts=("$@")

[ "$kube_context" = "k3d-test" ] && [ "$kube_ns" = "platform-test" ] || {
  echo "FATAL: TEST target guard refused" >&2
  exit 10
}

tmp_dir=$(mktemp -d)
trap 'rm -rf "$tmp_dir"' EXIT
chmod 700 "$tmp_dir"

for ingress_name in etik-speak-public-ui etik-speak-public-api; do
  live_annotations=$(
    kubectl --context "$kube_context" -n "$kube_ns" get ingress "$ingress_name" \
      -o jsonpath='{.metadata.annotations}'
  )
  grep -Fq '"nginx.ingress.kubernetes.io/enable-access-log":"false"' \
    <<<"$live_annotations" || {
      echo "FATAL: live public ingress access log is not disabled" >&2
      exit 11
    }
  grep -Fq '"nginx.ingress.kubernetes.io/enable-opentelemetry":"false"' \
    <<<"$live_annotations" || {
      echo "FATAL: live public ingress telemetry is not disabled" >&2
      exit 12
    }
  grep -Fq "\"nginx.ingress.kubernetes.io/proxy-set-headers\":\"$expected_header_config\"" \
    <<<"$live_annotations" || {
      echo "FATAL: live public ingress header boundary is missing" >&2
      exit 13
    }
  grep -Fq '"nginx.ingress.kubernetes.io/proxy-hide-headers":"Set-Cookie"' \
    <<<"$live_annotations" || {
      echo "FATAL: live public ingress cookie response guard is missing" >&2
      exit 14
    }
done

controller=$(
  kubectl --context "$kube_context" -n "$ingress_ns" get pod \
    -l app.kubernetes.io/component=controller \
    -o jsonpath='{.items[0].metadata.name}'
)
[ -n "$controller" ] || {
  echo "FATAL: ingress controller pod is missing" >&2
  exit 15
}
kubectl --context "$kube_context" -n "$ingress_ns" exec "$controller" -- \
  cat /etc/nginx/nginx.conf >"$tmp_dir/nginx.conf"
chmod 600 "$tmp_dir/nginx.conf"

for host in "${hosts[@]}"; do
  awk -v host="$host" '
    $0 ~ "## start server " host {capture=1}
    capture {print}
    $0 ~ "## end server " host {exit}
  ' "$tmp_dir/nginx.conf" >"$tmp_dir/server.conf"

  [ -s "$tmp_dir/server.conf" ] || {
    echo "FATAL: generated NGINX server block is missing" >&2
    exit 16
  }
  access_log_off_count=$(grep -Ec '^[[:space:]]*access_log[[:space:]]+off;' "$tmp_dir/server.conf" || true)
  [ "$access_log_off_count" -ge 3 ] || {
    echo "FATAL: generated NGINX public locations still have access logging" >&2
    exit 17
  }
  for header in \
    Authorization Cookie Forwarded Referer User-Agent X-Forwarded-For \
    X-Original-Forwarded-For X-Real-IP X-Request-ID
  do
    grep -Eq "proxy_set_header[[:space:]]+$header[[:space:]]+\\\"\\\";" \
      "$tmp_dir/server.conf" || {
        echo "FATAL: generated NGINX identity header is not stripped: $header" >&2
        exit 18
      }
  done
done

for host in "${hosts[@]}"; do
  response_headers="$tmp_dir/${host}.headers"
  http_code=$(
    curl --silent --show-error --output /dev/null --dump-header "$response_headers" \
      --write-out '%{http_code}' \
      --user-agent "$sentinel_ua" \
      --referer "$sentinel_referrer" \
      --header "X-Forwarded-For: $sentinel_forwarded" \
      --header "X-Real-IP: $sentinel_forwarded" \
      --header "Forwarded: for=$sentinel_forwarded" \
      --header "Cookie: $sentinel_cookie" \
      "https://$host/"
  )
  case "$http_code" in
    200|204|301|302|307|308) ;;
    *)
      echo "FATAL: public reporter host is unavailable (HTTP $http_code)" >&2
      exit 19
      ;;
  esac
  if grep -Eiq '^Set-Cookie:.*Domain=\.?acik\.com([;[:space:]]|$)' "$response_headers"; then
    echo "FATAL: Domain=.acik.com cookie escaped the public boundary" >&2
    exit 20
  fi
done

# Exercise the public API denial path without creating a case or a real secret.
api_code=$(
  curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
    --request POST --header 'Content-Type: application/json' \
    --user-agent "$sentinel_ua" --referer "$sentinel_referrer" \
    --header "X-Forwarded-For: $sentinel_forwarded" \
    --header "Cookie: $sentinel_cookie" \
    --data '{"synthetic":"es106-negative-control"}' \
    "https://${hosts[0]}/api/v1/public/ethics/reports"
)
case "$api_code" in
  400|401|403|404|405|409|415|422) ;;
  *)
    echo "FATAL: synthetic public API negative control was not denied (HTTP $api_code)" >&2
    exit 21
    ;;
esac

# Keep raw logs inside the mode-700 temporary directory. Only a leak count may
# leave this verifier.
kubectl --context "$kube_context" -n "$ingress_ns" logs \
  daemonset/ingress-nginx-controller --since-time="$started_at" \
  >"$tmp_dir/edge.log" 2>/dev/null || true
kubectl --context "$kube_context" -n "$kube_ns" logs \
  deployment/etik-speak-public --since-time="$started_at" \
  >"$tmp_dir/public-ui.log" 2>/dev/null || true
kubectl --context "$kube_context" -n "$kube_ns" logs \
  deployment/ethics-service --since-time="$started_at" \
  >"$tmp_dir/public-api.log" 2>/dev/null || true
chmod 600 "$tmp_dir"/*.log

leak_count=0
for log_file in "$tmp_dir"/*.log; do
  for sentinel in "$sentinel_ua" "$sentinel_referrer" "$sentinel_forwarded" "$sentinel_cookie"; do
    if grep -Fq "$sentinel" "$log_file"; then
      leak_count=$((leak_count + 1))
    fi
  done
done
[ "$leak_count" -eq 0 ] || {
  echo "FATAL: synthetic sentinel leaked into a durable log surface" >&2
  exit 22
}

echo "LIVE_INGRESS_ACCESS_LOG_DISABLED=true"
echo "LIVE_UPSTREAM_IDENTITY_HEADERS_STRIPPED=true"
echo "PUBLIC_PARENT_DOMAIN_COOKIE_ABSENT=true"
echo "SYNTHETIC_SENTINEL_LEAK_COUNT=0"
echo "NO_CORRELATION_ACCEPTED=true"
REMOTE
