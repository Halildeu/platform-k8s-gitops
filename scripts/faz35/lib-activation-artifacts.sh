#!/usr/bin/env bash
# Pure, read-only helpers for binding Faz 35 activation to reviewed artifacts.

faz35_rendered_deployment_image() {
  local manifest=$1 deployment=$2
  awk -v target="$deployment" '
    BEGIN { RS="---" }
    $0 ~ /kind: Deployment/ && $0 ~ ("name: " target "([[:space:]]|$)") {
      while (match($0, /image: [^[:space:]]+/)) {
        print substr($0, RSTART + 7, RLENGTH - 7)
        $0=substr($0, RSTART + RLENGTH)
      }
    }
  ' "$manifest"
}

faz35_assert_rendered_deployment_image() {
  local manifest=$1 deployment=$2 expected=$3 actual count
  actual=$(faz35_rendered_deployment_image "$manifest" "$deployment")
  count=$(printf '%s\n' "$actual" | sed '/^$/d' | wc -l | tr -d ' ')
  [ "$count" -eq 1 ] && [ "$actual" = "$expected" ] || {
    echo "FATAL: $deployment rendered image is not the reviewed immutable artifact" >&2
    return 1
  }
}

faz35_assert_root_activation_binding() {
  local root_overlay=$1 count
  count=$(grep -Ec '^[[:space:]]*-[[:space:]]*activation/etik-speak[[:space:]]*$' "$root_overlay")
  [ "$count" -eq 1 ] || {
    echo "FATAL: root TEST overlay must include Etik Speak activation exactly once" >&2
    return 1
  }
}
