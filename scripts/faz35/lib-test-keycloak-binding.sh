#!/usr/bin/env bash

# Prove that the host loopback endpoint receiving TEST credentials is the exact
# platform-kc-test container and that it advertises the canonical TEST issuer.
faz35_assert_test_keycloak_binding() {
  local container=$1 base_url=$2 realm=$3 expected_issuer=$4
  local port_binding discovery

  [ "${container}" = "platform-kc-test" ] &&
    [ "${base_url}" = "http://127.0.0.1:8082" ] &&
    [ "${realm}" = "platform-test" ] &&
    [ "${expected_issuer}" = "https://testai.acik.com/realms/platform-test" ] || return 1

  port_binding=$(docker inspect -f \
    '{{json (index .NetworkSettings.Ports "8080/tcp")}}' \
    "${container}" 2>/dev/null) || return 1
  [ "${port_binding}" = '[{"HostIp":"127.0.0.1","HostPort":"8082"}]' ] || return 1

  discovery=$(curl -sS --max-time 10 \
    "${base_url}/realms/${realm}/.well-known/openid-configuration") || return 1
  jq -e --arg issuer "${expected_issuer}" '
    .issuer == $issuer and
    .token_endpoint == ($issuer + "/protocol/openid-connect/token")
  ' <<<"${discovery}" >/dev/null
}
