#!/usr/bin/env bash
set -euo pipefail

# ES-106 read-only runtime verifier. It emits only booleans/counts; raw request
# or workload logs are never copied to stdout, evidence, GitHub, or chat.
readonly SSH_TARGET="${SSH_TARGET:-staging-sw}"
readonly KUBE_CONTEXT="k3d-test"
readonly KUBE_NS="platform-test"
readonly INGRESS_NS="ingress-nginx"
readonly EDGE_CONTAINER="platform-web-nginx"
readonly EXPECTED_HOSTS=("etik.acik.com" "speakup.acik.com")

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
ROOT_DIR=$(CDPATH='' cd -- "$SCRIPT_DIR/../.." && pwd)
ACTIVATION_DIR="$ROOT_DIR/kustomize/overlays/test/activation/etik-speak"
EDGE_CONFIG="$ROOT_DIR/host-compose/web-nginx/default.conf"

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
    'nginx.ingress.kubernetes.io/enable-opentelemetry: "false"'
  do
    grep -Fq "$exact_annotation" <<<"$ingress_block" || {
      echo "FATAL: rendered $ingress_name misses privacy annotation" >&2
      exit 4
    }
  done
  for forbidden_annotation in \
    'nginx.ingress.kubernetes.io/proxy-set-headers:' \
    'nginx.ingress.kubernetes.io/proxy-hide-headers:' \
    'nginx.ingress.kubernetes.io/limit-rps:' \
    'nginx.ingress.kubernetes.io/limit-rpm:' \
    'nginx.ingress.kubernetes.io/limit-connections:' \
    'nginx.ingress.kubernetes.io/limit-burst-multiplier:'
  do
    if grep -Fq "$forbidden_annotation" <<<"$ingress_block"; then
      echo "FATAL: rendered $ingress_name retains a displaced edge policy" >&2
      exit 5
    fi
  done
done

# Literal NGINX variables are intentionally not expanded by this verifier.
# shellcheck disable=SC2016
for edge_requirement in \
  'server_name etik.acik.com speakup.acik.com;' \
  'map $http_cookie $etik_speak_public_cookie' \
  '__Host-etik_mailbox=[^;]+' \
  'limit_req_zone $binary_remote_addr zone=etik_speak_api_rps:10m rate=3r/s;' \
  'limit_req_zone $binary_remote_addr zone=etik_speak_api_rpm:10m rate=60r/m;' \
  'limit_req_zone $binary_remote_addr zone=etik_speak_ui_rps:10m rate=10r/s;' \
  'limit_req_zone $binary_remote_addr zone=etik_speak_ui_rpm:10m rate=300r/m;' \
  'limit_conn_zone $binary_remote_addr zone=etik_speak_public_conn:10m;' \
  'proxy_set_header Cookie $etik_speak_public_cookie;' \
  'proxy_set_header X-Etik-Speak-Transport https;' \
  'map $upstream_http_set_cookie $etik_speak_mailbox_set_cookie_name' \
  'map $etik_speak_mailbox_set_cookie_httponly $etik_speak_public_set_cookie' \
  'proxy_hide_header Set-Cookie;' \
  'add_header Set-Cookie $etik_speak_public_set_cookie always;' \
  '"~*;\s*Domain=" "";' \
  '"~*;\s*Path=/(?:;|$)" $etik_speak_mailbox_set_cookie_domain;' \
  '"~*;\s*Secure(?:;|$)" $etik_speak_mailbox_set_cookie_path;' \
  '"~*;\s*HttpOnly(?:;|$)" $etik_speak_mailbox_set_cookie_secure;' \
  '"~*;\s*SameSite=Strict(?:;|$)" $etik_speak_mailbox_set_cookie_httponly;'
do
  grep -Fq "$edge_requirement" "$EDGE_CONFIG" || {
    echo "FATAL: canonical host edge misses the ES-106 privacy boundary" >&2
    exit 6
  }
done

for header in \
  Authorization Forwarded Referer User-Agent X-Forwarded-For \
  X-Original-Forwarded-For X-Real-IP X-Request-ID
do
  header_count=$(
    grep -Fc "proxy_set_header $header \"\";" "$EDGE_CONFIG" || true
  )
  [ "$header_count" -ge 2 ] || {
    echo "FATAL: canonical host edge does not clear identity header: $header" >&2
    exit 7
  }
done

sentinel_suffix=$(openssl rand -hex 12)
sentinel_ua="ES106-SYNTHETIC-UA-${sentinel_suffix}"
sentinel_referrer="https://synthetic.invalid/es106-${sentinel_suffix}"
sentinel_forwarded="198.51.100.42"
sentinel_cookie="suite_session=ES106-SYNTHETIC-${sentinel_suffix}"
started_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

ssh "$SSH_TARGET" bash -s -- \
  "$KUBE_CONTEXT" "$KUBE_NS" "$INGRESS_NS" "$EDGE_CONTAINER" \
  "$started_at" "$sentinel_ua" "$sentinel_referrer" "$sentinel_forwarded" \
  "$sentinel_cookie" "${EXPECTED_HOSTS[@]}" <<'REMOTE'
set -euo pipefail

readonly kube_context=$1
readonly kube_ns=$2
readonly ingress_ns=$3
readonly edge_container=$4
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
[ "$edge_container" = "platform-web-nginx" ] || {
  echo "FATAL: host-edge container guard refused" >&2
  exit 11
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
      exit 12
    }
  grep -Fq '"nginx.ingress.kubernetes.io/enable-opentelemetry":"false"' \
    <<<"$live_annotations" || {
      echo "FATAL: live public ingress telemetry is not disabled" >&2
      exit 13
    }
  for forbidden_annotation in \
    nginx.ingress.kubernetes.io/proxy-set-headers \
    nginx.ingress.kubernetes.io/proxy-hide-headers \
    nginx.ingress.kubernetes.io/limit-rps \
    nginx.ingress.kubernetes.io/limit-rpm \
    nginx.ingress.kubernetes.io/limit-connections \
    nginx.ingress.kubernetes.io/limit-burst-multiplier
  do
    if grep -Fq "\"$forbidden_annotation\":" <<<"$live_annotations"; then
      echo "FATAL: live public ingress retains a displaced edge policy" >&2
      exit 14
    fi
  done
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
  cat /etc/nginx/nginx.conf >"$tmp_dir/ingress-nginx.conf"
chmod 600 "$tmp_dir/ingress-nginx.conf"

for host in "${hosts[@]}"; do
  awk -v host="$host" '
    $0 ~ "## start server " host {capture=1}
    capture {print}
    $0 ~ "## end server " host {exit}
  ' "$tmp_dir/ingress-nginx.conf" >"$tmp_dir/ingress-server.conf"

  [ -s "$tmp_dir/ingress-server.conf" ] || {
    echo "FATAL: generated ingress NGINX server block is missing" >&2
    exit 16
  }
  access_log_off_count=$(
    grep -Ec '^[[:space:]]*access_log[[:space:]]+off;' \
      "$tmp_dir/ingress-server.conf" || true
  )
  [ "$access_log_off_count" -ge 3 ] || {
    echo "FATAL: generated ingress NGINX public locations still log access" >&2
    exit 17
  }
done

docker exec "$edge_container" nginx -T \
  >"$tmp_dir/host-edge-nginx.conf" 2>/dev/null
chmod 600 "$tmp_dir/host-edge-nginx.conf"
sed -n '/# Faz 35 ES-106/,$p' "$tmp_dir/host-edge-nginx.conf" \
  >"$tmp_dir/host-edge-public.conf"
[ -s "$tmp_dir/host-edge-public.conf" ] || {
  echo "FATAL: live host-edge ES-106 policy is missing" >&2
  exit 18
}

# Literal NGINX variables are intentionally not expanded in the remote shell.
# shellcheck disable=SC2016
for edge_requirement in \
  'server_name etik.acik.com speakup.acik.com;' \
  'map $http_cookie $etik_speak_public_cookie' \
  '__Host-etik_mailbox=[^;]+' \
  'limit_req_zone $binary_remote_addr zone=etik_speak_api_rps:10m rate=3r/s;' \
  'limit_req_zone $binary_remote_addr zone=etik_speak_api_rpm:10m rate=60r/m;' \
  'limit_req_zone $binary_remote_addr zone=etik_speak_ui_rps:10m rate=10r/s;' \
  'limit_req_zone $binary_remote_addr zone=etik_speak_ui_rpm:10m rate=300r/m;' \
  'limit_conn_zone $binary_remote_addr zone=etik_speak_public_conn:10m;' \
  'location ^~ /api/v1/public/ethics' \
  'limit_req zone=etik_speak_api_rps burst=6 nodelay;' \
  'limit_req zone=etik_speak_api_rpm burst=120 nodelay;' \
  'limit_conn etik_speak_public_conn 10;' \
  'limit_req zone=etik_speak_ui_rps burst=30 nodelay;' \
  'limit_req zone=etik_speak_ui_rpm burst=900 nodelay;' \
  'limit_conn etik_speak_public_conn 20;' \
  'proxy_set_header Cookie $etik_speak_public_cookie;' \
  'proxy_set_header X-Etik-Speak-Transport https;' \
  'map $upstream_http_set_cookie $etik_speak_mailbox_set_cookie_name' \
  'map $etik_speak_mailbox_set_cookie_httponly $etik_speak_public_set_cookie' \
  'proxy_hide_header Set-Cookie;' \
  'add_header Set-Cookie $etik_speak_public_set_cookie always;' \
  '"~*;\s*Domain=" "";' \
  '"~*;\s*Path=/(?:;|$)" $etik_speak_mailbox_set_cookie_domain;' \
  '"~*;\s*Secure(?:;|$)" $etik_speak_mailbox_set_cookie_path;' \
  '"~*;\s*HttpOnly(?:;|$)" $etik_speak_mailbox_set_cookie_secure;' \
  '"~*;\s*SameSite=Strict(?:;|$)" $etik_speak_mailbox_set_cookie_httponly;'
do
  grep -Fq "$edge_requirement" "$tmp_dir/host-edge-public.conf" || {
    echo "FATAL: live host edge misses the ES-106 privacy boundary" >&2
    exit 19
  }
done

host_access_log_off_count=$(
  grep -Ec '^[[:space:]]*access_log[[:space:]]+off;' \
    "$tmp_dir/host-edge-public.conf" || true
)
[ "$host_access_log_off_count" -ge 2 ] || {
  echo "FATAL: live host-edge public servers still log access" >&2
  exit 20
}

cookie_filter_count=$(
  grep -Fc 'proxy_set_header Cookie $etik_speak_public_cookie;' \
    "$tmp_dir/host-edge-public.conf" || true
)
[ "$cookie_filter_count" -eq 2 ] || {
  echo "FATAL: live host edge does not enforce the exact mailbox cookie filter" >&2
  exit 21
}

for header in \
  Authorization Forwarded Referer User-Agent X-Forwarded-For \
  X-Original-Forwarded-For X-Real-IP X-Request-ID
do
  header_count=$(
    grep -Fc "proxy_set_header $header \"\";" \
      "$tmp_dir/host-edge-public.conf" || true
  )
  [ "$header_count" -eq 2 ] || {
    echo "FATAL: live host edge does not clear identity header: $header" >&2
    exit 22
  }
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
      exit 23
      ;;
  esac
  if grep -Eiq '^Set-Cookie:.*Domain=\.?acik\.com([;[:space:]]|$)' "$response_headers"; then
    echo "FATAL: Domain=.acik.com cookie escaped the public boundary" >&2
    exit 24
  fi
  if grep -Ei '^Set-Cookie:' "$response_headers" \
    | grep -Eiv '^Set-Cookie:[[:space:]]*__Host-etik_mailbox=' \
    | grep -q .; then
    echo "FATAL: non-mailbox cookie escaped the public boundary" >&2
    exit 25
  fi
done

# Exercise the public API denial path without creating a case or a real secret.
api_headers="$tmp_dir/public-api.headers"
api_code=$(
  curl --silent --show-error --output /dev/null --dump-header "$api_headers" \
    --write-out '%{http_code}' \
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
    exit 26
    ;;
esac
if grep -Eiq '^Set-Cookie:.*Domain=\.?acik\.com([;[:space:]]|$)' "$api_headers"; then
  echo "FATAL: Domain=.acik.com API cookie escaped the public boundary" >&2
  exit 27
fi

# Keep raw logs inside the mode-700 temporary directory. Only a leak count may
# leave this verifier.
docker logs "$edge_container" --since "$started_at" \
  >"$tmp_dir/host-edge.log" 2>/dev/null || true
kubectl --context "$kube_context" -n "$ingress_ns" logs \
  daemonset/ingress-nginx-controller --since-time="$started_at" \
  >"$tmp_dir/ingress-edge.log" 2>/dev/null || true
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
  exit 28
}

echo "LIVE_INGRESS_ACCESS_LOG_DISABLED=true"
echo "LIVE_HOST_EDGE_ACCESS_LOG_DISABLED=true"
echo "LIVE_HOST_EDGE_VOLATILE_RATE_LIMIT=true"
echo "LIVE_SUITE_COOKIE_FILTER=true"
echo "LIVE_UPSTREAM_CLIENT_IDENTITY_STRIPPED=true"
echo "PUBLIC_PARENT_DOMAIN_COOKIE_ABSENT=true"
echo "SYNTHETIC_SENTINEL_LEAK_COUNT=0"
echo "NO_CORRELATION_ACCEPTED=true"
REMOTE
